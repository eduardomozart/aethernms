"""Jobs tab UI, job execution orchestration, and live progress/details mixin."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Dict, List
import uuid

from pssh_ui.i18n import _
from pssh_ui.job_builder import build_commands_for_job, wrap_commands_with_model
from pssh_ui.model_store import ModelStore
from pssh_ui.models import (
    HostEntry,
    HostExecutionResult,
    JobRecord,
    ScheduleSequence,
    SnippetType,
)
from pssh_ui.parser import parse_commands
from pssh_ui.ssh_runner import BatchSSHExecutor
from pssh_ui.dialogs.add_job_dialog import AddJobDialog
from pssh_ui.common import (
    TablePaginator,
    _attach_auto_scrollbars,
    _bind_tree_action_cursor,
    _is_all_filter,
    _make_readonly_text,
    _snippet_type_label,
    configure_editor_tags,
    format_operation_result_ui,
    open_path_in_os,
)
from pssh_ui.dialogs.device_dialogs import DeviceLogDialog
from pssh_ui.variables import render_template


class JobsTabMixin:
    """Mixin encapsulating the Jobs list, Job Details pane, and SSH execution lifecycle."""

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
        self.job_flt_type = tk.StringVar(value=_("All"))
        self.job_flt_os = tk.StringVar(value=_("All"))
        self.job_flt_status = tk.StringVar(value=_("All"))

        ttk.Label(flt_row, text=_("Name:")).grid(row=0, column=0, padx=(0, 4))
        e_jname = ttk.Entry(flt_row, textvariable=self.job_flt_name, width=20)
        e_jname.grid(row=0, column=1, sticky=tk.EW, padx=(0, 10))
        e_jname.bind("<KeyRelease>", lambda _e: self._refresh_jobs_tree(reset_page=True))

        self._job_type_filter_map = {
            _("All"): "All",
            _snippet_type_label(SnippetType.CONFIG): SnippetType.CONFIG.value,
            _snippet_type_label(SnippetType.AUDIT): SnippetType.AUDIT.value,
        }
        ttk.Label(flt_row, text=_("Job Type:")).grid(row=0, column=2, padx=(0, 4))
        cb_jtype = ttk.Combobox(
            flt_row,
            textvariable=self.job_flt_type,
            values=list(self._job_type_filter_map.keys()),
            state="readonly",
            width=18,
        )
        cb_jtype.grid(row=0, column=3, padx=(0, 10))
        cb_jtype.bind("<<ComboboxSelected>>", lambda _e: self._refresh_jobs_tree(reset_page=True))

        ttk.Label(flt_row, text=_("Device Type:")).grid(row=0, column=4, padx=(0, 4))
        cb_jos = ttk.Combobox(
            flt_row,
            textvariable=self.job_flt_os,
            values=[_("All"), *self._discovered_os_values()],
            state="readonly",
            width=12,
        )
        cb_jos.grid(row=0, column=5, padx=(0, 10))
        cb_jos.bind("<<ComboboxSelected>>", lambda _e: self._refresh_jobs_tree(reset_page=True))

        self._job_status_filter_map = {
            _("All"): "All",
            _("Success"): "Success",
            _("Failed"): "Failed",
            _("Running"): "Running",
        }
        ttk.Label(flt_row, text=_("Status:")).grid(row=0, column=6, padx=(0, 4))
        cb_jst = ttk.Combobox(
            flt_row,
            textvariable=self.job_flt_status,
            values=list(self._job_status_filter_map.keys()),
            state="readonly",
            width=12,
        )
        cb_jst.grid(row=0, column=7)
        cb_jst.bind("<<ComboboxSelected>>", lambda _e: self._refresh_jobs_tree(reset_page=True))

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
        self.jobs_tree.grid(row=2, column=0, sticky=tk.NSEW)
        j_sb.grid(row=2, column=1, sticky=tk.NS)
        _attach_auto_scrollbars(self.jobs_tree, y_sb=j_sb)
        self.jobs_tree.bind("<<TreeviewSelect>>", self._on_job_selected)
        self.jobs_tree.bind("<Button-1>", self._on_jobs_tree_click)
        _bind_tree_action_cursor(self.jobs_tree, f"#{len(cols)}")

        self.jobs_paginator = TablePaginator(
            jobs_card, lambda: self._refresh_jobs_tree(reset_page=False), foreground=self._total_fg()
        )
        self.jobs_paginator.grid(row=3, column=0, columnspan=2, sticky=tk.EW, pady=(6, 0))
        self.jobs_footer_lbl = self.jobs_paginator.summary_lbl

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
        self.job_cmds_text.grid(row=0, column=0, sticky=tk.NSEW)
        jc_sb.grid(row=0, column=1, sticky=tk.NS)
        jc_xsb.grid(row=1, column=0, sticky=tk.EW)
        _attach_auto_scrollbars(self.job_cmds_text, y_sb=jc_sb, x_sb=jc_xsb)

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
        self.dev_flt_status = tk.StringVar(value=_("All"))

        ttk.Label(dev_flt, text=_("Device:")).pack(side=tk.LEFT, padx=(0, 4))
        e_dn = ttk.Entry(dev_flt, textvariable=self.dev_flt_name, width=18)
        e_dn.pack(side=tk.LEFT, padx=(0, 10))
        e_dn.bind("<KeyRelease>", lambda _e: self._refresh_job_details(reset_page=True))

        ttk.Label(dev_flt, text=_("IP Address:")).pack(side=tk.LEFT, padx=(0, 4))
        e_dip = ttk.Entry(dev_flt, textvariable=self.dev_flt_ip, width=16)
        e_dip.pack(side=tk.LEFT, padx=(0, 10))
        e_dip.bind("<KeyRelease>", lambda _e: self._refresh_job_details(reset_page=True))

        self._job_dev_status_filter_map = {
            _("All"): "All",
            _("Success"): "Success",
            _("Failed"): "Failed",
            _("Running"): "Running",
            _("Pending"): "Pending",
        }
        ttk.Label(dev_flt, text=_("Status:")).pack(side=tk.LEFT, padx=(0, 4))
        cb_dst = ttk.Combobox(
            dev_flt,
            textvariable=self.dev_flt_status,
            values=list(self._job_dev_status_filter_map.keys()),
            state="readonly",
            width=12,
        )
        cb_dst.pack(side=tk.LEFT)
        cb_dst.bind("<<ComboboxSelected>>", lambda _e: self._refresh_job_details(reset_page=True))

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
        self.job_devices_tree.grid(row=1, column=0, sticky=tk.NSEW)
        d_sb.grid(row=1, column=1, sticky=tk.NS)
        _attach_auto_scrollbars(self.job_devices_tree, y_sb=d_sb)
        self.job_devices_tree.bind("<Button-1>", self._on_job_devices_click)
        self.job_devices_tree.bind("<Double-1>", lambda _e: self._open_selected_device_log())
        _bind_tree_action_cursor(self.job_devices_tree, f"#{len(dcols)}")

        self.job_devices_paginator = TablePaginator(
            dev_tab, lambda: self._refresh_job_details(reset_page=False), foreground=self._total_fg()
        )
        self.job_devices_paginator.grid(row=2, column=0, columnspan=2, sticky=tk.EW, pady=(6, 0))
        self.job_devices_footer_lbl = self.job_devices_paginator.summary_lbl

    def _get_selected_job(self) -> Optional[JobRecord]:
        if not self.selected_job_id:
            return None
        return next((j for j in self.session.jobs if j.job_id == self.selected_job_id), None)

    def _refresh_jobs_tree(self, reset_page: bool = False) -> None:
        name_q = self.job_flt_name.get().strip().lower()
        type_q = self._job_type_filter_map.get(self.job_flt_type.get(), self.job_flt_type.get())
        os_q = self.job_flt_os.get()
        status_q = self._job_status_filter_map.get(
            self.job_flt_status.get(), self.job_flt_status.get()
        )

        if reset_page:
            self.jobs_paginator.reset_page()

        for item in self.jobs_tree.get_children():
            self.jobs_tree.delete(item)

        shown = []
        for job in self.session.jobs:
            if name_q and name_q not in job.name.lower():
                continue
            if not _is_all_filter(type_q) and job.job_type.value != type_q:
                continue
            if not _is_all_filter(os_q) and job.device_type.value != os_q:
                continue
            if not _is_all_filter(status_q) and job.status != status_q:
                continue
            shown.append(job)

        page_jobs = self.jobs_paginator.paginate(shown)
        for job in page_jobs:
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
                    _snippet_type_label(job.job_type),
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
        elif page_jobs and not any(j.job_id == self.selected_job_id for j in shown):
            self.selected_job_id = page_jobs[0].job_id
            self.jobs_tree.selection_set(self.selected_job_id)

        self.jobs_footer_lbl.configure(
            text=_("Total Records: {total}").format(total=len(shown))
        )

    def _on_job_selected(self, _event=None) -> None:
        sel = self.jobs_tree.selection()
        self.selected_job_id = sel[0] if sel else None
        self._refresh_job_details(reset_page=True)

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

    def _refresh_job_details(self, reset_page: bool = False) -> None:
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
            self.job_devices_paginator.reset_page()
            self.job_devices_paginator.paginate([])
            self.job_devices_footer_lbl.configure(text=_("Total Records: {total}").format(total=0))
            return

        if reset_page:
            self.job_devices_paginator.reset_page()

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
        st_q = self._job_dev_status_filter_map.get(
            self.dev_flt_status.get(), self.dev_flt_status.get()
        )

        matched_dev = []
        for res in job.results:
            if dev_q and dev_q not in res.host.display_label.lower():
                continue
            if ip_q and ip_q not in res.host.ip.lower():
                continue
            if not _is_all_filter(st_q) and res.status != st_q:
                continue
            matched_dev.append(res)

        page_dev = self.job_devices_paginator.paginate(matched_dev)
        for res in page_dev:
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
                    format_operation_result_ui(res.operation_result),
                    log_icon,
                ),
            )

        self.job_devices_footer_lbl.configure(
            text=_("Total Records: {total}").format(total=len(matched_dev))
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

    def _open_add_job_dialog(self) -> None:
        if hasattr(self, "_stop_devices_ping_timer"):
            self._stop_devices_ping_timer()
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
        if hasattr(self, "_refresh_devices_tree"):
            self._refresh_devices_tree(reset_page=False)
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
        if not self.root.winfo_exists() or (
            hasattr(self, "jobs_tree") and not self.jobs_tree.winfo_exists()
        ):
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
                                r.operation_result = "Executing..."
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
        if hasattr(self, "_poll_devices_ping_queue"):
            self._poll_devices_ping_queue()
        self.root.after(100, self._poll_ui_queue)
