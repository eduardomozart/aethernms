"""Roles & RBAC permissions CRUD (/api/roles*) REST API routes."""

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
from aethernms.auth import ALL_PERMISSIONS


def register_roles_routes(get_ctx: CtxGetter, session: Any) -> None:
    """Register /api/roles and /api/roles/<role_id:int> routes."""

    @action("/api/roles", method="GET")
    @action.uses(session)
    def api_list_roles():
        ctx = get_ctx()
        _user, err = require_api_user(
            ctx, session, any_permissions=("roles:manage", "users:manage", "api_keys:manage")
        )
        if err:
            return err
        return json_response({"items": ctx.db.list_roles(), "all_permissions": list(ALL_PERMISSIONS)})

    @action("/api/roles", method="POST")
    @action.uses(session)
    def api_create_role():
        ctx = get_ctx()
        _user, err = require_api_user(ctx, session, permission="roles:manage")
        if err:
            return err
        body = read_json_body()
        if body is None:
            return json_error(400, "Invalid JSON payload.")
        raw_perms = body.get("permissions")
        if not isinstance(raw_perms, list):
            return json_error(400, "Permissions must be a list of permission keys.")
        try:
            created = ctx.db.create_role(
                name=str(body.get("name") or "").strip(),
                permissions=raw_perms,
                description=str(body.get("description") or "").strip(),
            )
        except ValueError as exc:
            return json_error(400, str(exc))
        return json_response(created, status=201)

    @action("/api/roles/<role_id:int>", method="PUT")
    @action.uses(session)
    def api_update_role(role_id: int):
        ctx = get_ctx()
        _user, err = require_api_user(ctx, session, permission="roles:manage")
        if err:
            return err
        body = read_json_body()
        if body is None:
            return json_error(400, "Invalid JSON payload.")
        raw_perms = body.get("permissions")
        if raw_perms is not None and not isinstance(raw_perms, list):
            return json_error(400, "Permissions must be a list of permission keys.")
        try:
            updated = ctx.db.update_role(
                role_id=role_id,
                name=str(body["name"]).strip() if "name" in body else None,
                permissions=raw_perms,
                description=str(body["description"]).strip() if "description" in body else None,
            )
        except ValueError as exc:
            msg = str(exc)
            status = 403 if "read-only" in msg.lower() else 400
            return json_error(status, msg)
        if updated is None:
            return json_error(404, "Role not found.")
        return json_response(updated)

    @action("/api/roles/<role_id:int>", method="DELETE")
    @action.uses(session)
    def api_delete_role(role_id: int):
        ctx = get_ctx()
        _user, err = require_api_user(ctx, session, permission="roles:manage")
        if err:
            return err
        try:
            deleted = ctx.db.delete_role(role_id)
        except ValueError as exc:
            msg = str(exc)
            status = 403 if "system role" in msg.lower() else 400
            return json_error(status, msg)
        if not deleted:
            return json_error(404, "Role not found.")
        return json_response({"ok": True})
