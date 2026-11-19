"""Tests for job_builder platform filtering, dynamic assigned models/groups, and validation."""

from pssh_ui.job_builder import (
    build_commands_for_job,
    discover_used_platforms,
    filter_hosts_by_platform,
    get_assigned_groups,
    get_assigned_models,
    job_platform_choices,
    validate_job_inputs,
)
from pssh_ui.models import ConnectionProtocol, HostEntry, Snippet


def test_get_assigned_models_and_groups_track_active_devices():
    hosts = [
        HostEntry(
            name="SW-1",
            ip="10.0.0.1",
            os_type="aruba_procurve",
            model="Aruba 2930F",
            folder_path="Building A",
        ),
        HostEntry(
            name="SW-2",
            ip="10.0.0.2",
            os_type="aruba_aoscx",
            model="Aruba 6300M",
            folder_path="Core",
        ),
        HostEntry(
            name="SW-3",
            ip="10.0.0.3",
            os_type="aruba_aoscx",
            model="Aruba 6300M",
            folder_path="Core",
        ),
        HostEntry(name="SW-4", ip="10.0.0.4", os_type="aruba_procurve", model="", folder_path=""),
    ]
    assert get_assigned_models(hosts) == ["Aruba 2930F", "Aruba 6300M"]
    assert get_assigned_groups(hosts) == ["Building A", "Core"]

    hosts.pop(0)
    assert get_assigned_models(hosts) == ["Aruba 6300M"]
    assert get_assigned_groups(hosts) == ["Core"]


def test_filter_hosts_by_platform_and_validate_job_inputs():
    h_s = HostEntry(
        name="SW-S",
        ip="10.0.0.1",
        os_type="aruba_procurve",
        protocol=ConnectionProtocol.TELNET,
        port=23,
        enabled=True,
    )
    h_cx = HostEntry(
        name="SW-CX",
        ip="10.0.0.2",
        os_type="aruba_aoscx",
        protocol=ConnectionProtocol.SSH,
        enabled=True,
    )
    h_cx_bad_proto = HostEntry(
        name="SW-CX-BAD",
        ip="10.0.0.3",
        os_type="aruba_aoscx",
        protocol=ConnectionProtocol.TELNET,
        enabled=True,
    )

    assert filter_hosts_by_platform([h_s, h_cx], "aruba_procurve") == [h_s]
    assert filter_hosts_by_platform([h_s, h_cx], "aruba_aoscx") == [h_cx]

    raw = (
        "vlan 10\n"
        "! comment\n"
        'snmpv3 user "${Usuário SNMP|text|^[a-z0-9_]+$}" auth sha "${Auth Password|password|^.{8,}$}"'
    )
    errs = validate_job_inputs(
        raw_commands=raw,
        selected_hosts=[h_s, h_cx_bad_proto],
        values={"Usuário SNMP": "bad user!", "Auth Password": "short"},
        username="admin",
        password="",
    )
    assert len(errs) == 4  # missing password + invalid telnet on aoscx + 2 var errors

    assert (
        validate_job_inputs(
            raw_commands=raw,
            selected_hosts=[h_s],
            values={"Usuário SNMP": "snmp_ro", "Auth Password": "DummyPass123!"},
            username="admin",
            password="dummy_ssh_password",
        )
        == []
    )

    cmds = build_commands_for_job(
        raw, {"Usuário SNMP": "snmp_ro", "Auth Password": "DummyPass123!"}, [h_s]
    )
    assert cmds[h_s.unique_key] == [
        "vlan 10",
        'snmpv3 user "snmp_ro" auth sha "DummyPass123!"',
    ]


def test_discover_and_prioritize_platforms():
    snips = [
        Snippet(name="S1", device_type="cisco_ios", commands="show version"),
        Snippet(name="S2", device_type="aruba_procurve", commands="show system"),
    ]
    assert discover_used_platforms(snippets=snips) == ["aruba_procurve", "cisco_ios"]
    choices = job_platform_choices(snips)
    assert choices[:2] == ["aruba_procurve", "cisco_ios"]
    assert "aruba_aoscx" in choices
