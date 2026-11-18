"""Headless GUI smoke tests covering Device Models tab, AboutDialog, SettingsDialog, circular wizard, Audit RegEx, and row actions."""

from pathlib import Path
import time
import tkinter as tk
from tkinter import messagebox, ttk
import pytest
import sv_ttk

from pssh_ui.airwave_importer import parse_airwave_folders
import pssh_ui.ping_checker as ping_checker
from pssh_ui.app import PsshApp
from pssh_ui.dialogs import (
    AboutDialog,
    AddJobDialog,
    AirWaveImportDialog,
    DeviceLogDialog,
    SettingsDialog,
    SnippetEditorDialog,
)
from pssh_ui.i18n import get_language, set_language
from pssh_ui.models import (
    HostEntry,
    HostExecutionResult,
    JobRecord,
    SnippetType,
    SwitchOS,
)
from pssh_ui.settings_store import load_settings_xml


@pytest.fixture(scope="module")
def tk_root():
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError as exc:
        pytest.skip(f"Tk display unavailable in this environment: {exc}")
    yield root
    if root.winfo_exists():
        root.destroy()


def test_gui_smoke_lifecycle(tmp_path: Path, monkeypatch, tk_root: tk.Tk):
    monkeypatch.setattr(
        ping_checker, "ping_host", lambda ip, timeout_ms=1000: ip in ("10.0.0.10", "10.9.9.1")
    )
    monkeypatch.setattr(messagebox, "showwarning", lambda *a, **kw: "ok")
    monkeypatch.setattr(messagebox, "askokcancel", lambda *a, **kw: True)
    prev_lang = get_language()
    root = tk_root
    app = None
    try:

        settings_file = tmp_path / "settings.xml"
        app = PsshApp(
            root,
            session_path=tmp_path / "session.xml",
            settings_path=settings_file,
            os_theme_override="light",
            os_lang_override="en",
        )

        # Sun-Valley light theme, 4 primary tabs, Device Models loaded from model/
        assert sv_ttk.get_theme(root) == "light"
        assert app.main_notebook.index(app.main_notebook.select()) == 0
        assert app.main_notebook.tab(2, "text") == "Devices"
        assert app.main_notebook.tab(3, "text") == "Device Models"
        assert len(app.snippets) >= 5
        assert len(app.device_models) >= 2
        assert str(app.jobs_footer_lbl.cget("foreground")) == "#000000"
        assert str(app.snippets_footer_lbl.cget("foreground")) == "#000000"
        assert str(app.devices_tab_footer_lbl.cget("foreground")) == "#000000"
        assert str(app.models_footer_lbl.cget("foreground")) == "#000000"

        # Header has logo, Config & Audit Automation subtitle, Info button, Cog button, NO Language label
        assert not hasattr(app, "header_lang_lbl")
        assert "Config & Audit Automation" in app.header_subtitle_lbl.cget("text")
        assert app.about_btn.cget("text") == "ⓘ"
        assert app.settings_btn.cget("text") == "⚙"
        header_right = app.about_btn.master
        assert header_right is app.settings_btn.master
        assert header_right.pack_slaves() == [app.about_btn, app.settings_btn]

        # AboutDialog displays clickable repo URL
        adlg = AboutDialog(root, dark_mode=False)
        adlg.withdraw()
        assert "github.com/" in adlg.repo_url
        assert adlg.repo_link_lbl.cget("text") == adlg.repo_url
        adlg.destroy()

        # SettingsDialog defaults to Auto (OS Default), fits Save/Cancel cleanly, enforces integer timeouts
        sdlg = SettingsDialog(root, app.settings)
        sdlg.withdraw()
        assert sdlg.lang_var.get() == "Auto (OS Default)"
        assert sdlg.theme_var.get() == "Auto (OS Default)"
        assert sdlg.connect_timeout_var.get() == 10
        assert sdlg.command_timeout_var.get() == 15
        assert "pt_BR" not in str(sdlg._lang_label_to_code.keys())
        assert "Português (Brasil)" in sdlg._lang_label_to_code
        sdlg.lang_var.set("Português (Brasil)")
        sdlg.theme_var.set(sdlg._theme_mode_to_label["dark"])
        sdlg._on_save()
        assert sdlg.result is not None
        app.settings = sdlg.result
        app._apply_effective_preferences()
        assert app.theme_mode == "dark"
        app._auto_save_settings()
        assert load_settings_xml(settings_file).language == "pt_BR"

        # Restore light/en for remaining English assertions
        app.settings.language = "en"
        app.settings.theme_mode = "light"
        app._apply_effective_preferences()
        sv_ttk.set_theme("light", root=root)
        app._build_layout()
        app._refresh_all_views()

        # Populate Devices with both AOS-S and AOS-CX models
        host_s = HostEntry(
            name="SW-AOSS-01",
            ip="10.9.9.1",
            os_type=SwitchOS.AOS_S,
            model="Aruba 2930F",
            folder_path="Building A",
        )
        host_cx = HostEntry(
            name="SW-AOSCX-01",
            ip="10.9.9.2",
            os_type=SwitchOS.AOS_CX,
            model="Aruba 6300M",
            folder_path="Core",
        )
        app.session.hosts = [host_s, host_cx]
        app._refresh_devices_tree()

        # Group search filters cleanly alongside Device/IP/OS/Status
        app.dev_flt_group.set("Building")
        app._refresh_devices_tree()
        assert list(app.devices_tree.get_children()) == ["0"]
        app.dev_flt_group.set("")
        app._refresh_devices_tree()
        assert len(app.devices_tree.get_children()) == 2

        # Row-level Action columns on Snippets, Devices, and Device Models
        assert "✎" in app.snippets_tree.item("0", "values")[-1]
        assert "✎" in app.devices_tree.item("0", "values")[-1]
        assert "✎" in app.models_tree.item("0", "values")[-1]

        # Import/Export Snippet and Import/Export Device Model buttons exist (no Open Folder buttons)
        def _collect_button_texts(widget):
            texts = []
            for child in widget.winfo_children():
                if isinstance(child, ttk.Button):
                    texts.append(child.cget("text"))
                texts.extend(_collect_button_texts(child))
            return texts

        snip_btns = _collect_button_texts(app.tab_snippets)
        mdl_btns = _collect_button_texts(app.tab_models)
        assert "Import Snippet" in snip_btns
        assert "Export Snippet" in snip_btns
        assert "Import Device Model" in mdl_btns
        assert "Export Device Model" in mdl_btns
        assert all("Open" not in t for t in snip_btns + mdl_btns)

        # SnippetEditorDialog uses compact Commands height (7), roomy Audit height (6),
        # ttk.Entry Description, and auto-hiding scrollbars when content fits
        sed = SnippetEditorDialog(root, dark_mode=False)
        sed.withdraw()
        sed.update_idletasks()
        assert int(sed.cmd_text.cget("height")) == 7
        assert int(sed.audit_regex_text.cget("height")) == 6
        assert isinstance(sed.desc_entry, ttk.Entry)
        sed_sbs = [w for w in sed.cmd_text.master.winfo_children() if isinstance(w, ttk.Scrollbar)]
        assert len(sed_sbs) == 2
        assert all(sb.winfo_manager() == "" for sb in sed_sbs)
        sed.destroy()

        # Verify dynamic AddJobDialog: starts with 3 steps (no variables), blue active label, blank snippet
        dlg = AddJobDialog(
            root,
            app.session,
            app.snippets,
            settings=app.settings,
            dark_mode=False,
            device_models=app.device_models,
        )
        dlg.withdraw()
        assert dlg.current_step == 0
        assert dlg.current_step_key == AddJobDialog.STEP_COMMAND
        assert dlg.job_name_var.get() == ""  # Empty Job Name
        assert dlg.snippet_choice_var.get() == ""  # Snippets dropdown starts blank
        assert len(dlg.step_circles) == 3  # Parameters hidden when template has no variables
        assert str(dlg.step_labels[0].cget("foreground")) == "#0067c0"
        assert isinstance(dlg.job_desc_entry, ttk.Entry)
        dlg_sbs = [w for w in dlg.cmd_text.master.winfo_children() if isinstance(w, ttk.Scrollbar)]
        assert len(dlg_sbs) == 2
        assert all(sb.winfo_manager() == "" for sb in dlg_sbs)

        # Clicking ahead to later steps is ignored
        dlg._on_step_label_click(2)
        assert dlg.current_step == 0

        # Switching to Audit on AOS-S shows "No Audit and Remediate snippets available for AOS-S."
        dlg.job_type_var.set(SnippetType.AUDIT.value)
        dlg._on_job_type_changed()
        assert "No Audit and Remediate snippets available for AOS-S." in dlg.snippet_desc_lbl.cget("text")
        dlg.job_type_var.set(SnippetType.CONFIG.value)
        dlg._on_job_type_changed()

        # Switching to Audit filters dropdown strictly to Audit snippets & resets selection to ""
        dlg.device_os_var.set("AOS-CX")
        dlg._on_os_changed()
        assert "ArubaOS-CX SNMPv3 Audit" not in dlg.snippet_combo.cget("values")
        dlg.snippet_choice_var.set("ArubaOS-CX NTP")
        dlg._on_snippet_chosen()
        assert len(dlg.step_circles) == 4  # Template has ${NTP Server} -> Parameters shown

        dlg.job_type_var.set(SnippetType.AUDIT.value)
        dlg._on_job_type_changed()
        assert dlg.snippet_choice_var.get() == ""  # Reset cleanly to blank
        assert list(dlg.snippet_combo.cget("values")) == ["ArubaOS-CX SNMPv3 Audit"]
        dlg.snippet_choice_var.set("ArubaOS-CX SNMPv3 Audit")
        dlg._on_snippet_chosen()
        assert dlg.job_type_var.get() == SnippetType.AUDIT.value
        assert "snmpv3 user" in dlg.audit_regex_text.get("1.0", "end-1c")
        assert len(dlg.step_circles) == 3  # Audit SNMPv3 has no ${} variables -> Parameters hidden
        dlg.job_name_var.set("Audit Only Test")
        dlg._on_next()
        assert dlg.current_step_key == AddJobDialog.STEP_DEVICES  # Skips Parameters cleanly!
        dlg._on_back()
        assert dlg.current_step_key == AddJobDialog.STEP_COMMAND

        # Switch back to Config + AOS-S SNMPv3 snippet (4 steps) and customize
        dlg.job_type_var.set(SnippetType.CONFIG.value)
        dlg._on_job_type_changed()
        assert dlg.snippet_choice_var.get() == ""
        dlg.device_os_var.set("AOS-S")
        dlg._on_os_changed()
        assert dlg.snippet_choice_var.get() == ""  # Blank again after OS switch
        assert "ArubaOS-CX SNMPv3 Audit" not in dlg.snippet_combo.cget("values")
        dlg.snippet_choice_var.set("ArubaOS-S SNMPv3 Configuration")
        dlg._on_snippet_chosen()
        assert dlg.job_type_var.get() == SnippetType.CONFIG.value
        assert len(dlg.step_circles) == 4
        dlg.job_name_var.set("Custom SNMPv3 Rollout")
        dlg.cmd_text.insert("end", '\nbanner motd "${Site Tier|["Access", "Core"]}"')

        # Advance to Step 2 (Parameters): ✓/✗ icons, password masking, python list Combobox
        dlg._on_next()
        assert dlg.current_step == 1
        assert "SNMPv3 Username" in dlg.param_entry_vars
        assert "Site Tier" in dlg.param_entry_vars
        assert dlg.param_status_labels["SNMPv3 Username"].cget("text") == "✗"
        dlg.param_entry_vars["SNMPv3 Username"].set("netmon_v3")
        dlg.param_entry_vars["Auth Password"].set("ExampleAuth!123")
        dlg.param_entry_vars["Privacy Password"].set("ExamplePriv!456")
        dlg.param_entry_vars["Site Tier"].set("Core")
        assert dlg.param_status_labels["SNMPv3 Username"].cget("text") == "✓"

        # Advance to Step 3 (Select Device): never auto-selects switches, no Device Role column, fixed Back | Next order
        dlg._on_next()
        assert dlg.current_step == 2
        assert dlg.selected_host_keys == set()  # Never auto-select switches
        assert "Snippet Target OS: AOS-S" in dlg.os_hint_lbl.cget("text")
        assert "role" not in dlg.device_tree.cget("columns")
        dlg.update_idletasks()
        assert int(dlg.back_btn.grid_info()["column"]) < int(dlg.next_btn.grid_info()["column"])
        assert dlg.back_btn.winfo_x() < dlg.next_btn.winfo_x()
        dlg._set_all_filtered(True)
        assert dlg.selected_host_keys == {host_s.unique_key}
        dlg._on_step_label_click(1)
        assert dlg.current_step == 1
        dlg._on_next()
        assert dlg.current_step == 2

        # Advance to Step 4 (Confirm): summary omits Device Model clutter, fixed Back | Run Job order
        dlg._on_next()
        assert dlg.current_step == 3
        dlg.update_idletasks()
        assert int(dlg.back_btn.grid_info()["column"]) < int(dlg.run_btn.grid_info()["column"])
        assert dlg.back_btn.winfo_x() < dlg.run_btn.winfo_x()
        assert dlg.confirm_summary_lbl.cget("text") == (
            "Job Name: Custom SNMPv3 Rollout  |  Snippet: ArubaOS-S SNMPv3 Configuration  |  "
            "Device Type: AOS-S (1 selected)"
        )
        # Returning from Step 4 to Step 3 preserves Back | Next order
        dlg._on_back()
        dlg.update_idletasks()
        assert int(dlg.back_btn.grid_info()["column"]) < int(dlg.next_btn.grid_info()["column"])
        assert dlg.back_btn.winfo_x() < dlg.next_btn.winfo_x()
        dlg._on_next()
        dlg.update_idletasks()
        assert dlg.back_btn.winfo_x() < dlg.run_btn.winfo_x()
        assert str(dlg.confirm_cmds_text.cget("state")) == "disabled"
        rendered_preview = dlg.confirm_cmds_text.get("1.0", "end-1c")
        assert rendered_preview.startswith("configure terminal\n")
        assert rendered_preview.endswith("\nend")
        assert "write memory" in dlg.write_cmd_check.cget("text")
        dlg.save_write_var.set(True)
        dlg._refresh_confirm_view()
        assert dlg.confirm_cmds_text.get("1.0", "end-1c").endswith("\nwrite memory")
        assert 'snmpv3 user "netmon_v3" auth sha "ExampleAuth!123" priv aes "ExamplePriv!456"' in rendered_preview
        assert 'banner motd "Core"' in rendered_preview
        dlg.destroy()

        # Verify redesigned Job Details (bold counts, borderless boxes, Open Logs Folder in Devices tab)
        job = JobRecord(
            job_id="j1",
            name="Test Job",
            job_type=SnippetType.AUDIT,
            device_type=SwitchOS.AOS_S,
            status="Failed",
            description="Rollout SNMPv3 configuration",
            commands_rendered="show snmpv3 users",
            audit_regex="snmpv3 user",
            creation_time="2026-11-17 16:40:00",
            start_time="2026-11-17 16:40:01",
            end_time="2026-11-17 16:40:04",
            results=[
                HostExecutionResult(
                    host=host_s,
                    status="Failed",
                    operation_result="Audit failed",
                    raw_output="Switch# show snmpv3 users\nNo users",
                )
            ],
        )
        app.session.jobs = [job]
        app.selected_job_id = "j1"
        app._refresh_jobs_tree()
        app._refresh_job_details()

        assert "Test Job" in app.job_details_title_lbl.cget("text")
        assert app.job_details_nb.index(app.job_details_nb.select()) == 0
        assert app.job_total_lbl.cget("text") == "1"
        assert app.job_fail_lbl.cget("text") == "1"
        assert str(app.job_desc_readonly.cget("relief")) == "flat"
        assert str(app.job_cmds_text.cget("relief")) == "flat"
        assert "show snmpv3 users" in app.job_cmds_text.get("1.0", "end-1c")
        assert "snmpv3 user" in app.job_audit_text.get("1.0", "end-1c")
        assert "🗑" in app.jobs_tree.item("j1", "values")[-1]
        assert app.job_devices_tree.item(host_s.unique_key, "values")[-1] == "📄"

        log_dlg = DeviceLogDialog(root, job.results[0], dark_mode=False)
        log_dlg.withdraw()
        log_dlg.destroy()

        # AirWaveImportDialog: Top-rooted folder indentation, no Device Role column,
        # Name/IP filters, and row checkboxes persisting across re-filtering
        folder_xml = (
            '<amp:amp_folder_list xmlns:amp="http://www.airwave.com">'
            '<folder id="1"><name>Top</name><parent_id>0</parent_id></folder>'
            '<folder id="10"><name>Campus</name><parent_id>1</parent_id></folder>'
            '<folder id="11"><name>Building A</name><parent_id>10</parent_id></folder>'
            '<folder id="12"><name>Building B</name><parent_id>10</parent_id></folder>'
            "</amp:amp_folder_list>"
        )
        ap_xml = (
            '<amp:amp_ap_list xmlns:amp="http://www.airwave.com">'
            '<ap id="1"><name>SW-A1</name><lan_ip>10.1.1.1</lan_ip><device_category>switch</device_category>'
            "<model>Aruba 2930F</model><firmware>WC.16.10.0017</firmware><is_up>true</is_up>"
            '<folder id="11">Building A</folder></ap>'
            '<ap id="2"><name>SW-B1</name><lan_ip>10.2.2.2</lan_ip><device_category>switch</device_category>'
            "<model>Aruba 6300M</model><firmware>FL.10.13.1000</firmware><is_up>true</is_up>"
            '<folder id="12">Building B</folder></ap>'
            "</amp:amp_ap_list>"
        )
        aw_dlg = AirWaveImportDialog(root, app.settings)
        aw_dlg.withdraw()
        assert "role" not in aw_dlg.tree.cget("columns")
        assert aw_dlg.tree.cget("columns")[0] == "sel"
        aw_dlg._on_inventory_loaded(parse_airwave_folders(folder_xml), ap_xml)
        assert list(aw_dlg.folder_combo.cget("values")) == [
            "All",
            "Top",
            "  Campus",
            "    Building A",
            "    Building B",
        ]
        aw_dlg.folder_var.set("    Building A")
        aw_dlg._apply_filters()
        assert [h.name for h in aw_dlg.preview_hosts] == ["SW-A1"]
        aw_dlg._set_all_visible(True)
        assert aw_dlg.checked_host_keys == {"10.1.1.1:22"}

        aw_dlg.folder_var.set("    Building B")
        aw_dlg._apply_filters()
        assert [h.name for h in aw_dlg.preview_hosts] == ["SW-B1"]
        assert aw_dlg.checked_host_keys == {"10.1.1.1:22"}  # Persists across re-filter
        aw_dlg._set_all_visible(True)
        assert aw_dlg.checked_host_keys == {"10.1.1.1:22", "10.2.2.2:22"}

        aw_dlg.folder_var.set("Top")
        aw_dlg._apply_filters()
        assert [aw_dlg.tree.item(h.unique_key, "values")[0] for h in aw_dlg.preview_hosts] == ["☑", "☑"]
        aw_dlg._accept()
        assert [h.name for h in (aw_dlg.imported_hosts or [])] == ["SW-A1", "SW-B1"]

        # Opening AirWaveImportDialog with existing AirWave devices:
        # 1) ignores stale saved filters & opens with OS Type = All / blank fields
        # 2) pre-populates & selects only existing AirWave devices (excluding Manual)
        # 3) unselected device stays in Devices list AND is NOT updated on import
        app.settings.airwave_filters.folder = "Building B"
        app.settings.airwave_filters.name_filter = "stale"
        app.settings.airwave_filters.ip_filter = "10.9"
        app.settings.airwave_filters.model = "6300"
        app.settings.airwave_filters.os_filter = "AOS-CX"
        app.settings.airwave_filters.status_filter = "Down"
        app.session.hosts = [
            HostEntry(
                name="MANUAL-SW",
                ip="10.9.9.9",
                os_type=SwitchOS.AOS_S,
                firmware="M.1.0",
                airwave_status="Manual",
            ),
            HostEntry(
                name="SW-A1",
                ip="10.1.1.1",
                os_type=SwitchOS.AOS_S,
                model="Aruba 2930F",
                firmware="OLD_FW_A",
                folder_id="11",
                folder_path="Top > Campus > Building A",
                airwave_status="Up",
            ),
            HostEntry(
                name="SW-B1",
                ip="10.2.2.2",
                os_type=SwitchOS.AOS_CX,
                model="Aruba 6300M",
                firmware="OLD_FW_B",
                folder_id="12",
                folder_path="Top > Campus > Building B",
                airwave_status="Up",
            ),
        ]
        aw_pre = AirWaveImportDialog(root, app.settings, existing_hosts=app.session.hosts)
        aw_pre.withdraw()
        assert aw_pre.os_var.get() == "All"
        assert aw_pre.folder_var.get() == "All"
        assert aw_pre.status_var.get() == "All"
        assert aw_pre.name_var.get() == ""
        assert aw_pre.ip_var.get() == ""
        assert aw_pre.model_var.get() == ""
        assert [h.name for h in aw_pre.preview_hosts] == ["SW-A1", "SW-B1"]
        assert aw_pre.checked_host_keys == {"10.1.1.1:22", "10.2.2.2:22"}
        assert [aw_pre.tree.item(h.unique_key, "values")[0] for h in aw_pre.preview_hosts] == ["☑", "☑"]

        ap_xml_updated = (
            '<amp:amp_ap_list xmlns:amp="http://www.airwave.com">'
            '<ap id="1"><name>SW-A1</name><lan_ip>10.1.1.1</lan_ip><device_category>switch</device_category>'
            "<model>Aruba 2930F</model><firmware>WC.16.10.0017</firmware><is_up>true</is_up>"
            '<folder id="11">Building A</folder></ap>'
            '<ap id="2"><name>SW-B1</name><lan_ip>10.2.2.2</lan_ip><device_category>switch</device_category>'
            "<model>Aruba 6300M</model><firmware>FL.10.13.1000</firmware><is_up>true</is_up>"
            '<folder id="12">Building B</folder></ap>'
            '<ap id="3"><name>SW-C1</name><lan_ip>10.3.3.3</lan_ip><device_category>switch</device_category>'
            "<model>Aruba 6200F</model><firmware>ML.10.14.0001</firmware><is_up>true</is_up>"
            '<folder id="11">Building A</folder></ap>'
            "</amp:amp_ap_list>"
        )
        aw_pre._on_inventory_loaded(parse_airwave_folders(folder_xml), ap_xml_updated)
        assert [aw_pre.tree.item(h.unique_key, "values")[0] for h in aw_pre.preview_hosts] == [
            "☑",
            "☑",
            "☐",
        ]
        # Uncheck SW-B1 and select new SW-C1
        aw_pre.checked_host_keys.discard("10.2.2.2:22")
        aw_pre.checked_host_keys.add("10.3.3.3:22")
        aw_pre._accept()
        assert app.settings.airwave_filters.os_filter == "All"
        assert app.settings.airwave_filters.folder == ""
        app._merge_imported_hosts(aw_pre.imported_hosts or [])
        by_key = {h.unique_key: h for h in app.session.hosts}
        assert by_key["10.1.1.1:22"].firmware == "WC.16.10.0017"  # Selected -> updated
        assert by_key["10.3.3.3:22"].name == "SW-C1"  # Newly selected -> added
        assert "10.2.2.2:22" in by_key
        assert by_key["10.2.2.2:22"].firmware == "OLD_FW_B"  # Unselected -> still exists & NOT updated
        assert by_key["10.9.9.9:22"].firmware == "M.1.0"  # Manual -> untouched

        # pt_BR localization applies across tabs, subtitle, SnippetType, "All", and Status dropdowns
        set_language("pt_BR")
        app._build_layout()
        app._refresh_all_views()
        assert app.main_notebook.tab(2, "text") == "Dispositivos"
        assert app.main_notebook.tab(3, "text") == "Modelos de Dispositivo"
        assert "Automação de Configuração e Auditoria" in app.header_subtitle_lbl.cget("text")
        assert app.jobs_tree.item("j1", "values")[1] == "Auditoria e Remediação"
        assert list(app._job_status_filter_map.keys()) == ["Todos", "Sucesso", "Falhou", "Executando"]
        assert list(app._job_dev_status_filter_map.keys()) == [
            "Todos",
            "Sucesso",
            "Falhou",
            "Executando",
            "Pendente",
        ]

        # Auto-hiding vertical scrollbars stay ungridded when content fits
        root.update()
        for tab, tree in (
            (app.tab_jobs, app.jobs_tree),
            (app.tab_snippets, app.snippets_tree),
            (app.tab_snippets, app.snippet_preview_text),
            (app.tab_devices, app.devices_tree),
            (app.tab_models, app.models_tree),
            (app.tab_models, app.model_preview_text),
        ):
            app.main_notebook.select(tab)
            root.update()
            sbs = [w for w in tree.master.winfo_children() if isinstance(w, ttk.Scrollbar)]
            assert sbs and all(sb.winfo_manager() == "" for sb in sbs)

        # Device Status & OS dropdowns use localized pt_BR values (Online / Offline / Desconhecido)
        dev_combos = []

        def _collect_combos(widget):
            for ch in widget.winfo_children():
                if isinstance(ch, ttk.Combobox):
                    dev_combos.append(ch)
                _collect_combos(ch)

        _collect_combos(app.tab_devices)
        status_combo = next(cb for cb in dev_combos if "Online" in cb.cget("values"))
        assert list(status_combo.cget("values")) == ["Todos", "Online", "Offline", "Desconhecido"]
        os_combo = next(cb for cb in dev_combos if "AOS-S" in cb.cget("values"))
        assert "Desconhecido" in os_combo.cget("values")
        by_key["10.1.1.1:22"].ping_status = "Up"
        app.dev_flt_st2.set("Online")
        app._refresh_devices_tree()
        assert len(app.devices_tree.get_children()) == 1
        first_iid = app.devices_tree.get_children()[0]
        assert app.devices_tree.item(first_iid, "values")[1] == "Online"
    finally:
        if app is not None:
            app._stop_devices_ping_timer()
        for child in list(tk_root.winfo_children()):
            child.destroy()
        set_language(prev_lang)


def _drain_tk_until(root: tk.Tk, pred, poll_fn, timeout_s: float = 2.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        poll_fn()
        root.update()
        if pred():
            return
        time.sleep(0.01)


def test_pagination_page_ping_offline_warning_and_status_separation(
    tmp_path: Path, monkeypatch, tk_root: tk.Tk
):
    prev_lang = get_language()
    ping_calls: list[str] = []
    warnings: list[tuple[str, str]] = []
    okcancel_calls: list[tuple[str, str]] = []
    okcancel_reply = [False]
    down_override: set[str] = set()

    def fake_ping(ip: str, timeout_ms: int = 1000) -> bool:
        ping_calls.append(ip)
        if ip in down_override:
            return False
        last_octet = int(ip.split(".")[-1])
        return (last_octet % 2) == 1

    monkeypatch.setattr(ping_checker, "ping_host", fake_ping)
    monkeypatch.setattr(
        messagebox,
        "showwarning",
        lambda title, msg, **_kw: (warnings.append((title, msg)), "ok")[1],
    )
    monkeypatch.setattr(
        messagebox,
        "askokcancel",
        lambda title, msg, **_kw: (okcancel_calls.append((title, msg)), okcancel_reply[0])[1],
    )

    root = tk_root
    app = None
    try:

        app = PsshApp(
            root,
            session_path=tmp_path / "session.xml",
            settings_path=tmp_path / "settings.xml",
            os_theme_override="light",
            os_lang_override="en",
        )
        # 15 switches so page_size=10 splits across 2 pages
        hosts = [
            HostEntry(
                name=f"SW-{i:02d}",
                ip=f"10.0.1.{i}",
                os_type=SwitchOS.AOS_S,
                model="Aruba 2930F",
                airwave_status="Down" if i == 1 else "Up",
            )
            for i in range(1, 16)
        ]
        app.session.hosts = hosts
        app.devices_paginator.page_size_var.set("10")
        app._refresh_devices_tree()
        assert len(app.devices_tree.get_children()) == 10
        assert "Page 1 of 2" in app.devices_paginator.page_lbl.cget("text")
        # Not on Devices tab -> no background ping sweeps fired
        assert ping_calls == []
        assert all(h.ping_status == "Unknown" for h in hosts)

        # Activate Devices tab -> pings ONLY current page (rows 1..10) concurrently
        app.main_notebook.select(app.tab_devices)
        app._on_tab_changed()
        _drain_tk_until(
            root,
            lambda: all(h.ping_status != "Unknown" for h in hosts[:10]),
            app._poll_devices_ping_queue,
        )
        assert set(ping_calls) == {f"10.0.1.{i}" for i in range(1, 11)}
        assert hosts[0].ping_status == "Up"
        assert hosts[1].ping_status == "Down"
        assert all(h.ping_status == "Unknown" for h in hosts[10:])
        # Status column renders ping_status (no latency ms); airwave_status stays intact
        assert app.devices_tree.item("0", "values")[1] == "Up"
        assert app.devices_tree.item("1", "values")[1] == "Down"
        assert hosts[0].airwave_status == "Down"  # AirWave origin status untouched!

        # Navigate to Page 2 -> pings ONLY rows 11..15
        ping_calls.clear()
        app.devices_paginator.next_page()
        _drain_tk_until(
            root,
            lambda: all(h.ping_status != "Unknown" for h in hosts[10:]),
            app._poll_devices_ping_queue,
        )
        assert set(ping_calls) == {f"10.0.1.{i}" for i in range(11, 16)}
        assert len(app.devices_tree.get_children()) == 5
        assert "Page 2 of 2" in app.devices_paginator.page_lbl.cget("text")

        # Switching away from Devices tab halts ping sweeps
        ping_calls.clear()
        app.main_notebook.select(app.tab_snippets)
        app._on_tab_changed()
        app._trigger_devices_ping_sweep()
        assert ping_calls == []

        # On-the-fly Status filtering: hosts starting Unknown get pinged when filtering Up
        fly_hosts = [
            HostEntry(
                name=f"FLY-{i:02d}",
                ip=f"10.0.3.{i}",
                os_type=SwitchOS.AOS_S,
                folder_path=f"Floor {i % 2}",
            )
            for i in range(1, 7)
        ]
        app.session.hosts = fly_hosts
        app.dev_flt_st2.set("Up")
        app._refresh_devices_tree(reset_page=True, trigger_ping=False)
        assert len(app.devices_tree.get_children()) == 0
        app.main_notebook.select(app.tab_devices)
        app._on_tab_changed()
        _drain_tk_until(
            root,
            lambda: len(app.devices_tree.get_children()) == 3,
            app._poll_devices_ping_queue,
        )
        assert len(app.devices_tree.get_children()) == 3
        assert all(
            app.devices_tree.item(iid, "values")[1] == "Up"
            for iid in app.devices_tree.get_children()
        )
        app.dev_flt_st2.set("All")
        app.main_notebook.select(app.tab_jobs)
        app._on_tab_changed()

        # Verify paginators exist across all 7 tables
        for pag in (
            app.jobs_paginator,
            app.job_devices_paginator,
            app.snippets_paginator,
            app.devices_paginator,
            app.models_paginator,
        ):
            assert pag.page_size == 25 or pag is app.devices_paginator

        # AddJobDialog Step 3: never auto-selects, unifies filters with Devices,
        # checks current page + selected devices, and shows OK/Cancel offline prompt on Next
        fresh_hosts = [
            HostEntry(
                name=f"SW-{i:02d}",
                ip=f"10.0.2.{i}",
                os_type=SwitchOS.AOS_S,
                model="Aruba 2930F",
                folder_path="Campus",
                airwave_status="Manual",
            )
            for i in range(1, 16)
        ]
        app.session.hosts = fresh_hosts
        ping_calls.clear()
        dlg = AddJobDialog(
            root,
            session=app.session,
            snippets=app.snippets,
            settings=app.settings,
            dark_mode=False,
            device_models=app.device_models,
        )
        dlg.withdraw()
        assert dlg.selected_host_keys == set()
        assert not hasattr(dlg, "col_flt_type")
        assert not hasattr(dlg, "col_flt_fw")
        dlg.devices_paginator.page_size_var.set("10")
        dlg.device_os_var.set("AOS-S")
        dlg._on_os_changed()
        dlg.snippet_choice_var.set("ArubaOS-S SNMPv3 Configuration")
        dlg._on_snippet_chosen()
        dlg.job_name_var.set("Pagination Test")
        assert ping_calls == []  # Step 1 does NOT ping

        # Step 2 (Parameters) & Step 3 (Select Device) hide vertical scrollbars when content fits
        dlg.snippet_choice_var.set("ArubaOS-S NTP")
        dlg._on_snippet_chosen()
        dlg._on_next()
        assert dlg.current_step_key == AddJobDialog.STEP_PARAMS
        dlg.update()
        param_sbs = [w for w in dlg.param_canvas.master.winfo_children() if isinstance(w, ttk.Scrollbar)]
        assert param_sbs and all(sb.winfo_manager() == "" for sb in param_sbs)

        # Enter Step 3 -> pings ONLY first 10 visible hosts concurrently
        dlg._go_to_step_key(AddJobDialog.STEP_DEVICES)
        dlg.update()
        step3_sbs = [w for w in dlg.device_tree.master.winfo_children() if isinstance(w, ttk.Scrollbar)]
        assert step3_sbs and all(sb.winfo_manager() == "" for sb in step3_sbs)
        assert dlg.selected_host_keys == set()
        _drain_tk_until(
            root,
            lambda: all(h.ping_status != "Unknown" for h in fresh_hosts[:10]),
            dlg._poll_step3_ping_queue,
        )
        assert set(ping_calls) == {f"10.0.2.{i}" for i in range(1, 11)}
        assert all(h.ping_status == "Unknown" for h in fresh_hosts[10:])

        # Select All applies across ALL 15 filtered hosts without immediate popup,
        # and queues pings for newly selected Unknown switches on page 2
        warnings.clear()
        okcancel_calls.clear()
        dlg._set_all_filtered(True)
        assert len(dlg.selected_host_keys) == 15
        assert warnings == []
        assert okcancel_calls == []
        _drain_tk_until(
            root,
            lambda: all(h.ping_status != "Unknown" for h in fresh_hosts[10:]),
            dlg._poll_step3_ping_queue,
        )

        # Selected Up switch turns Down while viewing Page 2 -> background sweep detects it,
        # pressing Next resolves any remaining Unknown and prompts OK/Cancel
        dlg._set_all_filtered(False)
        assert dlg.selected_host_keys == set()
        assert fresh_hosts[0].ping_status == "Up"
        dlg.selected_host_keys.add(fresh_hosts[0].unique_key)
        fresh_hosts[10].ping_status = "Unknown"
        dlg.selected_host_keys.add(fresh_hosts[10].unique_key)
        down_override.add("10.0.2.1")
        ping_calls.clear()
        dlg.devices_paginator.next_page()
        _drain_tk_until(
            root,
            lambda: fresh_hosts[0].ping_status == "Down" and fresh_hosts[10].ping_status == "Up",
            dlg._poll_step3_ping_queue,
        )
        assert "10.0.2.1" in ping_calls  # Off-page selected device still checked!

        # Next > with Unknown selected + Down selected: resolves Unknown, asks OK/Cancel
        fresh_hosts[10].ping_status = "Unknown"
        okcancel_reply[0] = False  # User clicks Cancel
        dlg._on_next()
        assert fresh_hosts[10].ping_status == "Up"
        assert len(okcancel_calls) == 1
        assert "Offline" in okcancel_calls[0][0]
        assert "10.0.2.1" in okcancel_calls[0][1]
        assert dlg.current_step_key == AddJobDialog.STEP_DEVICES

        okcancel_reply[0] = True  # User clicks OK to proceed anyway with offline switch
        dlg._on_next()
        assert dlg.current_step_key == AddJobDialog.STEP_CONFIRM

        # Multiple offline hosts list exact device labels & IPs in confirmation
        okcancel_calls.clear()
        fresh_hosts[1].ping_status = "Down"
        dlg._warn_offline_hosts([fresh_hosts[0], fresh_hosts[1]])
        assert len(okcancel_calls) == 1
        assert "SW-01 (10.0.2.1)" in okcancel_calls[0][1]
        assert "SW-02 (10.0.2.2)" in okcancel_calls[0][1]

        # Moving back to Step 1 stops Step 3 ping sweeps cleanly
        ping_calls.clear()
        dlg._go_to_step_key(AddJobDialog.STEP_COMMAND)
        dlg._trigger_step3_ping_sweep()
        assert ping_calls == []
        dlg.destroy()

        # AirWaveImportDialog paginates too, displays AirWave airwave_status, and Select All selects all pages
        folder_xml = (
            '<amp:amp_folder_list xmlns:amp="http://www.airwave.com">'
            '<folder id="1"><name>Top</name><parent_id>0</parent_id></folder>'
            "</amp:amp_folder_list>"
        )
        ap_items = "".join(
            f'<ap id="{i}"><name>AW-{i:02d}</name><lan_ip>10.9.1.{i}</lan_ip>'
            f'<device_category>switch</device_category><model>Aruba 2930F</model>'
            f'<firmware>WC.16.10</firmware><is_up>{"false" if i == 1 else "true"}</is_up>'
            f'<folder id="1">Top</folder></ap>'
            for i in range(1, 14)
        )
        aw_dlg = AirWaveImportDialog(root, app.settings, dark_mode=False)
        aw_dlg.withdraw()
        aw_dlg.paginator.page_size_var.set("10")
        aw_dlg._on_inventory_loaded(
            parse_airwave_folders(folder_xml),
            f'<amp:amp_ap_list xmlns:amp="http://www.airwave.com">{ap_items}</amp:amp_ap_list>',
        )
        assert len(aw_dlg.tree.get_children()) == 10
        assert aw_dlg.tree.item("10.9.1.1:22", "values")[2] == "Down"  # Shows AirWave reported status
        aw_dlg._set_all_visible(True)
        assert len(aw_dlg.checked_host_keys) == 13  # Applies across both pages
        aw_dlg.destroy()
    finally:
        if app is not None:
            app._stop_devices_ping_timer()
        for child in list(tk_root.winfo_children()):
            child.destroy()
        set_language(prev_lang)
