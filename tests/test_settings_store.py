"""Tests for global settings.xml persistence (settings_store)."""

from pathlib import Path

from pssh_ui.models import AirWaveFilter, AppSettings, ScheduleSequence
from pssh_ui.settings_store import load_settings_xml, save_settings_xml


def test_settings_xml_roundtrip_and_missing_defaults(tmp_path: Path):
    missing = tmp_path / "does_not_exist.xml"
    defaults = load_settings_xml(missing)
    assert defaults.language == "auto"
    assert defaults.theme_mode == "auto"
    assert defaults.ssh_port == 22
    assert defaults.max_parallel == 10

    custom = AppSettings(
        language="pt_BR",
        theme_mode="dark",
        ssh_username="noc_admin",
        ssh_port=2222,
        schedule_sequence=ScheduleSequence.SEQUENTIAL,
        max_parallel=4,
        command_timeout=25,
        connect_timeout=12,
        airwave_url="airwave.example.org",
        airwave_username="aw_reader",
        airwave_verify_ssl=True,
        airwave_filters=AirWaveFilter(
            folder="Core",
            category="switch",
            model="6300M",
            os_filter="AOS-CX",
            status_filter="Up",
            search_query="SW-",
        ),
    )

    settings_file = tmp_path / "settings.xml"
    save_settings_xml(custom, settings_file)
    restored = load_settings_xml(settings_file)

    assert restored.language == "pt_BR"
    assert restored.theme_mode == "dark"
    assert restored.ssh_username == "noc_admin"
    assert restored.ssh_port == 2222
    assert restored.schedule_sequence == ScheduleSequence.SEQUENTIAL
    assert restored.max_parallel == 4
    assert restored.command_timeout == 25
    assert restored.connect_timeout == 12
    assert isinstance(restored.command_timeout, int)
    assert isinstance(restored.connect_timeout, int)
    assert restored.airwave_url == "airwave.example.org"
    assert restored.airwave_username == "aw_reader"
    assert restored.airwave_verify_ssl is True
    assert restored.airwave_filters.folder == "Core"
    assert restored.airwave_filters.os_filter == "AOS-CX"
