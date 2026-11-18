"""Add / Edit XML Snippet modal dialog."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import List, Optional

from pssh_ui.i18n import _
from pssh_ui.models import Snippet, SnippetSeverity, SnippetType, SwitchOS, parse_device_type
from pssh_ui.snippet_store import SnippetStore
from pssh_ui.common import (
    _attach_auto_scrollbars,
    _snippet_type_label,
    apply_cli_syntax_highlighting,
    configure_editor_tags,
)
from pssh_ui.variables import extract_variables


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
        self.geometry("800x660")
        self.minsize(720, 580)
        self.transient(parent)
        self.grab_set()

        container = ttk.Frame(self, padding=14)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(1, weight=1)
        container.rowconfigure(5, weight=1)
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
                text=_snippet_type_label(st),
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

        ttk.Label(container, text=_("Description")).grid(row=4, column=0, sticky=tk.W, pady=4)
        self.desc_var = tk.StringVar(value=snippet.description if snippet else "")
        self.desc_entry = ttk.Entry(container, textvariable=self.desc_var)
        self.desc_entry.grid(row=4, column=1, sticky=tk.EW, pady=4)

        ttk.Label(
            container,
            text=_('Commands *\n(! comments,\n${var|type|regex},\n${var|["A", "B"]})'),
        ).grid(row=5, column=0, sticky=tk.NW, pady=4)
        cmd_wrap = ttk.Frame(container)
        cmd_wrap.grid(row=5, column=1, sticky=tk.NSEW, pady=4)
        cmd_wrap.rowconfigure(0, weight=1)
        cmd_wrap.columnconfigure(0, weight=1)

        self.cmd_text = tk.Text(cmd_wrap, height=7, wrap=tk.NONE, font=("Consolas", 10), undo=True)
        configure_editor_tags(self.cmd_text, dark_mode=dark_mode)
        y_sb = ttk.Scrollbar(cmd_wrap, orient=tk.VERTICAL, command=self.cmd_text.yview)
        x_sb = ttk.Scrollbar(cmd_wrap, orient=tk.HORIZONTAL, command=self.cmd_text.xview)
        self.cmd_text.grid(row=0, column=0, sticky=tk.NSEW)
        y_sb.grid(row=0, column=1, sticky=tk.NS)
        x_sb.grid(row=1, column=0, sticky=tk.EW)
        _attach_auto_scrollbars(self.cmd_text, y_sb=y_sb, x_sb=x_sb)

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
            self.audit_regex_wrap, height=6, wrap=tk.NONE, font=("Consolas", 10), undo=True
        )
        configure_editor_tags(self.audit_regex_text, dark_mode=dark_mode)
        ar_ysb = ttk.Scrollbar(
            self.audit_regex_wrap, orient=tk.VERTICAL, command=self.audit_regex_text.yview
        )
        ar_xsb = ttk.Scrollbar(
            self.audit_regex_wrap, orient=tk.HORIZONTAL, command=self.audit_regex_text.xview
        )
        self.audit_regex_text.grid(row=0, column=0, sticky=tk.NSEW)
        ar_ysb.grid(row=0, column=1, sticky=tk.NS)
        ar_xsb.grid(row=1, column=0, sticky=tk.EW)
        _attach_auto_scrollbars(self.audit_regex_text, y_sb=ar_ysb, x_sb=ar_xsb)

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
            description=self.desc_var.get().strip(),
            commands=commands,
            audit_regex=audit_rx,
            created_at=self._existing.created_at if self._existing else "",
            file_path=self._existing.file_path if self._existing else None,
        )
        self.destroy()
