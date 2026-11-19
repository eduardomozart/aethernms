"""Py4Web application shell, HTML page routes, interactive Web UI auth, static serving, and REST API bootstrap."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import threading
from typing import Any, Callable, Dict, Optional, Tuple

from py4web.core import Session, action, bottle, redirect, render, request, response
from yatl import XML

from aethernms.airwave_importer import fetch_airwave_inventory
from aethernms.api import register_api_routes
from aethernms.api.common import (
    check_external_api_access,
    effective_language,
    json_error,
    json_response,
    read_json_body,
    resolve_session_user,
    user_has_permission,
)
from aethernms.api.i18n import build_i18n_payload
from aethernms.auth import ensure_session_secret
from aethernms.carbon_icons import carbon_icon
from aethernms.db import DatabaseStore
from aethernms.paths import (
    get_assets_dir,
    get_db_path,
    get_static_dir,
    get_templates_dir,
)
from aethernms.ssh_runner import BatchSSHExecutor


@dataclass
class AppContext:
    """Mutable runtime context backing Py4Web routes (swappable cleanly in tests)."""

    db: DatabaseStore
    running_jobs: Dict[str, threading.Event] = field(default_factory=dict)
    job_threads: Dict[str, threading.Thread] = field(default_factory=dict)
    executor_factory: Callable[[], BatchSSHExecutor] = field(
        default_factory=lambda: (lambda: BatchSSHExecutor())
    )
    ping_fn: Optional[Callable[[str], bool]] = None
    airwave_fetch_fn: Callable[..., Tuple[Dict[str, Dict[str, Any]], str]] = field(
        default_factory=lambda: fetch_airwave_inventory
    )
    lock: threading.Lock = field(default_factory=threading.Lock)


_CONTEXT: Optional[AppContext] = None
_ROUTES_REGISTERED: bool = False

# Single Py4Web Session fixture whose secret is updated by create_app()
_SESSION = Session(
    secret=ensure_session_secret(get_db_path().parent),
    expiration=86400,
    same_site="Lax",
    name="aethernms_session",
)


def _get_ctx() -> AppContext:
    global _CONTEXT
    if _CONTEXT is None:
        create_app()
    assert _CONTEXT is not None
    return _CONTEXT


def _set_session_secret(secret: str) -> None:
    params = Session._params.get(_SESSION)
    if params is not None:
        params.secret = secret


def _read_template(name: str) -> str:
    return (get_templates_dir() / name).read_text(encoding="utf-8")


def _render_page(
    template_name: str,
    active_page: str,
    ctx: AppContext,
    user: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> str:
    settings = ctx.db.get_settings()
    eff_lang = effective_language(settings)
    theme_mode = (settings.theme_mode or "auto").strip().lower()
    if theme_mode not in ("auto", "light", "dark"):
        theme_mode = "auto"
    initial_theme = "g100" if theme_mode == "dark" else "white"
    perms = set((user or {}).get("permissions") or [])
    context: Dict[str, Any] = {
        "active_page": active_page,
        "theme_mode": theme_mode,
        "initial_theme": initial_theme,
        "html_lang": eff_lang.replace("_", "-"),
        "icon": carbon_icon,
        "XML": XML,
        "user": user or {"username": "", "display_name": "", "role": ""},
        "perms": perms,
        "has_admin_nav": bool(
            perms.intersection({"system:settings", "users:manage", "roles:manage", "api_keys:manage"})
        ),
        "api_enabled": bool(settings.api_enabled),
    }
    if extra:
        context.update(extra)
    return render(
        filename=template_name,
        path=str(get_templates_dir()),
        context=context,
        delimiters="[[ ]]",
    )


def _render_forbidden_html(message: str, status: int = 403) -> str:
    response.status = status
    response.headers["Content-Type"] = "text/html; charset=utf-8"
    return render(
        filename="forbidden.html",
        path=str(get_templates_dir()),
        context={
            "message": message,
            "icon": carbon_icon,
            "XML": XML,
        },
        delimiters="[[ ]]",
    )


def _require_page_user(
    ctx: AppContext,
    next_path: str = "/",
    permission: Optional[str] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    if ctx.db.user_count() == 0:
        target = "/login" if next_path in ("", "/") else f"/login?next={next_path}"
        redirect(target)
    user = resolve_session_user(ctx, _SESSION)
    if user is None:
        target = "/login" if next_path in ("", "/") else f"/login?next={next_path}"
        redirect(target)
    if permission and not user_has_permission(user, permission):
        return None, _render_forbidden_html(f"Access denied. Missing required permission: {permission}.")
    return user, None


def _register_routes() -> None:
    global _ROUTES_REGISTERED
    if _ROUTES_REGISTERED:
        return
    action.app_name = "_default"

    # ------------------------------------------------------------------
    # Static assets & Public UI i18n catalog
    # ------------------------------------------------------------------
    @action("/static/<filepath:path>", method="GET")
    def serve_static(filepath: str):
        return bottle.static_file(filepath, root=str(get_static_dir()))

    @action("/assets/<filepath:path>", method="GET")
    def serve_assets(filepath: str):
        return bottle.static_file(filepath, root=str(get_assets_dir()))

    @action("/i18n", method="GET")
    def web_ui_i18n():
        ctx = _get_ctx()
        req_lang = str(request.query.get("lang") or "").strip()
        return json_response(build_i18n_payload(ctx, requested_lang=req_lang))

    # ------------------------------------------------------------------
    # Interactive Web UI Browser Authentication (/login, /setup, /logout, /account/password)
    # (External API authentication lives strictly on /api/* via API Keys only.)
    # ------------------------------------------------------------------
    @action("/login", method="GET")
    @action.uses(_SESSION)
    def page_login():
        ctx = _get_ctx()
        needs_setup = ctx.db.user_count() == 0
        if not needs_setup and resolve_session_user(ctx, _SESSION) is not None:
            redirect("/")
        response.headers["Content-Type"] = "text/html; charset=utf-8"
        return _render_page(
            "login.html",
            active_page="login",
            ctx=ctx,
            user=None,
            extra={"needs_setup": needs_setup},
        )

    @action("/setup", method="POST")
    @action.uses(_SESSION)
    def web_ui_setup():
        ctx = _get_ctx()
        if ctx.db.user_count() > 0:
            return json_error(400, "Administrator account is already configured.")
        body = read_json_body()
        if body is None:
            return json_error(400, "Invalid JSON payload.")
        username = str(body.get("username") or "").strip()
        password = str(body.get("password") or "")
        try:
            user = ctx.db.create_user(username, password, role="Admin")
        except ValueError as exc:
            return json_error(400, str(exc))
        _SESSION["user_id"] = user["id"]
        _SESSION["username"] = user["username"]
        return json_response(
            {
                "needs_setup": False,
                "authenticated": True,
                "username": user["username"],
                "role": user["role"],
            },
            status=201,
        )

    @action("/login", method="POST")
    @action.uses(_SESSION)
    def web_ui_login():
        ctx = _get_ctx()
        if ctx.db.user_count() == 0:
            return json_error(400, "Initial administrator setup is required first.")
        body = read_json_body()
        if body is None:
            return json_error(400, "Invalid JSON payload.")
        username = str(body.get("username") or "").strip()
        password = str(body.get("password") or "")
        user = ctx.db.authenticate_user(username, password)
        if user is None:
            return json_error(401, "Invalid username or password.")
        _SESSION["user_id"] = user["id"]
        _SESSION["username"] = user["username"]
        return json_response(
            {
                "needs_setup": False,
                "authenticated": True,
                "username": user["username"],
                "role": user["role"],
            }
        )

    @action("/logout", method="POST")
    @action.uses(_SESSION)
    def web_ui_logout():
        _SESSION.clear()
        return json_response({"ok": True})

    @action("/account/password", method="POST")
    @action.uses(_SESSION)
    def web_ui_change_password():
        ctx = _get_ctx()
        user = resolve_session_user(ctx, _SESSION)
        if user is None:
            return json_error(401, "Authentication required.")
        body = read_json_body()
        if body is None:
            return json_error(400, "Invalid JSON payload.")
        cur_pw = str(body.get("current_password") or "")
        new_pw = str(body.get("new_password") or "")
        if ctx.db.authenticate_user(user["username"], cur_pw) is None:
            return json_error(400, "Current password is incorrect.")
        try:
            ctx.db.update_user_password(user["id"], new_pw)
        except ValueError as exc:
            return json_error(400, str(exc))
        return json_response({"ok": True})

    # ------------------------------------------------------------------
    # Authenticated Web UI HTML Pages
    # ------------------------------------------------------------------
    @action("/", method="GET")
    @action("/jobs", method="GET")
    @action.uses(_SESSION)
    def page_jobs():
        ctx = _get_ctx()
        user, denied = _require_page_user(ctx, request.path or "/jobs", permission="jobs:read")
        if denied:
            return denied
        response.headers["Content-Type"] = "text/html; charset=utf-8"
        return _render_page("jobs.html", active_page="jobs", ctx=ctx, user=user)

    @action("/snippets", method="GET")
    @action.uses(_SESSION)
    def page_snippets():
        ctx = _get_ctx()
        user, denied = _require_page_user(ctx, "/snippets", permission="snippets:read")
        if denied:
            return denied
        response.headers["Content-Type"] = "text/html; charset=utf-8"
        return _render_page("snippets.html", active_page="snippets", ctx=ctx, user=user)

    @action("/devices", method="GET")
    @action.uses(_SESSION)
    def page_devices():
        ctx = _get_ctx()
        user, denied = _require_page_user(ctx, "/devices", permission="devices:read")
        if denied:
            return denied
        response.headers["Content-Type"] = "text/html; charset=utf-8"
        return _render_page("devices.html", active_page="devices", ctx=ctx, user=user)

    @action("/administration", method="GET")
    @action.uses(_SESSION)
    def page_administration_root():
        ctx = _get_ctx()
        user, denied = _require_page_user(ctx, "/administration")
        if denied:
            return denied
        assert user is not None
        for perm, dest in (
            ("system:settings", "/administration/settings"),
            ("users:manage", "/administration/users"),
            ("roles:manage", "/administration/roles"),
            ("api_keys:manage", "/administration/api-keys"),
        ):
            if user_has_permission(user, perm):
                redirect(dest)
        return _render_forbidden_html("You do not have permission to access Administration pages.")

    @action("/administration/settings", method="GET")
    @action.uses(_SESSION)
    def page_admin_settings():
        ctx = _get_ctx()
        user, denied = _require_page_user(ctx, "/administration/settings", permission="system:settings")
        if denied:
            return denied
        response.headers["Content-Type"] = "text/html; charset=utf-8"
        return _render_page(
            "administration/settings.html", active_page="admin_settings", ctx=ctx, user=user
        )

    @action("/administration/users", method="GET")
    @action.uses(_SESSION)
    def page_admin_users():
        ctx = _get_ctx()
        user, denied = _require_page_user(ctx, "/administration/users", permission="users:manage")
        if denied:
            return denied
        response.headers["Content-Type"] = "text/html; charset=utf-8"
        return _render_page(
            "administration/users.html", active_page="admin_users", ctx=ctx, user=user
        )

    @action("/administration/roles", method="GET")
    @action.uses(_SESSION)
    def page_admin_roles():
        ctx = _get_ctx()
        user, denied = _require_page_user(ctx, "/administration/roles", permission="roles:manage")
        if denied:
            return denied
        response.headers["Content-Type"] = "text/html; charset=utf-8"
        return _render_page(
            "administration/roles.html", active_page="admin_roles", ctx=ctx, user=user
        )

    @action("/administration/api-keys", method="GET")
    @action.uses(_SESSION)
    def page_admin_api_keys():
        ctx = _get_ctx()
        user, denied = _require_page_user(ctx, "/administration/api-keys", permission="api_keys:manage")
        if denied:
            return denied
        response.headers["Content-Type"] = "text/html; charset=utf-8"
        return _render_page(
            "administration/api_keys.html", active_page="admin_api_keys", ctx=ctx, user=user
        )

    @action("/api/docs", method="GET")
    @action("/swagger", method="GET")
    def page_swagger():
        ctx = _get_ctx()
        ext_err = check_external_api_access(ctx)
        if ext_err:
            return _render_forbidden_html(ext_err, status=403)
        response.headers["Content-Type"] = "text/html; charset=utf-8"
        return _read_template("swagger.html")

    # Register all unified REST API controllers under aethernms/api/
    register_api_routes(_get_ctx, _SESSION)
    _ROUTES_REGISTERED = True


def create_app(
    db_path: Optional[Path | str] = None,
    executor_factory: Optional[Callable[[], BatchSSHExecutor]] = None,
    ping_fn: Optional[Callable[[str], bool]] = None,
    airwave_fetch_fn: Optional[Callable[..., Tuple[Dict[str, Dict[str, Any]], str]]] = None,
    seed_snippets: bool = True,
    migrate_legacy_xml: bool = True,
) -> Tuple[Any, AppContext]:
    """Initialize SQLite store, seed built-in snippets, register Py4Web routes, and return (wsgi_app, ctx)."""
    global _CONTEXT
    store = DatabaseStore(db_path=db_path)
    if migrate_legacy_xml:
        store.migrate_legacy_xml_files()
    if seed_snippets:
        store.seed_bundled_snippets()
    store.bootstrap_admin_from_env()

    _set_session_secret(ensure_session_secret(store.db_path.parent))
    ctx = AppContext(
        db=store,
        executor_factory=executor_factory or (lambda: BatchSSHExecutor()),
        ping_fn=ping_fn,
        airwave_fetch_fn=airwave_fetch_fn or fetch_airwave_inventory,
    )
    _CONTEXT = ctx
    _register_routes()
    return bottle.default_app(), ctx
