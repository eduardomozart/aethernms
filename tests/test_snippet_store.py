"""Tests for hierarchical XML snippets stored under snippets/<vendor>/<os>/."""

from pathlib import Path
import pytest

from pssh_ui.models import Snippet, SnippetSeverity, SnippetType, SwitchOS
from pssh_ui.snippet_store import SnippetStore


def test_builtin_aruba_snippets_exist_in_subfolders():
    store = SnippetStore()
    folders = store.list_folders()
    assert "aruba/aoss" in folders
    assert "aruba/aoscx" in folders

    snippets = store.load_all_snippets()
    aoss = [s for s in snippets if s.folder == "aruba/aoss"]
    aoscx = [s for s in snippets if s.folder == "aruba/aoscx"]
    assert len(aoss) >= 1
    assert len(aoscx) >= 1
    snmp_aoss = next(s for s in aoss if "snmpv3" in s.name.lower())
    assert "${SNMPv3 Username|text|" in snmp_aoss.commands
    assert "${Auth Password|password|" in snmp_aoss.commands
    assert "${Privacy Password|password|" in snmp_aoss.commands
    assert "readonly_user" not in snmp_aoss.commands
    assert "%" not in snmp_aoss.commands
    assert any("${SNMPv3 Username|text|" in s.commands for s in aoscx)
    assert any(s.name == "ArubaOS-CX NTP" for s in aoscx)
    assert any(s.name == "ArubaOS-CX Syslog" for s in aoscx)

    # Config snippets omit hardcoded 'configure terminal' (delegated to DeviceModel)
    assert "configure terminal" not in snmp_aoss.commands.lower()
    # Neither built-in snippets nor newly saved XML files include redundant <Folder>,
    # and <Description> fields never embed raw ${...} placeholders
    for s in snippets:
        assert "<Folder>" not in Path(s.file_path).read_text(encoding="utf-8")
        assert "${" not in s.description
        assert "}" not in s.description


def test_save_import_export_and_delete_snippets(tmp_path: Path):
    store = SnippetStore(base_dir=tmp_path / "snippets")
    store.ensure_default_folders()
    custom_dir = store.create_folder("aruba/custom")
    assert custom_dir.is_dir()

    snip = Snippet(
        name="VLAN 100 Setup",
        folder="aruba/aoss",
        snippet_type=SnippetType.CONFIG,
        device_type=SwitchOS.AOS_S,
        severity=SnippetSeverity.INFO,
        description="Configure VLAN 100",
        commands="configure terminal\nvlan ${vlan_id}\nname ${vlan_name|^[A-Za-z0-9_-]+$}",
    )
    saved_path = store.save_snippet(snip)
    assert saved_path.is_file()
    assert saved_path.parent.name == "aoss"
    assert "<Folder>" not in saved_path.read_text(encoding="utf-8")

    loaded = store.load_all_snippets()
    assert len(loaded) == 1
    assert loaded[0].name == "VLAN 100 Setup"
    assert loaded[0].folder == "aruba/aoss"
    assert "vlan ${vlan_id}" in loaded[0].commands

    export_file = tmp_path / "exported" / "vlan100.xml"
    store.export_snippet(loaded[0], export_file)
    assert export_file.is_file()

    imported = store.import_snippet(export_file, target_folder="aruba/aoscx")
    assert imported.folder == "aruba/aoscx"
    assert Path(imported.file_path).is_file()

    assert store.delete_snippet(imported) is True
    assert not Path(imported.file_path).exists()


def test_create_folder_rejects_empty_and_sanitizes_traversal(tmp_path: Path):
    store = SnippetStore(base_dir=tmp_path / "snippets")
    with pytest.raises(ValueError):
        store.create_folder("")

    # Normalization strips '..' segments so folders stay cleanly inside base_dir
    created = store.create_folder("../../aruba/aoss")
    assert store.base_dir.resolve() in created.parents
