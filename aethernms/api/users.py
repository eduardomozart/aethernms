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
)


def register_users_routes(get_ctx: CtxGetter, session: Any) -> None:
    """Register /api/users and /api/users/<user_id:int> routes."""

    @action("/api/users", method="GET")
    @action.uses(session)
    def api_list_users():
        ctx = get_ctx()
        _user, err = require_api_user(ctx, session, permission="users:manage")
        if err:
            return err
        return json_response({"items": ctx.db.list_users()})

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
            )
        except ValueError as exc:
            return json_error(400, str(exc))
        return json_response(created, status=201)

    @action("/api/users/<user_id:int>", method="PUT")
    @action.uses(session)
    def api_update_user(user_id: int):
        ctx = get_ctx()
        cur_user, err = require_api_user(ctx, session, permission="users:manage")
        if err:
            return err
        assert cur_user is not None
        body = read_json_body()
        if body is None:
            return json_error(400, "Invalid JSON payload.")
        if user_id == cur_user["id"] and body.get("is_active") is False:
            return json_error(400, "You cannot disable your own account.")
        try:
            updated = ctx.db.update_user(
                user_id=user_id,
                role=str(body["role"]).strip() if "role" in body else None,
                display_name=str(body["display_name"]).strip() if "display_name" in body else None,
                is_active=bool(body["is_active"]) if "is_active" in body else None,
                password=str(body["password"]) if body.get("password") else None,
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
