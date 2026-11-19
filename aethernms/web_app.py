"""Py4Web application shell, HTML page routes, Setup Guide, interactive Web UI auth, static serving, and REST API bootstrap."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import threading
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.parse import quote

from py4web.core import Session, action, bottle, redirect, render, request, response
from yatl import XML

from aethernms.airwave_importer import fetch_airwave_inventory
from aethernms.api import register_api_routes
from aethernms.api.common import (
    check_external_api_access,
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
from aethernms.db_config import (
    DB_ENGINE_MAP,
    build_dal_uri,
    check_engine_drivers,
    detect_engine_from_uri,
    get_dal_meta_dir,
    get_supported_engines_info,
    load_db_config,
    save_db_config,
    test_dal_connection,
)
from aethernms.models import AppSettings
from aethernms.paths import (
    get_assets_dir,
    get_docs_base_url,
    get_static_dir,
    get_templates_dir,
    runtime_root,
)
from aethernms.ssh_runner import BatchSSHExecutor


@dataclass
class AppContext:
    """Mutable runtime context backing Py4Web routes (swappable cleanly in tests and /setup)."""

    db: Optional[DatabaseStore] = None
    config_dir: Path = field(default_factory=runtime_root)
    db_source: str = "unconfigured"
    seed_snippets_default: bool = True
    migrate_legacy_xml: bool = True
    running_jobs: Dict[str, threading.Event] = field(default_factory=dict)
    job_threads: Dict[str, threading.Thread] = field(default_factory=dict)
    executor_factory: Callable[[], BatchSSHExecutor] = field(
        default_factory=lambda: (lambda: BatchSSHExecutor())
    )
    ping_fn: Optional[Callable[[str], bool]] = None
    airwave_fetch_fn: Callable[..., Tuple[Dict[str, Dict[str, Any]], str]] = field(
        default_factory=lambda: fetch_airwave_inventory
    )
    lock: threading.RLock = field(default_factory=threading.RLock)


_CONTEXT: Optional[AppContext] = None
_ROUTES_REGISTERED: bool = False

# Single Py4Web Session fixture whose secret is updated by create_app()
_SESSION = Session(
    secret=ensure_session_secret(runtime_root()),
    expiration=86400,
    same_site="Lax",
    name="aethernms_session",
)


def _get_ctx() -> AppContext:
    global _CONTEXT
    if _CONTEXT is None:
        create_app()
    assert _CONTEXT is not None
    _ensure_db_loaded(_CONTEXT)
    return _CONTEXT


PAGE_META_MAP: Dict[str, Tuple[str, str]] = {
    "jobs": ("Jobs", "/user-guide/jobs/"),
    "snippets": ("Snippets", "/user-guide/snippets-and-variables/"),
    "devices": ("Devices", "/user-guide/devices/"),
    "admin_settings": ("System Settings", "/user-guide/administration-settings/"),
    "admin_users": ("Users", "/user-guide/administration-users/"),
    "admin_roles": ("Roles", "/user-guide/administration-roles/"),
    "admin_api_keys": ("API Keys", "/user-guide/administration-api-keys/"),
    "login": ("Sign In", "/user-guide/getting-started/"),
    "setup": ("Initial Setup Guide", "/user-guide/getting-started/"),
    "swagger": ("API Docs (Swagger)", "/user-guide/rest-api/"),
    "forbidden": ("Access Denied", "/user-guide/"),
}


def _ensure_db_loaded(ctx: AppContext) -> None:
    """Lazy-reload db_config.json if ctx.db was unconfigured when another process finished /setup."""
    if ctx.db is not None or ctx.db_source != "unconfigured":
        return
    with ctx.lock:
        if ctx.db is not None or ctx.db_source != "unconfigured":
            return
        cfg_data = load_db_config(config_dir=ctx.config_dir)
        if cfg_data is None:
            return
        eng = cfg_data["engine"]
        uri = cfg_data["uri"]
        meta_folder = None if eng == "sqlite" else get_dal_meta_dir(ctx.config_dir)
        store = DatabaseStore(db_uri=uri, folder=meta_folder, engine=eng)
        if ctx.migrate_legacy_xml:
            store.migrate_legacy_xml_files(config_dir=ctx.config_dir)
        if ctx.seed_snippets_default:
            store.seed_bundled_snippets()
        store.bootstrap_admin_from_env()
        ctx.db = store
        ctx.db_source = str(cfg_data.get("source") or "config_file")


def _needs_setup(ctx: AppContext) -> bool:
    _ensure_db_loaded(ctx)
    return ctx.db is None or ctx.db.user_count() == 0


def _set_session_secret(secret: str) -> None:
    params = Session._params.get(_SESSION)
    if params is not None:
        params.secret = secret


def _build_i18n_render_context(
    ctx: AppContext,
    active_page: str,
    user: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    settings = ctx.db.get_settings() if ctx.db is not None else AppSettings()
    req_lang = str(request.query.get("lang") or "").strip()
    i18n_payload = build_i18n_payload(ctx, requested_lang=req_lang, user=user)
    eff_lang = str(i18n_payload["effective_language"])
    catalog = i18n_payload.get("catalog") or {}

    def translate_fn(msg: str) -> str:
        key = str(msg or "")
        return str(catalog.get(key, key))

    raw_theme = (user.get("theme_mode") if user else settings.theme_mode) or "auto"
    theme_mode = str(raw_theme).strip().lower()
    if theme_mode not in ("auto", "light", "dark"):
        theme_mode = "auto"
    initial_theme = "g100" if theme_mode == "dark" else "white"

    page_title_key, help_path = PAGE_META_MAP.get(active_page, ("aethernms", "/user-guide/"))
    help_url = f"{get_docs_base_url()}{help_path}"
    initial_i18n_json = json.dumps(i18n_payload, ensure_ascii=False).replace("</", "<\\/")

    return {
        "T": translate_fn,
        "eff_lang": eff_lang,
        "html_lang": eff_lang.replace("_", "-"),
        "theme_mode": theme_mode,
        "initial_theme": initial_theme,
        "page_title_key": page_title_key,
        "page_title": translate_fn(page_title_key),
        "help_url": help_url,
        "initial_i18n_json": initial_i18n_json,
        "api_enabled": bool(settings.api_enabled),
    }


def _render_page(
    template_name: str,
    active_page: str,
    ctx: AppContext,
    user: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> str:
    i18n_ctx = _build_i18n_render_context(ctx, active_page, user=user)
    perms = set((user or {}).get("permissions") or [])
    header_mode = "login" if active_page == "login" else ("setup" if active_page == "setup" else "app")
    header_href = "/login" if active_page == "login" else ("/setup" if active_page == "setup" else "/jobs")
    context: Dict[str, Any] = {
        "active_page": active_page,
        "header_mode": header_mode,
        "header_href": header_href,
        "icon": carbon_icon,
        "XML": XML,
        "user": user or {"id": None, "username": "", "display_name": "", "role": ""},
        "perms": perms,
        "can_manage_users": "users:manage" in perms,
        "has_admin_nav": bool(
            perms.intersection({"system:settings", "users:manage", "roles:manage", "api_keys:manage"})
        ),
        **i18n_ctx,
    }
    if extra:
        context.update(extra)
    return render(
        filename=template_name,
        path=str(get_templates_dir()),
        context=context,
        delimiters="[[ ]]",
    )


def _render_forbidden_html(
    message: str,
    status: int = 403,
    ctx: Optional[AppContext] = None,
    user: Optional[Dict[str, Any]] = None,
) -> str:
    response.status = status
    response.headers["Content-Type"] = "text/html; charset=utf-8"
    eff_ctx = ctx or _get_ctx()
    i18n_ctx = _build_i18n_render_context(eff_ctx, "forbidden", user=user)
    return render(
        filename="forbidden.html",
        path=str(get_templates_dir()),
        context={
            "header_mode": "forbidden",
            "header_href": "/",
            "message": message,
            "icon": carbon_icon,
            "XML": XML,
            **i18n_ctx,
        },
        delimiters="[[ ]]",
    )


def _require_page_user(
    ctx: AppContext,
    next_path: str = "/",
    permission: Optional[str] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    if _needs_setup(ctx):
        redirect("/setup")
    user = resolve_session_user(ctx, _SESSION)
    if user is None:
        target = "/login" if next_path in ("", "/") else f"/login?next={next_path}"
        redirect(target)
    if permission and not user_has_permission(user, permission):
        return None, _render_forbidden_html(
            f"Access denied. Missing required permission: {permission}.",
            ctx=ctx,
            user=user,
        )
    return user, None


def _scrub_password_text(text: str, password: str) -> str:
    cleaned = text
    for secret in (password, quote(password, safe="") if password else ""):
        if secret and len(secret) >= 2:
            cleaned = cleaned.replace(secret, "********")
    return cleaned


def _register_routes() -> None:
    global _ROUTES_REGISTERED
    if _ROUTES_REGISTERED:
        return
    action.app_name = "_default"

    # ------------------------------------------------------------------
    # Static assets, SVG/ICO/Touch Icons & Public UI i18n catalog
    # ------------------------------------------------------------------
    @action("/static/<filepath:path>", method="GET")
    def serve_static(filepath: str):
        return bottle.static_file(filepath, root=str(get_static_dir()))

    @action("/assets/<filepath:path>", method="GET")
    def serve_assets(filepath: str):
        return bottle.static_file(filepath, root=str(get_assets_dir()))

    @action("/i18n", method="GET")
    @action.uses(_SESSION)
    def web_ui_i18n():
        ctx = _get_ctx()
        _ensure_db_loaded(ctx)
        user = resolve_session_user(ctx, _SESSION)
        req_lang = str(request.query.get("lang") or "").strip()
        return json_response(build_i18n_payload(ctx, requested_lang=req_lang, user=user))

    # ------------------------------------------------------------------
    # First-Run 3-Step Setup Guide (/setup, /setup/info, /setup/test-db)
    # Permanently locked out once initial Admin setup has completed.
    # ------------------------------------------------------------------
    @action("/setup", method="GET")
    @action.uses(_SESSION)
    def page_setup():
        ctx = _get_ctx()
        if not _needs_setup(ctx):
            if resolve_session_user(ctx, _SESSION) is not None:
                redirect("/jobs")
            redirect("/login")
        response.headers["Content-Type"] = "text/html; charset=utf-8"
        return _render_page(
            "setup.html",
            active_page="setup",
            ctx=ctx,
            user=None,
        )

    @action("/setup/info", method="GET")
    def web_ui_setup_info():
        ctx = _get_ctx()
        if not _needs_setup(ctx):
            return json_error(403, "Initial setup has already been completed.")
        default_sqlite = str(ctx.config_dir / "aethernms.db")
        current_engine = ctx.db.engine if ctx.db is not None else "sqlite"
        current_uri_masked = ctx.db.db_uri_masked if ctx.db is not None else ""
        current_sqlite_path = (
            str(ctx.db.db_path)
            if (ctx.db is not None and ctx.db.db_path is not None)
            else default_sqlite
        )
        return json_response(
            {
                "needs_setup": True,
                "db_configured": ctx.db is not None,
                "db_locked": ctx.db_source in ("cli", "env"),
                "db_source": ctx.db_source,
                "current_engine": current_engine,
                "current_uri_masked": current_uri_masked,
                "current_sqlite_path": current_sqlite_path,
                "default_sqlite_path": default_sqlite,
                "engines": get_supported_engines_info(default_sqlite_path=default_sqlite),
            }
        )

    @action("/setup/test-db", method="POST")
    def web_ui_setup_test_db():
        ctx = _get_ctx()
        if not _needs_setup(ctx):
            return json_error(403, "Initial setup has already been completed.")
        body = read_json_body()
        if body is None:
            return json_error(400, "Invalid JSON payload.")

        default_sqlite = ctx.config_dir / "aethernms.db"
        if ctx.db_source in ("cli", "env") and ctx.db is not None:
            try:
                result = test_dal_connection(
                    engine=ctx.db.engine,
                    db_uri=ctx.db.raw_uri,
                    default_sqlite_path=default_sqlite,
                )
            except ValueError as exc:
                return json_error(400, str(exc))
            return json_response(result)

        engine = str(body.get("engine") or "sqlite").strip().lower()
        db_params = {
            "sqlite_path": body.get("sqlite_path", ""),
            "host": body.get("host", ""),
            "port": body.get("port", ""),
            "database": body.get("database", ""),
            "username": body.get("db_username") if "db_username" in body else body.get("username", ""),
            "password": body.get("db_password") if "db_password" in body else body.get("password", ""),
            "odbc_driver": body.get("odbc_driver", ""),
            "extra_params": body.get("extra_params", ""),
            "custom_uri": body.get("custom_uri") or body.get("db_uri") or "",
        }
        try:
            result = test_dal_connection(
                engine=engine,
                params=db_params,
                default_sqlite_path=default_sqlite,
            )
        except ValueError as exc:
            return json_error(400, str(exc))
        return json_response(result)

    @action("/setup", method="POST")
    @action.uses(_SESSION)
    def web_ui_setup():
        ctx = _get_ctx()
        if not _needs_setup(ctx):
            return json_error(403, "Initial setup has already been completed.")
        body = read_json_body()
        if body is None:
            return json_error(400, "Invalid JSON payload.")

        # Validate Administrator fields first before touching disk or creating any database file
        username = str(body.get("username") or "").strip()
        display_name = str(body.get("display_name") or "").strip()
        password = str(body.get("password") or "")
        if not username:
            return json_error(400, "Username is required.")
        if len(password) < 6:
            return json_error(400, "Password must be at least 6 characters long.")
        if "confirm_password" in body and password != str(body.get("confirm_password") or ""):
            return json_error(400, "Passwords do not match.")

        # Built-in Netmiko snippets are always seeded cleanly on initial setup.
        seed_snippets = bool(ctx.seed_snippets_default)
        has_db_fields = any(
            k in body
            for k in ("engine", "sqlite_path", "host", "database", "custom_uri", "db_uri")
        )
        db_password = str(body.get("db_password") or "")

        with ctx.lock:
            if not _needs_setup(ctx):
                return json_error(403, "Initial setup has already been completed.")

            if ctx.db_source in ("cli", "env") and ctx.db is not None:
                store = ctx.db
            elif ctx.db is not None and not has_db_fields:
                store = ctx.db
            else:
                default_sqlite = ctx.config_dir / "aethernms.db"
                engine = str(
                    body.get("engine") or (ctx.db.engine if ctx.db is not None else "sqlite")
                ).strip().lower()
                db_params = {
                    "sqlite_path": body.get("sqlite_path", ""),
                    "host": body.get("host", ""),
                    "port": body.get("port", ""),
                    "database": body.get("database", ""),
                    "username": body.get("db_username", ""),
                    "password": db_password,
                    "odbc_driver": body.get("odbc_driver", ""),
                    "extra_params": body.get("extra_params", ""),
                    "custom_uri": body.get("custom_uri") or body.get("db_uri") or "",
                }
                try:
                    target_uri = build_dal_uri(
                        engine, db_params, default_sqlite_path=default_sqlite
                    )
                except ValueError as exc:
                    return json_error(400, str(exc))

                eff_driver_engine = (
                    engine if engine != "custom" else detect_engine_from_uri(target_uri)
                )
                if eff_driver_engine in DB_ENGINE_MAP and eff_driver_engine != "custom":
                    drv = check_engine_drivers(eff_driver_engine)
                    if not drv["available"]:
                        checked = ", ".join(drv["checked_drivers"])
                        return json_error(
                            400,
                            f"Missing Python database driver ({checked}). Install with: {drv['pip_install']}",
                        )

                if ctx.db is not None and target_uri == ctx.db.raw_uri:
                    store = ctx.db
                else:
                    meta_folder = (
                        None if eff_driver_engine == "sqlite" else get_dal_meta_dir(ctx.config_dir)
                    )
                    try:
                        store = DatabaseStore(
                            db_uri=target_uri,
                            folder=meta_folder,
                            engine=engine,
                        )
                    except Exception as exc:
                        safe_err = _scrub_password_text(str(exc), db_password)
                        return json_error(400, f"Database initialization failed: {safe_err}")
                    if ctx.migrate_legacy_xml:
                        store.migrate_legacy_xml_files(config_dir=ctx.config_dir)

            if seed_snippets:
                store.seed_bundled_snippets()

            try:
                user = store.create_user(
                    username,
                    password,
                    role="Admin",
                    display_name=display_name,
                )
            except ValueError as exc:
                return json_error(400, str(exc))

            if ctx.db_source not in ("cli", "env"):
                save_db_config(store.engine, store.raw_uri, config_dir=ctx.config_dir)
                if ctx.db_source == "unconfigured":
                    ctx.db_source = "config_file"

            ctx.db = store

        _SESSION["user_id"] = user["id"]
        _SESSION["username"] = user["username"]
        return json_response(
            {
                "needs_setup": False,
                "authenticated": True,
                "username": user["username"],
                "display_name": user.get("display_name", ""),
                "role": user["role"],
                "db_engine": store.engine,
                "db_uri_masked": store.db_uri_masked,
                "redirect": "/jobs",
            },
            status=201,
        )

    # ------------------------------------------------------------------
    # Interactive Web UI Browser Authentication (/login, /logout, /account/password)
    # (External API authentication lives strictly on /api/* via API Keys only.)
    # ------------------------------------------------------------------
    @action("/login", method="GET")
    @action.uses(_SESSION)
    def page_login():
        ctx = _get_ctx()
        if _needs_setup(ctx):
            redirect("/setup")
        if resolve_session_user(ctx, _SESSION) is not None:
            redirect("/")
        response.headers["Content-Type"] = "text/html; charset=utf-8"
        return _render_page(
            "login.html",
            active_page="login",
            ctx=ctx,
            user=None,
            extra={"needs_setup": False},
        )

    @action("/login", method="POST")
    @action.uses(_SESSION)
    def web_ui_login():
        ctx = _get_ctx()
        if _needs_setup(ctx):
            return json_error(
                503 if ctx.db is None else 400,
                "Initial administrator setup is required first.",
                extra={"setup_required": True},
            )
        assert ctx.db is not None
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
        if ctx.db is None:
            return json_error(
                503,
                "Initial setup is required. Complete setup at /setup first.",
                extra={"setup_required": True},
            )
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
        return _render_forbidden_html(
            "You do not have permission to access Administration pages.",
            ctx=ctx,
            user=user,
        )

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
        next_target = "/administration/users?edit=me" if str(request.query.get("edit") or "") == "me" else "/administration/users"
        user, denied = _require_page_user(ctx, next_target)
        if denied:
            return denied
        assert user is not None
        edit_param = str(request.query.get("edit") or "").strip()
        if not user_has_permission(user, "users:manage") and edit_param != "me":
            return _render_forbidden_html(
                "Access denied. Missing required permission: users:manage.",
                ctx=ctx,
                user=user,
            )
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
        _ensure_db_loaded(ctx)
        if ctx.db is None:
            return _render_forbidden_html(
                "Initial setup is required. Complete setup at /setup first.", status=503, ctx=ctx
            )
        ext_err = check_external_api_access(ctx)
        if ext_err:
            return _render_forbidden_html(ext_err, status=403, ctx=ctx)
        response.headers["Content-Type"] = "text/html; charset=utf-8"
        i18n_ctx = _build_i18n_render_context(ctx, "swagger", user=None)
        return render(
            filename="swagger.html",
            path=str(get_templates_dir()),
            context={
                "header_mode": "swagger",
                "header_href": "/",
                "icon": carbon_icon,
                "XML": XML,
                **i18n_ctx,
            },
            delimiters="[[ ]]",
        )

    # Register all unified REST API controllers under aethernms/api/
    register_api_routes(_get_ctx, _SESSION)
    _ROUTES_REGISTERED = True


def create_app(
    db_path: Optional[Path | str] = None,
    db_uri: Optional[str] = None,
    config_dir: Optional[Path | str] = None,
    executor_factory: Optional[Callable[[], BatchSSHExecutor]] = None,
    ping_fn: Optional[Callable[[str], bool]] = None,
    airwave_fetch_fn: Optional[Callable[..., Tuple[Dict[str, Dict[str, Any]], str]]] = None,
    seed_snippets: bool = True,
    migrate_legacy_xml: bool = True,
) -> Tuple[Any, AppContext]:
    """Initialize Py4Web routes and database store (leaving ctx.db=None when unconfigured)."""
    global _CONTEXT

    if config_dir is not None:
        cfg_dir = Path(config_dir)
    elif db_path is not None:
        cfg_dir = Path(db_path).parent
    else:
        cfg_dir = runtime_root()
    cfg_dir.mkdir(parents=True, exist_ok=True)

    store: Optional[DatabaseStore] = None
    db_source = "unconfigured"
    cli_uri = (db_uri or "").strip()

    if cli_uri:
        eng = detect_engine_from_uri(cli_uri)
        meta_folder = None if eng == "sqlite" else get_dal_meta_dir(cfg_dir)
        store = DatabaseStore(db_uri=cli_uri, folder=meta_folder, engine=eng)
        db_source = "cli"
    elif db_path is not None:
        store = DatabaseStore(db_path=db_path)
        db_source = "cli"
    else:
        cfg_data = load_db_config(config_dir=cfg_dir)
        if cfg_data is not None:
            eng = cfg_data["engine"]
            uri = cfg_data["uri"]
            meta_folder = None if eng == "sqlite" else get_dal_meta_dir(cfg_dir)
            store = DatabaseStore(db_uri=uri, folder=meta_folder, engine=eng)
            db_source = str(cfg_data.get("source") or "config_file")
        else:
            existing_sqlite = cfg_dir / "aethernms.db"
            if existing_sqlite.is_file():
                store = DatabaseStore(db_path=existing_sqlite)
                db_source = "existing_sqlite"

    if store is not None:
        if migrate_legacy_xml:
            store.migrate_legacy_xml_files(config_dir=cfg_dir)
        if seed_snippets:
            store.seed_bundled_snippets()
        store.bootstrap_admin_from_env()

    _set_session_secret(ensure_session_secret(cfg_dir))
    ctx = AppContext(
        db=store,
        config_dir=cfg_dir,
        db_source=db_source,
        seed_snippets_default=seed_snippets,
        migrate_legacy_xml=migrate_legacy_xml,
        executor_factory=executor_factory or (lambda: BatchSSHExecutor()),
        ping_fn=ping_fn,
        airwave_fetch_fn=airwave_fetch_fn or fetch_airwave_inventory,
    )
    _CONTEXT = ctx
    _register_routes()
    return bottle.default_app(), ctx
