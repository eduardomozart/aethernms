"""Global Preferences (Settings) modal dialog."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Dict, Optional

from pssh_ui.i18n import _, available_languages, get_language_label
from pssh_ui.models import AppSettings
from pssh_ui.common import _create_int_spinbox


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
