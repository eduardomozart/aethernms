"""Tests for job_builder OS filtering, dynamic assigned models/groups, and validation."""

from pssh_ui.job_builder import (
    build_commands_for_job,
    discover_device_types,
    filter_hosts_by_os,
    get_assigned_groups,
    get_assigned_models,
    validate_job_inputs,
    wrap_commands_with_model,
)
from pssh_ui.models import DeviceModel, HostEntry, SnippetType, SwitchOS


def test_get_assigned_models_and_groups_track_active_devices():
    hosts = [
        HostEntry(
            name="SW-1",
            ip="10.0.0.1",
            os_type=SwitchOS.AOS_S,
            model="Aruba 2930F",
            folder_path="Building A",
        ),
        HostEntry(
            name="SW-2",
            ip="10.0.0.2",
            os_type=SwitchOS.AOS_CX,
            model="Aruba 6300M",
            folder_path="Core",
        ),
        HostEntry(
            name="SW-3",
            ip="10.0.0.3",
            os_type=SwitchOS.AOS_CX,
            model="Aruba 6300M",
            folder_path="Core",
        ),
        HostEntry(name="SW-4", ip="10.0.0.4", os_type=SwitchOS.AOS_S, model="", folder_path=""),
    ]
    assert get_assigned_models(hosts) == ["Aruba 2930F", "Aruba 6300M"]
    assert get_assigned_groups(hosts) == ["Building A", "Core"]

    # Removing the only device with Aruba 2930F / Building A removes both from dropdowns
    hosts.pop(0)
    assert get_assigned_models(hosts) == ["Aruba 6300M"]
    assert get_assigned_groups(hosts) == ["Core"]


def test_filter_hosts_by_os_and_validate_job_inputs():
    h_s = HostEntry(name="SW-S", ip="10.0.0.1", os_type=SwitchOS.AOS_S, enabled=True)
    h_cx = HostEntry(name="SW-CX", ip="10.0.0.2", os_type=SwitchOS.AOS_CX, enabled=True)

    assert filter_hosts_by_os([h_s, h_cx], SwitchOS.AOS_S) == [h_s]
    assert filter_hosts_by_os([h_s, h_cx], SwitchOS.AOS_CX) == [h_cx]

    raw = (
        "configure terminal\n"
        "! comment\n"
        'snmpv3 user "${Usuário SNMP|text|^[a-z0-9_]+$}" auth sha "${Auth Password|password|^.{8,}$}"'
    )
    errs = validate_job_inputs(
        raw_commands=raw,
        selected_hosts=[h_s],
        values={"Usuário SNMP": "bad user!", "Auth Password": "short"},
        ssh_username="admin",
        ssh_password="",
    )
    assert len(errs) == 3

    assert (
        validate_job_inputs(
            raw_commands=raw,
            selected_hosts=[h_s],
            values={"Usuário SNMP": "snmp_ro", "Auth Password": "DummyPass123!"},
            ssh_username="admin",
            ssh_password="dummy_ssh_password",
        )
        == []
    )

    cmds = build_commands_for_job(
        raw, {"Usuário SNMP": "snmp_ro", "Auth Password": "DummyPass123!"}, [h_s]
    )
    assert cmds[h_s.unique_key] == [
        "configure terminal",
        'snmpv3 user "snmp_ro" auth sha "DummyPass123!"',
    ]


def test_wrap_commands_with_device_model_avoids_duplicates():
    mdl = DeviceModel(
        name="ArubaOS-S",
        device_type=SwitchOS.AOS_S,
        pre_config_commands="configure terminal",
        post_config_commands="end",
        pre_audit_commands="",
        post_audit_commands="",
    )
    assert wrap_commands_with_model(["vlan 100"], SnippetType.CONFIG, mdl) == [
        "configure terminal",
        "vlan 100",
        "end",
    ]
    assert wrap_commands_with_model(
        ["vlan 100"], SnippetType.CONFIG, mdl, include_write_command=True
    ) == [
        "configure terminal",
        "vlan 100",
        "end",
        "write memory",
    ]
    assert wrap_commands_with_model(["configure terminal", "vlan 100", "end"], SnippetType.CONFIG, mdl) == [
        "configure terminal",
        "vlan 100",
        "end",
    ]
    assert wrap_commands_with_model(["show running-config"], SnippetType.AUDIT, mdl) == [
        "show running-config"
    ]
    assert discover_device_types([mdl]) == ["AOS-S"]
