"""Users CRUD (/api/users*) REST API routes."""

from __future__ import annotations

from typing import Any

from py4web.core import action

from aethernms.api.common import (
    CtxGetter,
    json_error,
    json_response,
    read_json_body,
    require_api_user,
    user_has_permission,
)


def register_users_routes(get_ctx: CtxGetter, session: Any) -> None:
    """Register /api/users and /api/users/<user_id:int> routes."""

    @action("/api/users", method="GET")
    @action.uses(session)
    def api_list_users():
        ctx = get_ctx()
        cur_user, err = require_api_user(ctx, session)
        if err:
            return err
        assert cur_user is not None
        can_manage = user_has_permission(cur_user, "users:manage")
        if can_manage:
            return json_response({"items": ctx.db.list_users(), "can_manage_users": True})
        self_rec = ctx.db.get_user_by_id(int(cur_user["id"]))
        items = [self_rec] if self_rec is not None else []
        return json_response({"items": items, "can_manage_users": False})

    @action("/api/users", method="POST")
    @action.uses(session)
    def api_create_user():
        ctx = get_ctx()
        _user, err = require_api_user(ctx, session, permission="users:manage")
        if err:
            return err
        body = read_json_body()
        if body is None:
            return json_error(400, "Invalid JSON payload.")
        try:
            created = ctx.db.create_user(
                username=str(body.get("username") or "").strip(),
                password=str(body.get("password") or ""),
                role=str(body.get("role") or "Viewer").strip(),
                display_name=str(body.get("display_name") or "").strip(),
                is_active=bool(body.get("is_active", True)),
                language=str(body.get("language") or "auto").strip() or "auto",
                theme_mode=str(body.get("theme_mode") or "auto").strip().lower() or "auto",
            )
        except ValueError as exc:
            return json_error(400, str(exc))
        return json_response(created, status=201)

    @action("/api/users/<user_id:int>", method="PUT")
    @action.uses(session)
    def api_update_user(user_id: int):
        ctx = get_ctx()
        cur_user, err = require_api_user(ctx, session)
        if err:
            return err
        assert cur_user is not None
        can_manage = user_has_permission(cur_user, "users:manage")
        is_self = int(user_id) == int(cur_user["id"])
        if not can_manage and not is_self:
            return json_error(403, "Missing required permission: 'users:manage'.")

        body = read_json_body()
        if body is None:
            return json_error(400, "Invalid JSON payload.")

        if can_manage:
            if is_self and body.get("is_active") is False:
                return json_error(400, "You cannot disable your own account.")
            role_arg = str(body["role"]).strip() if "role" in body else None
            active_arg = bool(body["is_active"]) if "is_active" in body else None
            pw_arg = str(body["password"]) if body.get("password") else None
        else:
            # Self-service profile mode: only display_name, language, theme_mode, and verified password change.
            if "role" in body and str(body["role"]).strip() != str(cur_user.get("role") or ""):
                return json_error(403, "Missing required permission: 'users:manage'.")
            if "is_active" in body and bool(body["is_active"]) is not bool(cur_user.get("is_active", True)):
                return json_error(403, "Missing required permission: 'users:manage'.")
            role_arg = None
            active_arg = None
            pw_arg = str(body["password"]) if body.get("password") else None
            if pw_arg:
                cur_pw = str(body.get("current_password") or "")
                if not ctx.db.verify_user_password(int(cur_user["id"]), cur_pw):
                    return json_error(400, "Current password is incorrect.")

        try:
            updated = ctx.db.update_user(
                user_id=user_id,
                role=role_arg,
                display_name=str(body["display_name"]).strip() if "display_name" in body else None,
                is_active=active_arg,
                password=pw_arg,
                language=str(body["language"]).strip() if "language" in body else None,
                theme_mode=str(body["theme_mode"]).strip().lower() if "theme_mode" in body else None,
            )
        except ValueError as exc:
            return json_error(400, str(exc))
        if updated is None:
            return json_error(404, "User not found.")
        return json_response(updated)

    @action("/api/users/<user_id:int>", method="DELETE")
    @action.uses(session)
    def api_delete_user(user_id: int):
        ctx = get_ctx()
        cur_user, err = require_api_user(ctx, session, permission="users:manage")
        if err:
            return err
        assert cur_user is not None
        if user_id == cur_user["id"]:
            return json_error(400, "You cannot delete your own account.")
        try:
            deleted = ctx.db.delete_user(user_id)
        except ValueError as exc:
            return json_error(400, str(exc))
        if not deleted:
            return json_error(404, "User not found.")
        return json_response({"ok": True})
