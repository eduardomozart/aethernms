"""System Settings (/api/settings) REST API routes."""

from __future__ import annotations

from typing import Any

from py4web.core import action

from aethernms.api.common import (
    CtxGetter,
    json_error,
    json_response,
    read_json_body,
    require_api_user,
    serialize_settings,
)
from aethernms.auth import DEFAULT_API_ALLOWED_IPS, parse_ip_allowlist
from aethernms.models import AppSettings, ConnectionProtocol, ScheduleSequence


def register_settings_routes(get_ctx: CtxGetter, session: Any) -> None:
    """Register GET/PUT /api/settings routes."""

    @action("/api/settings", method="GET")
    @action.uses(session)
    def api_get_settings():
        ctx = get_ctx()
        _user, err = require_api_user(ctx, session)
        if err:
            return err
        return json_response(serialize_settings(ctx.db.get_settings(), include_client_ip=True))

    @action("/api/settings", method="PUT")
    @action.uses(session)
    def api_put_settings():
        ctx = get_ctx()
        _user, err = require_api_user(ctx, session, permission="system:settings")
        if err:
            return err
        body = read_json_body()
        if body is None:
            return json_error(400, "Invalid JSON payload.")

        current = ctx.db.get_settings()
        lang = str(body.get("language", current.language) or "auto").strip()
        theme = str(body.get("theme_mode", current.theme_mode) or "auto").strip().lower()
        if theme not in ("auto", "light", "dark"):
            theme = "auto"
        raw_proto = str(body.get("default_protocol", current.default_protocol.value)).strip().lower()
        proto = (
            ConnectionProtocol.TELNET
            if raw_proto == ConnectionProtocol.TELNET.value.lower()
            else ConnectionProtocol.SSH
        )
        raw_seq = str(body.get("schedule_sequence", current.schedule_sequence.value)).strip().lower()
        seq = (
            ScheduleSequence.SEQUENTIAL
            if raw_seq == ScheduleSequence.SEQUENTIAL.value.lower()
            else ScheduleSequence.CONCURRENT
        )

        def _bounded_int(key: str, default: int, lo: int, hi: int) -> int:
            try:
                return max(lo, min(hi, int(body.get(key, default))))
            except (TypeError, ValueError):
                return default

        os_mappings = current.airwave_os_mappings
        if isinstance(body.get("airwave_os_mappings"), dict):
            os_mappings = {
                str(k).strip(): str(v).strip()
                for k, v in body["airwave_os_mappings"].items()
                if str(k).strip() and str(v).strip()
            }

        api_enabled = bool(body.get("api_enabled", current.api_enabled))
        raw_ips = str(
            body.get("api_allowed_ips", current.api_allowed_ips or DEFAULT_API_ALLOWED_IPS) or ""
        ).strip()
        parsed_ips, ip_err = parse_ip_allowlist(raw_ips)
        if ip_err:
            return json_error(400, ip_err)
        norm_ips = ", ".join(parsed_ips)

        updated = AppSettings(
            language=lang,
            theme_mode=theme,
            ssh_username=str(body.get("ssh_username", current.ssh_username) or "").strip(),
            default_protocol=proto,
            ssh_port=_bounded_int("ssh_port", current.ssh_port, 1, 65535),
            telnet_port=_bounded_int("telnet_port", current.telnet_port, 1, 65535),
            schedule_sequence=seq,
            max_parallel=_bounded_int("max_parallel", current.max_parallel, 1, 64),
            command_timeout=_bounded_int("command_timeout", current.command_timeout, 1, 300),
            connect_timeout=_bounded_int("connect_timeout", current.connect_timeout, 1, 120),
            airwave_url=str(body.get("airwave_url", current.airwave_url) or "").strip(),
            airwave_username=str(
                body.get("airwave_username", current.airwave_username) or ""
            ).strip(),
            airwave_verify_ssl=bool(
                body.get("airwave_verify_ssl", current.airwave_verify_ssl)
            ),
            airwave_filters=current.airwave_filters,
            airwave_os_mappings=os_mappings,
            api_enabled=api_enabled,
            api_allowed_ips=norm_ips,
        )
        saved = ctx.db.save_settings(updated)
        return json_response(serialize_settings(saved, include_client_ip=True))
