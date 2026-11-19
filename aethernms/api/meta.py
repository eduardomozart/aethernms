"""Application metadata and Netmiko platform catalog (/api/meta) REST API route."""

from __future__ import annotations

from typing import Any

from py4web.core import action

from aethernms import __app_name__, __version__
from aethernms.api.common import (
    CtxGetter,
    get_client_ip,
    json_response,
    require_api_user,
)
from aethernms.auth import ALL_PERMISSIONS
from aethernms.carbon_icons import export_ui_icon_subset
from aethernms.job_builder import (
    discover_used_platforms,
    get_assigned_groups,
    get_assigned_models,
    job_platform_choices,
)
from aethernms.models import ConnectionProtocol, SnippetSeverity, SnippetType
from aethernms.netmiko_catalog import get_supported_platforms, get_supported_protocols
from aethernms.os_integration import detect_os_theme
from aethernms.paths import get_repository_url


def register_meta_routes(get_ctx: CtxGetter, session: Any) -> None:
    """Register GET /api/meta route."""

    @action("/api/meta", method="GET")
    @action.uses(session)
    def api_meta():
        ctx = get_ctx()
        user, err = require_api_user(ctx, session)
        if err:
            return err
        assert user is not None
        snippets = ctx.db.list_snippets()
        devices = ctx.db.list_devices()
        jobs = ctx.db.list_jobs()
        settings = ctx.db.get_settings()
        platforms = get_supported_platforms()
        protocols_by_platform = {
            plat: [p.value for p in get_supported_protocols(plat)] for plat in platforms
        }
        return json_response(
            {
                "app_name": __app_name__,
                "version": __version__,
                "repository_url": get_repository_url(),
                "user_id": user["id"],
                "username": user["username"],
                "display_name": user.get("display_name", ""),
                "role": user.get("role", "Viewer"),
                "permissions": list(user.get("permissions") or []),
                "all_permissions": list(ALL_PERMISSIONS),
                "api_enabled": bool(settings.api_enabled),
                "client_ip": get_client_ip(),
                "icons": export_ui_icon_subset(),
                "os_theme": detect_os_theme(),
                "platforms": platforms,
                "job_platform_choices": job_platform_choices(snippets),
                "used_platforms": discover_used_platforms(snippets, devices, jobs),
                "protocols_by_platform": protocols_by_platform,
                "assigned_models": get_assigned_models(devices),
                "assigned_groups": get_assigned_groups(devices),
                "severities": [s.value for s in SnippetSeverity],
                "snippet_types": [t.value for t in SnippetType],
                "protocols": [p.value for p in ConnectionProtocol],
            }
        )
