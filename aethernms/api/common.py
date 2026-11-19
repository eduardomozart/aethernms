"""Shared REST API request/response, RBAC, External API IP gate, and JSON serialization helpers."""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional, Tuple

from py4web.core import request, response

from aethernms.auth import DEFAULT_API_ALLOWED_IPS, is_ip_allowed
from aethernms.common import format_operation_result_ui
from aethernms.i18n import available_languages, set_language
from aethernms.models import (
    AppSettings,
    HostEntry,
    HostExecutionResult,
    JobRecord,
    Snippet,
    is_airwave_host,
)
from aethernms.os_integration import detect_os_language, match_supported_language

CtxGetter = Callable[[], Any]


def json_response(payload: Any, status: int = 200) -> str:
    response.status = status
    response.headers["Content-Type"] = "application/json; charset=utf-8"
    return json.dumps(payload, ensure_ascii=False)


def json_error(
    status: int,
    message: str,
    errors: Optional[List[str]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> str:
    body: Dict[str, Any] = {"error": message}
    if errors is not None:
        body["errors"] = errors
    if extra:
        body.update(extra)
    return json_response(body, status=status)


def read_json_body() -> Optional[Dict[str, Any]]:
    try:
        raw = request.body.read()
    except Exception:
        raw = b""
    if not raw:
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def get_client_ip() -> str:
    return str(request.environ.get("REMOTE_ADDR") or "").strip()


def extract_api_key_header() -> str:
    direct = (request.headers.get("X-API-Key") or "").strip()
    if direct:
        return direct
    auth_hdr = (request.headers.get("Authorization") or "").strip()
    if auth_hdr.lower().startswith("bearer "):
        return auth_hdr[7:].strip()
    return ""


def check_external_api_access(ctx: Any) -> Optional[str]:
    """Enforce System Settings External API toggle and IP/CIDR allowlist. Returns error message or None."""
    settings = ctx.db.get_settings()
    if not settings.api_enabled:
        return "External API and Swagger access is disabled. Enable it in Administration -> System Settings."
    client_ip = get_client_ip()
    if not is_ip_allowed(client_ip, settings.api_allowed_ips or DEFAULT_API_ALLOWED_IPS):
        return f"External API access denied for IP address '{client_ip or 'unknown'}'."
    return None


def user_has_permission(user: Dict[str, Any], permission: str) -> bool:
    return permission in set(user.get("permissions") or [])


def resolve_session_user(ctx: Any, session: Any) -> Optional[Dict[str, Any]]:
    uid = session.get("user_id")
    if uid:
        user = ctx.db.get_user_by_id(int(uid))
        if user is not None and user.get("is_active", True):
            return user
    return None


def require_api_user(
    ctx: Any,
    session: Any,
    permission: Optional[str] = None,
    any_permissions: Optional[Tuple[str, ...]] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Authenticate a unified /api/* request via API Key (external) or signed Web UI browser session cookie.

    - External API Key requests (X-API-Key / Authorization: Bearer): gated by api_enabled + IP allowlist.
    - Signed Web UI browser session cookies (issued exclusively by /login and /setup): always allowed for
      authenticated UI interactions so administrators can manage the application even while External API is disabled.
    - Unauthenticated requests (neither API Key nor session cookie): 403 when External API is disabled or IP is
      blocked, else 401 requiring an API Key.
    """
    api_token = extract_api_key_header()
    if api_token:
        ext_err = check_external_api_access(ctx)
        if ext_err:
            return None, json_error(403, ext_err)
        user = ctx.db.authenticate_api_key(api_token)
        if user is None:
            return None, json_error(401, "Invalid or revoked API key.")
        user = dict(user)
        user["_auth_method"] = "api_key"
    else:
        session_user = resolve_session_user(ctx, session)
        if session_user is None:
            ext_err = check_external_api_access(ctx)
            if ext_err:
                return None, json_error(403, ext_err, extra={"auth_required": True})
            return None, json_error(
                401,
                "API key authentication required. Provide X-API-Key or Authorization: Bearer <token>.",
                extra={"auth_required": True},
            )
        user = dict(session_user)
        user["_auth_method"] = "session"

    if permission and not user_has_permission(user, permission):
        return None, json_error(403, f"Missing required permission: '{permission}'.")
    if any_permissions and not any(user_has_permission(user, p) for p in any_permissions):
        return None, json_error(403, "Insufficient permissions for this operation.")
    return user, None


def effective_language(settings: AppSettings, requested_lang: str = "") -> str:
    langs = available_languages()
    req = (requested_lang or "").strip()
    if req and req != "auto" and req in langs:
        return req
    saved = (settings.language or "auto").strip()
    if saved != "auto" and saved in langs:
        return saved
    accept_hdr = (request.headers.get("Accept-Language") or "").strip()
    if accept_hdr:
        for chunk in accept_hdr.split(","):
            code = chunk.split(";", 1)[0].strip()
            matched = match_supported_language(code, langs)
            if matched:
                return matched
    return detect_os_language(langs)


def activate_request_locale(ctx: Any, requested_lang: str = "") -> str:
    settings = ctx.db.get_settings()
    eff = effective_language(settings, requested_lang=requested_lang)
    set_language(eff)
    return eff


def serialize_settings(s: AppSettings, include_client_ip: bool = False) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "language": s.language,
        "theme_mode": s.theme_mode,
        "ssh_username": s.ssh_username,
        "default_protocol": s.default_protocol.value,
        "ssh_port": int(s.ssh_port),
        "telnet_port": int(s.telnet_port),
        "schedule_sequence": s.schedule_sequence.value,
        "max_parallel": int(s.max_parallel),
        "command_timeout": int(s.command_timeout),
        "connect_timeout": int(s.connect_timeout),
        "airwave_url": s.airwave_url,
        "airwave_username": s.airwave_username,
        "airwave_verify_ssl": bool(s.airwave_verify_ssl),
        "airwave_os_mappings": dict(s.airwave_os_mappings or {}),
        "api_enabled": bool(s.api_enabled),
        "api_allowed_ips": s.api_allowed_ips or DEFAULT_API_ALLOWED_IPS,
    }
    if include_client_ip:
        out["client_ip"] = get_client_ip()
    return out


def serialize_device(h: HostEntry) -> Dict[str, Any]:
    return {
        "id": h.id,
        "name": h.name,
        "ip": h.ip,
        "os_type": h.os_type,
        "protocol": h.protocol.value,
        "port": int(h.port),
        "model": h.model,
        "firmware": h.firmware,
        "folder_id": h.folder_id,
        "folder_path": h.folder_path,
        "device_category": h.device_category,
        "serial_number": h.serial_number,
        "airwave_status": h.airwave_status,
        "device_role": h.device_role,
        "airwave_os": h.airwave_os,
        "enabled": bool(h.enabled),
        "ping_status": h.ping_status or "Unknown",
        "is_airwave": is_airwave_host(h),
        "unique_key": h.unique_key,
        "display_label": h.display_label,
    }


def serialize_snippet(s: Snippet) -> Dict[str, Any]:
    return {
        "id": s.id,
        "name": s.name,
        "folder": s.folder,
        "snippet_type": s.snippet_type.value,
        "device_type": s.device_type,
        "severity": s.severity.value,
        "description": s.description,
        "commands": s.commands,
        "audit_regex": s.audit_regex,
        "created_at": s.created_at,
    }


def serialize_job_result(res: HostExecutionResult) -> Dict[str, Any]:
    return {
        "id": res.id,
        "host_key": res.host.unique_key,
        "host_name": res.host.display_label,
        "host_ip": res.host.ip,
        "host_port": int(res.host.port),
        "host_os": res.host.os_type,
        "host_protocol": res.host.protocol.value,
        "status": res.status,
        "started_at": res.started_at,
        "finished_at": res.finished_at,
        "operation_result": res.operation_result,
        "operation_result_localized": format_operation_result_ui(res.operation_result),
        "connection_method": res.connection_method
        or f"{res.host.protocol.value} ({res.host.os_type or '-'})",
        "has_log": bool(res.formatted_log or res.raw_output or res.exception_message),
    }


def serialize_job(job: JobRecord, include_results: bool = True) -> Dict[str, Any]:
    total = len(job.results)
    ok_cnt = sum(1 for r in job.results if r.status == "Success")
    fail_cnt = sum(1 for r in job.results if r.status == "Failed")
    data: Dict[str, Any] = {
        "job_id": job.job_id,
        "name": job.name,
        "job_type": job.job_type.value,
        "device_type": job.device_type,
        "status": job.status,
        "creation_time": job.creation_time,
        "start_time": job.start_time,
        "end_time": job.end_time,
        "description": job.description,
        "snippet_name": job.snippet_name,
        "commands_raw": job.commands_raw,
        "commands_rendered": job.commands_rendered,
        "audit_regex": job.audit_regex,
        "max_parallel": int(job.max_parallel),
        "schedule_sequence": job.schedule_sequence.value,
        "include_write": bool(job.include_write),
        "parameters_masked": dict(job.parameters_masked or {}),
        "counts": {"total": total, "success": ok_cnt, "failed": fail_cnt},
    }
    if include_results:
        data["results"] = [serialize_job_result(r) for r in job.results]
    return data
