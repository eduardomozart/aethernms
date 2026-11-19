"""Localization catalog (/api/i18n) REST API route and shared payload builder."""

from __future__ import annotations

from typing import Any, Dict

from py4web.core import action, request

from aethernms.api.common import (
    CtxGetter,
    effective_language,
    json_response,
    require_api_user,
)
from aethernms.i18n import available_languages, export_translations, get_language_label


def build_i18n_payload(ctx: Any, requested_lang: str = "") -> Dict[str, Any]:
    """Return UI translation catalog and available locale metadata."""
    settings = ctx.db.get_settings()
    eff = effective_language(settings, requested_lang=requested_lang)
    langs = available_languages()
    return {
        "language": settings.language,
        "effective_language": eff,
        "available_languages": [
            {"code": code, "label": get_language_label(code)} for code in langs
        ],
        "catalog": export_translations(eff),
    }


def register_i18n_routes(get_ctx: CtxGetter, session: Any) -> None:
    """Register GET /api/i18n route."""

    @action("/api/i18n", method="GET")
    @action.uses(session)
    def api_i18n():
        ctx = get_ctx()
        _user, err = require_api_user(ctx, session)
        if err:
            return err
        req_lang = str(request.query.get("lang") or "").strip()
        return json_response(build_i18n_payload(ctx, requested_lang=req_lang))
