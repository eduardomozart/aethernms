"""Dynamic Add Job wizard dialog (Command -> [Parameters] -> Devices -> Confirm)."""

from __future__ import annotations

import queue
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Dict, List, Optional

from pssh_ui.i18n import _, ngettext
from pssh_ui.job_builder import (
    build_commands_for_job,
    discover_device_types,
    validate_job_inputs,
)
from pssh_ui.model_store import ModelStore
from pssh_ui.models import (
    AppSettings,
    DeviceModel,
    HostEntry,
    JobRecord,
    ScheduleSequence,
    SessionData,
    Snippet,
    SnippetType,
    SwitchOS,
    parse_device_type,
)
from pssh_ui.parser import parse_commands
from pssh_ui.ping_checker import PingMonitor, probe_ips_concurrently
from pssh_ui.common import (
    TablePaginator,
    _attach_auto_scrollbars,
    _canonical_device_status,
    _create_int_spinbox,
    _make_step_ring_photo,
    _snippet_type_label,
    _status_label,
    apply_cli_syntax_highlighting,
    attach_status_orb_column,
    build_device_filter_bar,
    configure_editor_tags,
    filter_device_hosts,
)
from pssh_ui.variables import (
    extract_variables,
    render_template,
    validate_single_value,
    validate_variable_values,
)


class AddJobDialog(tk.Toplevel):
    """Dynamic Wizard: Config Command -> [Parameters if templated] -> Select Device -> Confirm."""

    STEP_COMMAND = "command"
    STEP_PARAMS = "params"
    STEP_DEVICES = "devices"
    STEP_CONFIRM = "confirm"

    def __init__(
        self,
        parent: tk.Misc,
        session: SessionData,
        snippets: List[Snippet],
        settings: Optional[AppSettings] = None,
        ssh_password: str = "",
        dark_mode: bool = False,
        device_models: Optional[List[DeviceModel]] = None,
        replay_job: Optional[JobRecord] = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self.settings = settings or AppSettings()
        self.snippets = snippets
        self.device_models = device_models if device_models is not None else ModelStore().load_all_models()
        self.dark_mode = dark_mode
        self._replay_job = replay_job
        self.launch_payload: Optional[Dict[str, Any]] = None
        self.current_step_key: str = self.STEP_COMMAND
        self._step_ring_cache: Dict[str, Any] = {}

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
        self._initial_saved_params: Dict[str, str] = {}
        self.param_values: Dict[str, str] = {}
        self.param_entry_vars: Dict[str, tk.StringVar] = {}
        self.param_status_labels: Dict[str, ttk.Label] = {}

        # Step 3 filter variables (matching Devices tab)
        self.col_flt_device = tk.StringVar()
        self.col_flt_ip = tk.StringVar()
        self.col_flt_os = tk.StringVar(value=_("All"))
        self.col_flt_group = tk.StringVar()
        self.col_flt_status = tk.StringVar(value=_("All"))

        self.filtered_hosts: List[HostEntry] = []
        self._page_hosts: List[HostEntry] = []
        self._step3_uncached_candidates: List[HostEntry] = []
        self._active_sweep_keys: set[str] = set()
        self._sweep_in_progress: bool = False
        # Never auto-select switches on Select Device
        self.selected_host_keys: set[str] = set()
        self._ping_queue: queue.Queue = queue.Queue()
        self._ping_monitor = PingMonitor(self._ping_queue)
        self._ping_timer_id: Optional[str] = None
        self._poll_ping_after_id: Optional[str] = None
        self.bind("<Destroy>", self._on_dialog_destroy, add="+")

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
        if replay_job is not None:
            self._apply_replay_job(replay_job)
        self._go_to_step_key(self.STEP_COMMAND)

    def _apply_replay_job(self, job: JobRecord) -> None:
        """Pre-fill Step 1-4 wizard fields from a previously saved JobRecord."""
        self.job_type_var.set(job.job_type.value)
        os_val = job.device_type.value
        if os_val and os_val not in self._os_choices:
            self._os_choices = [*self._os_choices, os_val]
            self.job_os_combo.configure(values=self._os_choices)
        if os_val:
            self.device_os_var.set(os_val)

        self._populate_snippets_for_os()
        self._toggle_audit_regex_field()

        self.job_name_var.set(job.name or "")
        self.job_desc_var.set(job.description or "")

        model_values = list(self.job_model_combo.cget("values"))
        if job.model_name and job.model_name in model_values:
            self.model_choice_var.set(job.model_name)

        if job.snippet_name and job.snippet_name in self._snippet_map:
            self.snippet_choice_var.set(job.snippet_name)
            self.snippet_desc_lbl.configure(
                text=self._snippet_map[job.snippet_name].description or ""
            )
        else:
            self.snippet_choice_var.set("")
            if self._snippet_map:
                self.snippet_desc_lbl.configure(text="")

        raw_cmds = job.commands_raw or job.commands_rendered or ""
        if raw_cmds:
            self.cmd_text.insert("1.0", raw_cmds)
            apply_cli_syntax_highlighting(self.cmd_text)

        if job.audit_regex:
            self.audit_regex_text.insert("1.0", job.audit_regex)
            apply_cli_syntax_highlighting(self.audit_regex_text)

        for k, v in (job.parameters_masked or {}).items():
            if v != "••••••••":
                self.param_values[k] = v
                self._initial_saved_params[k] = v

        result_keys = {res.host.unique_key for res in job.results if res.host}
        result_ips = {
            res.host.ip.strip() for res in job.results if res.host and res.host.ip.strip()
        }
        self.selected_host_keys = {
            h.unique_key
            for h in self.session.hosts
            if h.os_type == job.device_type
            and (h.unique_key in result_keys or h.ip.strip() in result_ips)
        }

        self.max_parallel_var.set(max(1, int(job.max_parallel or 10)))
        self.sequential_var.set(job.schedule_sequence == ScheduleSequence.SEQUENTIAL)
        self._on_seq_toggled()
        if job.results and job.results[0].host and job.results[0].host.port:
            try:
                self.ssh_port_var.set(int(job.results[0].host.port))
            except (ValueError, TypeError):
                pass

        active_model = self._get_active_model()
        write_cmd = (
            active_model.write_command.strip()
            if active_model and active_model.write_command.strip()
            else "write memory"
        )
        should_save_write = bool(getattr(job, "include_write", False)) or (
            job.job_type == SnippetType.CONFIG
            and bool(write_cmd)
            and (job.commands_rendered or "").strip().endswith(write_cmd)
            and not (job.commands_raw or "").strip().endswith(write_cmd)
        )
        self.save_write_var.set(should_save_write)
        self._refresh_stepper_header()

    @property
    def current_step(self) -> int:
        keys = self._active_step_keys()
        if self.current_step_key in keys:
            return keys.index(self.current_step_key)
        return 0

    def _has_template_variables(self) -> bool:
        return bool(extract_variables(self._get_all_template_text()))

    def _active_step_keys(self) -> List[str]:
        if self._has_template_variables():
            return [self.STEP_COMMAND, self.STEP_PARAMS, self.STEP_DEVICES, self.STEP_CONFIRM]
        return [self.STEP_COMMAND, self.STEP_DEVICES, self.STEP_CONFIRM]

    def _get_step_ring_image(self, stroke_color: str) -> Optional[Any]:
        if stroke_color not in self._step_ring_cache:
            self._step_ring_cache[stroke_color] = _make_step_ring_photo(
                self, 28, stroke_color, scale=8
            )
        return self._step_ring_cache[stroke_color]

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=16)
        outer.pack(fill=tk.BOTH, expand=True)
        outer.rowconfigure(1, weight=1)
        outer.columnconfigure(0, weight=1)

        # Top Stepper Bar (supersampled anti-aliased step circles, backwards-only click, dynamic Parameters)
        self.stepper_bar = ttk.Frame(outer)
        self.stepper_bar.grid(row=0, column=0, sticky=tk.EW, pady=(0, 12))
        self._step_defs = [
            (self.STEP_COMMAND, _("Config Command")),
            (self.STEP_PARAMS, _("Parameters")),
            (self.STEP_DEVICES, _("Select Device")),
            (self.STEP_CONFIRM, _("Confirm")),
        ]
        canvas_bg = ttk.Style(self).lookup("TFrame", "background") or (
            "#1c1c1c" if self.dark_mode else "#fafafa"
        )
        self._step_widgets: Dict[
            str, tuple[ttk.Frame, tk.Canvas, Optional[int], Optional[int], int, ttk.Label]
        ] = {}
        self.step_labels: List[ttk.Label] = []
        self.step_circles: List[tuple[tk.Canvas, Optional[int], int]] = []

        for step_idx, (step_key, text) in enumerate(self._step_defs):
            step_item = ttk.Frame(self.stepper_bar)
            circ = tk.Canvas(
                step_item, width=28, height=28, highlightthickness=0, bd=0, bg=canvas_bg
            )
            ring_img = self._get_step_ring_image("#94a3b8")
            img_id: Optional[int] = None
            oval_id: Optional[int] = None
            if ring_img is not None:
                img_id = circ.create_image(14, 14, image=ring_img)
            else:
                oval_id = circ.create_oval(2, 2, 26, 26, width=1.6, outline="#94a3b8")
            num_id = circ.create_text(
                14, 14, text=str(step_idx + 1), font=("Segoe UI", 9, "bold"), fill="#94a3b8"
            )
            circ.pack(side=tk.LEFT, padx=(0, 6))
            lbl = ttk.Label(step_item, text=text, font=("Segoe UI", 10))
            lbl.pack(side=tk.LEFT)
            circ.bind("<Button-1>", lambda _event, k=step_key: self._on_step_label_click(k))
            lbl.bind("<Button-1>", lambda _event, k=step_key: self._on_step_label_click(k))
            self._step_widgets[step_key] = (step_item, circ, img_id, oval_id, num_id, lbl)

        # Stage Container
        self.stage = ttk.Frame(outer)
        self.stage.grid(row=1, column=0, sticky=tk.NSEW)
        self.stage.rowconfigure(0, weight=1)
        self.stage.columnconfigure(0, weight=1)

        self.step_frames: Dict[str, ttk.Frame] = {
            key: ttk.Frame(self.stage)
            for key, _title in self._step_defs
        }
        for sf in self.step_frames.values():
            sf.grid(row=0, column=0, sticky=tk.NSEW)

        self._build_step1_config_command(self.step_frames[self.STEP_COMMAND])
        self._build_step2_parameters(self.step_frames[self.STEP_PARAMS])
        self._build_step3_select_device(self.step_frames[self.STEP_DEVICES])
        self._build_step4_confirm(self.step_frames[self.STEP_CONFIRM])

        # Bottom Navigation Bar (fixed two-column action layout preserves Back | Next/Run order)
        nav = ttk.Frame(outer)
        nav.grid(row=2, column=0, sticky=tk.EW, pady=(12, 0))
        ttk.Button(nav, text=_("Cancel"), command=self.destroy).pack(side=tk.LEFT)

        nav_actions = ttk.Frame(nav)
        nav_actions.pack(side=tk.RIGHT)

        self.back_btn = ttk.Button(nav_actions, text=_("< Back"), command=self._on_back)
        self.back_btn.grid(row=0, column=0, padx=(0, 8))

        self.next_btn = ttk.Button(
            nav_actions, text=_("Next >"), style="Accent.TButton", command=self._on_next
        )
        self.next_btn.grid(row=0, column=1)

        self.run_btn = ttk.Button(
            nav_actions, text=_("Run Job"), style="Accent.TButton", command=self._on_run
        )
        self.run_btn.grid(row=0, column=1)
        self.run_btn.grid_remove()

    # ---- Step 1: Config Command (Empty Job Name, Blank Snippet Default, Editable Commands + Audit RegEx) ----
    def _build_step1_config_command(self, parent: ttk.Frame) -> None:
        card = ttk.Frame(parent, style="Card.TFrame", padding=16)
        card.pack(fill=tk.BOTH, expand=True)
        card.columnconfigure(0, weight=1)
        card.rowconfigure(12, weight=1)
        card.rowconfigure(14, weight=1)

        ttk.Label(card, text=_("Job Type *"), font=("Segoe UI", 9, "bold")).grid(
            row=0, column=0, sticky=tk.W, pady=(0, 4)
        )
        jt_frame = ttk.Frame(card)
        jt_frame.grid(row=1, column=0, sticky=tk.W, pady=(0, 10))
        for st in SnippetType:
            ttk.Radiobutton(
                jt_frame,
                text=_snippet_type_label(st),
                variable=self.job_type_var,
                value=st.value,
                command=self._on_job_type_changed,
            ).pack(side=tk.LEFT, padx=(0, 18))

        ttk.Label(card, text=_("Job Name *"), font=("Segoe UI", 9, "bold")).grid(
            row=2, column=0, sticky=tk.W, pady=(0, 4)
        )
        ttk.Entry(card, textvariable=self.job_name_var).grid(row=3, column=0, sticky=tk.EW, pady=(0, 10))

        ttk.Label(card, text=_("Job Description"), font=("Segoe UI", 9, "bold")).grid(
            row=4, column=0, sticky=tk.W, pady=(0, 4)
        )
        self.job_desc_var = tk.StringVar()
        self.job_desc_entry = ttk.Entry(card, textvariable=self.job_desc_var)
        self.job_desc_entry.grid(row=5, column=0, sticky=tk.EW, pady=(0, 10))

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
        self.job_os_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_os_changed())

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

        self.cmd_text = tk.Text(cmd_wrap, wrap=tk.NONE, font=("Consolas", 10), undo=True, height=5)
        configure_editor_tags(self.cmd_text, dark_mode=self.dark_mode)
        c_ysb = ttk.Scrollbar(cmd_wrap, orient=tk.VERTICAL, command=self.cmd_text.yview)
        c_xsb = ttk.Scrollbar(cmd_wrap, orient=tk.HORIZONTAL, command=self.cmd_text.xview)
        self.cmd_text.grid(row=0, column=0, sticky=tk.NSEW)
        c_ysb.grid(row=0, column=1, sticky=tk.NS)
        c_xsb.grid(row=1, column=0, sticky=tk.EW)
        _attach_auto_scrollbars(self.cmd_text, y_sb=c_ysb, x_sb=c_xsb)
        self.cmd_text.bind("<KeyRelease>", lambda _e: self._on_step1_text_changed())

        self.audit_regex_lbl = ttk.Label(
            card, text=_("Audit Validation RegEx (1 pattern per line)"), font=("Segoe UI", 9, "bold")
        )
        self.audit_regex_lbl.grid(row=13, column=0, sticky=tk.W, pady=(0, 4))
        self.audit_regex_wrap = ttk.Frame(card)
        self.audit_regex_wrap.grid(row=14, column=0, sticky=tk.NSEW)
        self.audit_regex_wrap.rowconfigure(0, weight=1)
        self.audit_regex_wrap.columnconfigure(0, weight=1)

        self.audit_regex_text = tk.Text(
            self.audit_regex_wrap, wrap=tk.NONE, font=("Consolas", 10), undo=True, height=5
        )
        configure_editor_tags(self.audit_regex_text, dark_mode=self.dark_mode)
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
        self.audit_regex_text.bind("<KeyRelease>", lambda _e: self._on_step1_text_changed())
        self._toggle_audit_regex_field()

    def _close_snippet_dropdown(self) -> None:
        try:
            self.snippet_combo.tk.call("ttk::combobox::Unpost", self.snippet_combo._w)
        except tk.TclError:
            pass

    def _on_job_type_changed(self) -> None:
        self._close_snippet_dropdown()
        self._populate_snippets_for_os()
        self._toggle_audit_regex_field()
        self._refresh_stepper_header()

    def _on_os_changed(self) -> None:
        self._close_snippet_dropdown()
        self._populate_snippets_for_os()
        self._refresh_stepper_header()

    def _on_step1_text_changed(self) -> None:
        apply_cli_syntax_highlighting(self.cmd_text)
        apply_cli_syntax_highlighting(self.audit_regex_text)
        self._refresh_stepper_header()

    def _toggle_audit_regex_field(self) -> None:
        if self.job_type_var.get() == SnippetType.AUDIT.value:
            self.audit_regex_lbl.grid()
            self.audit_regex_wrap.grid()
        else:
            self.audit_regex_lbl.grid_remove()
            self.audit_regex_wrap.grid_remove()

    def _populate_snippets_for_os(self) -> None:
        target_os = self.device_os_var.get()
        target_type = self.job_type_var.get()

        # Populate matching Device Models for this Device Type
        matching_models = [m.name for m in self.device_models if m.device_type.value == target_os]
        self.job_model_combo.configure(values=matching_models)
        if matching_models:
            if self.model_choice_var.get() not in matching_models:
                self.model_choice_var.set(matching_models[0])
        else:
            self.model_choice_var.set("")

        matching = [
            s
            for s in self.snippets
            if s.device_type.value == target_os and s.snippet_type.value == target_type
        ]
        self._snippet_map = {s.name: s for s in matching}
        names = [s.name for s in matching]
        self.snippet_combo.configure(values=names)

        # Reset to blank selection so the operator explicitly picks a matching Snippet
        self.snippet_choice_var.set("")
        self.param_values.clear()
        self._initial_saved_params.clear()
        self.cmd_text.delete("1.0", tk.END)
        self.audit_regex_text.delete("1.0", tk.END)
        if names:
            self.snippet_desc_lbl.configure(text="")
        else:
            self.snippet_desc_lbl.configure(
                text=_("No {job_type} snippets available for {os}.").format(
                    job_type=_snippet_type_label(target_type), os=target_os
                )
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
        self._refresh_stepper_header()

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
        self.param_canvas.grid(row=1, column=0, sticky=tk.NSEW)
        p_sb.grid(row=1, column=1, sticky=tk.NS)
        self._refresh_param_scrollbars = _attach_auto_scrollbars(
            self.param_canvas, y_sb=p_sb
        )

        def _sync_param_region(_event=None) -> None:
            self.param_canvas.configure(scrollregion=self.param_canvas.bbox("all"))
            self._refresh_param_scrollbars()

        self.param_inner.bind("<Configure>", _sync_param_region)
        self.param_canvas.bind(
            "<Configure>",
            lambda e: (
                self.param_canvas.itemconfigure(self.param_canvas_win, width=e.width),
                self.param_canvas.after_idle(_sync_param_region),
            ),
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
            self.param_values[spec.name] = initial_val

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

        self.param_canvas.yview_moveto(0)
        if hasattr(self, "_refresh_param_scrollbars"):
            self.param_canvas.after_idle(
                lambda: (
                    self.param_canvas.configure(scrollregion=self.param_canvas.bbox("all")),
                    self._refresh_param_scrollbars(),
                )
            )

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

        flt = build_device_filter_bar(
            card,
            os_values=[*self._os_choices, SwitchOS.UNKNOWN.value],
            on_change=lambda: self._refresh_devices_table(reset_page=True),
            device_var=self.col_flt_device,
            ip_var=self.col_flt_ip,
            os_var=self.col_flt_os,
            group_var=self.col_flt_group,
            status_var=self.col_flt_status,
        )
        flt.grid(row=1, column=0, columnspan=2, sticky=tk.EW, pady=(0, 6))

        cols = ("sel", "device", "status", "ip", "os", "type", "group", "firmware")
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
            "group": _("Group"),
            "firmware": _("Firmware"),
        }
        widths = {
            "sel": 40,
            "device": 145,
            "status": 118,
            "ip": 115,
            "os": 75,
            "type": 135,
            "group": 160,
            "firmware": 115,
        }
        for col in cols:
            if col == "sel":
                self.device_tree.heading(col, text=headings[col], command=self._toggle_all_filtered)
            else:
                self.device_tree.heading(col, text=headings[col])
            self.device_tree.column(
                col, width=widths[col], anchor=tk.CENTER if col == "sel" else tk.W
            )

        self.device_tree.tag_configure("disabled_os", foreground="#94a3b8")
        self._step3_orb_overlay = attach_status_orb_column(
            self.device_tree, "status", dark_mode=self.dark_mode
        )

        d_sb = ttk.Scrollbar(card, orient=tk.VERTICAL, command=self.device_tree.yview)
        self.device_tree.grid(row=2, column=0, sticky=tk.NSEW)
        d_sb.grid(row=2, column=1, sticky=tk.NS)
        _attach_auto_scrollbars(
            self.device_tree,
            y_sb=d_sb,
            on_y_scroll=self._step3_orb_overlay.schedule_refresh,
        )
        self.device_tree.bind("<Button-1>", self._on_device_tree_click)

        total_fg = "#ffffff" if self.dark_mode else "#000000"
        self.devices_paginator = TablePaginator(
            card,
            lambda: self._refresh_devices_table(reset_page=False, trigger_ping=True),
            foreground=total_fg,
        )
        self.devices_paginator.grid(row=3, column=0, columnspan=2, sticky=tk.EW, pady=(6, 0))
        self.dev_count_lbl = self.devices_paginator.summary_lbl

    def _on_dialog_destroy(self, event: tk.Event) -> None:
        if event.widget is self:
            self._stop_step3_ping_timer()

    def _clear_column_filters(self) -> None:
        self.col_flt_device.set("")
        self.col_flt_ip.set("")
        self.col_flt_os.set(_("All"))
        self.col_flt_group.set("")
        self.col_flt_status.set(_("All"))
        self._refresh_devices_table(reset_page=True)

    def _target_os_enum(self):
        return parse_device_type(self.device_os_var.get(), SwitchOS.AOS_S)

    def _stop_step3_ping_timer(self) -> None:
        if getattr(self, "_ping_timer_id", None) is not None:
            try:
                self.after_cancel(self._ping_timer_id)
            except tk.TclError:
                pass
            self._ping_timer_id = None
        if getattr(self, "_poll_ping_after_id", None) is not None:
            try:
                self.after_cancel(self._poll_ping_after_id)
            except tk.TclError:
                pass
            self._poll_ping_after_id = None
        self._sweep_in_progress = False
        self._active_sweep_keys.clear()
        if hasattr(self, "_ping_monitor"):
            self._ping_monitor.cancel_active()

    def _trigger_step3_ping_sweep(self) -> None:
        if getattr(self, "_ping_timer_id", None) is not None:
            try:
                self.after_cancel(self._ping_timer_id)
            except tk.TclError:
                pass
            self._ping_timer_id = None
        if not self.winfo_exists() or self.current_step_key != self.STEP_DEVICES:
            return
        targets = [(h.unique_key, h.ip) for h in self._page_hosts]
        targets.extend(
            (h.unique_key, h.ip)
            for h in self.session.hosts
            if h.unique_key in self.selected_host_keys
        )
        targets.extend(
            (h.unique_key, h.ip)
            for h in self._step3_uncached_candidates
            if h.ping_status == "Unknown"
        )
        self._active_sweep_keys = {k for k, _ip in targets if k}
        self._sweep_in_progress = bool(self._active_sweep_keys)
        self._ping_monitor.start_sweep(targets)
        self._ping_timer_id = self.after(15000, self._trigger_step3_ping_sweep)
        if self._poll_ping_after_id is None:
            self._poll_ping_after_id = self.after(100, self._poll_step3_ping_queue)

    def _drain_step3_ping_queue(self) -> tuple[bool, bool]:
        updated = False
        needs_refilter = False
        active_sid = self._ping_monitor.sweep_id
        f_st = _canonical_device_status(self.col_flt_status.get())
        filtering_status = f_st != "All"
        host_by_key = {h.unique_key: h for h in self.session.hosts}
        try:
            while True:
                kind, sid, key, payload = self._ping_queue.get_nowait()
                if kind == "ping_sweep_done" and sid == active_sid:
                    self._sweep_in_progress = False
                elif kind == "ping_result" and sid == active_sid and key in host_by_key:
                    host = host_by_key[key]
                    old_status = host.ping_status
                    host.ping_status = str(payload)
                    if filtering_status and host.ping_status != old_status and (
                        host.ping_status == f_st or old_status == f_st
                    ):
                        needs_refilter = True
                    if self.device_tree.exists(key):
                        self.device_tree.set(key, "status", _status_label(host.ping_status))
                        updated = True
        except queue.Empty:
            pass
        return updated, needs_refilter

    def _poll_step3_ping_queue(self) -> None:
        self._poll_ping_after_id = None
        if not self.winfo_exists() or self.current_step_key != self.STEP_DEVICES:
            return
        updated, needs_refilter = self._drain_step3_ping_queue()
        if needs_refilter:
            self._refresh_devices_table(reset_page=False, trigger_ping=False)
        elif updated and hasattr(self, "_step3_orb_overlay"):
            self._step3_orb_overlay.schedule_refresh()
        self._poll_ping_after_id = self.after(100, self._poll_step3_ping_queue)

    def _resolve_unknown_hosts(self, hosts: List[HostEntry]) -> None:
        targets = [(h.unique_key, h.ip) for h in hosts if h.ping_status == "Unknown"]
        if not targets:
            return
        statuses = probe_ips_concurrently(targets)
        for h in hosts:
            if h.unique_key in statuses:
                h.ping_status = statuses[h.unique_key]
        self._refresh_devices_table(reset_page=False, trigger_ping=False)

    def _warn_offline_hosts(self, offline_hosts: List[HostEntry]) -> bool:
        if not offline_hosts:
            return True
        if len(offline_hosts) == 1:
            host = offline_hosts[0]
            msg = _(
                "Device '{name}' ({ip}) is currently Down (offline).\nDo you want to continue anyway?"
            ).format(name=host.display_label, ip=host.ip)
        else:
            max_listed = 10
            listed = [
                f"• {h.display_label} ({h.ip})" if (h.name and h.name.strip()) else f"• {h.ip}"
                for h in offline_hosts[:max_listed]
            ]
            extra = len(offline_hosts) - max_listed
            if extra > 0:
                listed.append(
                    ngettext("... and %d more device", "... and %d more devices", extra) % extra
                )
            header = (
                ngettext(
                    "%d selected device is currently Down (offline):",
                    "%d selected devices are currently Down (offline):",
                    len(offline_hosts),
                )
                % len(offline_hosts)
            )
            msg = (
                f"{header}\n\n"
                + "\n".join(listed)
                + "\n\n"
                + _("Do you want to continue anyway?")
            )
        return bool(
            messagebox.askokcancel(
                _("Offline Device"), msg, icon=messagebox.WARNING, parent=self
            )
        )

    def _refresh_devices_table(
        self, reset_page: bool = False, trigger_ping: bool = True
    ) -> None:
        if reset_page:
            self.devices_paginator.reset_page()
        target_os = self._target_os_enum()
        self.os_hint_lbl.configure(
            text=_("Snippet Target OS: {os}").format(os=target_os.value)
        )

        matched, self._step3_uncached_candidates = filter_device_hosts(
            self.session.hosts,
            name_q=self.col_flt_device.get(),
            ip_q=self.col_flt_ip.get(),
            os_q=self.col_flt_os.get(),
            group_q=self.col_flt_group.get(),
            status_q=self.col_flt_status.get(),
        )
        self.filtered_hosts = [h for _idx, h in matched]

        for item in self.device_tree.get_children():
            self.device_tree.delete(item)

        self._page_hosts = self.devices_paginator.paginate(self.filtered_hosts)
        for h in self._page_hosts:
            matches_os = h.os_type == target_os
            if matches_os and h.unique_key in self.selected_host_keys:
                mark = "☑"
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
                    _status_label(h.ping_status),
                    h.ip,
                    h.os_type.value,
                    h.model,
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
        if hasattr(self, "_step3_orb_overlay"):
            self._step3_orb_overlay.schedule_refresh()
        if trigger_ping and self.current_step_key == self.STEP_DEVICES:
            self._trigger_step3_ping_sweep()

    def _on_device_tree_click(self, event: tk.Event) -> None:
        region = self.device_tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        row_id = self.device_tree.identify_row(event.y)
        if not row_id:
            return
        host = next((h for h in self._page_hosts if h.unique_key == row_id), None)
        if not host or host.os_type != self._target_os_enum():
            return
        selecting = row_id not in self.selected_host_keys
        if selecting:
            self.selected_host_keys.add(row_id)
        else:
            self.selected_host_keys.remove(row_id)
        need_sweep = selecting and host.ping_status == "Unknown" and (
            not self._sweep_in_progress or row_id not in self._active_sweep_keys
        )
        self._refresh_devices_table(trigger_ping=need_sweep)

    def _set_all_filtered(self, select: bool) -> None:
        target_os = self._target_os_enum()
        newly_unknown = False
        for h in self.filtered_hosts:
            if h.os_type != target_os:
                continue
            if select:
                if (
                    h.unique_key not in self.selected_host_keys
                    and h.ping_status == "Unknown"
                    and (not self._sweep_in_progress or h.unique_key not in self._active_sweep_keys)
                ):
                    newly_unknown = True
                self.selected_host_keys.add(h.unique_key)
            else:
                self.selected_host_keys.discard(h.unique_key)
        self._refresh_devices_table(trigger_ping=select and newly_unknown)

    def _toggle_all_filtered(self) -> None:
        target_os = self._target_os_enum()
        eligible = [h for h in self.filtered_hosts if h.os_type == target_os]
        if not eligible:
            return
        all_selected = all(h.unique_key in self.selected_host_keys for h in eligible)
        self._set_all_filtered(not all_selected)

    # ---- Step 4: Confirm (Read-only resulting commands + SSH Credentials & Parallelism) ----
    def _build_step4_confirm(self, parent: ttk.Frame) -> None:
        card = ttk.Frame(parent, style="Card.TFrame", padding=16)
        card.pack(fill=tk.BOTH, expand=True)
        card.rowconfigure(3, weight=1)
        card.columnconfigure(0, weight=1)

        self.confirm_summary_lbl = ttk.Label(
            card, text="", font=("Segoe UI", 10, "bold"), justify=tk.LEFT
        )
        self.confirm_summary_lbl.grid(row=0, column=0, sticky=tk.EW, pady=(0, 8))
        card.bind(
            "<Configure>",
            lambda e: self.confirm_summary_lbl.configure(
                wraplength=max(320, e.width - 36)
            ),
        )

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
            text=_("Sequential (1 device at a time)"),
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
        self.confirm_cmds_text.grid(row=0, column=0, sticky=tk.NSEW)
        ysb.grid(row=0, column=1, sticky=tk.NS)
        xsb.grid(row=1, column=0, sticky=tk.EW)
        _attach_auto_scrollbars(self.confirm_cmds_text, y_sb=ysb, x_sb=xsb)

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

        for k, sv in self.param_entry_vars.items():
            self.param_values[k] = sv.get()

        rendered = render_template(self._get_raw_commands(), self.param_values)
        exec_cmds = parse_commands(rendered)

        sel_count = len(selected_hosts)
        sel_disp = (
            _("1 selected")
            if sel_count == 1
            else _("{count} selected").format(count=sel_count)
        )
        self.confirm_summary_lbl.configure(
            text=f"{_('Job Name')}: {self.job_name_var.get().strip()}  |  "
            f"{_('Snippet')}: {snip.name if snip else '-'}  |  "
            f"{_('Device Type')}: {target_os.value} ({sel_disp})"
        )

        self.confirm_cmds_text.configure(state=tk.NORMAL)
        self.confirm_cmds_text.delete("1.0", tk.END)
        self.confirm_cmds_text.insert(
            "1.0", "\n".join(exec_cmds) if exec_cmds else _("(No commands)")
        )
        apply_cli_syntax_highlighting(self.confirm_cmds_text)
        self.confirm_cmds_text.configure(state=tk.DISABLED)

    # ---- Stepper Transitions ----
    def _set_step_badge_style(
        self,
        circ: tk.Canvas,
        img_id: Optional[int],
        oval_id: Optional[int],
        num_id: int,
        step_num: int,
        color: str,
    ) -> None:
        circ.itemconfigure(num_id, text=str(step_num), fill=color)
        if img_id is not None:
            ring_img = self._get_step_ring_image(color)
            if ring_img is not None:
                circ.itemconfigure(img_id, image=ring_img)
        if oval_id is not None:
            circ.itemconfigure(oval_id, outline=color, fill="")

    def _refresh_stepper_header(self) -> None:
        keys = self._active_step_keys()
        if self.current_step_key not in keys:
            self.current_step_key = keys[0]
        cur_idx = keys.index(self.current_step_key)

        active_color = "#60cdff" if self.dark_mode else "#0067c0"
        done_color = "#4ade80" if self.dark_mode else "#15803d"
        idle_color = "#64748b" if self.dark_mode else "#94a3b8"
        idle_text = "#cbd5e1" if self.dark_mode else "#64748b"

        for item, _circ, _img_id, _oval_id, _num_id, _lbl in self._step_widgets.values():
            item.pack_forget()

        self.step_circles = []
        self.step_labels = []
        for pos, key in enumerate(keys):
            item, circ, img_id, oval_id, num_id, lbl = self._step_widgets[key]
            item.pack(side=tk.LEFT, padx=(0, 22))
            if pos == cur_idx:
                self._set_step_badge_style(circ, img_id, oval_id, num_id, pos + 1, active_color)
                circ.configure(cursor="")
                lbl.configure(font=("Segoe UI", 10, "bold"), foreground=active_color, cursor="")
            elif pos < cur_idx:
                self._set_step_badge_style(circ, img_id, oval_id, num_id, pos + 1, done_color)
                circ.configure(cursor="hand2")
                lbl.configure(font=("Segoe UI", 10), foreground=done_color, cursor="hand2")
            else:
                self._set_step_badge_style(circ, img_id, oval_id, num_id, pos + 1, idle_color)
                circ.configure(cursor="")
                lbl.configure(font=("Segoe UI", 10), foreground=idle_text, cursor="")
            self.step_circles.append((circ, img_id or oval_id, num_id))
            self.step_labels.append(lbl)

    def _on_step_label_click(self, step_or_idx: int | str) -> None:
        # Allow clicking ONLY on previous steps to go back; disallow advancing
        keys = self._active_step_keys()
        cur_idx = keys.index(self.current_step_key)
        if isinstance(step_or_idx, int):
            if 0 <= step_or_idx < len(keys):
                target_key = keys[step_or_idx]
            else:
                return
        else:
            if step_or_idx not in keys:
                return
            target_key = step_or_idx

        if keys.index(target_key) < cur_idx:
            self._go_to_step_key(target_key)

    def _go_to_step_key(self, step_key: str) -> None:
        keys = self._active_step_keys()
        if step_key not in keys:
            step_key = keys[min(len(keys) - 1, 1 if step_key == self.STEP_PARAMS else 0)]
        self.current_step_key = step_key
        self.step_frames[step_key].tkraise()
        self._refresh_stepper_header()

        cur_idx = keys.index(step_key)
        self.back_btn.configure(state=tk.NORMAL if cur_idx > 0 else tk.DISABLED)
        if step_key == self.STEP_CONFIRM:
            self.next_btn.grid_remove()
            self.run_btn.grid()
        else:
            self.run_btn.grid_remove()
            self.next_btn.grid()

        if step_key != self.STEP_DEVICES:
            self._stop_step3_ping_timer()

        if step_key == self.STEP_PARAMS:
            self._rebuild_parameters_form()
        elif step_key == self.STEP_DEVICES:
            self._refresh_devices_table(trigger_ping=True)
        elif step_key == self.STEP_CONFIRM:
            self._refresh_confirm_view()

    def _on_back(self) -> None:
        keys = self._active_step_keys()
        cur_idx = keys.index(self.current_step_key)
        self._go_to_step_key(keys[max(0, cur_idx - 1)])

    def _on_next(self) -> None:
        raw_commands = self._get_raw_commands()
        if self.current_step_key == self.STEP_COMMAND:
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
            if not self._has_template_variables():
                self.param_values.clear()
        elif self.current_step_key == self.STEP_PARAMS:
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
            self.param_values.update(vals)
        elif self.current_step_key == self.STEP_DEVICES:
            updated, needs_refilter = self._drain_step3_ping_queue()
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
            unknown_chosen = [h for h in chosen if h.ping_status == "Unknown"]
            if unknown_chosen:
                self._resolve_unknown_hosts(unknown_chosen)
            elif updated or needs_refilter:
                self._refresh_devices_table(reset_page=False, trigger_ping=False)
            offline_chosen = [h for h in chosen if h.ping_status == "Down"]
            if offline_chosen and not self._warn_offline_hosts(offline_chosen):
                return

        keys = self._active_step_keys()
        cur_idx = keys.index(self.current_step_key)
        self._go_to_step_key(keys[min(len(keys) - 1, cur_idx + 1)])

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

        for k, sv in self.param_entry_vars.items():
            self.param_values[k] = sv.get()

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
            "description": self.job_desc_var.get().strip(),
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
