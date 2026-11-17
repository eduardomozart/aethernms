"""Tests for XML DeviceModel persistence, folder hierarchy without <Folder>, and zero-code OS extensibility."""

from pathlib import Path

from pssh_ui.job_builder import discover_device_types
from pssh_ui.model_store import ModelStore
from pssh_ui.models import DeviceModel, SwitchOS
from pssh_ui.snippet_store import SnippetStore


def test_builtin_models_load_without_folder_tag():
    store = ModelStore()
    models = store.load_all_models()
    by_os = {m.device_type.value: m for m in models}

    assert SwitchOS.AOS_S.value in by_os
    assert SwitchOS.AOS_CX.value in by_os
    assert "configure terminal" in by_os[SwitchOS.AOS_S.value].pre_config_commands
    assert "configure terminal" in by_os[SwitchOS.AOS_CX.value].pre_config_commands
    assert by_os[SwitchOS.AOS_S.value].enable_command == "enable"

    for m in models:
        assert m.file_path
        raw_xml = Path(m.file_path).read_text(encoding="utf-8")
        assert "<Folder>" not in raw_xml


def test_new_vendor_xml_model_and_snippet_work_without_source_edits(tmp_path: Path):
    m_dir = tmp_path / "model" / "cisco"
    m_dir.mkdir(parents=True)
    (m_dir / "ios.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<DeviceModel version="1.0">\n'
        '  <Name>Cisco IOS Switch</Name>\n'
        '  <DeviceType>Cisco IOS</DeviceType>\n'
        '  <Vendor>Cisco</Vendor>\n'
        '  <EnableCommand>enable</EnableCommand>\n'
        '  <PreConfigCommands>configure terminal</PreConfigCommands>\n'
        '  <PostConfigCommands>end\nwrite memory</PostConfigCommands>\n'
        '</DeviceModel>\n',
        encoding="utf-8",
    )

    s_dir = tmp_path / "snippets" / "cisco" / "ios"
    s_dir.mkdir(parents=True)
    (s_dir / "ntp.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<Snippet version="1.0">\n'
        '  <Name>Cisco NTP</Name>\n'
        '  <Type>Config</Type>\n'
        '  <DeviceType>Cisco IOS</DeviceType>\n'
        '  <Severity>Info</Severity>\n'
        '  <Commands>ntp server ${NTP Server|text}</Commands>\n'
        '</Snippet>\n',
        encoding="utf-8",
    )

    m_store = ModelStore(base_dir=tmp_path / "model")
    s_store = SnippetStore(base_dir=tmp_path / "snippets")

    models = m_store.load_all_models()
    snippets = s_store.load_all_snippets()
    assert len(models) == 1
    assert models[0].folder == "cisco"
    assert models[0].device_type == "Cisco IOS"
    assert models[0].device_type.value == "Cisco IOS"

    assert len(snippets) == 1
    assert snippets[0].folder == "cisco/ios"
    assert snippets[0].device_type == "Cisco IOS"

    os_list = discover_device_types(models, snippets)
    assert "Cisco IOS" in os_list

    # Roundtrip save omits <Folder> while preserving folder hierarchy
    saved = m_store.save_model(
        DeviceModel(name="Custom Junos", device_type=models[0].device_type, vendor="Juniper", folder="juniper")
    )
    assert saved.parent.name == "juniper"
    assert "<Folder>" not in saved.read_text(encoding="utf-8")
