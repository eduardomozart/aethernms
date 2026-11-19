"""Tests for hierarchical XML snippets and legacy OS normalization."""

from pathlib import Path
import pytest

from aethernms.models import Snippet, SnippetSeverity, SnippetType
from aethernms.paths import bundled_snippets_dir
from aethernms.snippet_store import SnippetStore, snippet_from_xml_file


def test_builtin_aruba_snippets_exist_in_subfolders(tmp_path: Path):
    store = SnippetStore(base_dir=bundled_snippets_dir())
    folders = store.list_folders()
    assert "aruba/aruba_procurve" in folders
    assert "aruba/aruba_aoscx" in folders

    snippets = store.load_all_snippets()
    aoss = [s for s in snippets if s.folder == "aruba/aruba_procurve"]
    aoscx = [s for s in snippets if s.folder == "aruba/aruba_aoscx"]
    assert len(aoss) >= 1
    assert len(aoscx) >= 1
    assert all(s.device_type == "aruba_procurve" for s in aoss)
    assert all(s.device_type == "aruba_aoscx" for s in aoscx)

    snmp_aoss = next(s for s in aoss if "snmpv3" in s.name.lower())
    assert "${SNMPv3 Username|text|" in snmp_aoss.commands
    assert "${Auth Password|password|" in snmp_aoss.commands
    assert "${Privacy Password|password|" in snmp_aoss.commands
    assert "readonly_user" not in snmp_aoss.commands
    assert "%" not in snmp_aoss.commands
    assert any(s.name == "ArubaOS-S NTP" for s in aoss)
    assert any(s.name == "ArubaOS-S Syslog" for s in aoss)
    assert any("${SNMPv3 Username|text|" in s.commands for s in aoscx)
    assert any(s.name == "ArubaOS-CX NTP" for s in aoscx)
    assert any(s.name == "ArubaOS-CX Syslog" for s in aoscx)
    assert "configure terminal" not in snmp_aoss.commands.lower()

    for s in snippets:
        assert "<Folder>" not in Path(s.file_path).read_text(encoding="utf-8")
        assert "${" not in s.description
        assert "}" not in s.description

    # Seeding defaults into a clean user directory works cleanly even when unfrozen
    user_store = SnippetStore(base_dir=tmp_path / "user_snippets")
    assert user_store.seed_defaults() == []
    assert len(user_store.load_all_snippets()) == len(snippets)


def test_save_import_export_delete_and_legacy_migration(tmp_path: Path):
    store = SnippetStore(base_dir=tmp_path / "snippets")
    store.ensure_default_folders()
    custom_dir = store.create_folder("cisco/ios")
    assert custom_dir.is_dir()

    snip = Snippet(
        name="VLAN 100 Setup",
        folder="aruba/aruba_procurve",
        snippet_type=SnippetType.CONFIG,
        device_type="aruba_procurve",
        severity=SnippetSeverity.INFO,
        description="Configure VLAN 100",
        commands="vlan ${vlan_id}\nname ${vlan_name|^[A-Za-z0-9_-]+$}",
    )
    saved_path = store.save_snippet(snip)
    assert saved_path.is_file()
    assert saved_path.parent.name == "aruba_procurve"
    assert "<Folder>" not in saved_path.read_text(encoding="utf-8")
    assert SnippetStore.default_folder_for_os("cisco_ios") == "cisco/cisco_ios"

    loaded = store.load_all_snippets()
    assert len(loaded) == 1
    assert loaded[0].name == "VLAN 100 Setup"
    assert loaded[0].device_type == "aruba_procurve"

    # Legacy <DeviceType>AOS-S</DeviceType> auto-migrates on load
    legacy_xml = tmp_path / "legacy_snip.xml"
    legacy_xml.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<Snippet version="1.0"><Name>Old</Name><Type>Config</Type>'
        '<DeviceType>AOS-S</DeviceType><Severity>Info</Severity>'
        '<Description></Description><Commands>vlan 10</Commands></Snippet>\n',
        encoding="utf-8",
    )
    migrated = snippet_from_xml_file(legacy_xml)
    assert migrated.device_type == "aruba_procurve"

    export_file = tmp_path / "exported" / "vlan100.xml"
    store.export_snippet(loaded[0], export_file)
    assert export_file.is_file()

    imported = store.import_snippet(export_file, target_folder="aruba/aruba_aoscx")
    assert imported.folder == "aruba/aruba_aoscx"
    assert Path(imported.file_path).is_file()

    assert store.delete_snippet(imported) is True
    assert not Path(imported.file_path).exists()


def test_create_folder_rejects_empty_and_sanitizes_traversal(tmp_path: Path):
    store = SnippetStore(base_dir=tmp_path / "snippets")
    with pytest.raises(ValueError):
        store.create_folder("")

    created = store.create_folder("../../aruba/aruba_procurve")
    assert store.base_dir.resolve() in created.parents
