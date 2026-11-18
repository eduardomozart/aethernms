"""Devices inventory tab mixin (CRUD, filtering, and AirWave merge)."""

from __future__ import annotations

import queue
import tkinter as tk
from tkinter import messagebox, ttk
from typing import List

from pssh_ui.i18n import _
from pssh_ui.models import HostEntry, SwitchOS
from pssh_ui.dialogs.airwave_dialog import AirWaveImportDialog
from pssh_ui.common import (
    TablePaginator,
    _attach_auto_scrollbars,
    _canonical_device_status,
    _bind_tree_action_cursor,
    _status_label,
    attach_status_orb_column,
    build_device_filter_bar,
    filter_device_hosts,
)
from pssh_ui.dialogs.device_dialogs import DeviceEditorDialog


class DevicesTabMixin:
    """Mixin encapsulating the Devices table tab and AirWave device import."""

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

        self.dev_flt_dev = tk.StringVar()
        self.dev_flt_ip2 = tk.StringVar()
        self.dev_flt_os = tk.StringVar(value=_("All"))
        self.dev_flt_group = tk.StringVar()
        self.dev_flt_st2 = tk.StringVar(value=_("All"))
        self._uncached_status_candidates: List[HostEntry] = []

        flt = build_device_filter_bar(
            card,
            os_values=[*self._discovered_os_values(), SwitchOS.UNKNOWN.value],
            on_change=lambda: self._refresh_devices_tree(reset_page=True),
            device_var=self.dev_flt_dev,
            ip_var=self.dev_flt_ip2,
            os_var=self.dev_flt_os,
            group_var=self.dev_flt_group,
            status_var=self.dev_flt_st2,
        )
        flt.grid(row=1, column=0, columnspan=2, sticky=tk.EW, pady=(0, 6))

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
            "name": 175,
            "status": 120,
            "ip": 130,
            "os": 90,
            "model": 160,
            "folder": 170,
            "firmware": 120,
            "action": 80,
        }
        for col in cols:
            self.devices_tree.heading(col, text=h_heads[col])
            self.devices_tree.column(
                col, width=h_widths[col], anchor=tk.CENTER if col == "action" else tk.W
            )

        self._devices_orb_overlay = attach_status_orb_column(
            self.devices_tree, "status", dark_mode=self._is_dark()
        )
        h_sb = ttk.Scrollbar(card, orient=tk.VERTICAL, command=self.devices_tree.yview)
        self.devices_tree.grid(row=2, column=0, sticky=tk.NSEW)
        h_sb.grid(row=2, column=1, sticky=tk.NS)
        _attach_auto_scrollbars(
            self.devices_tree,
            y_sb=h_sb,
            on_y_scroll=self._devices_orb_overlay.schedule_refresh,
        )
        self.devices_tree.bind("<Button-1>", self._on_devices_tree_click)
        self.devices_tree.bind("<Double-1>", lambda _e: self._edit_selected_device())
        _bind_tree_action_cursor(self.devices_tree, f"#{len(cols)}")

        self.devices_paginator = TablePaginator(
            card,
            lambda: self._refresh_devices_tree(reset_page=False, trigger_ping=True),
            foreground=self._total_fg(),
        )
        self.devices_paginator.grid(row=3, column=0, columnspan=2, sticky=tk.EW, pady=(6, 0))
        self.devices_tab_footer_lbl = self.devices_paginator.summary_lbl

    def _is_devices_tab_active(self) -> bool:
        try:
            if not hasattr(self, "main_notebook") or not hasattr(self, "tab_devices"):
                return False
            if not self.root.winfo_exists():
                return False
            return (
                str(self.main_notebook.select()) == str(self.tab_devices)
                and self.root.grab_current() is None
            )
        except tk.TclError:
            return False

    def _stop_devices_ping_timer(self) -> None:
        if getattr(self, "_ping_timer_id", None) is not None:
            try:
                self.root.after_cancel(self._ping_timer_id)
            except tk.TclError:
                pass
            self._ping_timer_id = None
        if hasattr(self, "_ping_monitor"):
            self._ping_monitor.cancel_active()

    def _trigger_devices_ping_sweep(self) -> None:
        if getattr(self, "_ping_timer_id", None) is not None:
            try:
                self.root.after_cancel(self._ping_timer_id)
            except tk.TclError:
                pass
            self._ping_timer_id = None
        if not self._is_devices_tab_active():
            return
        targets = [(key, host.ip) for key, (_iid, host) in self._visible_device_rows.items()]
        targets.extend(
            (h.unique_key, h.ip)
            for h in getattr(self, "_uncached_status_candidates", [])
            if h.ping_status == "Unknown"
        )
        self._ping_monitor.start_sweep(targets)
        self._ping_timer_id = self.root.after(15000, self._trigger_devices_ping_sweep)

    def _poll_devices_ping_queue(self) -> None:
        if not hasattr(self, "_ping_queue") or not self.root.winfo_exists():
            return
        if hasattr(self, "devices_tree") and not self.devices_tree.winfo_exists():
            return
        updated = False
        needs_refilter = False
        active_sid = self._ping_monitor.sweep_id
        st_q = _canonical_device_status(
            self.dev_flt_st2.get() if hasattr(self, "dev_flt_st2") else "All"
        )
        filtering_status = st_q != "All"
        host_by_key = {h.unique_key: h for h in self.session.hosts}
        try:
            while True:
                kind, sid, key, payload = self._ping_queue.get_nowait()
                if kind == "ping_result" and sid == active_sid and key in host_by_key:
                    host = host_by_key[key]
                    old_status = host.ping_status
                    host.ping_status = str(payload)
                    if filtering_status and host.ping_status != old_status and (
                        host.ping_status == st_q or old_status == st_q
                    ):
                        needs_refilter = True
                    if key in self._visible_device_rows:
                        row_iid, _ = self._visible_device_rows[key]
                        if self.devices_tree.exists(row_iid):
                            self.devices_tree.set(row_iid, "status", _status_label(host.ping_status))
                        updated = True
        except queue.Empty:
            pass
        if needs_refilter:
            self._refresh_devices_tree(reset_page=False, trigger_ping=False)
        elif updated and hasattr(self, "_devices_orb_overlay"):
            self._devices_orb_overlay.schedule_refresh()

    def _refresh_devices_tree(
        self, reset_page: bool = False, trigger_ping: bool = True
    ) -> None:
        if reset_page:
            self.devices_paginator.reset_page()

        for item in self.devices_tree.get_children():
            self.devices_tree.delete(item)

        matched, self._uncached_status_candidates = filter_device_hosts(
            self.session.hosts,
            name_q=self.dev_flt_dev.get(),
            ip_q=self.dev_flt_ip2.get(),
            os_q=self.dev_flt_os.get(),
            group_q=self.dev_flt_group.get(),
            status_q=self.dev_flt_st2.get(),
        )

        page_items = self.devices_paginator.paginate(matched)
        self._visible_device_rows = {}
        for idx, h in page_items:
            row_iid = str(idx)
            self._visible_device_rows[h.unique_key] = (row_iid, h)
            self.devices_tree.insert(
                "",
                tk.END,
                iid=row_iid,
                values=(
                    h.name,
                    _status_label(h.ping_status),
                    h.ip,
                    h.os_type.value,
                    h.model,
                    h.folder_path,
                    h.firmware,
                    "✎   🗑",
                ),
            )
        self.devices_tab_footer_lbl.configure(
            text=_("Total Records: {total}").format(total=len(matched))
        )
        if hasattr(self, "_devices_orb_overlay"):
            self._devices_orb_overlay.schedule_refresh()
        if trigger_ping and self._is_devices_tab_active():
            self._trigger_devices_ping_sweep()

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

    def _merge_imported_hosts(self, imported_hosts: List[HostEntry]) -> None:
        """Update or add selected AirWave hosts while preserving unselected entries intact."""
        existing_ips = {h.unique_key: i for i, h in enumerate(self.session.hosts)}
        for new_h in imported_hosts:
            if new_h.unique_key in existing_ips:
                self.session.hosts[existing_ips[new_h.unique_key]] = new_h
            else:
                self.session.hosts.append(new_h)

    def _open_import_dialog(self) -> None:
        self._stop_devices_ping_timer()
        dlg = AirWaveImportDialog(
            self.root,
            self.settings,
            existing_hosts=self.session.hosts,
            dark_mode=self._is_dark(),
        )
        self.root.wait_window(dlg)
        if dlg.imported_hosts:
            self._merge_imported_hosts(dlg.imported_hosts)
            self._auto_save_session()
            self._auto_save_settings()
        self._refresh_devices_tree()

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
