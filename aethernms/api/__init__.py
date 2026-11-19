"""1-to-1 route-aligned REST API subpackage registering all unified /api/* endpoints for aethernms."""

from __future__ import annotations

from typing import Any

from aethernms.api.airwave import register_airwave_routes
from aethernms.api.auth import register_auth_routes
from aethernms.api.common import CtxGetter
from aethernms.api.devices import register_devices_routes
from aethernms.api.i18n import register_i18n_routes
from aethernms.api.jobs import register_jobs_routes
from aethernms.api.meta import register_meta_routes
from aethernms.api.openapi import build_openapi_spec, register_openapi_routes
from aethernms.api.roles import register_roles_routes
from aethernms.api.settings import register_settings_routes
from aethernms.api.snippets import register_snippets_routes
from aethernms.api.users import register_users_routes
from aethernms.api.variables import register_variables_routes


def register_api_routes(get_ctx: CtxGetter, session: Any) -> None:
    """Register all aethernms /api/* REST controllers on the active Py4Web app."""
    register_openapi_routes(get_ctx)
    register_auth_routes(get_ctx, session)
    register_users_routes(get_ctx, session)
    register_roles_routes(get_ctx, session)
    register_i18n_routes(get_ctx, session)
    register_meta_routes(get_ctx, session)
    register_settings_routes(get_ctx, session)
    register_devices_routes(get_ctx, session)
    register_airwave_routes(get_ctx, session)
    register_snippets_routes(get_ctx, session)
    register_variables_routes(get_ctx, session)
    register_jobs_routes(get_ctx, session)


__all__ = ["build_openapi_spec", "register_api_routes"]
