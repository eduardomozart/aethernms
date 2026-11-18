"""AirWave inventory fetch and hierarchical filter import dialog."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Dict, List, Optional

from pssh_ui.airwave_importer import (
    build_folder_hierarchy_options,
    build_folder_options_from_hosts,
    fetch_airwave_inventory,
    host_matches_airwave_filter,
    parse_airwave_devices,
)
from pssh_ui.i18n import _
from pssh_ui.models import AirWaveFilter, AppSettings, HostEntry, SwitchOS, is_airwave_host
from pssh_ui.common import (
    TablePaginator,
    _attach_auto_scrollbars,
    _canonical_device_status,
    _is_all_filter,
    _status_label,
    device_status_filter_map,
)


class AirWaveImportDialog(tk.Toplevel):
    """Modal dialog to import and filter switch devices from AirWave."""

    def __init__(
        self,
        parent: tk.Misc,
        settings: AppSettings,
        existing_hosts: Optional[List[HostEntry]] = None,
        dark_mode: bool = False,
    ) -> None:
        super().__init__(parent)
        self.title(_("Import from AirWave"))
        self.geometry("980x640")
        self.transient(parent)
        self.grab_set()

        self.settings = settings
        self.dark_mode = dark_mode
        self.imported_hosts: Optional[List[HostEntry]] = None
        self.folders_cache: Dict[str, Dict[str, Any]] = {}
        self.raw_ap_xml: str = ""
        self.preview_hosts: List[HostEntry] = []
        self._existing_airwave_hosts: List[HostEntry] = [
            h for h in (existing_hosts or []) if is_airwave_host(h)
        ]
        self._all_fetched_hosts: Dict[str, HostEntry] = {
            h.unique_key: h for h in self._existing_airwave_hosts
        }
        self.checked_host_keys: set[str] = {
            h.unique_key for h in self._existing_airwave_hosts
        }
        self._folder_label_to_id: Dict[str, str] = {}
        self._fetch_queue: queue.Queue = queue.Queue()

        self.url_var = tk.StringVar(value=settings.airwave_url)
        self.user_var = tk.StringVar(value=settings.airwave_username)
        self.pass_var = tk.StringVar(value="")
        self.verify_ssl_var = tk.BooleanVar(value=settings.airwave_verify_ssl)

        # Always start unfiltered when opening the dialog (OS Type = All, no stale filters)
        self.folder_var = tk.StringVar(value=_("All"))
        self.name_var = tk.StringVar(value="")
        self.model_var = tk.StringVar(value="")
        self.os_var = tk.StringVar(value=_("All"))
        self.status_var = tk.StringVar(value=_("All"))
        self.ip_var = tk.StringVar(value="")
        self.state_lbl_var = tk.StringVar(
            value=_("Enter AirWave credentials and click Fetch Inventory.")
        )

        self._build_ui()
        if self._existing_airwave_hosts:
            options = build_folder_options_from_hosts(self._existing_airwave_hosts)
            self._folder_label_to_id = {label: path for label, path in options}
            self.folder_combo.configure(values=[_("All"), *(label for label, _path in options)])
            self._apply_filters()
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
        self.folder_combo.bind("<<ComboboxSelected>>", lambda _e: self._apply_filters())

        ttk.Label(flt_box, text=_("Name:")).grid(row=0, column=2, sticky=tk.W, padx=4, pady=3)
        e_aw_name = ttk.Entry(flt_box, textvariable=self.name_var)
        e_aw_name.grid(row=0, column=3, sticky=tk.EW, padx=4, pady=3)
        e_aw_name.bind("<KeyRelease>", lambda _e: self._apply_filters())

        ttk.Label(flt_box, text=_("Model:")).grid(row=0, column=4, sticky=tk.W, padx=4, pady=3)
        e_aw_model = ttk.Entry(flt_box, textvariable=self.model_var)
        e_aw_model.grid(row=0, column=5, sticky=tk.EW, padx=4, pady=3)
        e_aw_model.bind("<KeyRelease>", lambda _e: self._apply_filters())

        ttk.Label(flt_box, text=_("OS Type:")).grid(row=1, column=0, sticky=tk.W, padx=4, pady=3)
        self.os_combo = ttk.Combobox(
            flt_box,
            textvariable=self.os_var,
            values=[_("All"), SwitchOS.AOS_S.value, SwitchOS.AOS_CX.value],
            state="readonly",
        )
        self.os_combo.grid(row=1, column=1, sticky=tk.EW, padx=4, pady=3)
        self.os_combo.bind("<<ComboboxSelected>>", lambda _e: self._apply_filters())

        self._status_filter_map = device_status_filter_map(include_unknown=False)
        ttk.Label(flt_box, text=_("Status:")).grid(row=1, column=2, sticky=tk.W, padx=4, pady=3)
        self.status_combo = ttk.Combobox(
            flt_box,
            textvariable=self.status_var,
            values=list(self._status_filter_map.keys()),
            state="readonly",
        )
        self.status_combo.grid(row=1, column=3, sticky=tk.EW, padx=4, pady=3)
        self.status_combo.bind("<<ComboboxSelected>>", lambda _e: self._apply_filters())

        ttk.Label(flt_box, text=_("IP:")).grid(row=1, column=4, sticky=tk.W, padx=4, pady=3)
        e_aw_ip = ttk.Entry(flt_box, textvariable=self.ip_var)
        e_aw_ip.grid(row=1, column=5, sticky=tk.EW, padx=4, pady=3)
        e_aw_ip.bind("<KeyRelease>", lambda _e: self._apply_filters())

        opt_row = ttk.Frame(flt_box)
        opt_row.grid(row=2, column=0, columnspan=6, sticky=tk.EW, pady=(4, 0))
        ttk.Button(opt_row, text=_("Select All"), command=lambda: self._set_all_visible(True)).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(
            opt_row, text=_("Deselect All"), command=lambda: self._set_all_visible(False)
        ).pack(side=tk.LEFT)
        ttk.Button(opt_row, text=_("Apply Filters"), command=self._apply_filters).pack(
            side=tk.RIGHT
        )

        table_box = ttk.Frame(outer)
        table_box.grid(row=2, column=0, sticky=tk.NSEW)
        table_box.rowconfigure(0, weight=1)
        table_box.columnconfigure(0, weight=1)

        cols = ("sel", "name", "status", "ip", "os", "model", "folder", "firmware")
        self.tree = ttk.Treeview(table_box, columns=cols, show="headings", selectmode="browse")
        headings = {
            "sel": "☑",
            "name": _("Device"),
            "status": _("Status"),
            "ip": _("IP Address"),
            "os": _("OS Type"),
            "model": _("Model"),
            "folder": _("Folder"),
            "firmware": _("Firmware"),
        }
        widths = {
            "sel": 40,
            "name": 160,
            "status": 118,
            "ip": 115,
            "os": 75,
            "model": 150,
            "folder": 195,
            "firmware": 115,
        }
        for col in cols:
            if col == "sel":
                self.tree.heading(col, text=headings[col], command=self._toggle_all_visible)
                self.tree.column(col, width=widths[col], anchor=tk.CENTER, stretch=False)
            else:
                self.tree.heading(col, text=headings[col])
                self.tree.column(col, width=widths[col], anchor=tk.W)

        y_sb = ttk.Scrollbar(table_box, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.grid(row=0, column=0, sticky=tk.NSEW)
        y_sb.grid(row=0, column=1, sticky=tk.NS)
        _attach_auto_scrollbars(self.tree, y_sb=y_sb)
        self.tree.bind("<Button-1>", self._on_tree_click)

        self.paginator = TablePaginator(
            table_box, self._render_current_page, show_summary=False
        )
        self.paginator.grid(row=1, column=0, columnspan=2, sticky=tk.EW, pady=(6, 0))

        footer = ttk.Frame(outer)
        footer.grid(row=3, column=0, sticky=tk.EW, pady=(8, 0))
        ttk.Label(footer, textvariable=self.state_lbl_var).pack(side=tk.LEFT)
        ttk.Button(footer, text=_("Cancel"), command=self.destroy).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(
            footer,
            text=_("Import Highlighted"),
            style="Accent.TButton",
            command=self._accept,
        ).pack(side=tk.RIGHT, padx=4)

    def _build_filter(self) -> AirWaveFilter:
        chosen_raw = self.folder_var.get()
        if _is_all_filter(chosen_raw):
            chosen_folder = ""
        else:
            chosen_folder = self._folder_label_to_id.get(chosen_raw, chosen_raw.strip())

        raw_os = self.os_var.get().strip()
        raw_status = _canonical_device_status(self.status_var.get())
        return AirWaveFilter(
            folder=chosen_folder,
            category=self.settings.airwave_filters.category or "switch",
            name_filter=self.name_var.get().strip(),
            ip_filter=self.ip_var.get().strip(),
            model=self.model_var.get().strip(),
            os_filter="All" if _is_all_filter(raw_os) else raw_os,
            status_filter=raw_status,
            search_query="",
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

    def _on_inventory_loaded(self, folders: Dict[str, Dict[str, Any]], ap_xml: str) -> None:
        self.folders_cache = folders
        self.raw_ap_xml = ap_xml
        all_hosts, _total = parse_airwave_devices(
            ap_xml,
            folders=folders,
            filters=AirWaveFilter(
                category=self.settings.airwave_filters.category or "switch",
                include_stacked=False,
            ),
        )
        self._all_fetched_hosts = {h.unique_key: h for h in all_hosts}
        self.checked_host_keys &= set(self._all_fetched_hosts.keys())

        options = build_folder_hierarchy_options(self.folders_cache)
        self._folder_label_to_id = {label: fid for label, fid in options}
        values = [_("All"), *(label for label, _fid in options)]
        self.folder_combo.configure(values=values)

        cur_folder = self.folder_var.get()
        if _is_all_filter(cur_folder):
            self.folder_var.set(_("All"))
        elif cur_folder not in values:
            cur_norm = cur_folder.strip().lower()
            matched_lbl = next(
                (
                    lbl
                    for lbl, fid in options
                    if fid == cur_folder.strip() or lbl.strip().lower() == cur_norm
                ),
                _("All"),
            )
            self.folder_var.set(matched_lbl)

        self._apply_filters()

    def _poll_fetch_queue(self) -> None:
        if not self.winfo_exists():
            return
        try:
            while True:
                kind, payload = self._fetch_queue.get_nowait()
                self.fetch_btn.configure(state=tk.NORMAL)
                if kind == "ok":
                    folders, ap_xml = payload
                    self._on_inventory_loaded(folders, ap_xml)
                else:
                    self.state_lbl_var.set(_("Error: {msg}").format(msg=payload))
                    messagebox.showerror(_("Import Error"), str(payload), parent=self)
        except queue.Empty:
            pass
        self.after(100, self._poll_fetch_queue)

    def _refresh_state_label(self, matched: int, total: int) -> None:
        self.state_lbl_var.set(
            _("Matched {matched} switches out of {total} total records   |   Selected: {sel}").format(
                matched=matched,
                total=total,
                sel=len(self.checked_host_keys),
            )
        )

    def _apply_filters(self) -> None:
        flt = self._build_filter()
        if self.raw_ap_xml:
            hosts, total = parse_airwave_devices(
                self.raw_ap_xml,
                folders=self.folders_cache,
                filters=flt,
            )
        elif self._existing_airwave_hosts:
            hosts = [
                h
                for h in self._existing_airwave_hosts
                if host_matches_airwave_filter(h, flt)
            ]
            hosts.sort(key=lambda h: (h.name.lower(), h.ip))
            total = len(self._existing_airwave_hosts)
        else:
            return
        self.preview_hosts = hosts
        for h in hosts:
            self._all_fetched_hosts[h.unique_key] = h
        self._total_records = total
        self.paginator.reset_page()
        self._render_current_page()

    def _render_current_page(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        page_hosts = self.paginator.paginate(self.preview_hosts)
        for h in page_hosts:
            mark = "☑" if h.unique_key in self.checked_host_keys else "☐"
            self.tree.insert(
                "",
                tk.END,
                iid=h.unique_key,
                values=(
                    mark,
                    h.name,
                    _status_label(h.airwave_status),
                    h.ip,
                    h.os_type.value,
                    h.model,
                    h.folder_path,
                    h.firmware,
                ),
            )
        self._refresh_state_label(
            len(self.preview_hosts),
            getattr(self, "_total_records", len(self.preview_hosts)),
        )

    def _on_tree_click(self, event: tk.Event) -> Optional[str]:
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return None
        row_id = self.tree.identify_row(event.y)
        if not row_id:
            return None
        if row_id in self.checked_host_keys:
            self.checked_host_keys.remove(row_id)
            mark = "☐"
        else:
            self.checked_host_keys.add(row_id)
            mark = "☑"
        vals = list(self.tree.item(row_id, "values"))
        if vals:
            vals[0] = mark
            self.tree.item(row_id, values=vals)
        self._refresh_state_label(len(self.preview_hosts), getattr(self, "_total_records", len(self.preview_hosts)))
        return "break"

    def _set_all_visible(self, select: bool) -> None:
        # Applies across all filtered hosts across every page
        for h in self.preview_hosts:
            if select:
                self.checked_host_keys.add(h.unique_key)
            else:
                self.checked_host_keys.discard(h.unique_key)
        self._render_current_page()

    def _toggle_all_visible(self) -> None:
        if not self.preview_hosts:
            return
        all_checked = all(h.unique_key in self.checked_host_keys for h in self.preview_hosts)
        self._set_all_visible(not all_checked)

    def _accept(self) -> None:
        if not self._all_fetched_hosts and not self.preview_hosts:
            messagebox.showinfo(_("Import"), _("No devices available to import."), parent=self)
            return
        chosen = [
            self._all_fetched_hosts[k]
            for k in sorted(
                self.checked_host_keys,
                key=lambda key: (self._all_fetched_hosts[key].name.lower(), key)
                if key in self._all_fetched_hosts
                else ("", key),
            )
            if k in self._all_fetched_hosts
        ]
        if not chosen:
            messagebox.showwarning(
                _("Import"), _("Select at least one row to import."), parent=self
            )
            return

        self.settings.airwave_url = self.url_var.get().strip()
        self.settings.airwave_username = self.user_var.get().strip()
        self.settings.airwave_verify_ssl = bool(self.verify_ssl_var.get())
        self.settings.airwave_filters = AirWaveFilter(
            category=self.settings.airwave_filters.category or "switch"
        )
        self.imported_hosts = chosen
        self.destroy()
