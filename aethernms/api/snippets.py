"""Snippets CRUD and XML Import/Export (/api/snippets*) REST API routes."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from py4web.core import action, request, response

from aethernms.api.common import (
    CtxGetter,
    json_error,
    json_response,
    read_json_body,
    require_api_user,
    serialize_snippet,
)
from aethernms.models import Snippet, SnippetSeverity, SnippetType
from aethernms.netmiko_catalog import canonical_platform, is_supported_platform
from aethernms.snippet_store import (
    SnippetStore,
    slugify_filename,
    snippet_from_xml_string,
    snippet_to_xml_string,
)


def _validate_snippet_payload(body: Dict[str, Any]) -> Tuple[Optional[Snippet], Optional[str]]:
    name = str(body.get("name") or "").strip()
    if not name:
        return None, "Snippet Name is required."
    raw_plat = str(body.get("device_type") or "").strip()
    plat = canonical_platform(raw_plat)
    if not plat or not is_supported_platform(plat):
        return None, f"Unsupported Netmiko platform: '{raw_plat}'."
    commands = str(body.get("commands") or "").strip("\r\n")
    if not commands.strip():
        return None, "Commands cannot be empty."
    raw_type = str(body.get("snippet_type") or SnippetType.CONFIG.value).strip()
    stype = (
        SnippetType.AUDIT
        if raw_type.lower() == SnippetType.AUDIT.value.lower()
        else SnippetType.CONFIG
    )
    raw_sev = str(body.get("severity") or SnippetSeverity.INFO.value).strip()
    sev = next(
        (s for s in SnippetSeverity if s.value.lower() == raw_sev.lower()),
        SnippetSeverity.INFO,
    )
    folder = str(body.get("folder") or "").strip() or SnippetStore.default_folder_for_os(plat)
    audit_regex = (
        str(body.get("audit_regex") or "").strip("\r\n") if stype == SnippetType.AUDIT else ""
    )
    return (
        Snippet(
            name=name,
            folder=folder,
            snippet_type=stype,
            device_type=plat,
            severity=sev,
            description=str(body.get("description") or "").strip(),
            commands=commands,
            audit_regex=audit_regex,
        ),
        None,
    )


def register_snippets_routes(get_ctx: CtxGetter, session: Any) -> None:
    """Register /api/snippets* routes."""

    @action("/api/snippets", method="GET")
    @action.uses(session)
    def api_list_snippets():
        ctx = get_ctx()
        _user, err = require_api_user(ctx, session, permission="snippets:read")
        if err:
            return err
        items = ctx.db.list_snippets()
        return json_response({"items": [serialize_snippet(s) for s in items]})

    @action("/api/snippets", method="POST")
    @action.uses(session)
    def api_create_snippet():
        ctx = get_ctx()
        _user, err = require_api_user(ctx, session, permission="snippets:write")
        if err:
            return err
        body = read_json_body()
        if body is None:
            return json_error(400, "Invalid JSON payload.")
        snip, val_err = _validate_snippet_payload(body)
        if val_err or snip is None:
            return json_error(400, val_err or "Invalid snippet payload.")
        saved = ctx.db.create_snippet(snip)
        return json_response(serialize_snippet(saved), status=201)

    @action("/api/snippets/<snippet_id:int>", method="PUT")
    @action.uses(session)
    def api_update_snippet(snippet_id: int):
        ctx = get_ctx()
        _user, err = require_api_user(ctx, session, permission="snippets:write")
        if err:
            return err
        body = read_json_body()
        if body is None:
            return json_error(400, "Invalid JSON payload.")
        snip, val_err = _validate_snippet_payload(body)
        if val_err or snip is None:
            return json_error(400, val_err or "Invalid snippet payload.")
        updated = ctx.db.update_snippet(snippet_id, snip)
        if updated is None:
            return json_error(404, "Snippet not found.")
        return json_response(serialize_snippet(updated))

    @action("/api/snippets/<snippet_id:int>", method="DELETE")
    @action.uses(session)
    def api_delete_snippet(snippet_id: int):
        ctx = get_ctx()
        _user, err = require_api_user(ctx, session, permission="snippets:write")
        if err:
            return err
        if not ctx.db.delete_snippet(snippet_id):
            return json_error(404, "Snippet not found.")
        return json_response({"ok": True})

    @action("/api/snippets/import", method="POST")
    @action.uses(session)
    def api_import_snippet():
        ctx = get_ctx()
        _user, err = require_api_user(ctx, session, permission="snippets:write")
        if err:
            return err
        ctype = (request.headers.get("Content-Type") or "").lower()
        xml_text = ""
        default_name = "snippet"
        if "application/json" in ctype:
            body = read_json_body()
            if body is None:
                return json_error(400, "Invalid JSON payload.")
            xml_text = str(body.get("xml") or "")
            default_name = Path(str(body.get("filename") or "snippet")).stem
        else:
            raw = request.body.read()
            xml_text = raw.decode("utf-8", errors="replace") if raw else ""

        if not xml_text.strip():
            return json_error(400, "XML snippet content is required.")
        try:
            snip = snippet_from_xml_string(xml_text, default_name=default_name)
        except Exception as exc:
            return json_error(400, f"Invalid Snippet XML: {exc}")
        saved = ctx.db.create_snippet(snip)
        return json_response(serialize_snippet(saved), status=201)

    @action("/api/snippets/<snippet_id:int>/export", method="GET")
    @action.uses(session)
    def api_export_snippet(snippet_id: int):
        ctx = get_ctx()
        _user, err = require_api_user(ctx, session, permission="snippets:read")
        if err:
            return err
        snip = ctx.db.get_snippet(snippet_id)
        if snip is None:
            return json_error(404, "Snippet not found.")
        xml_str = snippet_to_xml_string(snip)
        fname = f"{slugify_filename(snip.name)}.xml"
        response.status = 200
        response.headers["Content-Type"] = "application/xml; charset=utf-8"
        response.headers["Content-Disposition"] = f'attachment; filename="{fname}"'
        return xml_str
