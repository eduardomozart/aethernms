"""Tests for native Netmiko platform discovery, protocol constraints, and legacy normalization."""

import pytest

from pssh_ui.models import AppSettings, ConnectionProtocol
from pssh_ui.netmiko_catalog import (
    canonical_platform,
    default_port_for_protocol,
    default_protocol_for_platform,
    get_supported_platforms,
    get_supported_protocols,
    is_supported_platform,
    normalize_legacy_platform,
    resolve_netmiko_device_type,
)


def test_catalog_discovers_native_netmiko_platforms_and_excludes_serial():
    platforms = get_supported_platforms()
    assert len(platforms) > 100
    assert "aruba_procurve" in platforms
    assert "aruba_aoscx" in platforms
    assert "cisco_ios" in platforms
    assert "juniper_junos" in platforms
    assert "autodetect" not in platforms
    assert not any(p.endswith("_serial") or p.endswith("_ssh") or p.endswith("_telnet") for p in platforms)

    assert is_supported_platform("ARUBA_AOSCX") is True
    assert canonical_platform("Cisco_IOS") == "cisco_ios"
    assert is_supported_platform("not_a_real_platform") is False


def test_native_protocol_resolution_rejects_unsupported_telnet_variants():
    assert get_supported_protocols("aruba_procurve") == [
        ConnectionProtocol.SSH,
        ConnectionProtocol.TELNET,
    ]
    assert get_supported_protocols("aruba_aoscx") == [ConnectionProtocol.SSH]

    assert (
        resolve_netmiko_device_type("aruba_procurve", ConnectionProtocol.SSH) == "aruba_procurve"
    )
    assert (
        resolve_netmiko_device_type("aruba_procurve", ConnectionProtocol.TELNET)
        == "aruba_procurve_telnet"
    )
    assert resolve_netmiko_device_type("aruba_aoscx", ConnectionProtocol.SSH) == "aruba_aoscx"

    with pytest.raises(ValueError, match="Telnet"):
        resolve_netmiko_device_type("aruba_aoscx", ConnectionProtocol.TELNET)


def test_default_protocol_port_and_legacy_platform_normalization():
    settings = AppSettings(default_protocol=ConnectionProtocol.TELNET, ssh_port=2222, telnet_port=2323)
    assert (
        default_protocol_for_platform("aruba_procurve", settings.default_protocol)
        == ConnectionProtocol.TELNET
    )
    assert (
        default_protocol_for_platform("aruba_aoscx", settings.default_protocol)
        == ConnectionProtocol.SSH
    )
    assert default_port_for_protocol(ConnectionProtocol.SSH, settings) == 2222
    assert default_port_for_protocol(ConnectionProtocol.TELNET, settings) == 2323

    assert normalize_legacy_platform("AOS-S") == ("aruba_procurve", None)
    assert normalize_legacy_platform("AOS-CX") == ("aruba_aoscx", None)
    assert normalize_legacy_platform("Unknown") == ("", None)
    assert normalize_legacy_platform("cisco_ios_telnet") == ("cisco_ios", ConnectionProtocol.TELNET)
