"""Device Models tab mixin (automation prompts, wrappers, XML Import/Export)."""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import List, Optional

from pssh_ui.i18n import _
from pssh_ui.models import DeviceModel
from pssh_ui.parser import parse_commands
from pssh_ui.common import (
    TablePaginator,
    _attach_auto_scrollbars,
    _bind_tree_action_cursor,
    _is_all_filter,
    _make_readonly_text,
)
from pssh_ui.dialogs.device_dialogs import DeviceModelEditorDialog


class ModelsTabMixin:
    """Mixin encapsulating the Device Models tab and row actions."""

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
        ttk.Button(hdr, text=_("Export Device Model"), command=self._export_model_xml).pack(
            side=tk.RIGHT, padx=(0, 6)
        )
        ttk.Button(hdr, text=_("Import Device Model"), command=self._import_model_xml).pack(
            side=tk.RIGHT, padx=(0, 6)
        )

        flt = ttk.Frame(card)
        flt.grid(row=1, column=0, columnspan=2, sticky=tk.EW, pady=(0, 6))
        flt.columnconfigure(1, weight=1)

        self.mdl_flt_name = tk.StringVar()
        self.mdl_flt_os = tk.StringVar(value=_("All"))

        ttk.Label(flt, text=_("Name:")).grid(row=0, column=0, padx=(0, 4))
        e_mn = ttk.Entry(flt, textvariable=self.mdl_flt_name, width=22)
        e_mn.grid(row=0, column=1, sticky=tk.EW, padx=(0, 10))
        e_mn.bind("<KeyRelease>", lambda _e: self._refresh_models_table(reset_page=True))

        ttk.Label(flt, text=_("Switch OS:")).grid(row=0, column=2, padx=(0, 4))
        cb_mos = ttk.Combobox(
            flt,
            textvariable=self.mdl_flt_os,
            values=[_("All"), *self._discovered_os_values()],
            state="readonly",
            width=14,
        )
        cb_mos.grid(row=0, column=3)
        cb_mos.bind("<<ComboboxSelected>>", lambda _e: self._refresh_models_table(reset_page=True))

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
        self.models_tree.grid(row=2, column=0, sticky=tk.NSEW)
        m_sb.grid(row=2, column=1, sticky=tk.NS)
        _attach_auto_scrollbars(self.models_tree, y_sb=m_sb)
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
        self.model_preview_text.grid(row=0, column=0, sticky=tk.NSEW)
        mp_sb.grid(row=0, column=1, sticky=tk.NS)
        _attach_auto_scrollbars(self.model_preview_text, y_sb=mp_sb)

        self.models_paginator = TablePaginator(
            card, lambda: self._refresh_models_table(reset_page=False), foreground=self._total_fg()
        )
        self.models_paginator.grid(row=4, column=0, columnspan=2, sticky=tk.EW, pady=(6, 0))
        self.models_footer_lbl = self.models_paginator.summary_lbl

    def _refresh_models_table(self, reset_page: bool = False) -> None:
        if reset_page:
            self.models_paginator.reset_page()
        name_q = self.mdl_flt_name.get().strip().lower()
        os_q = self.mdl_flt_os.get()

        filtered: List[DeviceModel] = []
        for m in self.device_models:
            if name_q and name_q not in m.name.lower() and name_q not in m.vendor.lower():
                continue
            if not _is_all_filter(os_q) and m.device_type.value != os_q:
                continue
            filtered.append(m)

        self._table_models = filtered
        for item in self.models_tree.get_children():
            self.models_tree.delete(item)
        page_items = self.models_paginator.paginate(list(enumerate(filtered)))
        for idx, m in page_items:
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

    def _get_selected_model(self) -> Optional[DeviceModel]:
        sel = self.models_tree.selection()
        if not sel:
            return None
        idx = int(sel[0])
        if 0 <= idx < len(getattr(self, "_table_models", [])):
            return self._table_models[idx]
        return None

    def _import_model_xml(self) -> None:
        path_str = filedialog.askopenfilename(
            title=_("Import Device Model"),
            filetypes=[(_("XML files"), "*.xml"), (_("All files"), "*.*")],
        )
        if not path_str:
            return
        try:
            imported = self.model_store.import_model(path_str)
            self._reload_models_data()
            self._refresh_all_views()
            messagebox.showinfo(
                _("Import"),
                _("Imported device model '{name}'.").format(name=imported.name),
            )
        except Exception as exc:
            messagebox.showerror(_("Import Error"), str(exc))

    def _export_model_xml(self) -> None:
        mdl = self._get_selected_model()
        if not mdl:
            messagebox.showinfo(_("Export"), _("Select a device model row to export."))
            return
        path_str = filedialog.asksaveasfilename(
            title=_("Export Device Model"),
            defaultextension=".xml",
            initialfile=f"{mdl.name}.xml",
            filetypes=[(_("XML files"), "*.xml"), (_("All files"), "*.*")],
        )
        if not path_str:
            return
        self.model_store.export_model(mdl, path_str)
        messagebox.showinfo(_("Export"), _("Exported to {path}").format(path=path_str))

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
