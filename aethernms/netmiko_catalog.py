"""Dynamic catalog of native Netmiko platforms and supported transport protocols."""

from __future__ import annotations

from functools import lru_cache
from typing import Dict, List, Optional, Tuple

from aethernms.models import AppSettings, ConnectionProtocol


@lru_cache(maxsize=1)
def _platform_capabilities() -> Dict[str, Tuple[bool, bool]]:
    """
    Build {base_platform: (supports_ssh, supports_telnet)} directly from Netmiko's
    native `CLASS_MAPPER`, excluding serial-only drivers and non-connection dispatchers.
    """
    from netmiko.ssh_dispatcher import CLASS_MAPPER

    caps: Dict[str, Tuple[bool, bool]] = {}
    for raw_key in CLASS_MAPPER:
        if raw_key == "autodetect" or raw_key.endswith("_serial"):
            continue
        if raw_key.endswith("_telnet"):
            base = raw_key[:-7]
            has_ssh, _ = caps.get(base, (False, False))
            caps[base] = (has_ssh, True)
        elif raw_key.endswith("_ssh"):
            base = raw_key[:-4]
            _, has_telnet = caps.get(base, (False, False))
            caps[base] = (True, has_telnet)
        else:
            _, has_telnet = caps.get(raw_key, (False, False))
            caps[raw_key] = (True, has_telnet)
    return caps


def get_supported_platforms() -> List[str]:
    """Return sorted list of all native Netmiko base platforms supported over SSH/Telnet."""
    return sorted(_platform_capabilities().keys())


def is_supported_platform(platform: Optional[str]) -> bool:
    """Return True when `platform` is a supported base Netmiko platform."""
    cleaned = (platform or "").strip().lower()
    return bool(cleaned and cleaned in _platform_capabilities())


def canonical_platform(platform: Optional[str]) -> str:
    """Return canonical lowercase Netmiko platform string if supported, else ''."""
    cleaned = (platform or "").strip().lower()
    return cleaned if cleaned in _platform_capabilities() else ""


def get_supported_protocols(platform: Optional[str]) -> List[ConnectionProtocol]:
    """Return native Netmiko transport protocols supported for `platform`."""
    cleaned = canonical_platform(platform)
    if not cleaned:
        return [ConnectionProtocol.SSH]
    has_ssh, has_telnet = _platform_capabilities()[cleaned]
    protocols: List[ConnectionProtocol] = []
    if has_ssh:
        protocols.append(ConnectionProtocol.SSH)
    if has_telnet:
        protocols.append(ConnectionProtocol.TELNET)
    return protocols or [ConnectionProtocol.SSH]


def default_protocol_for_platform(
    platform: Optional[str],
    preferred: ConnectionProtocol = ConnectionProtocol.SSH,
) -> ConnectionProtocol:
    """Return `preferred` if natively supported for `platform`, else the platform's default."""
    supported = get_supported_protocols(platform)
    if preferred in supported:
        return preferred
    return supported[0]


def default_port_for_protocol(
    protocol: ConnectionProtocol,
    settings: Optional[AppSettings] = None,
) -> int:
    """Return global default TCP port for SSH or Telnet."""
    if protocol == ConnectionProtocol.TELNET:
        return int(settings.telnet_port) if settings is not None else 23
    return int(settings.ssh_port) if settings is not None else 22


def resolve_netmiko_device_type(
    platform: Optional[str],
    protocol: ConnectionProtocol = ConnectionProtocol.SSH,
) -> str:
    """
    Resolve `(platform, protocol)` to the exact native Netmiko `device_type` key
    registered in `CLASS_MAPPER`, raising `ValueError` if unsupported.
    """
    from netmiko.ssh_dispatcher import CLASS_MAPPER

    cleaned = canonical_platform(platform)
    if not cleaned:
        raw = (platform or "").strip()
        raise ValueError(
            f"Unsupported Netmiko platform: '{raw or 'Unmapped'}'."
        )

    if protocol == ConnectionProtocol.TELNET:
        telnet_key = f"{cleaned}_telnet"
        if telnet_key in CLASS_MAPPER:
            return telnet_key
        raise ValueError(
            f"Protocol 'Telnet' is not natively supported by Netmiko for '{cleaned}'."
        )

    if cleaned in CLASS_MAPPER:
        return cleaned
    ssh_key = f"{cleaned}_ssh"
    if ssh_key in CLASS_MAPPER:
        return ssh_key
    raise ValueError(
        f"Protocol 'SSH' is not natively supported by Netmiko for '{cleaned}'."
    )


def normalize_legacy_platform(
    raw: Optional[str],
) -> Tuple[str, Optional[ConnectionProtocol]]:
    """
    Normalize legacy pssh-ui OS names (`AOS-S`, `AOS-CX`, `Unknown`) or Netmiko
    driver keys (`*_telnet`, `*_ssh`) into `(base_platform, optional_protocol)`.
    """
    cleaned = (raw or "").strip()
    if not cleaned:
        return "", None
    low = cleaned.lower()
    if low in ("aos-s"):
        return "aruba_procurve", None
    if low in ("aos-cx"):
        return "aruba_aoscx", None
    if low in ("unknown", "unmapped"):
        return "", None

    caps = _platform_capabilities()
    if low.endswith("_telnet"):
        base = low[:-7]
        if base in caps and caps[base][1]:
            return base, ConnectionProtocol.TELNET
    if low.endswith("_ssh"):
        base = low[:-4]
        if base in caps and caps[base][0]:
            return base, ConnectionProtocol.SSH
    if low in caps:
        return low, None
    return "", None
