"""Headless GUI smoke tests covering Device Models tab, AboutDialog, SettingsDialog, circular wizard, Audit RegEx, and row actions."""

from pathlib import Path
import tkinter as tk
import pytest
import sv_ttk

from pssh_ui.gui import AboutDialog, AddJobDialog, DeviceLogDialog, PsshApp, SettingsDialog
from pssh_ui.i18n import get_language, set_language
from pssh_ui.models import (
    HostEntry,
    HostExecutionResult,
    JobRecord,
    SnippetType,
    SwitchOS,
)
from pssh_ui.settings_store import load_settings_xml


def test_gui_smoke_lifecycle(tmp_path: Path):
    prev_lang = get_language()
    try:
        try:
            root = tk.Tk()
            root.withdraw()
        except tk.TclError as exc:
            pytest.skip(f"Tk display unavailable in this environment: {exc}")

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
        root.update_idletasks()
        assert app.about_btn.winfo_x() >= app.settings_btn.winfo_x()

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

        # Dynamic Model dropdown updates cleanly when devices change
        assert list(app.dev_model_combo.cget("values")) == ["All", "Aruba 2930F", "Aruba 6300M"]
        app.session.hosts.pop(1)
        app._refresh_devices_tree()
        assert list(app.dev_model_combo.cget("values")) == ["All", "Aruba 2930F"]
        app.session.hosts.append(host_cx)
        app._refresh_devices_tree()

        # Row-level Action columns on Snippets, Devices, and Device Models
        assert "✎" in app.snippets_tree.item("0", "values")[-1]
        assert "✎" in app.devices_tree.item("0", "values")[-1]
        assert "✎" in app.models_tree.item("0", "values")[-1]

        # Verify 4-step AddJobDialog:
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
        assert dlg.job_name_var.get() == ""  # Empty Job Name
        assert dlg.snippet_choice_var.get() == ""  # Snippets dropdown starts blank
        assert len(dlg.step_circles) == 4  # Circular stepper without underline

        # Clicking ahead to Step 3 is ignored
        dlg._on_step_label_click(2)
        assert dlg.current_step == 0

        # Selecting an Audit snippet reveals Audit Validation RegEx textarea; Config hides it
        dlg.device_os_var.set("AOS-CX")
        dlg._populate_snippets_for_os()
        dlg.snippet_choice_var.set("ArubaOS-CX SNMPv3 Audit")
        dlg._on_snippet_chosen()
        assert dlg.job_type_var.get() == SnippetType.AUDIT.value
        assert "snmpv3 user" in dlg.audit_regex_text.get("1.0", "end-1c")

        # Switch back to AOS-S Config SNMPv3 snippet and customize
        dlg.device_os_var.set("AOS-S")
        dlg._populate_snippets_for_os()
        assert dlg.snippet_choice_var.get() == ""  # Blank again after OS switch
        dlg.snippet_choice_var.set("ArubaOS-S SNMPv3 Configuration")
        dlg._on_snippet_chosen()
        assert dlg.job_type_var.get() == SnippetType.CONFIG.value
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

        # Advance to Step 3 (Select Device): Snippet Target OS + back-click preserved
        dlg._on_next()
        assert dlg.current_step == 2
        assert "Snippet Target OS: AOS-S" in dlg.os_hint_lbl.cget("text")
        dlg._on_step_label_click(1)
        assert dlg.current_step == 1
        dlg._on_next()
        assert dlg.current_step == 2

        # Advance to Step 4 (Confirm): includes automatic DeviceModel Pre/Post commands + optional write checkbox
        dlg._on_next()
        assert dlg.current_step == 3
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

        # pt_BR localization applies across tabs & subtitle
        set_language("pt_BR")
        app._build_layout()
        assert app.main_notebook.tab(2, "text") == "Dispositivos"
        assert app.main_notebook.tab(3, "text") == "Modelos de Dispositivo"
        assert "Automação de Configuração e Auditoria" in app.header_subtitle_lbl.cget("text")

        root.destroy()
    finally:
        set_language(prev_lang)
