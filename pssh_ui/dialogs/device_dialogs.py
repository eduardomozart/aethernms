"""Device, Device Model, and Device Log viewer modal dialogs."""

from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk
from typing import List, Optional

from pssh_ui.airwave_importer import infer_switch_os
from pssh_ui.i18n import _
from pssh_ui.job_builder import get_assigned_groups, get_assigned_models
from pssh_ui.models import DeviceModel, HostEntry, HostExecutionResult, SwitchOS, parse_device_type
from pssh_ui.parser import detect_output_errors
from pssh_ui.common import (
    _attach_auto_scrollbars,
    _create_int_spinbox,
    apply_cli_syntax_highlighting,
    configure_editor_tags,
    open_path_in_os,
)


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
        text_box.grid(row=1, column=0, sticky=tk.NSEW)
        ysb.grid(row=1, column=1, sticky=tk.NS)
        xsb.grid(row=2, column=0, sticky=tk.EW)
        _attach_auto_scrollbars(text_box, y_sb=ysb, x_sb=xsb)

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
            ping_status=(
                self._existing.ping_status
                if (self._existing and self._existing.ip.strip() == ip)
                else "Unknown"
            ),
        )
        self.destroy()
