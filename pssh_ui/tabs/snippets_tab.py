"""Snippets library tab mixin (CRUD, preview, XML Import/Export)."""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from pssh_ui.i18n import _
from pssh_ui.models import Snippet, SnippetSeverity, SnippetType
from pssh_ui.common import (
    TablePaginator,
    _attach_auto_scrollbars,
    _bind_tree_action_cursor,
    _is_all_filter,
    _snippet_type_label,
    apply_cli_syntax_highlighting,
    configure_editor_tags,
)
from pssh_ui.dialogs.snippet_dialog import SnippetEditorDialog


class SnippetsTabMixin:
    """Mixin encapsulating the Snippets library tab and row actions."""

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
        ttk.Button(hdr, text=_("Export Snippet"), command=self._export_snippet_xml).pack(
            side=tk.RIGHT, padx=(0, 6)
        )
        ttk.Button(hdr, text=_("Import Snippet"), command=self._import_snippet_xml).pack(
            side=tk.RIGHT, padx=(0, 6)
        )

        flt = ttk.Frame(card)
        flt.grid(row=1, column=0, columnspan=2, sticky=tk.EW, pady=(0, 6))
        flt.columnconfigure(1, weight=1)
        flt.columnconfigure(9, weight=1)

        self.snip_flt_name = tk.StringVar()
        self.snip_flt_type = tk.StringVar(value=_("All"))
        self.snip_flt_sev = tk.StringVar(value=_("All"))
        self.snip_flt_os = tk.StringVar(value=_("All"))
        self.snip_flt_desc = tk.StringVar()

        ttk.Label(flt, text=_("Name:")).grid(row=0, column=0, padx=(0, 4))
        e_sn = ttk.Entry(flt, textvariable=self.snip_flt_name, width=18)
        e_sn.grid(row=0, column=1, sticky=tk.EW, padx=(0, 8))
        e_sn.bind("<KeyRelease>", lambda _e: self._refresh_snippets_table(reset_page=True))

        self._snip_type_filter_map = {
            _("All"): "All",
            _snippet_type_label(SnippetType.CONFIG): SnippetType.CONFIG.value,
            _snippet_type_label(SnippetType.AUDIT): SnippetType.AUDIT.value,
        }
        ttk.Label(flt, text=_("Snippet Type:")).grid(row=0, column=2, padx=(0, 4))
        cb_st = ttk.Combobox(
            flt,
            textvariable=self.snip_flt_type,
            values=list(self._snip_type_filter_map.keys()),
            state="readonly",
            width=18,
        )
        cb_st.grid(row=0, column=3, padx=(0, 8))
        cb_st.bind("<<ComboboxSelected>>", lambda _e: self._refresh_snippets_table(reset_page=True))

        ttk.Label(flt, text=_("Severity:")).grid(row=0, column=4, padx=(0, 4))
        cb_sv = ttk.Combobox(
            flt,
            textvariable=self.snip_flt_sev,
            values=[_("All")] + [s.value for s in SnippetSeverity],
            state="readonly",
            width=10,
        )
        cb_sv.grid(row=0, column=5, padx=(0, 8))
        cb_sv.bind("<<ComboboxSelected>>", lambda _e: self._refresh_snippets_table(reset_page=True))

        ttk.Label(flt, text=_("Device Type:")).grid(row=0, column=6, padx=(0, 4))
        cb_sos = ttk.Combobox(
            flt,
            textvariable=self.snip_flt_os,
            values=[_("All"), *self._discovered_os_values()],
            state="readonly",
            width=12,
        )
        cb_sos.grid(row=0, column=7, padx=(0, 8))
        cb_sos.bind("<<ComboboxSelected>>", lambda _e: self._refresh_snippets_table(reset_page=True))

        ttk.Label(flt, text=_("Description:")).grid(row=0, column=8, padx=(0, 4))
        e_sd = ttk.Entry(flt, textvariable=self.snip_flt_desc, width=20)
        e_sd.grid(row=0, column=9, sticky=tk.EW)
        e_sd.bind("<KeyRelease>", lambda _e: self._refresh_snippets_table(reset_page=True))

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
        self.snippets_tree.grid(row=2, column=0, sticky=tk.NSEW)
        s_sb.grid(row=2, column=1, sticky=tk.NS)
        _attach_auto_scrollbars(self.snippets_tree, y_sb=s_sb)
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
        self.snippet_preview_text.grid(row=0, column=0, sticky=tk.NSEW)
        p_sb.grid(row=0, column=1, sticky=tk.NS)
        _attach_auto_scrollbars(self.snippet_preview_text, y_sb=p_sb)

        self.snippets_paginator = TablePaginator(
            card, lambda: self._refresh_snippets_table(reset_page=False), foreground=self._total_fg()
        )
        self.snippets_paginator.grid(row=4, column=0, columnspan=2, sticky=tk.EW, pady=(6, 0))
        self.snippets_footer_lbl = self.snippets_paginator.summary_lbl

    def _refresh_snippets_table(self, reset_page: bool = False) -> None:
        if reset_page:
            self.snippets_paginator.reset_page()
        name_q = self.snip_flt_name.get().strip().lower()
        type_q = self._snip_type_filter_map.get(self.snip_flt_type.get(), self.snip_flt_type.get())
        sev_q = self.snip_flt_sev.get()
        os_q = self.snip_flt_os.get()
        desc_q = self.snip_flt_desc.get().strip().lower()

        filtered = []
        for s in self.snippets:
            if name_q and name_q not in s.name.lower():
                continue
            if not _is_all_filter(type_q) and s.snippet_type.value != type_q:
                continue
            if not _is_all_filter(sev_q) and s.severity.value != sev_q:
                continue
            if not _is_all_filter(os_q) and s.device_type.value != os_q:
                continue
            if desc_q and desc_q not in (s.description or "").lower():
                continue
            filtered.append(s)

        self._table_snippets = filtered
        for item in self.snippets_tree.get_children():
            self.snippets_tree.delete(item)
        page_items = self.snippets_paginator.paginate(list(enumerate(filtered)))
        for idx, s in page_items:
            self.snippets_tree.insert(
                "",
                tk.END,
                iid=str(idx),
                values=(
                    s.name,
                    _snippet_type_label(s.snippet_type),
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
