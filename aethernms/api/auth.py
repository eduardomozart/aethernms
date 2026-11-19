"""API Key identity (/api/auth/status) and API Keys CRUD (/api/auth/api-keys*) REST API routes."""

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


def register_auth_routes(get_ctx: CtxGetter, session: Any) -> None:
    """Register /api/auth/status and /api/auth/api-keys* routes."""

    @action("/api/auth/status", method="GET")
    @action.uses(session)
    def api_auth_status():
        ctx = get_ctx()
        user, err = require_api_user(ctx, session)
        if err:
            return err
        assert user is not None
        return json_response(
            {
                "authenticated": True,
                "auth_method": user.get("_auth_method", "session"),
                "username": user["username"],
                "display_name": user.get("display_name", ""),
                "role": user["role"],
                "permissions": list(user.get("permissions") or []),
            }
        )

    @action("/api/auth/api-keys", method="GET")
    @action.uses(session)
    def api_list_keys():
        ctx = get_ctx()
        user, err = require_api_user(ctx, session, permission="api_keys:manage")
        if err:
            return err
        assert user is not None
        can_manage_all = user_has_permission(user, "users:manage")
        items = ctx.db.list_api_keys(None if can_manage_all else user["id"])
        return json_response({"items": items})

    @action("/api/auth/api-keys", method="POST")
    @action.uses(session)
    def api_create_key():
        ctx = get_ctx()
        user, err = require_api_user(ctx, session, permission="api_keys:manage")
        if err:
            return err
        assert user is not None
        body = read_json_body()
        if body is None:
            return json_error(400, "Invalid JSON payload.")
        name = str(body.get("name") or "").strip() or "API Key"
        can_manage_all = user_has_permission(user, "users:manage")
        can_pick_role = user_has_permission(user, "roles:manage")
        target_uid = user["id"]
        if can_manage_all and body.get("user_id"):
            try:
                target_uid = int(body["user_id"])
            except (TypeError, ValueError):
                return json_error(400, "Invalid target user ID.")
        role_name = str(body.get("role_name") or "").strip() if can_pick_role else ""
        try:
            created = ctx.db.create_api_key(target_uid, name, role_name=role_name)
        except ValueError as exc:
            return json_error(400, str(exc))
        return json_response(created, status=201)

    @action("/api/auth/api-keys/<key_id:int>", method="DELETE")
    @action.uses(session)
    def api_delete_key(key_id: int):
        ctx = get_ctx()
        user, err = require_api_user(ctx, session, permission="api_keys:manage")
        if err:
            return err
        assert user is not None
        allow_any = user_has_permission(user, "users:manage")
        deleted = ctx.db.revoke_api_key(user["id"], key_id, allow_any=allow_any)
        if not deleted:
            return json_error(404, "API key not found.")
        return json_response({"ok": True})
