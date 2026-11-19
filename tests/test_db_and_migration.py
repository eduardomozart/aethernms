"""Tests for SQLite (PyDAL) persistence, SHA-256 snippet seeding, AirWave locks, and legacy XML migration."""

from __future__ import annotations

from pathlib import Path

import pytest

from aethernms.db import DatabaseStore
from aethernms.models import (
    AirWaveFilter,
    AppSettings,
    CommandStepResult,
    ConnectionProtocol,
    HostEntry,
    HostExecutionResult,
    JobRecord,
    ScheduleSequence,
    Snippet,
    SnippetSeverity,
    SnippetType,
)
from aethernms.snippet_store import snippet_from_xml_string, snippet_to_xml_string


def test_user_auth_api_keys_and_env_bootstrap(monkeypatch, tmp_path: Path):
    db = DatabaseStore(tmp_path / "aethernms.db")
    assert db.user_count() == 0

    monkeypatch.setenv("AETHERNMS_ADMIN_USER", "netops")
    monkeypatch.setenv("AETHERNMS_ADMIN_PASSWORD", "Secret123!")
    boot = db.bootstrap_admin_from_env()
    assert boot is not None
    assert boot["username"] == "netops"
    assert db.user_count() == 1

    # Second bootstrap call is a no-op because user_count > 0
    assert db.bootstrap_admin_from_env() is None

    assert db.authenticate_user("netops", "wrong") is None
    authed = db.authenticate_user("netops", "Secret123!")
    assert authed is not None
    assert authed["username"] == "netops"

    assert db.update_user_password(authed["id"], "NewPass456!") is True
    assert db.authenticate_user("netops", "Secret123!") is None
    assert db.authenticate_user("netops", "NewPass456!") is not None

    with pytest.raises(ValueError):
        db.create_user("netops", "Duplicate123!")
    with pytest.raises(ValueError):
        db.create_user("short", "123")

    created_key = db.create_api_key(authed["id"], "CI Runner")
    assert created_key["token"].startswith("aethernms_")
    assert created_key["name"] == "CI Runner"

    keys = db.list_api_keys(authed["id"])
    assert len(keys) == 1
    assert "token" not in keys[0]
    assert keys[0]["key_prefix"] == created_key["key_prefix"]

    key_user = db.authenticate_api_key(created_key["token"])
    assert key_user is not None
    assert key_user["username"] == "netops"
    assert db.list_api_keys(authed["id"])[0]["last_used_at"] != ""

    assert db.revoke_api_key(authed["id"], created_key["id"]) is True
    assert db.authenticate_api_key(created_key["token"]) is None


def test_settings_roundtrip_in_sqlite(tmp_path: Path):
    db = DatabaseStore(tmp_path / "aethernms.db")
    defaults = db.get_settings()
    assert defaults.language == "auto"
    assert defaults.theme_mode == "auto"
    assert defaults.default_protocol == ConnectionProtocol.SSH
    assert defaults.ssh_port == 22
    assert defaults.telnet_port == 23

    custom = AppSettings(
        language="pt_BR",
        theme_mode="dark",
        ssh_username="admin",
        default_protocol=ConnectionProtocol.TELNET,
        ssh_port=2222,
        telnet_port=2323,
        schedule_sequence=ScheduleSequence.SEQUENTIAL,
        max_parallel=4,
        command_timeout=30,
        connect_timeout=12,
        airwave_url="https://amp.example.local",
        airwave_username="awadmin",
        airwave_verify_ssl=True,
        airwave_filters=AirWaveFilter(folder="Top/Core", category="switch", status_filter="Up"),
        airwave_os_mappings={"ArubaOS-Switch": "aruba_procurve", "Comware": "hp_comware"},
    )
    db.save_settings(custom)
    loaded = db.get_settings()
    assert loaded.language == "pt_BR"
    assert loaded.theme_mode == "dark"
    assert loaded.ssh_username == "admin"
    assert loaded.default_protocol == ConnectionProtocol.TELNET
    assert loaded.ssh_port == 2222
    assert loaded.telnet_port == 2323
    assert loaded.schedule_sequence == ScheduleSequence.SEQUENTIAL
    assert loaded.max_parallel == 4
    assert loaded.command_timeout == 30
    assert loaded.connect_timeout == 12
    assert loaded.airwave_url == "https://amp.example.local"
    assert loaded.airwave_username == "awadmin"
    assert loaded.airwave_verify_ssl is True
    assert loaded.airwave_filters.folder == "Top/Core"
    assert loaded.airwave_os_mappings["ArubaOS-Switch"] == "aruba_procurve"
    assert loaded.airwave_os_mappings["Comware"] == "hp_comware"


def test_snippet_seeding_sha256_edits_deletes_and_xml_roundtrip(tmp_path: Path):
    db = DatabaseStore(tmp_path / "aethernms.db")
    src_v1 = tmp_path / "bundled_v1"
    (src_v1 / "aruba" / "aruba_procurve").mkdir(parents=True)

    s_auto = Snippet(
        name="Auto Update Me",
        folder="aruba/aruba_procurve",
        snippet_type=SnippetType.CONFIG,
        device_type="aruba_procurve",
        severity=SnippetSeverity.INFO,
        description="v1 desc",
        commands="show version",
    )
    s_edit = Snippet(
        name="User Edited",
        folder="aruba/aruba_procurve",
        snippet_type=SnippetType.AUDIT,
        device_type="aruba_procurve",
        severity=SnippetSeverity.MAJOR,
        description="v1 audit",
        commands="show running-config",
        audit_regex="ntp server",
    )
    s_del = Snippet(
        name="User Deleted",
        folder="aruba/aruba_procurve",
        snippet_type=SnippetType.CONFIG,
        device_type="aruba_procurve",
        commands="show time",
    )

    (src_v1 / "aruba" / "aruba_procurve" / "auto.xml").write_text(
        snippet_to_xml_string(s_auto), encoding="utf-8"
    )
    (src_v1 / "aruba" / "aruba_procurve" / "edit.xml").write_text(
        snippet_to_xml_string(s_edit), encoding="utf-8"
    )
    (src_v1 / "aruba" / "aruba_procurve" / "del.xml").write_text(
        snippet_to_xml_string(s_del), encoding="utf-8"
    )

    assert db.seed_bundled_snippets(src_v1) == 3
    all_snips = {s.name: s for s in db.list_snippets()}
    assert set(all_snips.keys()) == {"Auto Update Me", "User Edited", "User Deleted"}
    assert all(s.is_builtin for s in all_snips.values())

    # Built-in snippets are strictly read-only and cannot be modified or deleted
    edited = all_snips["User Edited"]
    assert edited.id is not None
    with pytest.raises(ValueError, match="read-only"):
        db.update_snippet(
            edited.id,
            Snippet(
                name="User Edited",
                folder=edited.folder,
                snippet_type=SnippetType.AUDIT,
                device_type="aruba_procurve",
                severity=SnippetSeverity.CRITICAL,
                description="custom override",
                commands="show custom",
                audit_regex="custom-regex",
            ),
        )
    deleted = all_snips["User Deleted"]
    assert deleted.id is not None
    with pytest.raises(ValueError, match="read-only"):
        db.delete_snippet(deleted.id)

    # Custom user snippet supports full edit, XML export/import, and delete
    custom = db.create_snippet(
        Snippet(
            name="Custom Template",
            folder="custom",
            snippet_type=SnippetType.AUDIT,
            device_type="aruba_procurve",
            severity=SnippetSeverity.CRITICAL,
            description="custom override",
            commands="show custom",
            audit_regex="custom-regex",
        )
    )
    assert custom.id is not None and custom.is_builtin is False
    updated_custom = db.update_snippet(
        custom.id,
        Snippet(
            name="Custom Template",
            folder="custom",
            snippet_type=SnippetType.AUDIT,
            device_type="aruba_procurve",
            severity=SnippetSeverity.CRITICAL,
            description="custom v2",
            commands="show custom v2",
            audit_regex="custom-regex",
        ),
    )
    assert updated_custom.description == "custom v2"

    # Upstream v2 refreshes all changed built-in XML files cleanly and adds a 4th
    src_v2 = tmp_path / "bundled_v2"
    (src_v2 / "aruba" / "aruba_procurve").mkdir(parents=True)
    s_auto.description = "v2 updated desc"
    s_edit.description = "v2 updated audit"
    s_del.description = "v2 updated time"
    s_new = Snippet(
        name="Brand New",
        folder="aruba/aruba_procurve",
        snippet_type=SnippetType.CONFIG,
        device_type="aruba_procurve",
        commands="show vlan",
    )
    (src_v2 / "aruba" / "aruba_procurve" / "auto.xml").write_text(
        snippet_to_xml_string(s_auto), encoding="utf-8"
    )
    (src_v2 / "aruba" / "aruba_procurve" / "edit.xml").write_text(
        snippet_to_xml_string(s_edit), encoding="utf-8"
    )
    (src_v2 / "aruba" / "aruba_procurve" / "del.xml").write_text(
        snippet_to_xml_string(s_del), encoding="utf-8"
    )
    (src_v2 / "aruba" / "aruba_procurve" / "new.xml").write_text(
        snippet_to_xml_string(s_new), encoding="utf-8"
    )

    assert db.seed_bundled_snippets(src_v2) == 4
    after = {s.name: s for s in db.list_snippets()}
    assert set(after.keys()) == {
        "Auto Update Me",
        "User Edited",
        "User Deleted",
        "Brand New",
        "Custom Template",
    }
    assert after["Auto Update Me"].description == "v2 updated desc"
    assert after["User Edited"].description == "v2 updated audit"
    assert after["Custom Template"].description == "custom v2"

    # XML export/import string roundtrip on custom snippet and delete cleanup
    xml_out = snippet_to_xml_string(after["Custom Template"])
    parsed = snippet_from_xml_string(xml_out)
    assert parsed.name == "Custom Template"
    assert parsed.snippet_type == SnippetType.AUDIT
    assert parsed.audit_regex == "custom-regex"
    assert parsed.severity == SnippetSeverity.CRITICAL
    assert db.delete_snippet(custom.id) is True


def test_devices_airwave_readonly_and_jobs_sqlite_logs(tmp_path: Path):
    db = DatabaseStore(tmp_path / "aethernms.db")

    # Manual device allows full edits
    manual = db.create_or_replace_device(
        HostEntry(name="SW-MAN", ip="10.0.0.10", os_type="aruba_procurve", port=22)
    )
    assert manual.id is not None
    updated_man = db.update_device(
        manual.id,
        HostEntry(
            name="SW-MAN-RENAMED",
            ip="10.0.0.11",
            os_type="hp_comware",
            protocol=ConnectionProtocol.TELNET,
            port=2323,
            model="5130",
            folder_path="Top/Lab",
        ),
    )
    assert updated_man is not None
    assert updated_man.name == "SW-MAN-RENAMED"
    assert updated_man.ip == "10.0.0.11"
    assert updated_man.protocol == ConnectionProtocol.TELNET
    assert updated_man.port == 2323

    # AirWave device locks identity fields while allowing platform/protocol/port override
    aw = db.create_or_replace_device(
        HostEntry(
            name="SW-AW-01",
            ip="10.0.1.5",
            os_type="aruba_procurve",
            protocol=ConnectionProtocol.SSH,
            port=22,
            model="2930F",
            folder_id="42",
            folder_path="Top/Campus",
            airwave_status="Up",
            airwave_os="ArubaOS-Switch",
        )
    )
    assert aw.id is not None
    aw_upd = db.update_device(
        aw.id,
        HostEntry(
            name="TRY-CHANGE-NAME",
            ip="10.9.9.9",
            os_type="hp_comware",
            protocol=ConnectionProtocol.TELNET,
            port=2300,
            model="TRY-MODEL",
            folder_path="TRY-GROUP",
        ),
    )
    assert aw_upd is not None
    assert aw_upd.name == "SW-AW-01"
    assert aw_upd.ip == "10.0.1.5"
    assert aw_upd.model == "2930F"
    assert aw_upd.folder_path == "Top/Campus"
    assert aw_upd.os_type == "hp_comware"
    assert aw_upd.protocol == ConnectionProtocol.TELNET
    assert aw_upd.port == 2300

    # Job persistence with SQLite-stored formatted_log & secret scrubbing
    res = HostExecutionResult(
        host=aw_upd,
        status="Success",
        commands_run=["show version"],
        step_results=[
            CommandStepResult(
                index=0,
                command="show version",
                result="Command successful.",
                begin_time="2026-01-01 10:00:00",
                finish_time="2026-01-01 10:00:01",
                output_snippet="WC.16.11.0005",
            )
        ],
        raw_output="SW-AW-01# show version\nWC.16.11.0005",
        operation_result="Operation succeeded",
        started_at="2026-01-01 10:00:00",
        finished_at="2026-01-01 10:00:01",
    )
    job = JobRecord(
        job_id="job_abc123",
        name="Password Rotate",
        job_type=SnippetType.CONFIG,
        device_type="aruba_procurve",
        status="Success",
        creation_time="2026-01-01 10:00:00",
        start_time="2026-01-01 10:00:00",
        end_time="2026-01-01 10:00:02",
        commands_raw="password operator plaintext ${new_pw|password}\nntp server ${ntp_ip}",
        commands_rendered="password operator plaintext ********\nntp server 10.1.1.1",
        parameters_masked={"new_pw": "SuperSecret!", "ntp_ip": "10.1.1.1"},
        results=[res],
    )
    created = db.create_job(job)
    assert created.parameters_masked["new_pw"] == "••••••••"
    assert created.parameters_masked["ntp_ip"] == "10.1.1.1"
    assert len(created.results) == 1
    rid = created.results[0].id
    assert rid is not None
    loaded_res = db.get_job_result("job_abc123", rid)
    assert loaded_res is not None
    assert "WC.16.11.0005" in loaded_res.formatted_log
    assert len(loaded_res.step_results) == 1
    assert loaded_res.step_results[0].result == "Command successful."

    db.save_parameters({"new_pw": "SuperSecret!", "ntp_ip": "10.1.1.1"}, secret_names={"new_pw"})
    saved_params = db.get_saved_parameters()
    assert "new_pw" not in saved_params
    assert saved_params["ntp_ip"] == "10.1.1.1"


def test_legacy_xml_migration_settings_devices_jobs_and_logs(tmp_path: Path):
    cfg = tmp_path / "legacy_cfg"
    cfg.mkdir()
    log_file = cfg / "sw1.log"
    log_file.write_text("Legacy switch execution transcript\nDone.", encoding="utf-8")

    (cfg / "settings.xml").write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<PsshSettings version="1">
  <Appearance>
    <Language>pt_BR</Language>
    <ThemeMode>dark</ThemeMode>
  </Appearance>
  <ExecutionDefaults>
    <SshUsername>legacy_ops</SshUsername>
    <DefaultProtocol>SSH</DefaultProtocol>
    <SshPort>2200</SshPort>
    <TelnetPort>2300</TelnetPort>
    <ScheduleSequence>Sequential</ScheduleSequence>
    <MaxParallel>5</MaxParallel>
    <CommandTimeout>25</CommandTimeout>
    <ConnectTimeout>12</ConnectTimeout>
  </ExecutionDefaults>
  <AirWave>
    <Url>https://amp.legacy.local</Url>
    <Username>aw_legacy</Username>
    <VerifySSL>true</VerifySSL>
    <OsMappings>
      <Mapping key="ArubaOS-Switch" platform="aruba_procurve" />
    </OsMappings>
  </AirWave>
</PsshSettings>""",
        encoding="utf-8",
    )

    (cfg / "devices.xml").write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<PsshDevices version="1">
  <Devices>
    <Device name="SW-MIG-1" ip="10.20.30.1" os="aruba_procurve" protocol="SSH" port="22" model="2930F" folder_path="Top/SiteA" airwave_status="Up" folder_id="7" />
  </Devices>
</PsshDevices>""",
        encoding="utf-8",
    )

    (cfg / "jobs.xml").write_text(
        f"""<?xml version="1.0" encoding="utf-8"?>
<PsshJobs version="1">
  <Parameters>
    <Param name="vlan_id">100</Param>
    <Param name="secret_pw">LEAKED_IF_NOT_SCRUBBED</Param>
  </Parameters>
  <Jobs>
    <Job id="legacy01" name="Migrated Job" job_type="Config Job" device_type="aruba_procurve" status="Success" creation_time="2026-01-02 09:00:00" start_time="2026-01-02 09:00:00" end_time="2026-01-02 09:00:05">
      <CommandsRaw>vlan ${{vlan_id}}\npassword ${{secret_pw|password}}</CommandsRaw>
      <CommandsRendered>vlan 100\npassword ********</CommandsRendered>
      <ParametersMasked>
        <Param name="vlan_id">100</Param>
        <Param name="secret_pw">LEAKED_IF_NOT_SCRUBBED</Param>
      </ParametersMasked>
      <Results>
        <DeviceResult name="SW-MIG-1" ip="10.20.30.1" port="22" os="aruba_procurve" protocol="SSH" status="Success" operation_result="Operation succeeded" log_path="{log_file}" />
      </Results>
    </Job>
  </Jobs>
</PsshJobs>""",
        encoding="utf-8",
    )

    db = DatabaseStore(cfg / "aethernms.db")
    counts = db.migrate_legacy_xml_files(cfg)
    assert counts == {"settings": 1, "devices": 1, "jobs": 1}

    # Re-running migration does not duplicate records
    assert db.migrate_legacy_xml_files(cfg) == {"settings": 0, "devices": 0, "jobs": 0}

    s = db.get_settings()
    assert s.language == "pt_BR"
    assert s.ssh_username == "legacy_ops"
    assert s.ssh_port == 2200
    assert s.schedule_sequence == ScheduleSequence.SEQUENTIAL
    assert s.airwave_os_mappings["ArubaOS-Switch"] == "aruba_procurve"

    devs = db.list_devices()
    assert len(devs) == 1
    assert devs[0].name == "SW-MIG-1"
    assert devs[0].folder_id == "7"

    jobs = db.list_jobs()
    assert len(jobs) == 1
    assert jobs[0].job_id == "legacy01"
    assert jobs[0].parameters_masked["secret_pw"] == "••••••••"
    assert "Legacy switch execution transcript" in jobs[0].results[0].formatted_log

    params = db.get_saved_parameters()
    assert params["vlan_id"] == "100"
    assert "secret_pw" not in params
