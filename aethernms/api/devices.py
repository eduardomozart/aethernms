"""Devices CRUD, Global Device Search, and ICMP Ping (/api/devices*) REST API routes."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from py4web.core import action, request

from aethernms.api.common import (
    CtxGetter,
    activate_request_locale,
    json_error,
    json_response,
    read_json_body,
    require_api_user,
    serialize_device,
)
from aethernms.common import filter_device_hosts
from aethernms.models import (
    AppSettings,
    ConnectionProtocol,
    HostEntry,
    is_airwave_host,
)
from aethernms.netmiko_catalog import (
    canonical_platform,
    default_port_for_protocol,
    is_supported_platform,
    resolve_netmiko_device_type,
)
from aethernms.ping_checker import probe_ips_concurrently


def _validate_and_build_host(
    body: Dict[str, Any],
    settings: AppSettings,
    existing: Optional[HostEntry] = None,
) -> Tuple[Optional[HostEntry], Optional[str]]:
    if existing is not None and is_airwave_host(existing):
        ip = existing.ip
        name = existing.name
        model = existing.model
        folder_path = existing.folder_path
        folder_id = existing.folder_id
        firmware = existing.firmware
        category = existing.device_category
        serial = existing.serial_number
        aw_status = existing.airwave_status
        role = existing.device_role
        aw_os = existing.airwave_os
    else:
        ip = str(body.get("ip", existing.ip if existing else "") or "").strip()
        if not ip:
            return None, "IP Address is required."
        name = str(body.get("name", existing.name if existing else "") or "").strip()
        model = str(body.get("model", existing.model if existing else "") or "").strip()
        folder_path = str(
            body.get("folder_path", existing.folder_path if existing else "") or ""
        ).strip()
        folder_id = existing.folder_id if existing else None
        firmware = str(body.get("firmware", existing.firmware if existing else "") or "").strip()
        category = str(
            body.get("device_category", existing.device_category if existing else "") or ""
        ).strip()
        serial = str(
            body.get("serial_number", existing.serial_number if existing else "") or ""
        ).strip()
        aw_status = existing.airwave_status if existing else "Manual"
        role = existing.device_role if existing else ""
        aw_os = existing.airwave_os if existing else ""

    raw_os = str(body.get("os_type", existing.os_type if existing else "") or "").strip()
    plat = canonical_platform(raw_os)
    if not plat or not is_supported_platform(plat):
        return None, f"Unsupported Netmiko platform: '{raw_os}'."

    raw_proto = str(
        body.get(
            "protocol",
            existing.protocol.value if existing else settings.default_protocol.value,
        )
        or ""
    ).strip().lower()
    proto = (
        ConnectionProtocol.TELNET
        if raw_proto == ConnectionProtocol.TELNET.value.lower()
        else ConnectionProtocol.SSH
    )
    try:
        resolve_netmiko_device_type(plat, proto)
    except ValueError as exc:
        return None, str(exc)

    default_port = default_port_for_protocol(proto, settings)
    try:
        port = int(body.get("port", existing.port if existing else default_port))
    except (TypeError, ValueError):
        return None, "Port must be an integer between 1 and 65535."
    if not (1 <= port <= 65535):
        return None, "Port must be an integer between 1 and 65535."

    host = HostEntry(
        id=existing.id if existing else None,
        name=name,
        ip=ip,
        os_type=plat,
        protocol=proto,
        port=port,
        model=model,
        firmware=firmware,
        folder_id=folder_id,
        folder_path=folder_path,
        device_category=category,
        serial_number=serial,
        airwave_status=aw_status,
        device_role=role,
        airwave_os=aw_os,
        enabled=bool(body.get("enabled", existing.enabled if existing else True)),
        ping_status=existing.ping_status if existing else "Unknown",
    )
    return host, None


def register_devices_routes(get_ctx: CtxGetter, session: Any) -> None:
    """Register /api/devices* routes."""

    @action("/api/devices/search", method="GET")
    @action.uses(session)
    def api_search_devices():
        ctx = get_ctx()
        _user, err = require_api_user(ctx, session, permission="devices:read")
        if err:
            return err
        q = str(request.query.get("q") or "").strip()
        try:
            limit = max(1, min(50, int(request.query.get("limit") or 10)))
        except (TypeError, ValueError):
            limit = 10
        matches = ctx.db.search_devices(q, limit=limit)
        return json_response({"query": q, "items": [serialize_device(h) for h in matches]})

    @action("/api/devices", method="GET")
    @action.uses(session)
    def api_list_devices():
        ctx = get_ctx()
        user, err = require_api_user(ctx, session, permission="devices:read")
        if err:
            return err
        activate_request_locale(ctx, user=user)
        hosts = ctx.db.list_devices()
        _indexed, filtered = filter_device_hosts(
            hosts,
            name_q=str(request.query.get("name") or ""),
            ip_q=str(request.query.get("ip") or ""),
            os_q=str(request.query.get("os") or "All"),
            group_q=str(request.query.get("group") or ""),
            status_q=str(request.query.get("status") or "All"),
        )
        return json_response({"items": [serialize_device(h) for h in filtered]})

    @action("/api/devices", method="POST")
    @action.uses(session)
    def api_create_device():
        ctx = get_ctx()
        _user, err = require_api_user(ctx, session, permission="devices:write")
        if err:
            return err
        body = read_json_body()
        if body is None:
            return json_error(400, "Invalid JSON payload.")
        settings = ctx.db.get_settings()
        host, val_err = _validate_and_build_host(body, settings)
        if val_err or host is None:
            return json_error(400, val_err or "Invalid device data.")
        saved = ctx.db.create_or_replace_device(host)
        return json_response(serialize_device(saved), status=201)

    @action("/api/devices/<device_id:int>", method="PUT")
    @action.uses(session)
    def api_update_device(device_id: int):
        ctx = get_ctx()
        _user, err = require_api_user(ctx, session, permission="devices:write")
        if err:
            return err
        existing = ctx.db.get_device(device_id)
        if existing is None:
            return json_error(404, "Device not found.")
        body = read_json_body()
        if body is None:
            return json_error(400, "Invalid JSON payload.")
        settings = ctx.db.get_settings()
        host, val_err = _validate_and_build_host(body, settings, existing=existing)
        if val_err or host is None:
            return json_error(400, val_err or "Invalid device data.")
        updated = ctx.db.update_device(device_id, host)
        if updated is None:
            return json_error(404, "Device not found.")
        return json_response(serialize_device(updated))

    @action("/api/devices/<device_id:int>", method="DELETE")
    @action.uses(session)
    def api_delete_device(device_id: int):
        ctx = get_ctx()
        _user, err = require_api_user(ctx, session, permission="devices:write")
        if err:
            return err
        if not ctx.db.delete_device(device_id):
            return json_error(404, "Device not found.")
        return json_response({"ok": True})

    @action("/api/devices/ping", method="POST")
    @action.uses(session)
    def api_ping_devices():
        ctx = get_ctx()
        _user, err = require_api_user(ctx, session, permission="devices:read")
        if err:
            return err
        body = read_json_body() or {}
        req_ids = body.get("device_ids")
        hosts = ctx.db.list_devices()
        if isinstance(req_ids, list) and req_ids:
            id_set = {int(i) for i in req_ids if str(i).isdigit()}
            targets_hosts = [h for h in hosts if h.id in id_set]
        else:
            targets_hosts = hosts

        targets = [(h.unique_key, h.ip) for h in targets_hosts]
        statuses = probe_ips_concurrently(targets, ping_fn=ctx.ping_fn)
        ctx.db.update_ping_statuses(statuses)
        by_id = {
            str(h.id): statuses.get(h.unique_key, h.ping_status)
            for h in targets_hosts
            if h.id is not None
        }
        return json_response({"statuses": statuses, "by_id": by_id})
