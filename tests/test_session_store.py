"""Tests for XML session persistence ensuring password-typed variables are never saved."""

from pathlib import Path

from pssh_ui.models import (
    HostEntry,
    HostExecutionResult,
    JobRecord,
    ScheduleSequence,
    SessionData,
    SnippetType,
    SwitchOS,
)
from pssh_ui.session_store import (
    load_session_xml,
    migrate_legacy_settings_from_session,
    save_session_xml,
)


def test_session_xml_roundtrip_excludes_password_fields(tmp_path: Path):
    host_a = HostEntry(
        name="SW-A-01",
        ip="10.0.0.10",
        os_type=SwitchOS.AOS_S,
        model="Aruba 2930F-24G",
        firmware="WC.16.10.0017",
        folder_id="12",
        folder_path="Campus > Building A",
        device_category="switch",
        serial_number="SN001",
        airwave_status="Up",
        device_role="Commander",
        enabled=True,
        port=22,
    )
    host_b = HostEntry(
        name="SW-CX-01",
        ip="10.0.0.20",
        os_type=SwitchOS.AOS_CX,
        model="Aruba 6300M",
        firmware="FL.10.13.1000",
        enabled=False,
        port=2222,
    )
    job = JobRecord(
        job_id="job123",
        name="SNMPv3 Deployment",
        job_type=SnippetType.CONFIG,
        device_type=SwitchOS.AOS_S,
        status="Success",
        creation_time="2026-11-17 15:40:00",
        start_time="2026-11-17 15:40:01",
        end_time="2026-11-17 15:40:05",
        description="Deploy SNMPv3 across buildings",
        snippet_name="ArubaOS-S SNMPv3 Configuration",
        commands_raw=(
            'configure terminal\n'
            'snmpv3 user "${SNMPv3 Username|text}" '
            'auth sha "${Auth Password|password}" '
            'priv aes "${Privacy Password|password}"'
        ),
        commands_rendered='configure terminal\nsnmpv3 user "monitoring_ro" auth sha "********" priv aes "********"',
        max_parallel=15,
        schedule_sequence=ScheduleSequence.CONCURRENT,
        include_write=True,
        parameters_masked={
            "SNMPv3 Username": "monitoring_ro",
            "Auth Password": "TOP_SECRET_AUTH_123!",
        },
        results=[
            HostExecutionResult(
                host=host_a,
                status="Success",
                started_at="2026-11-17 15:40:01",
                finished_at="2026-11-17 15:40:05",
                operation_result="Completed (2 commands)",
            )
        ],
    )

    session = SessionData(
        variable_values={
            "SNMPv3 Username": "monitoring_ro",
            "Auth Password": "TOP_SECRET_AUTH_123!",
            "Privacy Password": "TOP_SECRET_PRIV_456!",
            "ntp_server": "10.1.1.10",
        },
        hosts=[host_a, host_b],
        jobs=[job],
    )

    xml_file = tmp_path / "session.xml"
    save_session_xml(session, xml_file)
    raw_xml = xml_file.read_text(encoding="utf-8")

    # Password-typed parameter values MUST NEVER be written to disk
    assert "TOP_SECRET_AUTH_123!" not in raw_xml
    assert "TOP_SECRET_PRIV_456!" not in raw_xml

    restored = load_session_xml(xml_file)
    assert restored.variable_values == {
        "SNMPv3 Username": "monitoring_ro",
        "ntp_server": "10.1.1.10",
    }
    assert len(restored.hosts) == 2
    assert len(restored.jobs) == 1
    assert restored.jobs[0].description == "Deploy SNMPv3 across buildings"
    assert restored.jobs[0].include_write is True
    assert 'monitoring_ro' in restored.jobs[0].commands_rendered
    assert restored.jobs[0].parameters_masked["Auth Password"] == "••••••••"
    assert restored.jobs[0].results[0].host.name == "SW-A-01"


def test_migrate_legacy_settings_from_v1_session_xml(tmp_path: Path):
    legacy = tmp_path / "legacy_session.xml"
    legacy.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<PsshSession version="1.0">\n'
        '  <Metadata><Language>pt_BR</Language><ThemeMode>dark</ThemeMode></Metadata>\n'
        '  <ExecutionSettings>\n'
        '    <SshUsername>netadmin</SshUsername>\n'
        '    <SshPort>2222</SshPort>\n'
        '    <MaxParallel>8</MaxParallel>\n'
        '  </ExecutionSettings>\n'
        '  <AirWave><Url>airwave.local</Url><Username>aw_user</Username><VerifySSL>true</VerifySSL></AirWave>\n'
        '</PsshSession>\n',
        encoding="utf-8",
    )

    migrated = migrate_legacy_settings_from_session(legacy)
    assert migrated is not None
    assert migrated.language == "auto"
    assert migrated.theme_mode == "auto"
    assert migrated.ssh_username == "netadmin"
    assert migrated.ssh_port == 2222
    assert migrated.max_parallel == 8
    assert migrated.airwave_url == "airwave.local"
    assert migrated.airwave_username == "aw_user"
    assert migrated.airwave_verify_ssl is True
