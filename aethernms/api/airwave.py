"""Aruba AirWave Discovery and Import (/api/airwave/*) REST API routes."""

from __future__ import annotations

from typing import Any, Dict, List

from py4web.core import action

from aethernms.airwave_importer import (
    airwave_mapping_key,
    build_folder_hierarchy_options,
    parse_airwave_devices,
)
from aethernms.api.common import (
    CtxGetter,
    json_error,
    json_response,
    read_json_body,
    require_api_user,
    serialize_device,
)
from aethernms.models import (
    AirWaveFilter,
    ConnectionProtocol,
    HostEntry,
    is_airwave_host,
)
from aethernms.netmiko_catalog import (
    canonical_platform,
    default_port_for_protocol,
    default_protocol_for_platform,
    is_supported_platform,
)


def register_airwave_routes(get_ctx: CtxGetter, session: Any) -> None:
    """Register POST /api/airwave/fetch and POST /api/airwave/import routes."""

    @action("/api/airwave/fetch", method="POST")
    @action.uses(session)
    def api_airwave_fetch():
        ctx = get_ctx()
        _user, err = require_api_user(ctx, session, permission="airwave:import")
        if err:
            return err
        body = read_json_body()
        if body is None:
            return json_error(400, "Invalid JSON payload.")

        url = str(body.get("url") or "").strip()
        username = str(body.get("username") or "").strip()
        password = str(body.get("password") or "")
        verify_ssl = bool(body.get("verify_ssl", False))
        if not url or not username or not password:
            return json_error(400, "AirWave URL, username, and password are required.")

        settings = ctx.db.get_settings()
        try:
            folders, ap_xml = ctx.airwave_fetch_fn(
                url=url,
                username=username,
                password=password,
                verify_ssl=verify_ssl,
            )
        except Exception as exc:
            return json_error(400, str(exc))

        hosts, total_records = parse_airwave_devices(
            ap_xml,
            folders=folders,
            filters=AirWaveFilter(category="switch", include_stacked=False),
            settings=settings,
        )

        existing_aw = [h for h in ctx.db.list_devices() if is_airwave_host(h)]
        by_key = {h.unique_key: h for h in existing_aw}
        by_ip = {h.ip.strip(): h for h in existing_aw}
        preselected_keys: List[str] = []
        for h in hosts:
            prev = by_key.get(h.unique_key) or by_ip.get(h.ip.strip())
            if prev is not None:
                preselected_keys.append(h.unique_key)
                if is_supported_platform(prev.os_type):
                    h.os_type = prev.os_type
                    h.protocol = default_protocol_for_platform(prev.os_type, prev.protocol)
                    h.port = int(prev.port or default_port_for_protocol(h.protocol, settings))

        unmapped_groups: Dict[str, Dict[str, Any]] = {}
        for h in hosts:
            if not is_supported_platform(h.os_type):
                mkey = airwave_mapping_key(h)
                grp = unmapped_groups.setdefault(
                    mkey,
                    {"key": mkey, "count": 0, "firmware": h.firmware, "model": h.model},
                )
                grp["count"] += 1

        folder_opts = [
            {"label": lbl, "id": fid} for lbl, fid in build_folder_hierarchy_options(folders)
        ]
        return json_response(
            {
                "folder_options": folder_opts,
                "items": [serialize_device(h) for h in hosts],
                "total_records": total_records,
                "preselected_keys": preselected_keys,
                "unmapped_groups": sorted(
                    unmapped_groups.values(), key=lambda g: g["key"].lower()
                ),
            }
        )

    @action("/api/airwave/import", method="POST")
    @action.uses(session)
    def api_airwave_import():
        ctx = get_ctx()
        _user, err = require_api_user(ctx, session, permission="airwave:import")
        if err:
            return err
        body = read_json_body()
        if body is None:
            return json_error(400, "Invalid JSON payload.")

        raw_devices = body.get("devices")
        if not isinstance(raw_devices, list) or not raw_devices:
            return json_error(400, "Select at least one device to import.")

        settings = ctx.db.get_settings()
        new_mappings = body.get("os_mappings")
        if isinstance(new_mappings, dict):
            for k, v in new_mappings.items():
                ck = str(k or "").strip()
                cp = canonical_platform(str(v or ""))
                if ck and cp and is_supported_platform(cp):
                    settings.airwave_os_mappings[ck] = cp

        if "airwave_url" in body:
            settings.airwave_url = str(body.get("airwave_url") or "").strip()
        if "airwave_username" in body:
            settings.airwave_username = str(body.get("airwave_username") or "").strip()
        if "airwave_verify_ssl" in body:
            settings.airwave_verify_ssl = bool(body.get("airwave_verify_ssl"))

        lowered_maps = {k.lower(): v for k, v in settings.airwave_os_mappings.items()}
        to_import: List[HostEntry] = []
        unmapped_names: List[str] = []

        for item in raw_devices:
            if not isinstance(item, dict):
                continue
            raw_os = str(item.get("os_type") or "").strip()
            plat = canonical_platform(raw_os)
            aw_os = str(item.get("airwave_os") or "").strip()
            model = str(item.get("model") or "").strip()
            name = str(item.get("name") or "").strip()
            ip = str(item.get("ip") or "").strip()
            if not ip:
                continue
            if not plat or not is_supported_platform(plat):
                for cand in (aw_os, model, name, ip):
                    cl = cand.lower()
                    if cl and cl in lowered_maps:
                        plat = lowered_maps[cl]
                        break
            if not plat or not is_supported_platform(plat):
                unmapped_names.append(name or ip)
                continue

            raw_proto = str(item.get("protocol") or settings.default_protocol.value).strip().lower()
            pref_proto = (
                ConnectionProtocol.TELNET
                if raw_proto == ConnectionProtocol.TELNET.value.lower()
                else ConnectionProtocol.SSH
            )
            proto = default_protocol_for_platform(plat, pref_proto)
            def_port = default_port_for_protocol(proto, settings)
            try:
                port = max(1, min(65535, int(item.get("port") or def_port)))
            except (TypeError, ValueError):
                port = def_port

            to_import.append(
                HostEntry(
                    name=name,
                    ip=ip,
                    os_type=plat,
                    protocol=proto,
                    port=port,
                    model=model,
                    firmware=str(item.get("firmware") or "").strip(),
                    folder_id=str(item.get("folder_id") or "").strip() or None,
                    folder_path=str(item.get("folder_path") or "").strip(),
                    device_category=str(item.get("device_category") or "switch").strip(),
                    serial_number=str(item.get("serial_number") or "").strip(),
                    airwave_status=str(item.get("airwave_status") or "Up").strip() or "Up",
                    device_role=str(item.get("device_role") or "").strip(),
                    airwave_os=aw_os,
                    enabled=True,
                )
            )

        if unmapped_names:
            return json_error(
                400,
                "All imported devices must be mapped to a Netmiko platform.",
                errors=unmapped_names,
            )

        ctx.db.save_settings(settings)
        saved = ctx.db.merge_airwave_devices(to_import)
        return json_response({"imported": len(saved), "items": [serialize_device(h) for h in saved]})
