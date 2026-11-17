"""Multiplatform Sun-Valley-ttk GUI with OS theme/language detection, settings.xml, and AirWave-style tabs."""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable, Dict, List, Optional
import uuid
import webbrowser

import sv_ttk

from pssh_ui import __app_name__, __version__
from pssh_ui.airwave_importer import (
    fetch_airwave_inventory,
    infer_switch_os,
    parse_airwave_devices,
)
from pssh_ui.i18n import (
    _,
    available_languages,
    get_language,
    get_language_label,
    set_language,
)
from pssh_ui.job_builder import (
    build_commands_for_job,
    discover_device_types,
    get_assigned_groups,
    get_assigned_models,
    validate_job_inputs,
    wrap_commands_with_model,
)
from pssh_ui.model_store import ModelStore
from pssh_ui.models import (
    AirWaveFilter,
    AppSettings,
    DeviceModel,
    HostEntry,
    HostExecutionResult,
    JobRecord,
    ScheduleSequence,
    SessionData,
    Snippet,
    SnippetSeverity,
    SnippetType,
    SwitchOS,
    parse_device_type,
)
from pssh_ui.os_integration import detect_os_language, detect_os_theme
from pssh_ui.parser import detect_output_errors, parse_commands
from pssh_ui.paths import get_assets_dir, get_repository_url
from pssh_ui.session_store import (
    DEFAULT_SESSION_PATH,
    load_session_xml,
    migrate_legacy_settings_from_session,
    save_session_xml,
)
from pssh_ui.settings_store import (
    DEFAULT_SETTINGS_PATH,
    load_settings_xml,
    save_settings_xml,
)
from pssh_ui.snippet_store import SnippetStore
from pssh_ui.ssh_runner import BatchSSHExecutor
from pssh_ui.variables import (
    extract_variables,
    render_template,
    scan_dollar_brace_tokens,
    validate_single_value,
    validate_variable_values,
)


def open_path_in_os(target: Path | str) -> None:
    """Open a file or directory using the platform's default file manager/viewer."""
    path = Path(target)
    if not path.exists():
        return
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def apply_sun_valley_theme(root: tk.Tk, mode: str) -> None:
    """Apply Sun-Valley ttk theme ('light' or 'dark')."""
    target = "dark" if (mode or "").lower() == "dark" else "light"
    sv_ttk.set_theme(target, root=root)


def configure_editor_tags(text_widget: tk.Text, dark_mode: bool = False) -> None:
    """Configure visual syntax tags on a CLI text widget."""
    if dark_mode:
        text_widget.tag_configure("comment", foreground="#6ee7b7")
        text_widget.tag_configure("variable", foreground="#60a5fa", underline=True)
    else:
        text_widget.tag_configure("comment", foreground="#15803d")
        text_widget.tag_configure("variable", foreground="#007fff", underline=True)


def apply_cli_syntax_highlighting(text_widget: tk.Text) -> None:
    """Highlight '!' comment lines and ${var|...} tokens."""
    text_widget.tag_remove("comment", "1.0", tk.END)
    text_widget.tag_remove("variable", "1.0", tk.END)

    content = text_widget.get("1.0", "end-1c")
    for line_idx, raw_line in enumerate(content.splitlines(), start=1):
        stripped = raw_line.lstrip()
        if stripped.startswith("!"):
            text_widget.tag_add("comment", f"{line_idx}.0", f"{line_idx}.end")
            continue

        for start, end, _inner in scan_dollar_brace_tokens(raw_line):
            text_widget.tag_add("variable", f"{line_idx}.{start}", f"{line_idx}.{end}")


def _make_readonly_text(
    parent: tk.Misc,
    height: int = 4,
    dark_mode: bool = False,
    wrap: str = tk.WORD,
    font: tuple[str, int] = ("Segoe UI", 10),
) -> tk.Text:
    """Create a borderless styled read-only Tk Text widget matching light/dark surface tokens."""
    bg = "#1e293b" if dark_mode else "#f1f5f9"
    fg = "#f8fafc" if dark_mode else "#0f172a"
    return tk.Text(
        parent,
        wrap=wrap,
        height=height,
        font=font,
        bg=bg,
        fg=fg,
        relief=tk.FLAT,
        borderwidth=0,
        padx=8,
        pady=6,
        highlightthickness=0,
        state=tk.DISABLED,
    )


def _create_int_spinbox(
    parent: tk.Misc,
    textvariable: tk.IntVar,
    from_: int,
    to: int,
    width: Optional[int] = None,
) -> ttk.Spinbox:
    """Create a ttk.Spinbox restricted to integer digits only (no decimals/dots)."""
    vcmd = (parent.register(lambda new_val: new_val == "" or new_val.isdigit()), "%P")
    kwargs: Dict[str, Any] = {
        "from_": from_,
        "to": to,
        "increment": 1,
        "textvariable": textvariable,
        "validate": "key",
        "validatecommand": vcmd,
    }
    if width is not None:
        kwargs["width"] = width
    return ttk.Spinbox(parent, **kwargs)


def _bind_tree_action_cursor(tree: ttk.Treeview, action_col_id: str) -> None:
    """Show a hand cursor when hovering over an action/log icon column."""

    def _on_motion(event: tk.Event) -> None:
        region = tree.identify("region", event.x, event.y)
        col = tree.identify_column(event.x)
        row = tree.identify_row(event.y)
        tree.configure(cursor="hand2" if (region == "cell" and row and col == action_col_id) else "")

    tree.bind("<Motion>", _on_motion)


class SettingsDialog(tk.Toplevel):
    """Global application settings dialog (Language, Dark Theme, and Execution Defaults)."""

    def __init__(self, parent: tk.Misc, current: AppSettings) -> None:
        super().__init__(parent)
        self.title(_("Settings"))
        self.transient(parent)
        self.grab_set()
        self.result: Optional[AppSettings] = None
        self._current = current

        frame = ttk.Frame(self, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.columnconfigure(1, weight=1)

        # Appearance (Language + Dark Theme)
        app_box = ttk.LabelFrame(frame, text=_("Appearance"), padding=12)
        app_box.grid(row=0, column=0, columnspan=2, sticky=tk.EW, pady=(0, 10))
        app_box.columnconfigure(1, weight=1)

        langs = available_languages()
        auto_lang_label = _("Auto (OS Default)")
        self._lang_label_to_code: Dict[str, str] = {auto_lang_label: "auto"}
        self._lang_code_to_label: Dict[str, str] = {"auto": auto_lang_label}
        for code in langs:
            lbl = get_language_label(code)
            self._lang_label_to_code[lbl] = code
            self._lang_code_to_label[code] = lbl

        initial_lang_lbl = self._lang_code_to_label.get(
            current.language if current.language in self._lang_code_to_label else "auto",
            auto_lang_label,
        )
        self.lang_var = tk.StringVar(value=initial_lang_lbl)

        ttk.Label(app_box, text=_("Language:")).grid(row=0, column=0, sticky=tk.W, pady=4, padx=(0, 10))
        ttk.Combobox(
            app_box,
            textvariable=self.lang_var,
            values=list(self._lang_label_to_code.keys()),
            state="readonly",
        ).grid(row=0, column=1, sticky=tk.EW, pady=4)

        theme_auto_lbl = _("Auto (OS Default)")
        theme_light_lbl = _("Light")
        theme_dark_lbl = _("Dark")
        self._theme_label_to_mode = {
            theme_auto_lbl: "auto",
            theme_light_lbl: "light",
            theme_dark_lbl: "dark",
        }
        self._theme_mode_to_label = {v: k for k, v in self._theme_label_to_mode.items()}
        self.theme_var = tk.StringVar(
            value=self._theme_mode_to_label.get(
                (current.theme_mode or "auto").lower(), theme_auto_lbl
            )
        )

        ttk.Label(app_box, text=_("Dark Theme:")).grid(row=1, column=0, sticky=tk.W, pady=4, padx=(0, 10))
        ttk.Combobox(
            app_box,
            textvariable=self.theme_var,
            values=list(self._theme_label_to_mode.keys()),
            state="readonly",
        ).grid(row=1, column=1, sticky=tk.EW, pady=4)

        # Execution Defaults (strict integers)
        exec_box = ttk.LabelFrame(frame, text=_("SSH & Execution Defaults"), padding=12)
        exec_box.grid(row=1, column=0, columnspan=2, sticky=tk.EW, pady=(0, 12))
        exec_box.columnconfigure(1, weight=1)

        self.ssh_user_var = tk.StringVar(value=current.ssh_username)
        self.ssh_port_var = tk.IntVar(value=max(1, int(current.ssh_port)))
        self.max_parallel_var = tk.IntVar(value=max(1, int(current.max_parallel)))
        self.connect_timeout_var = tk.IntVar(value=max(1, int(current.connect_timeout)))
        self.command_timeout_var = tk.IntVar(value=max(1, int(current.command_timeout)))

        exec_rows = [
            (_("Default SSH Username:"), ttk.Entry(exec_box, textvariable=self.ssh_user_var)),
            (_("Default SSH Port:"), _create_int_spinbox(exec_box, self.ssh_port_var, 1, 65535)),
            (_("Max Parallel Executions:"), _create_int_spinbox(exec_box, self.max_parallel_var, 1, 64)),
            (_("Connect Timeout (s):"), _create_int_spinbox(exec_box, self.connect_timeout_var, 1, 120)),
            (_("Command Timeout (s):"), _create_int_spinbox(exec_box, self.command_timeout_var, 1, 300)),
        ]
        for r_idx, (lbl, widget) in enumerate(exec_rows):
            ttk.Label(exec_box, text=lbl).grid(row=r_idx, column=0, sticky=tk.W, pady=4, padx=(0, 10))
            widget.grid(row=r_idx, column=1, sticky=tk.EW, pady=4)

        btn_bar = ttk.Frame(frame)
        btn_bar.grid(row=2, column=0, columnspan=2, sticky=tk.E, pady=(6, 0))
        ttk.Button(btn_bar, text=_("Cancel"), command=self.destroy).pack(side=tk.RIGHT, padx=(8, 0))
        ttk.Button(btn_bar, text=_("Save"), style="Accent.TButton", command=self._on_save).pack(
            side=tk.RIGHT
        )

        self.update_idletasks()
        req_w = max(520, self.winfo_reqwidth() + 16)
        req_h = max(460, self.winfo_reqheight() + 12)
        self.geometry(f"{req_w}x{req_h}")
        self.minsize(req_w, req_h)
        self.resizable(False, False)

    def _on_save(self) -> None:
        lang_code = self._lang_label_to_code.get(self.lang_var.get(), "auto")
        theme_mode = self._theme_label_to_mode.get(self.theme_var.get(), "auto")
        try:
            ssh_port = max(1, min(65535, int(self.ssh_port_var.get())))
        except (ValueError, tk.TclError):
            ssh_port = 22
        try:
            max_parallel = max(1, int(self.max_parallel_var.get()))
        except (ValueError, tk.TclError):
            max_parallel = 10
        try:
            conn_to = max(1, int(self.connect_timeout_var.get()))
        except (ValueError, tk.TclError):
            conn_to = 10
        try:
            cmd_to = max(1, int(self.command_timeout_var.get()))
        except (ValueError, tk.TclError):
            cmd_to = 15

        self.result = AppSettings(
            language=lang_code,
            theme_mode=theme_mode,
            ssh_username=self.ssh_user_var.get().strip(),
            ssh_port=ssh_port,
            schedule_sequence=self._current.schedule_sequence,
            max_parallel=max_parallel,
            command_timeout=cmd_to,
            connect_timeout=conn_to,
            airwave_url=self._current.airwave_url,
            airwave_username=self._current.airwave_username,
            airwave_verify_ssl=self._current.airwave_verify_ssl,
            airwave_filters=self._current.airwave_filters,
        )
        self.destroy()


class AboutDialog(tk.Toplevel):
    """Information dialog displaying app icon, name, version, and clickable Git repository URL."""

    def __init__(self, parent: tk.Misc, dark_mode: bool = False) -> None:
        super().__init__(parent)
        self.title(_("About {app}").format(app=__app_name__))
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        frame = ttk.Frame(self, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)

        self.repo_url = get_repository_url()
        self._about_icon_img: Optional[tk.PhotoImage] = None
        about_png = get_assets_dir() / "pssh-ui-about.png"
        if about_png.is_file():
            try:
                self._about_icon_img = tk.PhotoImage(file=str(about_png))
                ttk.Label(frame, image=self._about_icon_img).pack(pady=(0, 10))
            except tk.TclError:
                pass

        ttk.Label(frame, text=f"{__app_name__}", font=("Segoe UI", 16, "bold")).pack()
        ttk.Label(
            frame,
            text=f"v{__version__} — {_('Config & Audit Automation')}",
            foreground="#cbd5e1" if dark_mode else "#475569",
        ).pack(pady=(2, 12))

        ttk.Label(frame, text=_("Repository:")).pack()
        self.repo_link_lbl = ttk.Label(
            frame,
            text=self.repo_url,
            foreground="#60a5fa" if dark_mode else "#007fff",
            font=("Segoe UI", 10, "underline"),
            cursor="hand2",
        )
        self.repo_link_lbl.pack(pady=(2, 16))
        self.repo_link_lbl.bind("<Button-1>", lambda _e: webbrowser.open(self.repo_url))

        ttk.Button(frame, text=_("Close"), style="Accent.TButton", command=self.destroy).pack()
        self.update_idletasks()
        self.minsize(max(380, self.winfo_reqwidth() + 24), max(250, self.winfo_reqheight() + 12))


class DeviceModelEditorDialog(tk.Toplevel):
    """Dialog to add or edit a switch DeviceModel (automation prompts & pre/post commands)."""

    def __init__(
        self,
        parent: tk.Misc,
        model: Optional[DeviceModel] = None,
        dark_mode: bool = False,
        device_types: Optional[List[str]] = None,
    ) -> None:
        super().__init__(parent)
        self._existing = model
        self.result: Optional[DeviceModel] = None
        self.title(_("Edit Device Model") if model else _("Add Device Model"))
        self.geometry("760x680")
        self.minsize(680, 580)
        self.transient(parent)
        self.grab_set()

        frame = ttk.Frame(self, padding=14)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(9, weight=1)

        d = model or DeviceModel(name="")
        os_choices = list(device_types or [SwitchOS.AOS_S.value, SwitchOS.AOS_CX.value])
        if d.device_type.value not in os_choices:
            os_choices.append(d.device_type.value)

        self.name_var = tk.StringVar(value=d.name)
        self.os_var = tk.StringVar(value=d.device_type.value)
        self.vendor_var = tk.StringVar(value=d.vendor)
        self.desc_var = tk.StringVar(value=d.description)
        self.enable_cmd_var = tk.StringVar(value=d.enable_command)
        self.nopage_cmd_var = tk.StringVar(value=d.disable_paging_command)
        self.write_cmd_var = tk.StringVar(value=d.write_command)
        self.cli_prompt_var = tk.StringVar(value=d.cli_prompt_regex)
        self.user_prompt_var = tk.StringVar(value=d.username_prompt_regex)
        self.pwd_prompt_var = tk.StringVar(value=d.password_prompt_regex)
        self.en_prompt_var = tk.StringVar(value=d.enable_prompt_regex)
        self.en_pwd_prompt_var = tk.StringVar(value=d.enable_password_prompt_regex)
        self.pager_re_var = tk.StringVar(value=d.pager_prompt_regex)

        top_fields = [
            (_("Model Name *"), ttk.Entry(frame, textvariable=self.name_var)),
            (
                _("Switch OS *"),
                ttk.Combobox(
                    frame,
                    textvariable=self.os_var,
                    values=os_choices,
                ),
            ),
            (_("Vendor"), ttk.Entry(frame, textvariable=self.vendor_var)),
            (_("Description"), ttk.Entry(frame, textvariable=self.desc_var)),
            (_("Enable Command"), ttk.Entry(frame, textvariable=self.enable_cmd_var)),
            (_("Disable Paging Command"), ttk.Entry(frame, textvariable=self.nopage_cmd_var)),
            (_("Write / Save Command"), ttk.Entry(frame, textvariable=self.write_cmd_var)),
        ]
        for r_idx, (lbl, widget) in enumerate(top_fields):
            ttk.Label(frame, text=lbl).grid(row=r_idx, column=0, sticky=tk.W, pady=3, padx=(0, 10))
            widget.grid(row=r_idx, column=1, sticky=tk.EW, pady=3)

        rx_box = ttk.LabelFrame(
            frame, text=_("Automation Prompt Detection RegEx (Credentials, Enable & Paging)"), padding=10
        )
        rx_box.grid(row=7, column=0, columnspan=2, sticky=tk.EW, pady=(8, 8))
        rx_box.columnconfigure(1, weight=1)

        rx_rows = [
            (_("CLI Prompt RegEx"), self.cli_prompt_var),
            (_("Username Prompt RegEx"), self.user_prompt_var),
            (_("Password Prompt RegEx"), self.pwd_prompt_var),
            (_("Enable Prompt RegEx"), self.en_prompt_var),
            (_("Enable Password Prompt RegEx"), self.en_pwd_prompt_var),
            (_("Pager / Banner RegEx"), self.pager_re_var),
        ]
        for r_idx, (lbl, var) in enumerate(rx_rows):
            ttk.Label(rx_box, text=lbl).grid(row=r_idx, column=0, sticky=tk.W, pady=2, padx=(0, 8))
            ttk.Entry(rx_box, textvariable=var, font=("Consolas", 9)).grid(
                row=r_idx, column=1, sticky=tk.EW, pady=2
            )

        cmds_box = ttk.LabelFrame(frame, text=_("Common Task Commands"), padding=10)
        cmds_box.grid(row=9, column=0, columnspan=2, sticky=tk.NSEW, pady=(0, 8))
        cmds_box.columnconfigure(0, weight=1)
        cmds_box.columnconfigure(1, weight=1)
        cmds_box.rowconfigure(1, weight=1)
        cmds_box.rowconfigure(3, weight=1)

        ttk.Label(cmds_box, text=_("Pre-Config Commands (e.g. configure terminal)")).grid(
            row=0, column=0, sticky=tk.W, padx=(0, 8)
        )
        ttk.Label(cmds_box, text=_("Post-Config Commands (e.g. end / write memory)")).grid(
            row=0, column=1, sticky=tk.W
        )

        self.pre_cfg_text = tk.Text(cmds_box, height=3, wrap=tk.NONE, font=("Consolas", 9))
        self.post_cfg_text = tk.Text(cmds_box, height=3, wrap=tk.NONE, font=("Consolas", 9))
        self.pre_cfg_text.insert("1.0", d.pre_config_commands)
        self.post_cfg_text.insert("1.0", d.post_config_commands)
        self.pre_cfg_text.grid(row=1, column=0, sticky=tk.NSEW, padx=(0, 8), pady=(2, 8))
        self.post_cfg_text.grid(row=1, column=1, sticky=tk.NSEW, pady=(2, 8))

        ttk.Label(cmds_box, text=_("Pre-Audit Commands")).grid(
            row=2, column=0, sticky=tk.W, padx=(0, 8)
        )
        ttk.Label(cmds_box, text=_("Post-Audit Commands")).grid(row=2, column=1, sticky=tk.W)

        self.pre_aud_text = tk.Text(cmds_box, height=2, wrap=tk.NONE, font=("Consolas", 9))
        self.post_aud_text = tk.Text(cmds_box, height=2, wrap=tk.NONE, font=("Consolas", 9))
        self.pre_aud_text.insert("1.0", d.pre_audit_commands)
        self.post_aud_text.insert("1.0", d.post_audit_commands)
        self.pre_aud_text.grid(row=3, column=0, sticky=tk.NSEW, padx=(0, 8), pady=(2, 0))
        self.post_aud_text.grid(row=3, column=1, sticky=tk.NSEW, pady=(2, 0))

        for tw in (self.pre_cfg_text, self.post_cfg_text, self.pre_aud_text, self.post_aud_text):
            configure_editor_tags(tw, dark_mode=dark_mode)
            apply_cli_syntax_highlighting(tw)

        btn_bar = ttk.Frame(frame)
        btn_bar.grid(row=10, column=0, columnspan=2, sticky=tk.E)
        ttk.Button(btn_bar, text=_("Cancel"), command=self.destroy).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(btn_bar, text=_("Save"), style="Accent.TButton", command=self._on_save).pack(
            side=tk.RIGHT
        )

    def _on_save(self) -> None:
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning(_("Validation"), _("Model Name is required."), parent=self)
            return
        os_enum = parse_device_type(self.os_var.get(), SwitchOS.AOS_S)
        vendor = self.vendor_var.get().strip() or "Aruba"
        self.result = DeviceModel(
            name=name,
            device_type=os_enum,
            vendor=vendor,
            folder=self._existing.folder if self._existing else vendor.lower(),
            description=self.desc_var.get().strip(),
            cli_prompt_regex=self.cli_prompt_var.get().strip(),
            username_prompt_regex=self.user_prompt_var.get().strip(),
            password_prompt_regex=self.pwd_prompt_var.get().strip(),
            enable_command=self.enable_cmd_var.get().strip(),
            enable_prompt_regex=self.en_prompt_var.get().strip(),
            enable_password_prompt_regex=self.en_pwd_prompt_var.get().strip(),
            pager_prompt_regex=self.pager_re_var.get().strip(),
            pager_dismiss_key=self._existing.pager_dismiss_key if self._existing else " ",
            disable_paging_command=self.nopage_cmd_var.get().strip(),
            pre_config_commands=self.pre_cfg_text.get("1.0", "end-1c").strip("\n"),
            post_config_commands=self.post_cfg_text.get("1.0", "end-1c").strip("\n"),
            write_command=self.write_cmd_var.get().strip(),
            pre_audit_commands=self.pre_aud_text.get("1.0", "end-1c").strip("\n"),
            post_audit_commands=self.post_aud_text.get("1.0", "end-1c").strip("\n"),
            file_path=self._existing.file_path if self._existing else None,
        )
        self.destroy()


class DeviceLogDialog(tk.Toplevel):
    """Modal viewer showing a switch's SSH execution log with highlighted CLI errors."""

    def __init__(
        self,
        parent: tk.Misc,
        result: HostExecutionResult,
        dark_mode: bool = False,
    ) -> None:
        super().__init__(parent)
        self.result = result
        self.title(_("Device Log — {name} ({ip})").format(name=result.host.display_label, ip=result.host.ip))
        self.geometry("820x540")
        self.transient(parent)
        self.grab_set()

        frame = ttk.Frame(self, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)

        content = result.raw_output or ""
        if not content and result.log_path and Path(result.log_path).is_file():
            try:
                content = Path(result.log_path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                content = ""

        errs = result.error_lines or detect_output_errors(content)
        if errs:
            first_err = errs[0]
            summary = first_err.get("reason") or first_err.get("text", "")
            banner_txt = _("⚠ {count} error(s) detected: {summary}").format(
                count=len(errs), summary=summary
            )
            banner_fg = "#f87171" if dark_mode else "#b91c1c"
        else:
            banner_txt = _("Operation Result: {msg}").format(msg=result.operation_result or result.status)
            banner_fg = "#4ade80" if result.status == "Success" and dark_mode else (
                "#15803d" if result.status == "Success" else ("#e2e8f0" if dark_mode else "#0f172a")
            )

        ttk.Label(frame, text=banner_txt, foreground=banner_fg, font=("Segoe UI", 9, "bold")).grid(
            row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 8)
        )

        text_box = tk.Text(
            frame, wrap=tk.NONE, font=("Consolas", 9), bg="#0f172a", fg="#e2e8f0"
        )
        text_box.tag_configure("error_line", background="#7f1d1d", foreground="#fecaca")
        text_box.tag_configure("line_num", foreground="#64748b")

        err_set = {e.get("line_no") for e in errs if e.get("line_no") is not None}
        for line_no, raw_line in enumerate(content.splitlines() or [result.operation_result or ""], start=1):
            line_start = text_box.index("end-1c")
            text_box.insert(tk.END, f"{line_no:4d} | ", "line_num")
            text_box.insert(tk.END, raw_line + "\n")
            line_end = text_box.index("end-1c")
            if line_no in err_set:
                text_box.tag_add("error_line", line_start, line_end)
        text_box.configure(state=tk.DISABLED)

        ysb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=text_box.yview)
        xsb = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=text_box.xview)
        text_box.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        text_box.grid(row=1, column=0, sticky=tk.NSEW)
        ysb.grid(row=1, column=1, sticky=tk.NS)
        xsb.grid(row=2, column=0, sticky=tk.EW)

        footer = ttk.Frame(frame)
        footer.grid(row=3, column=0, columnspan=2, sticky=tk.EW, pady=(8, 0))
        if result.log_path and Path(result.log_path).exists():
            ttk.Button(
                footer,
                text=_("Open External Log"),
                command=lambda: open_path_in_os(result.log_path),
            ).pack(side=tk.LEFT)
        ttk.Button(footer, text=_("Close"), command=self.destroy).pack(side=tk.RIGHT)


class DeviceEditorDialog(tk.Toplevel):
    """Dialog to add or edit a switch device entry with dynamic Model and Group dropdowns."""

    def __init__(
        self,
        parent: tk.Misc,
        existing_hosts: List[HostEntry],
        host: Optional[HostEntry] = None,
        default_port: int = 22,
        device_types: Optional[List[str]] = None,
    ) -> None:
        super().__init__(parent)
        self.existing_hosts = existing_hosts
        self.result: Optional[HostEntry] = None
        self.title(_("Edit Device") if host else _("Add Device"))
        self.geometry("460x320")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        frame = ttk.Frame(self, padding=14)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.columnconfigure(1, weight=1)

        os_choices = list(device_types or [SwitchOS.AOS_S.value, SwitchOS.AOS_CX.value])
        if SwitchOS.UNKNOWN.value not in os_choices:
            os_choices.append(SwitchOS.UNKNOWN.value)

        self.name_var = tk.StringVar(value=host.name if host else "")
        self.ip_var = tk.StringVar(value=host.ip if host else "")
        self.model_var = tk.StringVar(value=host.model if host else "")
        self.os_var = tk.StringVar(
            value=host.os_type.value if host else os_choices[0]
        )
        self.folder_var = tk.StringVar(value=host.folder_path if host else "")
        self.port_var = tk.IntVar(value=host.port if host else default_port)

        assigned_models = get_assigned_models(existing_hosts)
        model_combo = ttk.Combobox(frame, textvariable=self.model_var, values=assigned_models)
        model_combo.bind("<<ComboboxSelected>>", self._on_model_chosen)

        assigned_groups = get_assigned_groups(existing_hosts)
        group_combo = ttk.Combobox(frame, textvariable=self.folder_var, values=assigned_groups)

        rows = [
            (_("Device Name"), ttk.Entry(frame, textvariable=self.name_var)),
            (_("IP Address *"), ttk.Entry(frame, textvariable=self.ip_var)),
            (_("Model"), model_combo),
            (
                _("Switch OS *"),
                ttk.Combobox(
                    frame,
                    textvariable=self.os_var,
                    values=os_choices,
                    state="readonly",
                ),
            ),
            (_("Group"), group_combo),
            (_("SSH Port"), _create_int_spinbox(frame, self.port_var, 1, 65535)),
        ]

        for r_idx, (label, widget) in enumerate(rows):
            ttk.Label(frame, text=label).grid(row=r_idx, column=0, sticky=tk.W, pady=4, padx=(0, 10))
            widget.grid(row=r_idx, column=1, sticky=tk.EW, pady=4)

        btn_bar = ttk.Frame(frame)
        btn_bar.grid(row=len(rows), column=0, columnspan=2, sticky=tk.E, pady=(14, 0))
        ttk.Button(btn_bar, text=_("Cancel"), command=self.destroy).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(btn_bar, text=_("Save"), style="Accent.TButton", command=self._on_save).pack(
            side=tk.RIGHT
        )

        self._existing = host

    def _on_model_chosen(self, _event=None) -> None:
        chosen = self.model_var.get().strip()
        for h in self.existing_hosts:
            if h.model.strip().lower() == chosen.lower() and h.os_type != SwitchOS.UNKNOWN:
                self.os_var.set(h.os_type.value)
                return
        inferred = infer_switch_os(model=chosen)
        if inferred != SwitchOS.UNKNOWN:
            self.os_var.set(inferred.value)

    def _on_save(self) -> None:
        ip = self.ip_var.get().strip()
        if not ip:
            messagebox.showwarning(_("Validation"), _("IP Address is required."), parent=self)
            return
        name = self.name_var.get().strip() or ip
        try:
            port = int(self.port_var.get())
        except (ValueError, tk.TclError):
            port = 22
        os_val = self.os_var.get().strip()
        os_enum = parse_device_type(os_val, SwitchOS.UNKNOWN)

        self.result = HostEntry(
            name=name,
            ip=ip,
            os_type=os_enum,
            model=self.model_var.get().strip(),
            firmware=self._existing.firmware if self._existing else "",
            folder_id=self._existing.folder_id if self._existing else None,
            folder_path=self.folder_var.get().strip(),
            device_category=self._existing.device_category if self._existing else "switch",
            serial_number=self._existing.serial_number if self._existing else "",
            airwave_status=self._existing.airwave_status if self._existing else "Manual",
            device_role=self._existing.device_role if self._existing else "",
            enabled=self._existing.enabled if self._existing else True,
            port=port,
        )
        self.destroy()


class SnippetEditorDialog(tk.Toplevel):
    """Add / Edit XML Snippet dialog (hides directory path; routes by OS)."""

    def __init__(
        self,
        parent: tk.Misc,
        snippet: Optional[Snippet] = None,
        dark_mode: bool = False,
        device_types: Optional[List[str]] = None,
    ) -> None:
        super().__init__(parent)
        self.result: Optional[Snippet] = None
        self._existing = snippet
        self.title(_("Edit Snippet") if snippet else _("Add Snippet"))
        self.geometry("780x640")
        self.transient(parent)
        self.grab_set()

        container = ttk.Frame(self, padding=14)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(1, weight=1)
        container.rowconfigure(5, weight=2)
        container.rowconfigure(6, weight=1)

        os_choices = list(device_types or [SwitchOS.AOS_S.value, SwitchOS.AOS_CX.value])
        default_type = snippet.snippet_type.value if snippet else SnippetType.CONFIG.value
        default_os = snippet.device_type.value if snippet else os_choices[0]
        if default_os not in os_choices:
            os_choices.append(default_os)
        default_sev = snippet.severity.value if snippet else SnippetSeverity.INFO.value

        self.type_var = tk.StringVar(value=default_type)
        self.name_var = tk.StringVar(value=snippet.name if snippet else "")
        self.severity_var = tk.StringVar(value=default_sev)
        self.device_type_var = tk.StringVar(value=default_os)

        ttk.Label(container, text=_("Snippet Type *")).grid(row=0, column=0, sticky=tk.W, pady=4)
        type_frame = ttk.Frame(container)
        type_frame.grid(row=0, column=1, sticky=tk.W, pady=4)
        for st in SnippetType:
            ttk.Radiobutton(
                type_frame,
                text=st.value,
                variable=self.type_var,
                value=st.value,
                command=self._on_type_changed,
            ).pack(side=tk.LEFT, padx=(0, 14))

        ttk.Label(container, text=_("Name *")).grid(row=1, column=0, sticky=tk.W, pady=4)
        ttk.Entry(container, textvariable=self.name_var).grid(row=1, column=1, sticky=tk.EW, pady=4)

        ttk.Label(container, text=_("Device Type (OS) *")).grid(
            row=2, column=0, sticky=tk.W, pady=4
        )
        ttk.Combobox(
            container,
            textvariable=self.device_type_var,
            values=os_choices,
            width=26,
        ).grid(row=2, column=1, sticky=tk.W, pady=4)

        ttk.Label(container, text=_("Severity")).grid(row=3, column=0, sticky=tk.W, pady=4)
        ttk.Combobox(
            container,
            textvariable=self.severity_var,
            values=[s.value for s in SnippetSeverity],
            state="readonly",
            width=20,
        ).grid(row=3, column=1, sticky=tk.W, pady=4)

        ttk.Label(container, text=_("Description")).grid(row=4, column=0, sticky=tk.NW, pady=4)
        self.desc_text = tk.Text(container, height=3, wrap=tk.WORD)
        self.desc_text.grid(row=4, column=1, sticky=tk.EW, pady=4)
        if snippet and snippet.description:
            self.desc_text.insert("1.0", snippet.description)

        ttk.Label(
            container,
            text=_('Commands *\n(! comments,\n${var|type|regex},\n${var|["A", "B"]})'),
        ).grid(row=5, column=0, sticky=tk.NW, pady=4)
        cmd_wrap = ttk.Frame(container)
        cmd_wrap.grid(row=5, column=1, sticky=tk.NSEW, pady=4)
        cmd_wrap.rowconfigure(0, weight=1)
        cmd_wrap.columnconfigure(0, weight=1)

        self.cmd_text = tk.Text(cmd_wrap, wrap=tk.NONE, font=("Consolas", 10), undo=True)
        configure_editor_tags(self.cmd_text, dark_mode=dark_mode)
        y_sb = ttk.Scrollbar(cmd_wrap, orient=tk.VERTICAL, command=self.cmd_text.yview)
        x_sb = ttk.Scrollbar(cmd_wrap, orient=tk.HORIZONTAL, command=self.cmd_text.xview)
        self.cmd_text.configure(yscrollcommand=y_sb.set, xscrollcommand=x_sb.set)
        self.cmd_text.grid(row=0, column=0, sticky=tk.NSEW)
        y_sb.grid(row=0, column=1, sticky=tk.NS)
        x_sb.grid(row=1, column=0, sticky=tk.EW)

        if snippet and snippet.commands:
            self.cmd_text.insert("1.0", snippet.commands)
        apply_cli_syntax_highlighting(self.cmd_text)
        self.cmd_text.bind("<KeyRelease>", self._on_cmd_changed)

        self.audit_regex_lbl = ttk.Label(
            container,
            text=_("Audit Validation RegEx\n(1 pattern per line)"),
        )
        self.audit_regex_lbl.grid(row=6, column=0, sticky=tk.NW, pady=4)
        self.audit_regex_wrap = ttk.Frame(container)
        self.audit_regex_wrap.grid(row=6, column=1, sticky=tk.NSEW, pady=4)
        self.audit_regex_wrap.rowconfigure(0, weight=1)
        self.audit_regex_wrap.columnconfigure(0, weight=1)

        self.audit_regex_text = tk.Text(
            self.audit_regex_wrap, height=4, wrap=tk.NONE, font=("Consolas", 10), undo=True
        )
        configure_editor_tags(self.audit_regex_text, dark_mode=dark_mode)
        ar_ysb = ttk.Scrollbar(
            self.audit_regex_wrap, orient=tk.VERTICAL, command=self.audit_regex_text.yview
        )
        ar_xsb = ttk.Scrollbar(
            self.audit_regex_wrap, orient=tk.HORIZONTAL, command=self.audit_regex_text.xview
        )
        self.audit_regex_text.configure(yscrollcommand=ar_ysb.set, xscrollcommand=ar_xsb.set)
        self.audit_regex_text.grid(row=0, column=0, sticky=tk.NSEW)
        ar_ysb.grid(row=0, column=1, sticky=tk.NS)
        ar_xsb.grid(row=1, column=0, sticky=tk.EW)

        if snippet and snippet.audit_regex:
            self.audit_regex_text.insert("1.0", snippet.audit_regex)
        apply_cli_syntax_highlighting(self.audit_regex_text)
        self.audit_regex_text.bind("<KeyRelease>", self._on_audit_changed)

        self.var_preview_lbl = ttk.Label(container, text="", foreground="#007fff")
        self.var_preview_lbl.grid(row=7, column=1, sticky=tk.W, pady=(2, 6))
        self._on_type_changed()
        self._update_var_preview()

        btn_bar = ttk.Frame(container)
        btn_bar.grid(row=8, column=0, columnspan=2, sticky=tk.E, pady=(8, 0))
        ttk.Button(btn_bar, text=_("Cancel"), command=self.destroy).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(
            btn_bar, text=_("Save Snippet"), style="Accent.TButton", command=self._on_save
        ).pack(side=tk.RIGHT)

    def _on_type_changed(self) -> None:
        is_audit = self.type_var.get() == SnippetType.AUDIT.value
        if is_audit:
            self.audit_regex_lbl.grid()
            self.audit_regex_wrap.grid()
        else:
            self.audit_regex_lbl.grid_remove()
            self.audit_regex_wrap.grid_remove()
        self._update_var_preview()

    def _on_cmd_changed(self, _event=None) -> None:
        apply_cli_syntax_highlighting(self.cmd_text)
        self._update_var_preview()

    def _on_audit_changed(self, _event=None) -> None:
        apply_cli_syntax_highlighting(self.audit_regex_text)
        self._update_var_preview()

    def _update_var_preview(self) -> None:
        text = self.cmd_text.get("1.0", "end-1c")
        if self.type_var.get() == SnippetType.AUDIT.value:
            text = f"{text}\n{self.audit_regex_text.get('1.0', 'end-1c')}"
        specs = extract_variables(text)
        if not specs:
            self.var_preview_lbl.configure(text=_("Detected template variables: none"))
        else:
            desc = ", ".join(f"{s.name} ({s.field_type})" for s in specs)
            self.var_preview_lbl.configure(
                text=_("Detected template variables: {vars}").format(vars=desc)
            )

    def _on_save(self) -> None:
        name = self.name_var.get().strip()
        commands = self.cmd_text.get("1.0", "end-1c").strip("\n")
        if not name:
            messagebox.showwarning(_("Validation"), _("Snippet Name is required."), parent=self)
            return
        if not commands.strip():
            messagebox.showwarning(_("Validation"), _("Commands cannot be empty."), parent=self)
            return

        os_enum = parse_device_type(self.device_type_var.get(), SwitchOS.AOS_S)
        type_enum = next(
            (t for t in SnippetType if t.value == self.type_var.get()), SnippetType.CONFIG
        )
        sev_enum = next(
            (s for s in SnippetSeverity if s.value == self.severity_var.get()),
            SnippetSeverity.INFO,
        )
        audit_rx = (
            self.audit_regex_text.get("1.0", "end-1c").strip("\n")
            if type_enum == SnippetType.AUDIT
            else ""
        )
        folder = self._existing.folder if self._existing else SnippetStore.default_folder_for_os(os_enum)
        self.result = Snippet(
            name=name,
            folder=folder,
            snippet_type=type_enum,
            device_type=os_enum,
            severity=sev_enum,
            description=self.desc_text.get("1.0", "end-1c").strip(),
            commands=commands,
            audit_regex=audit_rx,
            created_at=self._existing.created_at if self._existing else "",
            file_path=self._existing.file_path if self._existing else None,
        )
        self.destroy()


class AirWaveImportDialog(tk.Toplevel):
    """Modal dialog to import and filter switch devices from AirWave."""

    def __init__(self, parent: tk.Misc, settings: AppSettings) -> None:
        super().__init__(parent)
        self.title(_("Import from AirWave"))
        self.geometry("960x620")
        self.transient(parent)
        self.grab_set()

        self.settings = settings
        self.imported_hosts: Optional[List[HostEntry]] = None
        self.folders_cache: Dict[str, Dict[str, Any]] = {}
        self.raw_ap_xml: str = ""
        self.preview_hosts: List[HostEntry] = []
        self._fetch_queue: queue.Queue = queue.Queue()

        self.url_var = tk.StringVar(value=settings.airwave_url)
        self.user_var = tk.StringVar(value=settings.airwave_username)
        self.pass_var = tk.StringVar(value="")
        self.verify_ssl_var = tk.BooleanVar(value=settings.airwave_verify_ssl)

        flt = settings.airwave_filters
        self.folder_var = tk.StringVar(value=flt.folder or _("All"))
        self.category_var = tk.StringVar(value=flt.category or "switch")
        self.model_var = tk.StringVar(value=flt.model)
        self.os_var = tk.StringVar(value=flt.os_filter or "All")
        self.status_var = tk.StringVar(value=flt.status_filter or "All")
        self.search_var = tk.StringVar(value=flt.search_query)
        self.state_lbl_var = tk.StringVar(
            value=_("Enter AirWave credentials and click Fetch Inventory.")
        )

        self._build_ui()
        self.after(100, self._poll_fetch_queue)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)
        outer.rowconfigure(2, weight=1)
        outer.columnconfigure(0, weight=1)

        conn_box = ttk.LabelFrame(outer, text=_("AirWave Connection"), padding=10)
        conn_box.grid(row=0, column=0, sticky=tk.EW, pady=(0, 8))
        conn_box.columnconfigure(1, weight=2)
        conn_box.columnconfigure(3, weight=1)
        conn_box.columnconfigure(5, weight=1)

        ttk.Label(conn_box, text=_("AirWave Name / IP:")).grid(row=0, column=0, sticky=tk.W, padx=4)
        ttk.Entry(conn_box, textvariable=self.url_var).grid(row=0, column=1, sticky=tk.EW, padx=4)
        ttk.Label(conn_box, text=_("Username:")).grid(row=0, column=2, sticky=tk.W, padx=4)
        ttk.Entry(conn_box, textvariable=self.user_var).grid(row=0, column=3, sticky=tk.EW, padx=4)
        ttk.Label(conn_box, text=_("Password:")).grid(row=0, column=4, sticky=tk.W, padx=4)
        ttk.Entry(conn_box, textvariable=self.pass_var, show="*").grid(
            row=0, column=5, sticky=tk.EW, padx=4
        )
        ttk.Checkbutton(conn_box, text=_("Verify SSL"), variable=self.verify_ssl_var).grid(
            row=0, column=6, padx=6
        )
        self.fetch_btn = ttk.Button(
            conn_box, text=_("Fetch Inventory"), style="Accent.TButton", command=self._start_fetch
        )
        self.fetch_btn.grid(row=0, column=7, padx=4)

        flt_box = ttk.LabelFrame(outer, text=_("Device Filters"), padding=10)
        flt_box.grid(row=1, column=0, sticky=tk.EW, pady=(0, 8))
        for c in (1, 3, 5):
            flt_box.columnconfigure(c, weight=1)

        ttk.Label(flt_box, text=_("Folder:")).grid(row=0, column=0, sticky=tk.W, padx=4, pady=3)
        self.folder_combo = ttk.Combobox(
            flt_box, textvariable=self.folder_var, values=[_("All")], state="readonly"
        )
        self.folder_combo.grid(row=0, column=1, sticky=tk.EW, padx=4, pady=3)

        ttk.Label(flt_box, text=_("Category:")).grid(row=0, column=2, sticky=tk.W, padx=4, pady=3)
        ttk.Entry(flt_box, textvariable=self.category_var).grid(
            row=0, column=3, sticky=tk.EW, padx=4, pady=3
        )

        ttk.Label(flt_box, text=_("Model:")).grid(row=0, column=4, sticky=tk.W, padx=4, pady=3)
        ttk.Entry(flt_box, textvariable=self.model_var).grid(
            row=0, column=5, sticky=tk.EW, padx=4, pady=3
        )

        ttk.Label(flt_box, text=_("OS Type:")).grid(row=1, column=0, sticky=tk.W, padx=4, pady=3)
        ttk.Combobox(
            flt_box,
            textvariable=self.os_var,
            values=["All", SwitchOS.AOS_S.value, SwitchOS.AOS_CX.value],
            state="readonly",
        ).grid(row=1, column=1, sticky=tk.EW, padx=4, pady=3)

        ttk.Label(flt_box, text=_("Status:")).grid(row=1, column=2, sticky=tk.W, padx=4, pady=3)
        ttk.Combobox(
            flt_box,
            textvariable=self.status_var,
            values=["All", "Up", "Down"],
            state="readonly",
        ).grid(row=1, column=3, sticky=tk.EW, padx=4, pady=3)

        ttk.Label(flt_box, text=_("Search (Name/IP):")).grid(
            row=1, column=4, sticky=tk.W, padx=4, pady=3
        )
        ttk.Entry(flt_box, textvariable=self.search_var).grid(
            row=1, column=5, sticky=tk.EW, padx=4, pady=3
        )

        opt_row = ttk.Frame(flt_box)
        opt_row.grid(row=2, column=0, columnspan=6, sticky=tk.EW, pady=(4, 0))
        ttk.Button(opt_row, text=_("Apply Filters"), command=self._apply_filters).pack(
            side=tk.RIGHT
        )

        table_box = ttk.Frame(outer)
        table_box.grid(row=2, column=0, sticky=tk.NSEW)
        table_box.rowconfigure(0, weight=1)
        table_box.columnconfigure(0, weight=1)

        cols = ("name", "status", "ip", "os", "model", "role", "folder", "firmware")
        self.tree = ttk.Treeview(table_box, columns=cols, show="headings", selectmode="extended")
        headings = {
            "name": _("Device"),
            "status": _("Status"),
            "ip": _("IP Address"),
            "os": _("OS Type"),
            "model": _("Model"),
            "role": _("Device Role"),
            "folder": _("Folder"),
            "firmware": _("Firmware"),
        }
        widths = {
            "name": 160,
            "status": 65,
            "ip": 115,
            "os": 75,
            "model": 150,
            "role": 85,
            "folder": 160,
            "firmware": 115,
        }
        for col in cols:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor=tk.W)

        y_sb = ttk.Scrollbar(table_box, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=y_sb.set)
        self.tree.grid(row=0, column=0, sticky=tk.NSEW)
        y_sb.grid(row=0, column=1, sticky=tk.NS)

        footer = ttk.Frame(outer)
        footer.grid(row=3, column=0, sticky=tk.EW, pady=(8, 0))
        ttk.Label(footer, textvariable=self.state_lbl_var).pack(side=tk.LEFT)
        ttk.Button(footer, text=_("Cancel"), command=self.destroy).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(
            footer,
            text=_("Import All Filtered"),
            style="Accent.TButton",
            command=lambda: self._accept(selected_only=False),
        ).pack(side=tk.RIGHT, padx=4)
        ttk.Button(
            footer, text=_("Import Highlighted"), command=lambda: self._accept(selected_only=True)
        ).pack(side=tk.RIGHT, padx=4)

    def _build_filter(self) -> AirWaveFilter:
        chosen_folder = self.folder_var.get().strip()
        if chosen_folder in ("", "All", _("All")):
            chosen_folder = ""
        return AirWaveFilter(
            folder=chosen_folder,
            category=self.category_var.get().strip(),
            model=self.model_var.get().strip(),
            os_filter=self.os_var.get().strip() or "All",
            status_filter=self.status_var.get().strip() or "All",
            search_query=self.search_var.get().strip(),
            include_stacked=False,
        )

    def _start_fetch(self) -> None:
        url = self.url_var.get().strip()
        user = self.user_var.get().strip()
        pwd = self.pass_var.get()
        if not url or not user or not pwd:
            messagebox.showwarning(
                _("Validation"),
                _("AirWave Name / IP, Username, and Password are required."),
                parent=self,
            )
            return

        self.fetch_btn.configure(state=tk.DISABLED)
        self.state_lbl_var.set(_("Connecting to AirWave and fetching inventory..."))

        def _worker() -> None:
            try:
                folders, ap_xml = fetch_airwave_inventory(
                    url=url,
                    username=user,
                    password=pwd,
                    verify_ssl=bool(self.verify_ssl_var.get()),
                )
                self._fetch_queue.put(("ok", (folders, ap_xml)))
            except Exception as exc:
                self._fetch_queue.put(("err", str(exc)))

        threading.Thread(target=_worker, daemon=True).start()

    def _poll_fetch_queue(self) -> None:
        if not self.winfo_exists():
            return
        try:
            while True:
                kind, payload = self._fetch_queue.get_nowait()
                self.fetch_btn.configure(state=tk.NORMAL)
                if kind == "ok":
                    self.folders_cache, self.raw_ap_xml = payload
                    folder_names = sorted(
                        {
                            str(fdata.get("name", "")).strip()
                            for fdata in self.folders_cache.values()
                            if str(fdata.get("name", "")).strip()
                        },
                        key=str.lower,
                    )
                    self.folder_combo.configure(values=[_("All")] + folder_names)
                    if self.folder_var.get() not in [_("All")] + folder_names:
                        self.folder_var.set(_("All"))
                    self._apply_filters()
                else:
                    self.state_lbl_var.set(_("Error: {msg}").format(msg=payload))
                    messagebox.showerror(_("Import Error"), str(payload), parent=self)
        except queue.Empty:
            pass
        self.after(100, self._poll_fetch_queue)

    def _apply_filters(self) -> None:
        if not self.raw_ap_xml:
            return
        flt = self._build_filter()
        hosts, total = parse_airwave_devices(
            self.raw_ap_xml,
            folders=self.folders_cache,
            filters=flt,
        )
        self.preview_hosts = hosts

        for item in self.tree.get_children():
            self.tree.delete(item)
        for idx, h in enumerate(hosts):
            self.tree.insert(
                "",
                tk.END,
                iid=str(idx),
                values=(
                    h.name,
                    h.airwave_status,
                    h.ip,
                    h.os_type.value,
                    h.model,
                    h.device_role,
                    h.folder_path,
                    h.firmware,
                ),
            )
        self.state_lbl_var.set(
            _("Matched {matched} switches out of {total} total records.").format(
                matched=len(hosts), total=total
            )
        )

    def _accept(self, selected_only: bool) -> None:
        if not self.preview_hosts:
            messagebox.showinfo(_("Import"), _("No devices available to import."), parent=self)
            return
        if selected_only:
            sel = self.tree.selection()
            if not sel:
                messagebox.showwarning(
                    _("Import"), _("Select at least one row or click Import All Filtered."), parent=self
                )
                return
            chosen = [self.preview_hosts[int(iid)] for iid in sel]
        else:
            chosen = list(self.preview_hosts)

        self.settings.airwave_url = self.url_var.get().strip()
        self.settings.airwave_username = self.user_var.get().strip()
        self.settings.airwave_verify_ssl = bool(self.verify_ssl_var.get())
        self.settings.airwave_filters = self._build_filter()
        self.imported_hosts = chosen
        self.destroy()


class AddJobDialog(tk.Toplevel):
    """4-Step Wizard: Config Command -> Parameters -> Select Device -> Confirm (No Schedule)."""

    def __init__(
        self,
        parent: tk.Misc,
        session: SessionData,
        snippets: List[Snippet],
        settings: Optional[AppSettings] = None,
        ssh_password: str = "",
        dark_mode: bool = False,
        device_models: Optional[List[DeviceModel]] = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self.settings = settings or AppSettings()
        self.snippets = snippets
        self.device_models = device_models if device_models is not None else ModelStore().load_all_models()
        self.dark_mode = dark_mode
        self.launch_payload: Optional[Dict[str, Any]] = None
        self.current_step: int = 0

        self.title(_("Add Job"))
        self.geometry("980x710")
        self.minsize(820, 600)
        self.transient(parent)
        self.grab_set()

        os_choices = discover_device_types(self.device_models, self.snippets, session.hosts)
        # Step 1 state: Job Name starts EMPTY; Snippet starts BLANK; Config Commands editable
        self.job_type_var = tk.StringVar(value=SnippetType.CONFIG.value)
        self.job_name_var = tk.StringVar(value="")
        self.device_os_var = tk.StringVar(value=os_choices[0])
        self.model_choice_var = tk.StringVar(value="")
        self.snippet_choice_var = tk.StringVar(value="")
        self._os_choices = os_choices

        # Step 2 state
        self._initial_saved_params: Dict[str, str] = dict(session.variable_values)
        self.param_values: Dict[str, str] = {}
        self.param_entry_vars: Dict[str, tk.StringVar] = {}
        self.param_status_labels: Dict[str, ttk.Label] = {}

        # Step 3 column filter variables
        self.col_flt_device = tk.StringVar()
        self.col_flt_status = tk.StringVar(value="All")
        self.col_flt_ip = tk.StringVar()
        self.col_flt_os = tk.StringVar(value="All")
        self.col_flt_type = tk.StringVar(value="All")
        self.col_flt_role = tk.StringVar()
        self.col_flt_group = tk.StringVar()
        self.col_flt_fw = tk.StringVar()

        self.filtered_hosts: List[HostEntry] = []
        self.selected_host_keys: set[str] = {h.unique_key for h in session.hosts if h.enabled}

        # Step 4 credentials & parallelism
        self.ssh_user_var = tk.StringVar(value=self.settings.ssh_username)
        self.ssh_pass_var = tk.StringVar(value=ssh_password)
        self.enable_pass_var = tk.StringVar(value="")
        self.save_write_var = tk.BooleanVar(value=False)
        self.ssh_port_var = tk.IntVar(value=self.settings.ssh_port)
        self.max_parallel_var = tk.IntVar(value=self.settings.max_parallel)
        self.sequential_var = tk.BooleanVar(
            value=(self.settings.schedule_sequence == ScheduleSequence.SEQUENTIAL)
        )

        self._snippet_map: Dict[str, Snippet] = {}
        self._build_ui()
        self._populate_snippets_for_os()
        self._go_to_step(0)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=16)
        outer.pack(fill=tk.BOTH, expand=True)
        outer.rowconfigure(1, weight=1)
        outer.columnconfigure(0, weight=1)

        # Top Stepper Bar (circular step numbers, clickable ONLY for previous steps, no underline)
        stepper = ttk.Frame(outer)
        stepper.grid(row=0, column=0, sticky=tk.EW, pady=(0, 12))
        self.step_titles = [
            _("Config Command"),
            _("Parameters"),
            _("Select Device"),
            _("Confirm"),
        ]
        canvas_bg = "#1c1c1c" if self.dark_mode else "#fafafa"
        self.step_labels: List[ttk.Label] = []
        self.step_circles: List[tuple[tk.Canvas, int, int]] = []
        for idx, text in enumerate(self.step_titles):
            step_item = ttk.Frame(stepper)
            step_item.pack(side=tk.LEFT, padx=(0, 22))
            circ = tk.Canvas(
                step_item, width=26, height=26, highlightthickness=0, bd=0, bg=canvas_bg
            )
            oval_id = circ.create_oval(2, 2, 24, 24, width=1.6, outline="#94a3b8")
            num_id = circ.create_text(
                13, 13, text=str(idx + 1), font=("Segoe UI", 9, "bold"), fill="#94a3b8"
            )
            circ.pack(side=tk.LEFT, padx=(0, 6))
            lbl = ttk.Label(step_item, text=text, font=("Segoe UI", 10))
            lbl.pack(side=tk.LEFT)
            circ.bind("<Button-1>", lambda _event, step_idx=idx: self._on_step_label_click(step_idx))
            lbl.bind("<Button-1>", lambda _event, step_idx=idx: self._on_step_label_click(step_idx))
            self.step_circles.append((circ, oval_id, num_id))
            self.step_labels.append(lbl)

        # Stage Container
        self.stage = ttk.Frame(outer)
        self.stage.grid(row=1, column=0, sticky=tk.NSEW)
        self.stage.rowconfigure(0, weight=1)
        self.stage.columnconfigure(0, weight=1)

        self.step_frames = [ttk.Frame(self.stage) for _step in range(4)]
        for sf in self.step_frames:
            sf.grid(row=0, column=0, sticky=tk.NSEW)

        self._build_step1_config_command(self.step_frames[0])
        self._build_step2_parameters(self.step_frames[1])
        self._build_step3_select_device(self.step_frames[2])
        self._build_step4_confirm(self.step_frames[3])

        # Bottom Navigation Bar
        nav = ttk.Frame(outer)
        nav.grid(row=2, column=0, sticky=tk.EW, pady=(12, 0))
        ttk.Button(nav, text=_("Cancel"), command=self.destroy).pack(side=tk.LEFT)

        self.next_btn = ttk.Button(
            nav, text=_("Next >"), style="Accent.TButton", command=self._on_next
        )
        self.next_btn.pack(side=tk.RIGHT)

        self.run_btn = ttk.Button(
            nav, text=_("Run Job"), style="Accent.TButton", command=self._on_run
        )

        self.back_btn = ttk.Button(nav, text=_("< Back"), command=self._on_back)
        self.back_btn.pack(side=tk.RIGHT, padx=(0, 8))

    # ---- Step 1: Config Command (Empty Job Name, Blank Snippet Default, Editable Commands + Audit RegEx) ----
    def _build_step1_config_command(self, parent: ttk.Frame) -> None:
        card = ttk.Frame(parent, style="Card.TFrame", padding=16)
        card.pack(fill=tk.BOTH, expand=True)
        card.columnconfigure(0, weight=1)
        card.rowconfigure(12, weight=2)
        card.rowconfigure(14, weight=1)

        ttk.Label(card, text=_("Job Type *"), font=("Segoe UI", 9, "bold")).grid(
            row=0, column=0, sticky=tk.W, pady=(0, 4)
        )
        jt_frame = ttk.Frame(card)
        jt_frame.grid(row=1, column=0, sticky=tk.W, pady=(0, 10))
        for st in SnippetType:
            ttk.Radiobutton(
                jt_frame,
                text=st.value,
                variable=self.job_type_var,
                value=st.value,
                command=self._toggle_audit_regex_field,
            ).pack(side=tk.LEFT, padx=(0, 18))

        ttk.Label(card, text=_("Job Name *"), font=("Segoe UI", 9, "bold")).grid(
            row=2, column=0, sticky=tk.W, pady=(0, 4)
        )
        ttk.Entry(card, textvariable=self.job_name_var).grid(row=3, column=0, sticky=tk.EW, pady=(0, 10))

        ttk.Label(card, text=_("Job Description"), font=("Segoe UI", 9, "bold")).grid(
            row=4, column=0, sticky=tk.W, pady=(0, 4)
        )
        self.job_desc_text = tk.Text(card, height=2, wrap=tk.WORD)
        self.job_desc_text.grid(row=5, column=0, sticky=tk.EW, pady=(0, 10))

        ttk.Label(card, text=_("Device Type *"), font=("Segoe UI", 9, "bold")).grid(
            row=6, column=0, sticky=tk.W, pady=(0, 4)
        )
        dt_row = ttk.Frame(card)
        dt_row.grid(row=7, column=0, sticky=tk.EW, pady=(0, 10))
        dt_row.columnconfigure(1, weight=1)
        dt_row.columnconfigure(3, weight=1)

        self.job_os_combo = ttk.Combobox(
            dt_row,
            textvariable=self.device_os_var,
            values=self._os_choices,
            state="readonly",
            width=24,
        )
        self.job_os_combo.grid(row=0, column=0, sticky=tk.W, padx=(0, 16))
        self.job_os_combo.bind("<<ComboboxSelected>>", lambda _e: self._populate_snippets_for_os())

        ttk.Label(dt_row, text=_("Device Model:")).grid(row=0, column=2, sticky=tk.E, padx=(16, 6))
        self.job_model_combo = ttk.Combobox(
            dt_row, textvariable=self.model_choice_var, state="readonly", width=28
        )
        self.job_model_combo.grid(row=0, column=3, sticky=tk.W)

        ttk.Label(card, text=_("Snippets *"), font=("Segoe UI", 9, "bold")).grid(
            row=8, column=0, sticky=tk.W, pady=(0, 4)
        )
        self.snippet_combo = ttk.Combobox(
            card, textvariable=self.snippet_choice_var, state="readonly"
        )
        self.snippet_combo.grid(row=9, column=0, sticky=tk.EW, pady=(0, 4))
        self.snippet_combo.bind("<<ComboboxSelected>>", self._on_snippet_chosen)

        self.snippet_desc_lbl = ttk.Label(card, text="", foreground="#64748b", wraplength=820)
        self.snippet_desc_lbl.grid(row=10, column=0, sticky=tk.W, pady=(0, 8))

        ttk.Label(card, text=_("Config Commands *"), font=("Segoe UI", 9, "bold")).grid(
            row=11, column=0, sticky=tk.W, pady=(0, 4)
        )
        cmd_wrap = ttk.Frame(card)
        cmd_wrap.grid(row=12, column=0, sticky=tk.NSEW, pady=(0, 8))
        cmd_wrap.rowconfigure(0, weight=1)
        cmd_wrap.columnconfigure(0, weight=1)

        self.cmd_text = tk.Text(cmd_wrap, wrap=tk.NONE, font=("Consolas", 10), undo=True, height=7)
        configure_editor_tags(self.cmd_text, dark_mode=self.dark_mode)
        c_ysb = ttk.Scrollbar(cmd_wrap, orient=tk.VERTICAL, command=self.cmd_text.yview)
        c_xsb = ttk.Scrollbar(cmd_wrap, orient=tk.HORIZONTAL, command=self.cmd_text.xview)
        self.cmd_text.configure(yscrollcommand=c_ysb.set, xscrollcommand=c_xsb.set)
        self.cmd_text.grid(row=0, column=0, sticky=tk.NSEW)
        c_ysb.grid(row=0, column=1, sticky=tk.NS)
        c_xsb.grid(row=1, column=0, sticky=tk.EW)
        self.cmd_text.bind("<KeyRelease>", lambda _e: apply_cli_syntax_highlighting(self.cmd_text))

        self.audit_regex_lbl = ttk.Label(
            card, text=_("Audit Validation RegEx (1 pattern per line)"), font=("Segoe UI", 9, "bold")
        )
        self.audit_regex_lbl.grid(row=13, column=0, sticky=tk.W, pady=(0, 4))
        self.audit_regex_wrap = ttk.Frame(card)
        self.audit_regex_wrap.grid(row=14, column=0, sticky=tk.NSEW)
        self.audit_regex_wrap.rowconfigure(0, weight=1)
        self.audit_regex_wrap.columnconfigure(0, weight=1)

        self.audit_regex_text = tk.Text(
            self.audit_regex_wrap, wrap=tk.NONE, font=("Consolas", 10), undo=True, height=4
        )
        configure_editor_tags(self.audit_regex_text, dark_mode=self.dark_mode)
        ar_ysb = ttk.Scrollbar(
            self.audit_regex_wrap, orient=tk.VERTICAL, command=self.audit_regex_text.yview
        )
        ar_xsb = ttk.Scrollbar(
            self.audit_regex_wrap, orient=tk.HORIZONTAL, command=self.audit_regex_text.xview
        )
        self.audit_regex_text.configure(yscrollcommand=ar_ysb.set, xscrollcommand=ar_xsb.set)
        self.audit_regex_text.grid(row=0, column=0, sticky=tk.NSEW)
        ar_ysb.grid(row=0, column=1, sticky=tk.NS)
        ar_xsb.grid(row=1, column=0, sticky=tk.EW)
        self.audit_regex_text.bind(
            "<KeyRelease>", lambda _e: apply_cli_syntax_highlighting(self.audit_regex_text)
        )
        self._toggle_audit_regex_field()

    def _toggle_audit_regex_field(self) -> None:
        if self.job_type_var.get() == SnippetType.AUDIT.value:
            self.audit_regex_lbl.grid()
            self.audit_regex_wrap.grid()
        else:
            self.audit_regex_lbl.grid_remove()
            self.audit_regex_wrap.grid_remove()

    def _populate_snippets_for_os(self) -> None:
        target_os = self.device_os_var.get()

        # Populate matching Device Models for this Device Type
        matching_models = [m.name for m in self.device_models if m.device_type.value == target_os]
        self.job_model_combo.configure(values=matching_models)
        if matching_models:
            if self.model_choice_var.get() not in matching_models:
                self.model_choice_var.set(matching_models[0])
        else:
            self.model_choice_var.set("")

        matching = [s for s in self.snippets if s.device_type.value == target_os]
        self._snippet_map = {s.name: s for s in matching}
        names = [s.name for s in matching]
        self.snippet_combo.configure(values=names)

        # Default to blank selection so the operator explicitly selects a Snippet
        self.snippet_choice_var.set("")
        self.cmd_text.delete("1.0", tk.END)
        self.audit_regex_text.delete("1.0", tk.END)
        if names:
            self.snippet_desc_lbl.configure(text="")
        else:
            self.snippet_desc_lbl.configure(
                text=_("No snippets available for {os}.").format(os=target_os)
            )

    def _get_active_model(self) -> Optional[DeviceModel]:
        return ModelStore.get_model_for_os(
            self._target_os_enum(), self.device_models, self.model_choice_var.get()
        )

    def _on_snippet_chosen(self, _event=None) -> None:
        snip = self._get_selected_snippet()
        if not snip:
            return
        self.job_type_var.set(snip.snippet_type.value)
        self.snippet_desc_lbl.configure(text=snip.description or "")
        self.cmd_text.delete("1.0", tk.END)
        self.cmd_text.insert("1.0", snip.commands or "")
        apply_cli_syntax_highlighting(self.cmd_text)
        self.audit_regex_text.delete("1.0", tk.END)
        if snip.audit_regex:
            self.audit_regex_text.insert("1.0", snip.audit_regex)
            apply_cli_syntax_highlighting(self.audit_regex_text)
        self._toggle_audit_regex_field()

    def _get_selected_snippet(self) -> Optional[Snippet]:
        return self._snippet_map.get(self.snippet_choice_var.get())

    def _get_raw_commands(self) -> str:
        return self.cmd_text.get("1.0", "end-1c")

    def _get_raw_audit_regex(self) -> str:
        if self.job_type_var.get() != SnippetType.AUDIT.value:
            return ""
        return self.audit_regex_text.get("1.0", "end-1c").strip("\n")

    def _get_all_template_text(self) -> str:
        raw_cmds = self._get_raw_commands()
        raw_audit = self._get_raw_audit_regex()
        return f"{raw_cmds}\n{raw_audit}" if raw_audit else raw_cmds

    # ---- Step 2: Parameters (HTML field types + Python lists + ✓/✗ icons) ----
    def _build_step2_parameters(self, parent: ttk.Frame) -> None:
        card = ttk.Frame(parent, style="Card.TFrame", padding=16)
        card.pack(fill=tk.BOTH, expand=True)
        card.rowconfigure(1, weight=1)
        card.columnconfigure(0, weight=1)

        ttk.Label(
            card,
            text=_("Fill in the snippet variables below."),
            foreground="#64748b",
        ).grid(row=0, column=0, sticky=tk.W, pady=(0, 10))

        self.param_canvas = tk.Canvas(card, highlightthickness=0)
        p_sb = ttk.Scrollbar(card, orient=tk.VERTICAL, command=self.param_canvas.yview)
        self.param_inner = ttk.Frame(self.param_canvas)
        self.param_inner.columnconfigure(1, weight=1)
        self.param_canvas_win = self.param_canvas.create_window(
            (0, 0), window=self.param_inner, anchor=tk.NW
        )
        self.param_canvas.configure(yscrollcommand=p_sb.set)
        self.param_canvas.grid(row=1, column=0, sticky=tk.NSEW)
        p_sb.grid(row=1, column=1, sticky=tk.NS)

        self.param_inner.bind(
            "<Configure>",
            lambda _e: self.param_canvas.configure(scrollregion=self.param_canvas.bbox("all")),
        )
        self.param_canvas.bind(
            "<Configure>",
            lambda e: self.param_canvas.itemconfigure(self.param_canvas_win, width=e.width),
        )

    def _rebuild_parameters_form(self) -> None:
        for child in self.param_inner.winfo_children():
            child.destroy()
        self.param_entry_vars.clear()
        self.param_status_labels.clear()

        specs = extract_variables(self._get_all_template_text())
        if not specs:
            ttk.Label(
                self.param_inner,
                text=_("No variables required by this snippet. Click Next to select devices."),
            ).grid(row=0, column=0, sticky=tk.W, padx=6, pady=12)
            return

        ttk.Label(self.param_inner, text=_("Variable"), font=("Segoe UI", 9, "bold")).grid(
            row=0, column=0, sticky=tk.W, padx=6, pady=4
        )
        ttk.Label(self.param_inner, text=_("Value"), font=("Segoe UI", 9, "bold")).grid(
            row=0, column=1, sticky=tk.W, padx=6, pady=4
        )
        ttk.Label(self.param_inner, text=_("Status"), font=("Segoe UI", 9, "bold")).grid(
            row=0, column=2, sticky=tk.W, padx=6, pady=4
        )

        for r_idx, spec in enumerate(specs, start=1):
            ttk.Label(
                self.param_inner,
                text=f"{spec.name} *",
                font=("Segoe UI", 9, "bold"),
            ).grid(row=r_idx, column=0, sticky=tk.W, padx=6, pady=6)

            if spec.name in self.param_values:
                initial_val = self.param_values[spec.name]
            elif not spec.is_secret:
                initial_val = self._initial_saved_params.get(spec.name, "")
            else:
                initial_val = ""
            sv = tk.StringVar(value=initial_val)
            self.param_entry_vars[spec.name] = sv

            entry_wrap = ttk.Frame(self.param_inner)
            entry_wrap.grid(row=r_idx, column=1, sticky=tk.EW, padx=6, pady=6)
            entry_wrap.columnconfigure(0, weight=1)

            if spec.field_type == "select":
                widget = ttk.Combobox(
                    entry_wrap,
                    textvariable=sv,
                    values=spec.options,
                    state="readonly",
                )
                widget.grid(row=0, column=0, sticky=tk.EW)
            else:
                entry = ttk.Entry(entry_wrap, textvariable=sv, show="*" if spec.is_secret else "")
                entry.grid(row=0, column=0, sticky=tk.EW)

                if spec.is_secret:
                    show_v = tk.BooleanVar(value=False)
                    ttk.Checkbutton(
                        entry_wrap,
                        text=_("Show"),
                        variable=show_v,
                        command=lambda e=entry, s=show_v: e.configure(show="" if s.get() else "*"),
                    ).grid(row=0, column=1, padx=(6, 0))

            status_lbl = ttk.Label(self.param_inner, text="", font=("Segoe UI", 11, "bold"))
            status_lbl.grid(row=r_idx, column=2, sticky=tk.W, padx=10, pady=6)
            self.param_status_labels[spec.name] = status_lbl

            sv.trace_add(
                "write",
                lambda *_a, sp=spec, var=sv: self._on_param_changed(sp, var),
            )
            self._update_param_badge(spec, sv.get())

    def _on_param_changed(self, spec, sv: tk.StringVar) -> None:
        val = sv.get()
        self.param_values[spec.name] = val
        self._update_param_badge(spec, val)

    def _update_param_badge(self, spec, val: str) -> None:
        lbl = self.param_status_labels.get(spec.name)
        if not lbl:
            return
        err = validate_single_value(spec, val)
        if err is None:
            lbl.configure(text="✓", foreground="#15803d")
        else:
            lbl.configure(text="✗", foreground="#b91c1c")

    # ---- Step 3: Select Device (All devices + column filters) ----
    def _build_step3_select_device(self, parent: ttk.Frame) -> None:
        card = ttk.Frame(parent, style="Card.TFrame", padding=12)
        card.pack(fill=tk.BOTH, expand=True)
        card.rowconfigure(2, weight=1)
        card.columnconfigure(0, weight=1)

        bar = ttk.Frame(card)
        bar.grid(row=0, column=0, columnspan=2, sticky=tk.EW, pady=(0, 8))
        ttk.Button(bar, text=_("Select All"), command=lambda: self._set_all_filtered(True)).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(
            bar, text=_("Deselect All"), command=lambda: self._set_all_filtered(False)
        ).pack(side=tk.LEFT, padx=(0, 10))
        self.os_hint_lbl = ttk.Label(bar, text="", foreground="#007fff")
        self.os_hint_lbl.pack(side=tk.LEFT)
        ttk.Button(bar, text=_("Clear Filters"), command=self._clear_column_filters).pack(
            side=tk.RIGHT
        )

        flt_grid = ttk.Frame(card)
        flt_grid.grid(row=1, column=0, columnspan=2, sticky=tk.EW, pady=(0, 4))
        for c in range(8):
            flt_grid.columnconfigure(c, weight=1)

        assigned_models = ["All"] + get_assigned_models(self.session.hosts)

        filter_defs = [
            (_("Device"), ttk.Entry(flt_grid, textvariable=self.col_flt_device, width=14), True),
            (
                _("Status"),
                ttk.Combobox(
                    flt_grid,
                    textvariable=self.col_flt_status,
                    values=["All", "Up", "Down", "Manual"],
                    state="readonly",
                    width=9,
                ),
                False,
            ),
            (_("IP Address"), ttk.Entry(flt_grid, textvariable=self.col_flt_ip, width=14), True),
            (
                _("OS"),
                ttk.Combobox(
                    flt_grid,
                    textvariable=self.col_flt_os,
                    values=["All", *self._os_choices],
                    state="readonly",
                    width=9,
                ),
                False,
            ),
            (
                _("Model"),
                ttk.Combobox(
                    flt_grid,
                    textvariable=self.col_flt_type,
                    values=assigned_models,
                    state="readonly",
                    width=14,
                ),
                False,
            ),
            (_("Device Role"), ttk.Entry(flt_grid, textvariable=self.col_flt_role, width=12), True),
            (_("Group"), ttk.Entry(flt_grid, textvariable=self.col_flt_group, width=14), True),
            (_("Firmware"), ttk.Entry(flt_grid, textvariable=self.col_flt_fw, width=12), True),
        ]

        for col_idx, (col_lbl, widget, is_entry) in enumerate(filter_defs):
            cell = ttk.Frame(flt_grid)
            cell.grid(row=0, column=col_idx, sticky=tk.EW, padx=(0, 4))
            cell.columnconfigure(0, weight=1)
            ttk.Label(cell, text=col_lbl, font=("Segoe UI", 8, "bold")).grid(
                row=0, column=0, sticky=tk.W
            )
            widget.grid(row=1, column=0, sticky=tk.EW)
            if is_entry:
                widget.bind("<KeyRelease>", lambda _e: self._refresh_devices_table())
            else:
                widget.bind("<<ComboboxSelected>>", lambda _e: self._refresh_devices_table())

        cols = ("sel", "device", "status", "ip", "os", "type", "role", "group", "firmware")
        self.device_tree = ttk.Treeview(
            card, columns=cols, show="headings", selectmode="browse"
        )
        headings = {
            "sel": "☑",
            "device": _("Device"),
            "status": _("Status"),
            "ip": _("IP Address"),
            "os": _("OS"),
            "type": _("Model"),
            "role": _("Device Role"),
            "group": _("Group"),
            "firmware": _("Firmware"),
        }
        widths = {
            "sel": 40,
            "device": 150,
            "status": 65,
            "ip": 115,
            "os": 75,
            "type": 140,
            "role": 85,
            "group": 145,
            "firmware": 115,
        }
        for col in cols:
            self.device_tree.heading(col, text=headings[col])
            self.device_tree.column(
                col, width=widths[col], anchor=tk.CENTER if col == "sel" else tk.W
            )

        self.device_tree.tag_configure("disabled_os", foreground="#94a3b8")

        d_sb = ttk.Scrollbar(card, orient=tk.VERTICAL, command=self.device_tree.yview)
        self.device_tree.configure(yscrollcommand=d_sb.set)
        self.device_tree.grid(row=2, column=0, sticky=tk.NSEW)
        d_sb.grid(row=2, column=1, sticky=tk.NS)
        self.device_tree.bind("<Button-1>", self._on_device_tree_click)

        total_fg = "#ffffff" if self.dark_mode else "#000000"
        self.dev_count_lbl = ttk.Label(card, text="", foreground=total_fg)
        self.dev_count_lbl.grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=(6, 0))

    def _clear_column_filters(self) -> None:
        self.col_flt_device.set("")
        self.col_flt_status.set("All")
        self.col_flt_ip.set("")
        self.col_flt_os.set("All")
        self.col_flt_type.set("All")
        self.col_flt_role.set("")
        self.col_flt_group.set("")
        self.col_flt_fw.set("")
        self._refresh_devices_table()

    def _target_os_enum(self):
        return parse_device_type(self.device_os_var.get(), SwitchOS.AOS_S)

    def _refresh_devices_table(self) -> None:
        target_os = self._target_os_enum()
        self.os_hint_lbl.configure(
            text=_("Snippet Target OS: {os}").format(os=target_os.value)
        )

        f_dev = self.col_flt_device.get().strip().lower()
        f_st = self.col_flt_status.get()
        f_ip = self.col_flt_ip.get().strip().lower()
        f_os = self.col_flt_os.get()
        f_tp = self.col_flt_type.get()
        f_rl = self.col_flt_role.get().strip().lower()
        f_gp = self.col_flt_group.get().strip().lower()
        f_fw = self.col_flt_fw.get().strip().lower()

        self.filtered_hosts = []
        for h in self.session.hosts:
            if f_dev and f_dev not in h.name.lower():
                continue
            if f_st != "All" and h.airwave_status != f_st:
                continue
            if f_ip and f_ip not in h.ip.lower():
                continue
            if f_os != "All" and h.os_type.value != f_os:
                continue
            if f_tp != "All" and h.model != f_tp:
                continue
            if f_rl and f_rl not in h.device_role.lower():
                continue
            if f_gp and f_gp not in h.folder_path.lower():
                continue
            if f_fw and f_fw not in h.firmware.lower():
                continue
            self.filtered_hosts.append(h)

        for item in self.device_tree.get_children():
            self.device_tree.delete(item)

        eligible_selected = 0
        for h in self.filtered_hosts:
            matches_os = h.os_type == target_os
            if matches_os and h.unique_key in self.selected_host_keys:
                mark = "☑"
                eligible_selected += 1
            elif matches_os:
                mark = "☐"
            else:
                mark = "—"

            self.device_tree.insert(
                "",
                tk.END,
                iid=h.unique_key,
                tags=() if matches_os else ("disabled_os",),
                values=(
                    mark,
                    h.name,
                    h.airwave_status,
                    h.ip,
                    h.os_type.value,
                    h.model,
                    h.device_role,
                    h.folder_path,
                    h.firmware,
                ),
            )

        total_chosen = sum(
            1
            for h in self.session.hosts
            if h.os_type == target_os and h.unique_key in self.selected_host_keys
        )
        self.dev_count_lbl.configure(
            text=_("Total Records: {shown}   |   Selected ({os}): {chosen}").format(
                shown=len(self.filtered_hosts),
                os=target_os.value,
                chosen=total_chosen,
            )
        )

    def _on_device_tree_click(self, event: tk.Event) -> None:
        region = self.device_tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        row_id = self.device_tree.identify_row(event.y)
        if not row_id:
            return
        host = next((h for h in self.filtered_hosts if h.unique_key == row_id), None)
        if not host or host.os_type != self._target_os_enum():
            return
        if row_id in self.selected_host_keys:
            self.selected_host_keys.remove(row_id)
        else:
            self.selected_host_keys.add(row_id)
        self._refresh_devices_table()

    def _set_all_filtered(self, select: bool) -> None:
        target_os = self._target_os_enum()
        for h in self.filtered_hosts:
            if h.os_type != target_os:
                continue
            if select:
                self.selected_host_keys.add(h.unique_key)
            else:
                self.selected_host_keys.discard(h.unique_key)
        self._refresh_devices_table()

    # ---- Step 4: Confirm (Read-only resulting commands + SSH Credentials & Parallelism) ----
    def _build_step4_confirm(self, parent: ttk.Frame) -> None:
        card = ttk.Frame(parent, style="Card.TFrame", padding=16)
        card.pack(fill=tk.BOTH, expand=True)
        card.rowconfigure(3, weight=1)
        card.columnconfigure(0, weight=1)

        self.confirm_summary_lbl = ttk.Label(card, text="", font=("Segoe UI", 10, "bold"))
        self.confirm_summary_lbl.grid(row=0, column=0, sticky=tk.W, pady=(0, 8))

        cred_box = ttk.LabelFrame(card, text=_("SSH Credentials & Execution Settings"), padding=10)
        cred_box.grid(row=1, column=0, sticky=tk.EW, pady=(0, 10))
        cred_box.columnconfigure(1, weight=1)
        cred_box.columnconfigure(3, weight=1)

        ttk.Label(cred_box, text=_("SSH Username *")).grid(row=0, column=0, sticky=tk.W, padx=(0, 6))
        ttk.Entry(cred_box, textvariable=self.ssh_user_var).grid(
            row=0, column=1, sticky=tk.EW, padx=(0, 14)
        )
        ttk.Label(cred_box, text=_("SSH Password *")).grid(row=0, column=2, sticky=tk.W, padx=(0, 6))
        ttk.Entry(cred_box, textvariable=self.ssh_pass_var, show="*").grid(
            row=0, column=3, sticky=tk.EW
        )

        ttk.Label(cred_box, text=_("SSH Port")).grid(
            row=1, column=0, sticky=tk.W, padx=(0, 6), pady=(8, 0)
        )
        _create_int_spinbox(cred_box, self.ssh_port_var, 1, 65535, width=10).grid(
            row=1, column=1, sticky=tk.W, pady=(8, 0)
        )
        ttk.Label(cred_box, text=_("Max Parallel Executions")).grid(
            row=1, column=2, sticky=tk.W, padx=(0, 6), pady=(8, 0)
        )
        par_wrap = ttk.Frame(cred_box)
        par_wrap.grid(row=1, column=3, sticky=tk.W, pady=(8, 0))
        self.parallel_spin = _create_int_spinbox(
            par_wrap, self.max_parallel_var, 1, 64, width=8
        )
        self.parallel_spin.pack(side=tk.LEFT, padx=(0, 10))
        ttk.Checkbutton(
            par_wrap,
            text=_("Sequential (1 switch at a time)"),
            variable=self.sequential_var,
            command=self._on_seq_toggled,
        ).pack(side=tk.LEFT)
        self._on_seq_toggled()

        ttk.Label(cred_box, text=_("Enable Password")).grid(
            row=2, column=0, sticky=tk.W, padx=(0, 6), pady=(8, 0)
        )
        ttk.Entry(cred_box, textvariable=self.enable_pass_var, show="*").grid(
            row=2, column=1, sticky=tk.EW, padx=(0, 14), pady=(8, 0)
        )
        self.write_cmd_check = ttk.Checkbutton(
            cred_box,
            text=_("Save configuration"),
            variable=self.save_write_var,
            command=self._refresh_confirm_view,
        )
        self.write_cmd_check.grid(row=2, column=2, columnspan=2, sticky=tk.W, pady=(8, 0))

        ttk.Label(card, text=_("Resulting Commands (Read-Only)"), font=("Segoe UI", 9, "bold")).grid(
            row=2, column=0, sticky=tk.W, pady=(0, 4)
        )
        cmd_wrap = ttk.Frame(card)
        cmd_wrap.grid(row=3, column=0, sticky=tk.NSEW)
        cmd_wrap.rowconfigure(0, weight=1)
        cmd_wrap.columnconfigure(0, weight=1)

        self.confirm_cmds_text = tk.Text(
            cmd_wrap, wrap=tk.NONE, font=("Consolas", 10), state=tk.DISABLED
        )
        configure_editor_tags(self.confirm_cmds_text, dark_mode=self.dark_mode)
        ysb = ttk.Scrollbar(cmd_wrap, orient=tk.VERTICAL, command=self.confirm_cmds_text.yview)
        xsb = ttk.Scrollbar(cmd_wrap, orient=tk.HORIZONTAL, command=self.confirm_cmds_text.xview)
        self.confirm_cmds_text.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        self.confirm_cmds_text.grid(row=0, column=0, sticky=tk.NSEW)
        ysb.grid(row=0, column=1, sticky=tk.NS)
        xsb.grid(row=1, column=0, sticky=tk.EW)

    def _on_seq_toggled(self) -> None:
        self.parallel_spin.configure(
            state=tk.DISABLED if self.sequential_var.get() else tk.NORMAL
        )

    def _refresh_confirm_view(self) -> None:
        snip = self._get_selected_snippet()
        target_os = self._target_os_enum()
        active_model = self._get_active_model()
        job_type = next(
            (t for t in SnippetType if t.value == self.job_type_var.get()),
            SnippetType.CONFIG,
        )
        selected_hosts = [
            h
            for h in self.session.hosts
            if h.os_type == target_os and h.unique_key in self.selected_host_keys
        ]
        can_write = bool(
            job_type == SnippetType.CONFIG
            and active_model
            and active_model.write_command.strip()
        )
        if can_write and active_model:
            self.write_cmd_check.configure(
                text=_("Run write command ({cmd})").format(cmd=active_model.write_command.strip())
            )
            self.write_cmd_check.grid()
        else:
            self.save_write_var.set(False)
            self.write_cmd_check.grid_remove()

        rendered = render_template(self._get_raw_commands(), self.param_values)
        exec_cmds = wrap_commands_with_model(
            parse_commands(rendered),
            job_type=job_type,
            device_model=active_model,
            include_write_command=bool(can_write and self.save_write_var.get()),
        )

        model_disp = f"   |   {_('Device Model')}: {active_model.name}" if active_model else ""
        self.confirm_summary_lbl.configure(
            text=f"{_('Job Name')}: {self.job_name_var.get().strip()}   |   "
            f"{_('Snippet')}: {snip.name if snip else '-'}   |   "
            f"{_('Device Type')}: {target_os.value}{model_disp}   |   "
            f"{_('Selected Devices')}: {len(selected_hosts)}"
        )

        self.confirm_cmds_text.configure(state=tk.NORMAL)
        self.confirm_cmds_text.delete("1.0", tk.END)
        self.confirm_cmds_text.insert(
            "1.0", "\n".join(exec_cmds) if exec_cmds else _("(No commands)")
        )
        apply_cli_syntax_highlighting(self.confirm_cmds_text)
        self.confirm_cmds_text.configure(state=tk.DISABLED)

    # ---- Stepper Transitions ----
    def _on_step_label_click(self, idx: int) -> None:
        # Allow clicking ONLY on previous steps to go back; disallow advancing
        if idx < self.current_step:
            self._go_to_step(idx)

    def _go_to_step(self, idx: int) -> None:
        self.current_step = max(0, min(3, idx))
        self.step_frames[self.current_step].tkraise()

        active_color = "#d97706"
        done_color = "#15803d"
        idle_color = "#94a3b8"
        idle_text = "#cbd5e1" if self.dark_mode else "#64748b"

        for i, lbl in enumerate(self.step_labels):
            circ, oval_id, num_id = self.step_circles[i]
            if i == self.current_step:
                circ.itemconfigure(oval_id, outline=active_color, fill="")
                circ.itemconfigure(num_id, fill=active_color)
                circ.configure(cursor="")
                lbl.configure(font=("Segoe UI", 10, "bold"), foreground=active_color, cursor="")
            elif i < self.current_step:
                circ.itemconfigure(oval_id, outline=done_color, fill="")
                circ.itemconfigure(num_id, fill=done_color)
                circ.configure(cursor="hand2")
                lbl.configure(font=("Segoe UI", 10), foreground=done_color, cursor="hand2")
            else:
                circ.itemconfigure(oval_id, outline=idle_color, fill="")
                circ.itemconfigure(num_id, fill=idle_color)
                circ.configure(cursor="")
                lbl.configure(font=("Segoe UI", 10), foreground=idle_text, cursor="")

        self.back_btn.configure(state=tk.NORMAL if self.current_step > 0 else tk.DISABLED)
        if self.current_step == 3:
            self.next_btn.pack_forget()
            self.run_btn.pack(side=tk.RIGHT)
        else:
            self.run_btn.pack_forget()
            self.next_btn.pack(side=tk.RIGHT)

        if self.current_step == 1:
            self._rebuild_parameters_form()
        elif self.current_step == 2:
            self._refresh_devices_table()
        elif self.current_step == 3:
            self._refresh_confirm_view()

    def _on_back(self) -> None:
        self._go_to_step(self.current_step - 1)

    def _on_next(self) -> None:
        raw_commands = self._get_raw_commands()
        if self.current_step == 0:
            if not self._get_selected_snippet():
                messagebox.showwarning(
                    _("Validation"), _("Please select a Snippet."), parent=self
                )
                return
            if not self.job_name_var.get().strip():
                messagebox.showwarning(
                    _("Validation"), _("Job Name is required."), parent=self
                )
                return
            if not parse_commands(raw_commands):
                messagebox.showwarning(
                    _("Validation"), _("Commands cannot be empty."), parent=self
                )
                return
        elif self.current_step == 1:
            specs = extract_variables(self._get_all_template_text())
            vals = {k: sv.get() for k, sv in self.param_entry_vars.items()}
            errs = validate_variable_values(specs, vals)
            if errs:
                messagebox.showwarning(
                    _("Validation"),
                    "\n• ".join([_("Please correct the parameter values:")] + list(errs.values())),
                    parent=self,
                )
                return
        elif self.current_step == 2:
            target_os = self._target_os_enum()
            chosen = [
                h
                for h in self.session.hosts
                if h.os_type == target_os and h.unique_key in self.selected_host_keys
            ]
            if not chosen:
                messagebox.showwarning(
                    _("Validation"),
                    _("Select at least one target switch matching this snippet OS."),
                    parent=self,
                )
                return

        self._go_to_step(self.current_step + 1)

    def _on_run(self) -> None:
        snip = self._get_selected_snippet()
        raw_commands = self._get_raw_commands()
        raw_audit_regex = self._get_raw_audit_regex()
        if not raw_commands.strip():
            return
        target_os = self._target_os_enum()
        selected_hosts = [
            h
            for h in self.session.hosts
            if h.os_type == target_os and h.unique_key in self.selected_host_keys
        ]
        ssh_user = self.ssh_user_var.get().strip()
        ssh_pwd = self.ssh_pass_var.get()

        errors = validate_job_inputs(
            raw_commands=self._get_all_template_text(),
            selected_hosts=selected_hosts,
            values=self.param_values,
            ssh_username=ssh_user,
            ssh_password=ssh_pwd,
        )
        if errors:
            messagebox.showwarning(
                _("Validation"),
                "\n• ".join([_("Please resolve the following before running:")] + errors),
                parent=self,
            )
            return

        try:
            ssh_port = int(self.ssh_port_var.get())
        except (ValueError, tk.TclError):
            ssh_port = 22
        try:
            max_parallel = max(1, int(self.max_parallel_var.get()))
        except (ValueError, tk.TclError):
            max_parallel = 10

        job_type = next(
            (t for t in SnippetType if t.value == self.job_type_var.get()),
            SnippetType.CONFIG,
        )
        seq = (
            ScheduleSequence.SEQUENTIAL
            if self.sequential_var.get()
            else ScheduleSequence.CONCURRENT
        )

        self.settings.ssh_username = ssh_user
        self.settings.ssh_port = ssh_port
        self.settings.max_parallel = max_parallel
        self.settings.schedule_sequence = seq

        specs = extract_variables(self._get_all_template_text())
        secret_names = {sp.name for sp in specs if sp.is_secret}
        for k, v in self.param_values.items():
            if k not in secret_names:
                self.session.variable_values[k] = v

        targets = [
            HostEntry(
                name=h.name,
                ip=h.ip,
                os_type=h.os_type,
                model=h.model,
                firmware=h.firmware,
                folder_id=h.folder_id,
                folder_path=h.folder_path,
                device_category=h.device_category,
                serial_number=h.serial_number,
                airwave_status=h.airwave_status,
                device_role=h.device_role,
                enabled=True,
                port=h.port or ssh_port,
            )
            for h in selected_hosts
        ]

        active_model = self._get_active_model()
        self.launch_payload = {
            "job_name": self.job_name_var.get().strip(),
            "description": self.job_desc_text.get("1.0", "end-1c").strip(),
            "job_type": job_type,
            "device_type": target_os,
            "snippet_name": snip.name if snip else "",
            "model_name": active_model.name if active_model else "",
            "commands_raw": raw_commands,
            "audit_regex": raw_audit_regex,
            "values": dict(self.param_values),
            "secret_names": secret_names,
            "hosts": targets,
            "ssh_username": ssh_user,
            "ssh_password": ssh_pwd,
            "enable_password": self.enable_pass_var.get(),
            "include_write": bool(self.save_write_var.get()),
            "max_parallel": max_parallel,
            "schedule_sequence": seq,
        }
        self.destroy()


class PsshApp:
    """Main application window using Sun-Valley ttk theme with Jobs, Snippets, Devices, and Device Models tabs."""

    def __init__(
        self,
        root: tk.Tk,
        snippet_store: Optional[SnippetStore] = None,
        model_store: Optional[ModelStore] = None,
        session_path: Optional[Path | str] = None,
        settings_path: Optional[Path | str] = None,
        os_theme_override: Optional[str] = None,
        os_lang_override: Optional[str] = None,
    ) -> None:
        self.root = root
        self.snippet_store = snippet_store or SnippetStore()
        self.snippet_store.ensure_default_folders()
        self.model_store = model_store or ModelStore()
        self.session_path = Path(session_path) if session_path else DEFAULT_SESSION_PATH
        self.settings_path = Path(settings_path) if settings_path else DEFAULT_SETTINGS_PATH
        self._os_theme_override = os_theme_override
        self._os_lang_override = os_lang_override

        self.settings = self._load_initial_settings()
        self.session = self._load_initial_session()
        self._apply_effective_preferences()

        self.ssh_password: str = ""
        self.snippets: List[Snippet] = []
        self.device_models: List[DeviceModel] = []
        self.selected_job_id: Optional[str] = (
            self.session.jobs[0].job_id if self.session.jobs else None
        )
        self.active_tab_index: int = 0
        self.running_jobs: Dict[str, threading.Event] = {}
        self.ui_queue: queue.Queue = queue.Queue()
        self._app_icon_img: Optional[tk.PhotoImage] = None
        self._header_logo_img: Optional[tk.PhotoImage] = None

        self._apply_window_icon()
        apply_sun_valley_theme(self.root, self.theme_mode)
        self._reload_snippets_data()
        self._reload_models_data()
        self._build_layout()
        self._refresh_all_views()
        self.root.after(100, self._poll_ui_queue)

    def _apply_window_icon(self) -> None:
        assets = get_assets_dir()
        ico_path = assets / "pssh-ui.ico"
        png_path = assets / "pssh-ui.png"
        if ico_path.is_file() and sys.platform.startswith("win"):
            try:
                self.root.iconbitmap(default=str(ico_path))
            except tk.TclError:
                pass
        if png_path.is_file():
            try:
                self._app_icon_img = tk.PhotoImage(file=str(png_path))
                self.root.iconphoto(True, self._app_icon_img)
            except tk.TclError:
                pass

    def _discovered_os_values(self) -> List[str]:
        return discover_device_types(self.device_models, self.snippets, self.session.hosts)

    def _load_initial_settings(self) -> AppSettings:
        if self.settings_path.is_file():
            try:
                return load_settings_xml(self.settings_path)
            except Exception:
                pass
        if self.session_path.is_file():
            migrated = migrate_legacy_settings_from_session(self.session_path)
            if migrated is not None:
                try:
                    save_settings_xml(migrated, self.settings_path)
                except Exception:
                    pass
                return migrated
        return AppSettings()

    def _load_initial_session(self) -> SessionData:
        if self.session_path.is_file():
            try:
                return load_session_xml(self.session_path)
            except Exception:
                pass
        return SessionData()

    def _apply_effective_preferences(self) -> None:
        mode = (self.settings.theme_mode or "auto").lower()
        if mode in ("light", "dark"):
            self.theme_mode = mode
        else:
            self.theme_mode = self._os_theme_override or detect_os_theme()

        langs = available_languages()
        saved_lang = self.settings.language or "auto"
        if saved_lang != "auto" and saved_lang in langs:
            effective_lang = saved_lang
        else:
            effective_lang = self._os_lang_override or detect_os_language(langs)
        set_language(effective_lang)

    def _auto_save_settings(self) -> None:
        try:
            save_settings_xml(self.settings, self.settings_path)
        except Exception:
            pass

    def _auto_save_session(self) -> None:
        try:
            save_session_xml(self.session, self.session_path)
        except Exception:
            pass

    def _is_dark(self) -> bool:
        return self.theme_mode == "dark"

    def _total_fg(self) -> str:
        """Return crisp black (light theme) or white (dark theme) for table record totals."""
        return "#ffffff" if self._is_dark() else "#000000"

    def _build_layout(self) -> None:
        self.root.title(f"{__app_name__} v{__version__} — {_('Config & Audit Automation')}")
        self.root.geometry("1220x820")
        self.root.minsize(960, 640)

        for child in self.root.winfo_children():
            child.destroy()

        # Header Bar with app logo, title, Config & Audit Automation subtitle, Info button, and Cog button
        header = ttk.Frame(self.root, padding=(14, 10))
        header.pack(fill=tk.X)

        title_col = ttk.Frame(header)
        title_col.pack(side=tk.LEFT)
        header_png = get_assets_dir() / "pssh-ui-header.png"
        if header_png.is_file():
            try:
                self._header_logo_img = tk.PhotoImage(file=str(header_png))
                self.header_logo_lbl = ttk.Label(title_col, image=self._header_logo_img)
                self.header_logo_lbl.pack(side=tk.LEFT, padx=(0, 8))
            except tk.TclError:
                self.header_logo_lbl = None
        else:
            self.header_logo_lbl = None

        ttk.Label(title_col, text=f"{__app_name__}", font=("Segoe UI", 14, "bold")).pack(
            side=tk.LEFT
        )
        self.header_subtitle_lbl = ttk.Label(
            title_col,
            text="  |  " + _("Config & Audit Automation"),
            foreground="#cbd5e1" if self._is_dark() else "#64748b",
        )
        self.header_subtitle_lbl.pack(side=tk.LEFT, pady=(2, 0))

        right_ctrl = ttk.Frame(header)
        right_ctrl.pack(side=tk.RIGHT)

        self.settings_btn = ttk.Button(
            right_ctrl,
            text="⚙",
            width=3,
            command=self._open_settings_dialog,
        )
        self.settings_btn.pack(side=tk.LEFT, padx=(0, 6))

        self.about_btn = ttk.Button(
            right_ctrl,
            text="ⓘ",
            width=3,
            command=self._open_about_dialog,
        )
        self.about_btn.pack(side=tk.LEFT)

        # Primary 4 Tabs: Jobs (default), Snippets, Devices, Device Models
        self.main_notebook = ttk.Notebook(self.root)
        self.main_notebook.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))

        self.tab_jobs = ttk.Frame(self.main_notebook, padding=10)
        self.tab_snippets = ttk.Frame(self.main_notebook, padding=10)
        self.tab_devices = ttk.Frame(self.main_notebook, padding=10)
        self.tab_models = ttk.Frame(self.main_notebook, padding=10)

        self.main_notebook.add(self.tab_jobs, text=_("Jobs"))
        self.main_notebook.add(self.tab_snippets, text=_("Snippets"))
        self.main_notebook.add(self.tab_devices, text=_("Devices"))
        self.main_notebook.add(self.tab_models, text=_("Device Models"))

        self._build_jobs_tab()
        self._build_snippets_tab()
        self._build_devices_tab()
        self._build_models_tab()

        if 0 <= self.active_tab_index < 4:
            self.main_notebook.select(self.active_tab_index)
        self.main_notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

    def _on_tab_changed(self, _event=None) -> None:
        try:
            self.active_tab_index = self.main_notebook.index(self.main_notebook.select())
        except tk.TclError:
            pass

    def _open_about_dialog(self) -> None:
        dlg = AboutDialog(self.root, dark_mode=self._is_dark())
        self.root.wait_window(dlg)

    def _open_settings_dialog(self) -> None:
        dlg = SettingsDialog(self.root, self.settings)
        self.root.wait_window(dlg)
        if not dlg.result:
            return
        self.settings = dlg.result
        self._apply_effective_preferences()
        apply_sun_valley_theme(self.root, self.theme_mode)
        self._build_layout()
        self._refresh_all_views()
        self._auto_save_settings()

    # ------------------------------------------------------------------
    # Tab 1: Jobs + Job Details (Details | Devices)
    # ------------------------------------------------------------------
    def _build_jobs_tab(self) -> None:
        self.tab_jobs.rowconfigure(0, weight=1)
        self.tab_jobs.columnconfigure(0, weight=1)

        v_pane = ttk.PanedWindow(self.tab_jobs, orient=tk.VERTICAL)
        v_pane.grid(row=0, column=0, sticky=tk.NSEW)

        # Top Card: Jobs List (Action icons per row; header has only + Add Job)
        jobs_card = ttk.Frame(v_pane, style="Card.TFrame", padding=12)
        jobs_card.rowconfigure(2, weight=1)
        jobs_card.columnconfigure(0, weight=1)
        v_pane.add(jobs_card, weight=2)

        hdr = ttk.Frame(jobs_card)
        hdr.grid(row=0, column=0, columnspan=2, sticky=tk.EW, pady=(0, 8))
        ttk.Label(hdr, text=_("Jobs"), font=("Segoe UI", 12, "bold")).pack(side=tk.LEFT)
        ttk.Button(
            hdr,
            text="+ " + _("Add Job"),
            style="Accent.TButton",
            command=self._open_add_job_dialog,
        ).pack(side=tk.RIGHT)

        flt_row = ttk.Frame(jobs_card)
        flt_row.grid(row=1, column=0, columnspan=2, sticky=tk.EW, pady=(0, 6))
        flt_row.columnconfigure(1, weight=1)

        self.job_flt_name = tk.StringVar()
        self.job_flt_type = tk.StringVar(value="All")
        self.job_flt_os = tk.StringVar(value="All")
        self.job_flt_status = tk.StringVar(value="All")

        ttk.Label(flt_row, text=_("Name:")).grid(row=0, column=0, padx=(0, 4))
        e_jname = ttk.Entry(flt_row, textvariable=self.job_flt_name, width=20)
        e_jname.grid(row=0, column=1, sticky=tk.EW, padx=(0, 10))
        e_jname.bind("<KeyRelease>", lambda _e: self._refresh_jobs_tree())

        ttk.Label(flt_row, text=_("Job Type:")).grid(row=0, column=2, padx=(0, 4))
        cb_jtype = ttk.Combobox(
            flt_row,
            textvariable=self.job_flt_type,
            values=["All", SnippetType.CONFIG.value, SnippetType.AUDIT.value],
            state="readonly",
            width=18,
        )
        cb_jtype.grid(row=0, column=3, padx=(0, 10))
        cb_jtype.bind("<<ComboboxSelected>>", lambda _e: self._refresh_jobs_tree())

        ttk.Label(flt_row, text=_("Device Type:")).grid(row=0, column=4, padx=(0, 4))
        cb_jos = ttk.Combobox(
            flt_row,
            textvariable=self.job_flt_os,
            values=["All", *self._discovered_os_values()],
            state="readonly",
            width=12,
        )
        cb_jos.grid(row=0, column=5, padx=(0, 10))
        cb_jos.bind("<<ComboboxSelected>>", lambda _e: self._refresh_jobs_tree())

        ttk.Label(flt_row, text=_("Status:")).grid(row=0, column=6, padx=(0, 4))
        cb_jst = ttk.Combobox(
            flt_row,
            textvariable=self.job_flt_status,
            values=["All", "Success", "Failed", "Running"],
            state="readonly",
            width=10,
        )
        cb_jst.grid(row=0, column=7)
        cb_jst.bind("<<ComboboxSelected>>", lambda _e: self._refresh_jobs_tree())

        cols = ("name", "type", "os", "status", "created", "start", "end", "action")
        self.jobs_tree = ttk.Treeview(
            jobs_card, columns=cols, show="headings", selectmode="browse"
        )
        j_heads = {
            "name": _("Name"),
            "type": _("Job Type"),
            "os": _("Device Type"),
            "status": _("Status"),
            "created": _("Creation Time"),
            "start": _("Start Time"),
            "end": _("End Time"),
            "action": _("Action"),
        }
        j_widths = {
            "name": 220,
            "type": 130,
            "os": 95,
            "status": 105,
            "created": 140,
            "start": 140,
            "end": 140,
            "action": 80,
        }
        for col in cols:
            self.jobs_tree.heading(col, text=j_heads[col])
            self.jobs_tree.column(
                col, width=j_widths[col], anchor=tk.CENTER if col == "action" else tk.W
            )

        self.jobs_tree.tag_configure("Success", foreground="#15803d")
        self.jobs_tree.tag_configure("Failed", foreground="#b91c1c")
        self.jobs_tree.tag_configure("Running", foreground="#007fff")

        j_sb = ttk.Scrollbar(jobs_card, orient=tk.VERTICAL, command=self.jobs_tree.yview)
        self.jobs_tree.configure(yscrollcommand=j_sb.set)
        self.jobs_tree.grid(row=2, column=0, sticky=tk.NSEW)
        j_sb.grid(row=2, column=1, sticky=tk.NS)
        self.jobs_tree.bind("<<TreeviewSelect>>", self._on_job_selected)
        self.jobs_tree.bind("<Button-1>", self._on_jobs_tree_click)
        _bind_tree_action_cursor(self.jobs_tree, f"#{len(cols)}")

        self.jobs_footer_lbl = ttk.Label(jobs_card, text="", foreground=self._total_fg())
        self.jobs_footer_lbl.grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=(6, 0))

        # Bottom Card: Job Details (Details first [default], Devices second)
        details_card = ttk.Frame(v_pane, style="Card.TFrame", padding=12)
        details_card.rowconfigure(1, weight=1)
        details_card.columnconfigure(0, weight=1)
        v_pane.add(details_card, weight=3)

        self.job_details_title_lbl = ttk.Label(
            details_card, text=_("Job Details"), font=("Segoe UI", 11, "bold")
        )
        self.job_details_title_lbl.grid(row=0, column=0, sticky=tk.W, pady=(0, 6))

        self.job_details_nb = ttk.Notebook(details_card)
        self.job_details_nb.grid(row=1, column=0, sticky=tk.NSEW)

        # ---- Sub-tab 1 (Default): Details ----
        info_tab = ttk.Frame(self.job_details_nb, padding=10)
        info_tab.rowconfigure(5, weight=2)
        info_tab.rowconfigure(7, weight=1)
        info_tab.columnconfigure(0, weight=1)
        self.job_details_nb.add(info_tab, text=_("Details"))

        ttk.Label(info_tab, text=_("Devices"), font=("Segoe UI", 9, "bold")).grid(
            row=0, column=0, sticky=tk.W, pady=(0, 4)
        )
        counts_bar = ttk.Frame(info_tab)
        counts_bar.grid(row=1, column=0, sticky=tk.EW, pady=(0, 10))

        total_wrap = ttk.Frame(counts_bar)
        total_wrap.pack(side=tk.LEFT, padx=(0, 18))
        ttk.Label(total_wrap, text=_("Total:") + " ", foreground="#2563eb").pack(side=tk.LEFT)
        self.job_total_lbl = ttk.Label(
            total_wrap, text="0", foreground="#2563eb", font=("Segoe UI", 9, "bold")
        )
        self.job_total_lbl.pack(side=tk.LEFT)

        ok_wrap = ttk.Frame(counts_bar)
        ok_wrap.pack(side=tk.LEFT, padx=(0, 18))
        ttk.Label(ok_wrap, text=f"✓ {_('Success')}: ", foreground="#15803d").pack(side=tk.LEFT)
        self.job_ok_lbl = ttk.Label(
            ok_wrap, text="0", foreground="#15803d", font=("Segoe UI", 9, "bold")
        )
        self.job_ok_lbl.pack(side=tk.LEFT)

        fail_wrap = ttk.Frame(counts_bar)
        fail_wrap.pack(side=tk.LEFT, padx=(0, 18))
        ttk.Label(fail_wrap, text=f"⚠ {_('Failed')}: ", foreground="#b91c1c").pack(side=tk.LEFT)
        self.job_fail_lbl = ttk.Label(
            fail_wrap, text="0", foreground="#b91c1c", font=("Segoe UI", 9, "bold")
        )
        self.job_fail_lbl.pack(side=tk.LEFT)

        self.job_meta_extra_lbl = ttk.Label(counts_bar, text="", foreground="#64748b")
        self.job_meta_extra_lbl.pack(side=tk.LEFT)

        ttk.Label(info_tab, text=_("Description"), font=("Segoe UI", 9, "bold")).grid(
            row=2, column=0, sticky=tk.W, pady=(0, 4)
        )
        self.job_desc_readonly = _make_readonly_text(
            info_tab, height=3, dark_mode=self._is_dark(), wrap=tk.WORD
        )
        self.job_desc_readonly.grid(row=3, column=0, sticky=tk.EW, pady=(0, 10))

        ttk.Label(info_tab, text=_("Config Commands"), font=("Segoe UI", 9, "bold")).grid(
            row=4, column=0, sticky=tk.W, pady=(0, 4)
        )
        cmd_box_wrap = ttk.Frame(info_tab)
        cmd_box_wrap.grid(row=5, column=0, sticky=tk.NSEW, pady=(0, 8))
        cmd_box_wrap.rowconfigure(0, weight=1)
        cmd_box_wrap.columnconfigure(0, weight=1)

        self.job_cmds_text = _make_readonly_text(
            cmd_box_wrap, height=5, dark_mode=self._is_dark(), wrap=tk.NONE, font=("Consolas", 10)
        )
        configure_editor_tags(self.job_cmds_text, dark_mode=self._is_dark())
        jc_sb = ttk.Scrollbar(cmd_box_wrap, orient=tk.VERTICAL, command=self.job_cmds_text.yview)
        jc_xsb = ttk.Scrollbar(cmd_box_wrap, orient=tk.HORIZONTAL, command=self.job_cmds_text.xview)
        self.job_cmds_text.configure(yscrollcommand=jc_sb.set, xscrollcommand=jc_xsb.set)
        self.job_cmds_text.grid(row=0, column=0, sticky=tk.NSEW)
        jc_sb.grid(row=0, column=1, sticky=tk.NS)
        jc_xsb.grid(row=1, column=0, sticky=tk.EW)

        self.job_audit_lbl = ttk.Label(
            info_tab, text=_("Audit Validation RegEx"), font=("Segoe UI", 9, "bold")
        )
        self.job_audit_lbl.grid(row=6, column=0, sticky=tk.W, pady=(0, 4))
        self.job_audit_wrap = ttk.Frame(info_tab)
        self.job_audit_wrap.grid(row=7, column=0, sticky=tk.NSEW)
        self.job_audit_wrap.rowconfigure(0, weight=1)
        self.job_audit_wrap.columnconfigure(0, weight=1)
        self.job_audit_text = _make_readonly_text(
            self.job_audit_wrap, height=3, dark_mode=self._is_dark(), wrap=tk.NONE, font=("Consolas", 10)
        )
        configure_editor_tags(self.job_audit_text, dark_mode=self._is_dark())
        self.job_audit_text.grid(row=0, column=0, sticky=tk.NSEW)
        self.job_audit_lbl.grid_remove()
        self.job_audit_wrap.grid_remove()

        # ---- Sub-tab 2: Devices (Row list + clickable Log icon per row, Open Logs Folder button) ----
        dev_tab = ttk.Frame(self.job_details_nb, padding=8)
        dev_tab.rowconfigure(1, weight=1)
        dev_tab.columnconfigure(0, weight=1)
        self.job_details_nb.add(dev_tab, text=_("Devices"))

        dev_flt = ttk.Frame(dev_tab)
        dev_flt.grid(row=0, column=0, columnspan=2, sticky=tk.EW, pady=(0, 6))
        self.dev_flt_name = tk.StringVar()
        self.dev_flt_ip = tk.StringVar()
        self.dev_flt_status = tk.StringVar(value="All")

        ttk.Label(dev_flt, text=_("Device:")).pack(side=tk.LEFT, padx=(0, 4))
        e_dn = ttk.Entry(dev_flt, textvariable=self.dev_flt_name, width=18)
        e_dn.pack(side=tk.LEFT, padx=(0, 10))
        e_dn.bind("<KeyRelease>", lambda _e: self._refresh_job_details())

        ttk.Label(dev_flt, text=_("IP Address:")).pack(side=tk.LEFT, padx=(0, 4))
        e_dip = ttk.Entry(dev_flt, textvariable=self.dev_flt_ip, width=16)
        e_dip.pack(side=tk.LEFT, padx=(0, 10))
        e_dip.bind("<KeyRelease>", lambda _e: self._refresh_job_details())

        ttk.Label(dev_flt, text=_("Status:")).pack(side=tk.LEFT, padx=(0, 4))
        cb_dst = ttk.Combobox(
            dev_flt,
            textvariable=self.dev_flt_status,
            values=["All", "Success", "Failed", "Running", "Pending"],
            state="readonly",
            width=10,
        )
        cb_dst.pack(side=tk.LEFT)
        cb_dst.bind("<<ComboboxSelected>>", lambda _e: self._refresh_job_details())

        self.open_logs_btn = ttk.Button(
            dev_flt, text=_("Open Logs Folder"), command=self._open_selected_job_logs_folder
        )
        self.open_logs_btn.pack(side=tk.RIGHT)

        dcols = ("device", "ip", "status", "start", "end", "operation", "log")
        self.job_devices_tree = ttk.Treeview(
            dev_tab, columns=dcols, show="headings", selectmode="browse"
        )
        d_heads = {
            "device": _("Device"),
            "ip": _("IP Address"),
            "status": _("Status"),
            "start": _("Start Time"),
            "end": _("End Time"),
            "operation": _("Operation Result"),
            "log": _("Log"),
        }
        d_widths = {
            "device": 160,
            "ip": 120,
            "status": 100,
            "start": 135,
            "end": 135,
            "operation": 280,
            "log": 65,
        }
        for col in dcols:
            self.job_devices_tree.heading(col, text=d_heads[col])
            self.job_devices_tree.column(
                col, width=d_widths[col], anchor=tk.CENTER if col == "log" else tk.W
            )

        self.job_devices_tree.tag_configure("Success", foreground="#15803d")
        self.job_devices_tree.tag_configure("Failed", foreground="#b91c1c")
        self.job_devices_tree.tag_configure("Running", foreground="#007fff")
        self.job_devices_tree.tag_configure("Pending", foreground="#64748b")

        d_sb = ttk.Scrollbar(dev_tab, orient=tk.VERTICAL, command=self.job_devices_tree.yview)
        self.job_devices_tree.configure(yscrollcommand=d_sb.set)
        self.job_devices_tree.grid(row=1, column=0, sticky=tk.NSEW)
        d_sb.grid(row=1, column=1, sticky=tk.NS)
        self.job_devices_tree.bind("<Button-1>", self._on_job_devices_click)
        self.job_devices_tree.bind("<Double-1>", lambda _e: self._open_selected_device_log())
        _bind_tree_action_cursor(self.job_devices_tree, f"#{len(dcols)}")

        self.job_devices_footer_lbl = ttk.Label(dev_tab, text="", foreground=self._total_fg())
        self.job_devices_footer_lbl.grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=(6, 0))

    # ------------------------------------------------------------------
    # Tab 2: Snippets (Action icons per row)
    # ------------------------------------------------------------------
    def _build_snippets_tab(self) -> None:
        self.tab_snippets.rowconfigure(0, weight=1)
        self.tab_snippets.columnconfigure(0, weight=1)

        card = ttk.Frame(self.tab_snippets, style="Card.TFrame", padding=12)
        card.grid(row=0, column=0, sticky=tk.NSEW)
        card.rowconfigure(2, weight=2)
        card.rowconfigure(3, weight=1)
        card.columnconfigure(0, weight=1)

        hdr = ttk.Frame(card)
        hdr.grid(row=0, column=0, columnspan=2, sticky=tk.EW, pady=(0, 8))
        ttk.Label(hdr, text=_("Snippets"), font=("Segoe UI", 12, "bold")).pack(side=tk.LEFT)

        ttk.Button(
            hdr, text="+ " + _("Add Snippet"), style="Accent.TButton", command=self._new_snippet
        ).pack(side=tk.RIGHT)
        ttk.Button(hdr, text=_("Export XML..."), command=self._export_snippet_xml).pack(
            side=tk.RIGHT, padx=(0, 6)
        )
        ttk.Button(hdr, text=_("Import XML..."), command=self._import_snippet_xml).pack(
            side=tk.RIGHT, padx=(0, 6)
        )

        flt = ttk.Frame(card)
        flt.grid(row=1, column=0, columnspan=2, sticky=tk.EW, pady=(0, 6))
        flt.columnconfigure(1, weight=1)
        flt.columnconfigure(9, weight=1)

        self.snip_flt_name = tk.StringVar()
        self.snip_flt_type = tk.StringVar(value="All")
        self.snip_flt_sev = tk.StringVar(value="All")
        self.snip_flt_os = tk.StringVar(value="All")
        self.snip_flt_desc = tk.StringVar()

        ttk.Label(flt, text=_("Name:")).grid(row=0, column=0, padx=(0, 4))
        e_sn = ttk.Entry(flt, textvariable=self.snip_flt_name, width=18)
        e_sn.grid(row=0, column=1, sticky=tk.EW, padx=(0, 8))
        e_sn.bind("<KeyRelease>", lambda _e: self._refresh_snippets_table())

        ttk.Label(flt, text=_("Snippet Type:")).grid(row=0, column=2, padx=(0, 4))
        cb_st = ttk.Combobox(
            flt,
            textvariable=self.snip_flt_type,
            values=["All", SnippetType.CONFIG.value, SnippetType.AUDIT.value],
            state="readonly",
            width=18,
        )
        cb_st.grid(row=0, column=3, padx=(0, 8))
        cb_st.bind("<<ComboboxSelected>>", lambda _e: self._refresh_snippets_table())

        ttk.Label(flt, text=_("Severity:")).grid(row=0, column=4, padx=(0, 4))
        cb_sv = ttk.Combobox(
            flt,
            textvariable=self.snip_flt_sev,
            values=["All"] + [s.value for s in SnippetSeverity],
            state="readonly",
            width=10,
        )
        cb_sv.grid(row=0, column=5, padx=(0, 8))
        cb_sv.bind("<<ComboboxSelected>>", lambda _e: self._refresh_snippets_table())

        ttk.Label(flt, text=_("Device Type:")).grid(row=0, column=6, padx=(0, 4))
        cb_sos = ttk.Combobox(
            flt,
            textvariable=self.snip_flt_os,
            values=["All", *self._discovered_os_values()],
            state="readonly",
            width=12,
        )
        cb_sos.grid(row=0, column=7, padx=(0, 8))
        cb_sos.bind("<<ComboboxSelected>>", lambda _e: self._refresh_snippets_table())

        ttk.Label(flt, text=_("Description:")).grid(row=0, column=8, padx=(0, 4))
        e_sd = ttk.Entry(flt, textvariable=self.snip_flt_desc, width=20)
        e_sd.grid(row=0, column=9, sticky=tk.EW)
        e_sd.bind("<KeyRelease>", lambda _e: self._refresh_snippets_table())

        cols = ("name", "type", "severity", "os", "created", "description", "action")
        self.snippets_tree = ttk.Treeview(
            card, columns=cols, show="headings", selectmode="browse"
        )
        s_heads = {
            "name": _("Name"),
            "type": _("Snippet Type"),
            "severity": _("Severity"),
            "os": _("Device Type"),
            "created": _("Creation Time"),
            "description": _("Description"),
            "action": _("Action"),
        }
        s_widths = {
            "name": 200,
            "type": 135,
            "severity": 80,
            "os": 95,
            "created": 140,
            "description": 310,
            "action": 80,
        }
        for col in cols:
            self.snippets_tree.heading(col, text=s_heads[col])
            self.snippets_tree.column(
                col, width=s_widths[col], anchor=tk.CENTER if col == "action" else tk.W
            )

        s_sb = ttk.Scrollbar(card, orient=tk.VERTICAL, command=self.snippets_tree.yview)
        self.snippets_tree.configure(yscrollcommand=s_sb.set)
        self.snippets_tree.grid(row=2, column=0, sticky=tk.NSEW)
        s_sb.grid(row=2, column=1, sticky=tk.NS)
        self.snippets_tree.bind("<<TreeviewSelect>>", self._on_snippet_selected)
        self.snippets_tree.bind("<Button-1>", self._on_snippets_tree_click)
        self.snippets_tree.bind("<Double-1>", lambda _e: self._edit_snippet())
        _bind_tree_action_cursor(self.snippets_tree, f"#{len(cols)}")

        prev_box = ttk.LabelFrame(card, text=_("Snippet Commands Preview"), padding=6)
        prev_box.grid(row=3, column=0, columnspan=2, sticky=tk.NSEW, pady=(8, 0))
        prev_box.rowconfigure(0, weight=1)
        prev_box.columnconfigure(0, weight=1)

        self.snippet_preview_text = tk.Text(
            prev_box, wrap=tk.NONE, font=("Consolas", 10), state=tk.DISABLED, height=6
        )
        configure_editor_tags(self.snippet_preview_text, dark_mode=self._is_dark())
        p_sb = ttk.Scrollbar(prev_box, orient=tk.VERTICAL, command=self.snippet_preview_text.yview)
        self.snippet_preview_text.configure(yscrollcommand=p_sb.set)
        self.snippet_preview_text.grid(row=0, column=0, sticky=tk.NSEW)
        p_sb.grid(row=0, column=1, sticky=tk.NS)

        self.snippets_footer_lbl = ttk.Label(card, text="", foreground=self._total_fg())
        self.snippets_footer_lbl.grid(row=4, column=0, columnspan=2, sticky=tk.W, pady=(6, 0))

    # ------------------------------------------------------------------
    # Tab 3: Devices (Action icons per row + dynamic Model & Group dropdowns)
    # ------------------------------------------------------------------
    def _build_devices_tab(self) -> None:
        self.tab_devices.rowconfigure(0, weight=1)
        self.tab_devices.columnconfigure(0, weight=1)

        card = ttk.Frame(self.tab_devices, style="Card.TFrame", padding=12)
        card.grid(row=0, column=0, sticky=tk.NSEW)
        card.rowconfigure(2, weight=1)
        card.columnconfigure(0, weight=1)

        hdr = ttk.Frame(card)
        hdr.grid(row=0, column=0, columnspan=2, sticky=tk.EW, pady=(0, 8))
        ttk.Label(hdr, text=_("Devices"), font=("Segoe UI", 12, "bold")).pack(side=tk.LEFT)

        ttk.Button(
            hdr, text="+ " + _("Add Device"), style="Accent.TButton", command=self._add_device_dialog
        ).pack(side=tk.RIGHT)
        ttk.Button(hdr, text=_("Import from AirWave..."), command=self._open_import_dialog).pack(
            side=tk.RIGHT, padx=(0, 6)
        )

        flt = ttk.Frame(card)
        flt.grid(row=1, column=0, columnspan=2, sticky=tk.EW, pady=(0, 6))
        flt.columnconfigure(1, weight=1)
        flt.columnconfigure(7, weight=1)

        self.dev_flt_dev = tk.StringVar()
        self.dev_flt_ip2 = tk.StringVar()
        self.dev_flt_os = tk.StringVar(value="All")
        self.dev_flt_model = tk.StringVar(value="All")
        self.dev_flt_st2 = tk.StringVar(value="All")

        ttk.Label(flt, text=_("Device:")).grid(row=0, column=0, padx=(0, 4))
        e_hn = ttk.Entry(flt, textvariable=self.dev_flt_dev, width=16)
        e_hn.grid(row=0, column=1, sticky=tk.EW, padx=(0, 8))
        e_hn.bind("<KeyRelease>", lambda _e: self._refresh_devices_tree())

        ttk.Label(flt, text=_("IP Address:")).grid(row=0, column=2, padx=(0, 4))
        e_hip = ttk.Entry(flt, textvariable=self.dev_flt_ip2, width=15)
        e_hip.grid(row=0, column=3, padx=(0, 8))
        e_hip.bind("<KeyRelease>", lambda _e: self._refresh_devices_tree())

        ttk.Label(flt, text=_("OS Type:")).grid(row=0, column=4, padx=(0, 4))
        cb_hos = ttk.Combobox(
            flt,
            textvariable=self.dev_flt_os,
            values=["All", *self._discovered_os_values(), SwitchOS.UNKNOWN.value],
            state="readonly",
            width=12,
        )
        cb_hos.grid(row=0, column=5, padx=(0, 8))
        cb_hos.bind("<<ComboboxSelected>>", lambda _e: self._refresh_devices_tree())

        ttk.Label(flt, text=_("Model:")).grid(row=0, column=6, padx=(0, 4))
        self.dev_model_combo = ttk.Combobox(
            flt,
            textvariable=self.dev_flt_model,
            values=["All"],
            state="readonly",
            width=18,
        )
        self.dev_model_combo.grid(row=0, column=7, sticky=tk.EW, padx=(0, 8))
        self.dev_model_combo.bind("<<ComboboxSelected>>", lambda _e: self._refresh_devices_tree())

        ttk.Label(flt, text=_("Status:")).grid(row=0, column=8, padx=(0, 4))
        cb_hst = ttk.Combobox(
            flt,
            textvariable=self.dev_flt_st2,
            values=["All", "Up", "Down", "Manual"],
            state="readonly",
            width=10,
        )
        cb_hst.grid(row=0, column=9)
        cb_hst.bind("<<ComboboxSelected>>", lambda _e: self._refresh_devices_tree())

        cols = ("name", "status", "ip", "os", "model", "folder", "firmware", "action")
        self.devices_tree = ttk.Treeview(
            card, columns=cols, show="headings", selectmode="browse"
        )
        h_heads = {
            "name": _("Device"),
            "status": _("Status"),
            "ip": _("IP Address"),
            "os": _("OS Type"),
            "model": _("Model"),
            "folder": _("Group"),
            "firmware": _("Firmware"),
            "action": _("Action"),
        }
        h_widths = {
            "name": 180,
            "status": 80,
            "ip": 130,
            "os": 95,
            "model": 165,
            "folder": 175,
            "firmware": 125,
            "action": 80,
        }
        for col in cols:
            self.devices_tree.heading(col, text=h_heads[col])
            self.devices_tree.column(
                col, width=h_widths[col], anchor=tk.CENTER if col == "action" else tk.W
            )

        h_sb = ttk.Scrollbar(card, orient=tk.VERTICAL, command=self.devices_tree.yview)
        self.devices_tree.configure(yscrollcommand=h_sb.set)
        self.devices_tree.grid(row=2, column=0, sticky=tk.NSEW)
        h_sb.grid(row=2, column=1, sticky=tk.NS)
        self.devices_tree.bind("<Button-1>", self._on_devices_tree_click)
        self.devices_tree.bind("<Double-1>", lambda _e: self._edit_selected_device())
        _bind_tree_action_cursor(self.devices_tree, f"#{len(cols)}")

        self.devices_tab_footer_lbl = ttk.Label(card, text="", foreground=self._total_fg())
        self.devices_tab_footer_lbl.grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=(6, 0))

    # ------------------------------------------------------------------
    # Tab 4: Device Models (Automation Prompts & Common Task Wrappers)
    # ------------------------------------------------------------------
    def _build_models_tab(self) -> None:
        self.tab_models.rowconfigure(0, weight=1)
        self.tab_models.columnconfigure(0, weight=1)

        card = ttk.Frame(self.tab_models, style="Card.TFrame", padding=12)
        card.grid(row=0, column=0, sticky=tk.NSEW)
        card.rowconfigure(2, weight=2)
        card.rowconfigure(3, weight=1)
        card.columnconfigure(0, weight=1)

        hdr = ttk.Frame(card)
        hdr.grid(row=0, column=0, columnspan=2, sticky=tk.EW, pady=(0, 8))
        ttk.Label(hdr, text=_("Device Models"), font=("Segoe UI", 12, "bold")).pack(side=tk.LEFT)
        ttk.Button(
            hdr, text="+ " + _("Add Model"), style="Accent.TButton", command=self._new_model
        ).pack(side=tk.RIGHT)

        flt = ttk.Frame(card)
        flt.grid(row=1, column=0, columnspan=2, sticky=tk.EW, pady=(0, 6))
        flt.columnconfigure(1, weight=1)

        self.mdl_flt_name = tk.StringVar()
        self.mdl_flt_os = tk.StringVar(value="All")

        ttk.Label(flt, text=_("Name:")).grid(row=0, column=0, padx=(0, 4))
        e_mn = ttk.Entry(flt, textvariable=self.mdl_flt_name, width=22)
        e_mn.grid(row=0, column=1, sticky=tk.EW, padx=(0, 10))
        e_mn.bind("<KeyRelease>", lambda _e: self._refresh_models_table())

        ttk.Label(flt, text=_("Switch OS:")).grid(row=0, column=2, padx=(0, 4))
        cb_mos = ttk.Combobox(
            flt,
            textvariable=self.mdl_flt_os,
            values=["All", *self._discovered_os_values()],
            state="readonly",
            width=14,
        )
        cb_mos.grid(row=0, column=3)
        cb_mos.bind("<<ComboboxSelected>>", lambda _e: self._refresh_models_table())

        mcols = ("name", "os", "vendor", "enable", "pre_cfg", "post_cfg", "action")
        self.models_tree = ttk.Treeview(
            card, columns=mcols, show="headings", selectmode="browse"
        )
        m_heads = {
            "name": _("Name"),
            "os": _("Device Type"),
            "vendor": _("Vendor"),
            "enable": _("Enable Command"),
            "pre_cfg": _("Pre-Config Commands"),
            "post_cfg": _("Post-Config Commands"),
            "action": _("Action"),
        }
        m_widths = {
            "name": 200,
            "os": 100,
            "vendor": 95,
            "enable": 115,
            "pre_cfg": 175,
            "post_cfg": 175,
            "action": 80,
        }
        for col in mcols:
            self.models_tree.heading(col, text=m_heads[col])
            self.models_tree.column(
                col, width=m_widths[col], anchor=tk.CENTER if col == "action" else tk.W
            )

        m_sb = ttk.Scrollbar(card, orient=tk.VERTICAL, command=self.models_tree.yview)
        self.models_tree.configure(yscrollcommand=m_sb.set)
        self.models_tree.grid(row=2, column=0, sticky=tk.NSEW)
        m_sb.grid(row=2, column=1, sticky=tk.NS)
        self.models_tree.bind("<<TreeviewSelect>>", self._on_model_selected)
        self.models_tree.bind("<Button-1>", self._on_models_tree_click)
        self.models_tree.bind("<Double-1>", lambda _e: self._edit_model())
        _bind_tree_action_cursor(self.models_tree, f"#{len(mcols)}")

        prev_box = ttk.LabelFrame(card, text=_("Device Model Automation Preview"), padding=6)
        prev_box.grid(row=3, column=0, columnspan=2, sticky=tk.NSEW, pady=(8, 0))
        prev_box.rowconfigure(0, weight=1)
        prev_box.columnconfigure(0, weight=1)

        self.model_preview_text = _make_readonly_text(
            prev_box, height=6, dark_mode=self._is_dark(), wrap=tk.NONE, font=("Consolas", 9)
        )
        mp_sb = ttk.Scrollbar(prev_box, orient=tk.VERTICAL, command=self.model_preview_text.yview)
        self.model_preview_text.configure(yscrollcommand=mp_sb.set)
        self.model_preview_text.grid(row=0, column=0, sticky=tk.NSEW)
        mp_sb.grid(row=0, column=1, sticky=tk.NS)

        self.models_footer_lbl = ttk.Label(card, text="", foreground=self._total_fg())
        self.models_footer_lbl.grid(row=4, column=0, columnspan=2, sticky=tk.W, pady=(6, 0))

    # ------------------------------------------------------------------
    # Refreshers
    # ------------------------------------------------------------------
    def _reload_snippets_data(self) -> None:
        self.snippets = self.snippet_store.load_all_snippets()

    def _reload_models_data(self) -> None:
        self.device_models = self.model_store.load_all_models()

    def _refresh_all_views(self) -> None:
        self._refresh_jobs_tree()
        self._refresh_job_details()
        self._refresh_snippets_table()
        self._refresh_devices_tree()
        self._refresh_models_table()

    def _get_selected_job(self) -> Optional[JobRecord]:
        if not self.selected_job_id:
            return None
        return next((j for j in self.session.jobs if j.job_id == self.selected_job_id), None)

    def _refresh_jobs_tree(self) -> None:
        name_q = self.job_flt_name.get().strip().lower()
        type_q = self.job_flt_type.get()
        os_q = self.job_flt_os.get()
        status_q = self.job_flt_status.get()

        for item in self.jobs_tree.get_children():
            self.jobs_tree.delete(item)

        shown = []
        for job in self.session.jobs:
            if name_q and name_q not in job.name.lower():
                continue
            if type_q != "All" and job.job_type.value != type_q:
                continue
            if os_q != "All" and job.device_type.value != os_q:
                continue
            if status_q != "All" and job.status != status_q:
                continue
            shown.append(job)

            if job.status == "Success":
                status_disp = f"✓ {_('Success')}"
            elif job.status == "Failed":
                status_disp = f"▲ {_('Failed')}"
            else:
                status_disp = f"⟳ {_('Running')}"

            action_disp = "⏹   🗑" if job.job_id in self.running_jobs else "🗑"

            self.jobs_tree.insert(
                "",
                tk.END,
                iid=job.job_id,
                tags=(job.status,),
                values=(
                    job.name,
                    job.job_type.value,
                    job.device_type.value,
                    status_disp,
                    job.creation_time,
                    job.start_time,
                    job.end_time or "-",
                    action_disp,
                ),
            )

        if self.selected_job_id and self.jobs_tree.exists(self.selected_job_id):
            self.jobs_tree.selection_set(self.selected_job_id)
        elif shown:
            self.selected_job_id = shown[0].job_id
            self.jobs_tree.selection_set(self.selected_job_id)

        self.jobs_footer_lbl.configure(
            text=_("Total Records: {total}").format(total=len(shown))
        )

    def _on_job_selected(self, _event=None) -> None:
        sel = self.jobs_tree.selection()
        self.selected_job_id = sel[0] if sel else None
        self._refresh_job_details()

    def _on_jobs_tree_click(self, event: tk.Event) -> Optional[str]:
        region = self.jobs_tree.identify("region", event.x, event.y)
        col = self.jobs_tree.identify_column(event.x)
        job_id = self.jobs_tree.identify_row(event.y)
        if region != "cell" or not job_id or col != "#8":
            return None

        self.selected_job_id = job_id
        self.jobs_tree.selection_set(job_id)
        if job_id in self.running_jobs:
            bbox = self.jobs_tree.bbox(job_id, col)
            if bbox and event.x < bbox[0] + (bbox[2] / 2):
                self._stop_job_by_id(job_id)
            else:
                self._delete_job_by_id(job_id)
        else:
            self._delete_job_by_id(job_id)
        return "break"

    def _set_readonly_text_content(
        self, widget: tk.Text, content: str, highlight_cli: bool = False
    ) -> None:
        widget.configure(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert("1.0", content)
        if highlight_cli:
            apply_cli_syntax_highlighting(widget)
        widget.configure(state=tk.DISABLED)

    def _refresh_job_details(self) -> None:
        job = self._get_selected_job()
        for item in self.job_devices_tree.get_children():
            self.job_devices_tree.delete(item)

        if not job:
            self.job_details_title_lbl.configure(text=_("Job Details"))
            self.job_total_lbl.configure(text="0")
            self.job_ok_lbl.configure(text="0")
            self.job_fail_lbl.configure(text="0")
            self.job_meta_extra_lbl.configure(text="")
            self._set_readonly_text_content(self.job_desc_readonly, "")
            self._set_readonly_text_content(self.job_cmds_text, "", highlight_cli=True)
            self._set_readonly_text_content(self.job_audit_text, "", highlight_cli=True)
            self.job_audit_lbl.grid_remove()
            self.job_audit_wrap.grid_remove()
            self.job_devices_footer_lbl.configure(text=_("Total Records: {total}").format(total=0))
            return

        self.job_details_title_lbl.configure(
            text=_("Job Details ({name})").format(name=job.name)
        )

        total_dev = len(job.results)
        ok_cnt = sum(1 for r in job.results if r.status == "Success")
        fail_cnt = sum(1 for r in job.results if r.status == "Failed")

        self.job_total_lbl.configure(text=str(total_dev))
        self.job_ok_lbl.configure(text=str(ok_cnt))
        self.job_fail_lbl.configure(text=str(fail_cnt))
        seq_str = (
            ScheduleSequence.SEQUENTIAL.value
            if job.schedule_sequence == ScheduleSequence.SEQUENTIAL
            else f"{ScheduleSequence.CONCURRENT.value} ({job.max_parallel})"
        )
        extra_bits = [bit for bit in (job.snippet_name, job.model_name, seq_str) if bit]
        self.job_meta_extra_lbl.configure(text="   |   ".join(extra_bits))

        self._set_readonly_text_content(self.job_desc_readonly, job.description or "-")
        self._set_readonly_text_content(
            self.job_cmds_text,
            job.commands_rendered or job.commands_raw or "",
            highlight_cli=True,
        )
        if job.audit_regex and job.audit_regex.strip():
            self.job_audit_lbl.grid()
            self.job_audit_wrap.grid()
            self._set_readonly_text_content(
                self.job_audit_text, job.audit_regex, highlight_cli=True
            )
        else:
            self._set_readonly_text_content(self.job_audit_text, "", highlight_cli=True)
            self.job_audit_lbl.grid_remove()
            self.job_audit_wrap.grid_remove()

        dev_q = self.dev_flt_name.get().strip().lower()
        ip_q = self.dev_flt_ip.get().strip().lower()
        st_q = self.dev_flt_status.get()

        shown_dev = 0
        for res in job.results:
            if dev_q and dev_q not in res.host.display_label.lower():
                continue
            if ip_q and ip_q not in res.host.ip.lower():
                continue
            if st_q != "All" and res.status != st_q:
                continue
            shown_dev += 1

            if res.status == "Success":
                st_disp = f"✓ {_('Success')}"
            elif res.status == "Failed":
                st_disp = f"▲ {_('Failed')}"
            elif res.status == "Running":
                st_disp = f"⟳ {_('Running')}"
            else:
                st_disp = f"• {_('Pending')}"

            log_icon = "📄" if (res.log_path or res.raw_output) else "-"

            self.job_devices_tree.insert(
                "",
                tk.END,
                iid=res.host.unique_key,
                tags=(res.status,),
                values=(
                    res.host.display_label,
                    res.host.ip,
                    st_disp,
                    res.started_at or "-",
                    res.finished_at or "-",
                    res.operation_result,
                    log_icon,
                ),
            )

        self.job_devices_footer_lbl.configure(
            text=_("Total Records: {total}").format(total=shown_dev)
        )

    def _on_job_devices_click(self, event: tk.Event) -> Optional[str]:
        region = self.job_devices_tree.identify("region", event.x, event.y)
        col = self.job_devices_tree.identify_column(event.x)
        dev_key = self.job_devices_tree.identify_row(event.y)
        if region == "cell" and dev_key and col == "#7":
            self.job_devices_tree.selection_set(dev_key)
            self._open_device_log_by_key(dev_key)
            return "break"
        return None

    def _refresh_snippets_table(self) -> None:
        name_q = self.snip_flt_name.get().strip().lower()
        type_q = self.snip_flt_type.get()
        sev_q = self.snip_flt_sev.get()
        os_q = self.snip_flt_os.get()
        desc_q = self.snip_flt_desc.get().strip().lower()

        filtered = []
        for s in self.snippets:
            if name_q and name_q not in s.name.lower():
                continue
            if type_q != "All" and s.snippet_type.value != type_q:
                continue
            if sev_q != "All" and s.severity.value != sev_q:
                continue
            if os_q != "All" and s.device_type.value != os_q:
                continue
            if desc_q and desc_q not in (s.description or "").lower():
                continue
            filtered.append(s)

        self._table_snippets = filtered
        for item in self.snippets_tree.get_children():
            self.snippets_tree.delete(item)
        for idx, s in enumerate(filtered):
            self.snippets_tree.insert(
                "",
                tk.END,
                iid=str(idx),
                values=(
                    s.name,
                    s.snippet_type.value,
                    s.severity.value,
                    s.device_type.value,
                    s.created_at or "-",
                    s.description,
                    "✎   🗑",
                ),
            )
        self.snippets_footer_lbl.configure(
            text=_("Total Items: {total}").format(total=len(filtered))
        )
        self._on_snippet_selected()

    def _on_snippets_tree_click(self, event: tk.Event) -> Optional[str]:
        region = self.snippets_tree.identify("region", event.x, event.y)
        col = self.snippets_tree.identify_column(event.x)
        row_iid = self.snippets_tree.identify_row(event.y)
        if region != "cell" or not row_iid or col != "#7":
            return None

        self.snippets_tree.selection_set(row_iid)
        idx = int(row_iid)
        bbox = self.snippets_tree.bbox(row_iid, col)
        if bbox and event.x < bbox[0] + (bbox[2] / 2):
            self._edit_snippet_by_idx(idx)
        else:
            self._delete_snippet_by_idx(idx)
        return "break"

    def _on_snippet_selected(self, _event=None) -> None:
        sel = self.snippets_tree.selection()
        snip = (
            self._table_snippets[int(sel[0])]
            if sel and 0 <= int(sel[0]) < len(getattr(self, "_table_snippets", []))
            else None
        )
        self.snippet_preview_text.configure(state=tk.NORMAL)
        self.snippet_preview_text.delete("1.0", tk.END)
        if snip:
            self.snippet_preview_text.insert("1.0", snip.commands)
            apply_cli_syntax_highlighting(self.snippet_preview_text)
        self.snippet_preview_text.configure(state=tk.DISABLED)

    def _refresh_devices_tree(self) -> None:
        assigned_models = get_assigned_models(self.session.hosts)
        model_values = ["All"] + assigned_models
        self.dev_model_combo.configure(values=model_values)
        if self.dev_flt_model.get() not in model_values:
            self.dev_flt_model.set("All")

        name_q = self.dev_flt_dev.get().strip().lower()
        ip_q = self.dev_flt_ip2.get().strip().lower()
        os_q = self.dev_flt_os.get()
        model_q = self.dev_flt_model.get()
        st_q = self.dev_flt_st2.get()

        for item in self.devices_tree.get_children():
            self.devices_tree.delete(item)

        shown = 0
        for idx, h in enumerate(self.session.hosts):
            if name_q and name_q not in h.name.lower():
                continue
            if ip_q and ip_q not in h.ip.lower():
                continue
            if os_q != "All" and h.os_type.value != os_q:
                continue
            if model_q != "All" and h.model.strip() != model_q:
                continue
            if st_q != "All" and h.airwave_status != st_q:
                continue
            shown += 1
            self.devices_tree.insert(
                "",
                tk.END,
                iid=str(idx),
                values=(
                    h.name,
                    h.airwave_status,
                    h.ip,
                    h.os_type.value,
                    h.model,
                    h.folder_path,
                    h.firmware,
                    "✎   🗑",
                ),
            )
        self.devices_tab_footer_lbl.configure(
            text=_("Total Records: {total}").format(total=shown)
        )

    def _on_devices_tree_click(self, event: tk.Event) -> Optional[str]:
        region = self.devices_tree.identify("region", event.x, event.y)
        col = self.devices_tree.identify_column(event.x)
        row_iid = self.devices_tree.identify_row(event.y)
        if region != "cell" or not row_iid or col != "#8":
            return None

        self.devices_tree.selection_set(row_iid)
        idx = int(row_iid)
        bbox = self.devices_tree.bbox(row_iid, col)
        if bbox and event.x < bbox[0] + (bbox[2] / 2):
            self._edit_device_by_idx(idx)
        else:
            self._remove_device_by_idx(idx)
        return "break"

    def _refresh_models_table(self) -> None:
        name_q = self.mdl_flt_name.get().strip().lower()
        os_q = self.mdl_flt_os.get()

        filtered: List[DeviceModel] = []
        for m in self.device_models:
            if name_q and name_q not in m.name.lower() and name_q not in m.vendor.lower():
                continue
            if os_q != "All" and m.device_type.value != os_q:
                continue
            filtered.append(m)

        self._table_models = filtered
        for item in self.models_tree.get_children():
            self.models_tree.delete(item)
        for idx, m in enumerate(filtered):
            self.models_tree.insert(
                "",
                tk.END,
                iid=str(idx),
                values=(
                    m.name,
                    m.device_type.value,
                    m.vendor,
                    m.enable_command or "-",
                    " | ".join(parse_commands(m.pre_config_commands)) or "-",
                    " | ".join(parse_commands(m.post_config_commands)) or "-",
                    "✎   🗑",
                ),
            )
        self.models_footer_lbl.configure(
            text=_("Total Items: {total}").format(total=len(filtered))
        )
        self._on_model_selected()

    def _on_models_tree_click(self, event: tk.Event) -> Optional[str]:
        region = self.models_tree.identify("region", event.x, event.y)
        col = self.models_tree.identify_column(event.x)
        row_iid = self.models_tree.identify_row(event.y)
        if region != "cell" or not row_iid or col != "#7":
            return None

        self.models_tree.selection_set(row_iid)
        idx = int(row_iid)
        bbox = self.models_tree.bbox(row_iid, col)
        if bbox and event.x < bbox[0] + (bbox[2] / 2):
            self._edit_model_by_idx(idx)
        else:
            self._delete_model_by_idx(idx)
        return "break"

    def _on_model_selected(self, _event=None) -> None:
        sel = self.models_tree.selection()
        mdl = (
            self._table_models[int(sel[0])]
            if sel and 0 <= int(sel[0]) < len(getattr(self, "_table_models", []))
            else None
        )
        if not mdl:
            self._set_readonly_text_content(self.model_preview_text, "")
            return
        lines = [
            f"{_('Description')}: {mdl.description or '-'}",
            f"{_('Disable Paging Command')}: {mdl.disable_paging_command or '-'}   |   {_('Enable Command')}: {mdl.enable_command or '-'}",
            f"{_('Username Prompt RegEx')}: {mdl.username_prompt_regex or '-'}",
            f"{_('Password Prompt RegEx')}: {mdl.password_prompt_regex or '-'}",
            f"{_('Enable Password Prompt RegEx')}: {mdl.enable_password_prompt_regex or '-'}",
            f"{_('Pre-Config Commands')}: {' ; '.join(parse_commands(mdl.pre_config_commands)) or '-'}",
            f"{_('Post-Config Commands')}: {' ; '.join(parse_commands(mdl.post_config_commands)) or '-'}",
        ]
        self._set_readonly_text_content(self.model_preview_text, "\n".join(lines))

    # ------------------------------------------------------------------
    # Actions: Jobs
    # ------------------------------------------------------------------
    def _open_add_job_dialog(self) -> None:
        dlg = AddJobDialog(
            self.root,
            session=self.session,
            snippets=self.snippets,
            settings=self.settings,
            ssh_password=self.ssh_password,
            dark_mode=self._is_dark(),
            device_models=self.device_models,
        )
        self.root.wait_window(dlg)
        if not dlg.launch_payload:
            return
        self.ssh_password = dlg.launch_payload["ssh_password"]
        self._auto_save_settings()
        self._launch_job(dlg.launch_payload)

    def _launch_job(self, payload: Dict[str, Any]) -> None:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        job_id = uuid.uuid4().hex[:10]
        hosts: List[HostEntry] = payload["hosts"]
        values: Dict[str, str] = payload["values"]
        secret_names: set[str] = set(payload.get("secret_names") or ())
        raw_commands: str = payload["commands_raw"]
        raw_audit_regex: str = payload.get("audit_regex", "")
        job_type: SnippetType = payload["job_type"]
        active_model = ModelStore.get_model_for_os(
            payload["device_type"],
            self.device_models,
            payload.get("model_name", ""),
        )

        include_write = bool(payload.get("include_write", False))
        cmd_map = build_commands_for_job(
            raw_commands,
            values,
            hosts,
            job_type=job_type,
            device_model=active_model,
            include_write_command=include_write,
        )
        audit_regex_map = (
            {h.unique_key: render_template(raw_audit_regex, values, host=h) for h in hosts}
            if raw_audit_regex.strip()
            else {}
        )
        masked_params = {
            k: ("••••••••" if k in secret_names else v) for k, v in values.items()
        }
        display_values = {
            k: ("********" if k in secret_names else v) for k, v in values.items()
        }
        commands_rendered = "\n".join(
            wrap_commands_with_model(
                parse_commands(render_template(raw_commands, display_values)),
                job_type=job_type,
                device_model=active_model,
                include_write_command=include_write,
            )
        )
        audit_rendered = render_template(raw_audit_regex, display_values) if raw_audit_regex else ""

        initial_results = [
            HostExecutionResult(
                host=h,
                status="Pending",
                commands_run=cmd_map.get(h.unique_key, []),
                operation_result=_("Queued"),
            )
            for h in hosts
        ]

        job = JobRecord(
            job_id=job_id,
            name=payload["job_name"],
            job_type=job_type,
            device_type=payload["device_type"],
            status="Running",
            creation_time=now_str,
            start_time=now_str,
            end_time="",
            description=payload["description"],
            snippet_name=payload["snippet_name"],
            model_name=active_model.name if active_model else payload.get("model_name", ""),
            commands_raw=raw_commands,
            commands_rendered=commands_rendered,
            audit_regex=audit_rendered,
            max_parallel=payload["max_parallel"],
            schedule_sequence=payload["schedule_sequence"],
            parameters_masked=masked_params,
            results=initial_results,
        )
        self.session.jobs.insert(0, job)
        self.selected_job_id = job.job_id

        cancel_evt = threading.Event()
        self.running_jobs[job_id] = cancel_evt

        self._refresh_jobs_tree()
        self._refresh_job_details()
        self._auto_save_session()

        ssh_user = payload["ssh_username"]
        ssh_pwd = payload["ssh_password"]
        enable_pwd = payload.get("enable_password", "")
        conn_to = self.settings.connect_timeout
        cmd_to = self.settings.command_timeout

        def _worker() -> None:
            executor = BatchSSHExecutor()
            run_dir, results = executor.run_batch(
                hosts=hosts,
                username=ssh_user,
                password=ssh_pwd,
                commands_by_host=cmd_map,
                max_parallel=job.max_parallel,
                schedule_sequence=job.schedule_sequence,
                connect_timeout=conn_to,
                command_timeout=cmd_to,
                cancel_event=cancel_evt,
                on_host_start=lambda h: self.ui_queue.put(("host_start", (job_id, h))),
                on_host_complete=lambda r: self.ui_queue.put(("host_done", (job_id, r))),
                audit_regex_by_host=audit_regex_map,
                enable_password=enable_pwd,
                device_model=active_model,
            )
            self.ui_queue.put(("job_done", (job_id, run_dir, results)))

        threading.Thread(target=_worker, daemon=True).start()

    def _stop_job_by_id(self, job_id: str) -> None:
        if job_id in self.running_jobs:
            self.running_jobs[job_id].set()

    def _delete_job_by_id(self, job_id: str, confirm: bool = True) -> None:
        job = next((j for j in self.session.jobs if j.job_id == job_id), None)
        if not job:
            return
        if job.job_id in self.running_jobs:
            messagebox.showwarning(_("Job Running"), _("Stop the running job before deleting it."))
            return
        if confirm and not messagebox.askyesno(
            _("Confirm Delete"),
            _("Remove job '{name}' from history?").format(name=job.name),
        ):
            return
        self.session.jobs = [j for j in self.session.jobs if j.job_id != job_id]
        if self.selected_job_id == job_id:
            self.selected_job_id = self.session.jobs[0].job_id if self.session.jobs else None
        self._refresh_jobs_tree()
        self._refresh_job_details()
        self._auto_save_session()

    def _open_device_log_by_key(self, unique_key: str) -> None:
        job = self._get_selected_job()
        if not job:
            return
        res = next((r for r in job.results if r.host.unique_key == unique_key), None)
        if not res:
            return
        if res.log_path and Path(res.log_path).exists():
            open_path_in_os(res.log_path)
        else:
            dlg = DeviceLogDialog(self.root, res, dark_mode=self._is_dark())
            self.root.wait_window(dlg)

    def _open_selected_device_log(self) -> None:
        sel = self.job_devices_tree.selection()
        if sel:
            self._open_device_log_by_key(sel[0])

    def _open_selected_job_logs_folder(self) -> None:
        job = self._get_selected_job()
        if job and job.log_dir and Path(job.log_dir).exists():
            open_path_in_os(job.log_dir)

    def _poll_ui_queue(self) -> None:
        if not self.root.winfo_exists():
            return
        dirty = False
        try:
            while True:
                kind, payload = self.ui_queue.get_nowait()
                dirty = True
                if kind == "host_start":
                    job_id, host = payload
                    job = next((j for j in self.session.jobs if j.job_id == job_id), None)
                    if job:
                        for r in job.results:
                            if r.host.unique_key == host.unique_key:
                                r.status = "Running"
                                r.operation_result = _("Executing...")
                elif kind == "host_done":
                    job_id, res = payload
                    job = next((j for j in self.session.jobs if j.job_id == job_id), None)
                    if job:
                        for i, r in enumerate(job.results):
                            if r.host.unique_key == res.host.unique_key:
                                job.results[i] = res
                                break
                elif kind == "job_done":
                    job_id, run_dir, results = payload
                    self.running_jobs.pop(job_id, None)
                    job = next((j for j in self.session.jobs if j.job_id == job_id), None)
                    if job:
                        job.results = results
                        job.log_dir = str(run_dir)
                        job.end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        has_fail = any(r.status != "Success" for r in results)
                        job.status = "Failed" if has_fail else "Success"
                        self._auto_save_session()
        except queue.Empty:
            pass

        if dirty:
            self._refresh_jobs_tree()
            self._refresh_job_details()
        self.root.after(100, self._poll_ui_queue)

    # ------------------------------------------------------------------
    # Actions: Snippets
    # ------------------------------------------------------------------
    def _get_selected_snippet(self) -> Optional[Snippet]:
        sel = self.snippets_tree.selection()
        if not sel:
            return None
        idx = int(sel[0])
        if 0 <= idx < len(getattr(self, "_table_snippets", [])):
            return self._table_snippets[idx]
        return None

    def _new_snippet(self) -> None:
        dlg = SnippetEditorDialog(
            self.root,
            snippet=None,
            dark_mode=self._is_dark(),
            device_types=self._discovered_os_values(),
        )
        self.root.wait_window(dlg)
        if dlg.result:
            self.snippet_store.save_snippet(dlg.result)
            self._reload_snippets_data()
            self._refresh_all_views()

    def _edit_snippet_by_idx(self, idx: int) -> None:
        table = getattr(self, "_table_snippets", [])
        if not (0 <= idx < len(table)):
            return
        snip = table[idx]
        dlg = SnippetEditorDialog(
            self.root,
            snippet=snip,
            dark_mode=self._is_dark(),
            device_types=self._discovered_os_values(),
        )
        self.root.wait_window(dlg)
        if dlg.result:
            self.snippet_store.save_snippet(dlg.result)
            self._reload_snippets_data()
            self._refresh_all_views()

    def _edit_snippet(self) -> None:
        sel = self.snippets_tree.selection()
        if sel:
            self._edit_snippet_by_idx(int(sel[0]))

    def _delete_snippet_by_idx(self, idx: int, confirm: bool = True) -> None:
        table = getattr(self, "_table_snippets", [])
        if not (0 <= idx < len(table)):
            return
        snip = table[idx]
        if confirm and not messagebox.askyesno(
            _("Delete Snippet"),
            _("Delete snippet '{name}'?").format(name=snip.name),
        ):
            return
        self.snippet_store.delete_snippet(snip)
        self._reload_snippets_data()
        self._refresh_snippets_table()

    def _import_snippet_xml(self) -> None:
        path_str = filedialog.askopenfilename(
            title=_("Import Snippet XML"),
            filetypes=[(_("XML files"), "*.xml"), (_("All files"), "*.*")],
        )
        if not path_str:
            return
        try:
            imported = self.snippet_store.import_snippet(path_str)
            self._reload_snippets_data()
            self._refresh_snippets_table()
            messagebox.showinfo(
                _("Import"),
                _("Imported snippet '{name}'.").format(name=imported.name),
            )
        except Exception as exc:
            messagebox.showerror(_("Import Error"), str(exc))

    def _export_snippet_xml(self) -> None:
        snip = self._get_selected_snippet()
        if not snip:
            messagebox.showinfo(_("Export"), _("Select a snippet row to export."))
            return
        path_str = filedialog.asksaveasfilename(
            title=_("Export Snippet XML"),
            defaultextension=".xml",
            initialfile=f"{snip.name}.xml",
            filetypes=[(_("XML files"), "*.xml"), (_("All files"), "*.*")],
        )
        if not path_str:
            return
        self.snippet_store.export_snippet(snip, path_str)
        messagebox.showinfo(_("Export"), _("Exported to {path}").format(path=path_str))

    # ------------------------------------------------------------------
    # Actions: Devices
    # ------------------------------------------------------------------
    def _open_import_dialog(self) -> None:
        dlg = AirWaveImportDialog(self.root, self.settings)
        self.root.wait_window(dlg)
        if not dlg.imported_hosts:
            return
        existing_ips = {h.unique_key: i for i, h in enumerate(self.session.hosts)}
        for new_h in dlg.imported_hosts:
            if new_h.unique_key in existing_ips:
                self.session.hosts[existing_ips[new_h.unique_key]] = new_h
            else:
                self.session.hosts.append(new_h)
        self._refresh_devices_tree()
        self._auto_save_session()
        self._auto_save_settings()

    def _add_device_dialog(self) -> None:
        dlg = DeviceEditorDialog(
            self.root,
            existing_hosts=self.session.hosts,
            default_port=self.settings.ssh_port,
            device_types=self._discovered_os_values(),
        )
        self.root.wait_window(dlg)
        if not dlg.result:
            return
        replaced = False
        for i, h in enumerate(self.session.hosts):
            if h.unique_key == dlg.result.unique_key:
                self.session.hosts[i] = dlg.result
                replaced = True
                break
        if not replaced:
            self.session.hosts.append(dlg.result)
        self._refresh_devices_tree()
        self._auto_save_session()

    def _edit_device_by_idx(self, idx: int) -> None:
        if not (0 <= idx < len(self.session.hosts)):
            return
        dlg = DeviceEditorDialog(
            self.root,
            existing_hosts=self.session.hosts,
            host=self.session.hosts[idx],
            default_port=self.settings.ssh_port,
            device_types=self._discovered_os_values(),
        )
        self.root.wait_window(dlg)
        if dlg.result:
            self.session.hosts[idx] = dlg.result
            self._refresh_devices_tree()
            self._auto_save_session()

    def _edit_selected_device(self) -> None:
        sel = self.devices_tree.selection()
        if sel:
            self._edit_device_by_idx(int(sel[0]))

    def _remove_device_by_idx(self, idx: int, confirm: bool = True) -> None:
        if not (0 <= idx < len(self.session.hosts)):
            return
        dev = self.session.hosts[idx]
        if confirm and not messagebox.askyesno(
            _("Delete Device"),
            _("Remove device '{name}'?").format(name=dev.display_label),
        ):
            return
        self.session.hosts.pop(idx)
        self._refresh_devices_tree()
        self._auto_save_session()

    def _remove_selected_devices(self) -> None:
        sel = self.devices_tree.selection()
        if not sel:
            return
        indices = sorted({int(iid) for iid in sel}, reverse=True)
        for idx in indices:
            if 0 <= idx < len(self.session.hosts):
                self.session.hosts.pop(idx)
        self._refresh_devices_tree()
        self._auto_save_session()

    # ------------------------------------------------------------------
    # Actions: Device Models
    # ------------------------------------------------------------------
    def _new_model(self) -> None:
        dlg = DeviceModelEditorDialog(
            self.root,
            model=None,
            dark_mode=self._is_dark(),
            device_types=self._discovered_os_values(),
        )
        self.root.wait_window(dlg)
        if dlg.result:
            self.model_store.save_model(dlg.result)
            self._reload_models_data()
            self._refresh_all_views()

    def _edit_model_by_idx(self, idx: int) -> None:
        table = getattr(self, "_table_models", [])
        if not (0 <= idx < len(table)):
            return
        dlg = DeviceModelEditorDialog(
            self.root,
            model=table[idx],
            dark_mode=self._is_dark(),
            device_types=self._discovered_os_values(),
        )
        self.root.wait_window(dlg)
        if dlg.result:
            self.model_store.save_model(dlg.result)
            self._reload_models_data()
            self._refresh_all_views()

    def _edit_model(self) -> None:
        sel = self.models_tree.selection()
        if sel:
            self._edit_model_by_idx(int(sel[0]))

    def _delete_model_by_idx(self, idx: int, confirm: bool = True) -> None:
        table = getattr(self, "_table_models", [])
        if not (0 <= idx < len(table)):
            return
        mdl = table[idx]
        if confirm and not messagebox.askyesno(
            _("Delete Device Model"),
            _("Delete device model '{name}'?").format(name=mdl.name),
        ):
            return
        self.model_store.delete_model(mdl)
        self._reload_models_data()
        self._refresh_all_views()


def main() -> None:
    """Entry point launching the Sun-Valley-styled GUI."""
    root = tk.Tk()
    PsshApp(root)
    root.mainloop()
