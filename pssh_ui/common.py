"""Shared Sun-Valley styling, CLI highlighting, scrollbar, and tree widget helpers."""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, TypeVar

import sv_ttk

try:
    from PIL import Image, ImageDraw, ImageTk

    _HAS_PIL = True
except ImportError:  # pragma: no cover - fallback when Pillow unavailable
    _HAS_PIL = False

from pssh_ui.i18n import _, ngettext
from pssh_ui.models import SnippetType
from pssh_ui.variables import scan_dollar_brace_tokens

_T = TypeVar("_T")


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


def _make_step_ring_photo(
    master: tk.Misc, size: int, stroke_color: str, scale: int = 8
) -> Optional[Any]:
    """Render an anti-aliased circular outline badge via Pillow supersampling."""
    if not _HAS_PIL:
        return None
    hi = size * scale
    img = Image.new("RGBA", (hi, hi), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pad = int(round(2.5 * scale))
    stroke_w = max(scale, int(round(1.9 * scale)))
    draw.ellipse((pad, pad, hi - pad - 1, hi - pad - 1), outline=stroke_color, width=stroke_w)
    resized = img.resize((size, size), Image.Resampling.LANCZOS)
    return ImageTk.PhotoImage(resized, master=master)


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


def _snippet_type_label(st: SnippetType | str) -> str:
    """Return translated UI display label for a SnippetType enum or canonical string."""
    val = st.value if isinstance(st, SnippetType) else str(st)
    if val == SnippetType.CONFIG.value:
        return _("Config")
    if val == SnippetType.AUDIT.value:
        return _("Audit and Remediate")
    return _(val)


_OP_ERR_RE = re.compile(r"^(\d+)\s+errors?(?:\(s\))?\s+detected(?::\s*(.+))?$")
_OP_AUDIT_RE = re.compile(r"^Audit failed \((\d+)\s+RegEx patterns?(?:\(s\))?\s+not matched\)$")
_OP_DONE_RE = re.compile(r"^Completed \((\d+)\s+commands?\)$")
_OP_SKIP_OS_RE = re.compile(r"^Skipped \(no commands for (.+)\)$")


def _translate_error_reason(reason: str) -> str:
    """Translate canonical English CLI/audit diagnostic reasons for GUI display."""
    cleaned = (reason or "").strip()
    mapping = {
        "Invalid CLI input": _("Invalid CLI input"),
        "Invalid command or parameter": _("Invalid command or parameter"),
        "Ambiguous command": _("Ambiguous command"),
        "Incomplete command": _("Incomplete command"),
        "Unknown command": _("Unknown command"),
        "Execution error": _("Execution error"),
        "Target entity not found": _("Target entity not found"),
        "Authentication / Authorization failure": _("Authentication / Authorization failure"),
        "Command rejected by switch": _("Command rejected by switch"),
        "SSH communication error": _("SSH communication error"),
        "CLI error": _("CLI error"),
        "Expected audit RegEx not found in output": _("Expected audit RegEx not found in output"),
    }
    if cleaned in mapping:
        return mapping[cleaned]
    if cleaned.startswith("Invalid audit RegEx:"):
        detail = cleaned.split(":", 1)[1].strip()
        return _("Invalid audit RegEx: {err}").format(err=detail)
    return cleaned


def format_operation_result_ui(operation_result: str) -> str:
    """Format canonical English HostExecutionResult.operation_result for the active UI locale."""
    raw = (operation_result or "").strip()
    if not raw:
        return ""

    m_err = _OP_ERR_RE.match(raw)
    if m_err:
        count = int(m_err.group(1))
        prefix = ngettext("%d error detected", "%d errors detected", count) % count
        reason = (m_err.group(2) or "").strip()
        return f"{prefix}: {_translate_error_reason(reason)}" if reason else prefix

    m_aud = _OP_AUDIT_RE.match(raw)
    if m_aud:
        count = int(m_aud.group(1))
        return (
            ngettext(
                "Audit failed (%d RegEx pattern not matched)",
                "Audit failed (%d RegEx patterns not matched)",
                count,
            )
            % count
        )

    m_done = _OP_DONE_RE.match(raw)
    if m_done:
        count = int(m_done.group(1))
        return ngettext("Completed (%d command)", "Completed (%d commands)", count) % count

    m_skip = _OP_SKIP_OS_RE.match(raw)
    if m_skip:
        return _("Skipped (no commands for {os})").format(os=m_skip.group(1))

    fixed = {
        "Audit failed": _("Audit failed"),
        "Executing...": _("Executing..."),
        "Cancelled by operator": _("Cancelled by operator"),
        "Cancelled before start": _("Cancelled before start"),
        "Authentication failed": _("Authentication failed"),
        "SSH connection error": _("SSH connection error"),
        "Unexpected worker error": _("Unexpected worker error"),
    }
    return fixed.get(raw, raw)


def _is_all_filter(val: str) -> bool:
    """Return True if a filter dropdown value represents 'All' (canonical or translated)."""
    return (val or "").strip() in ("", "All", _("All"))


def _status_label(canonical: str) -> str:
    """Return localized display label for canonical device statuses ('Up', 'Down', 'Unknown')."""
    val = (canonical or "").strip()
    if val in ("Up", "Down", "Unknown"):
        return _(val)
    return val


def device_status_filter_map(include_unknown: bool = True) -> Dict[str, str]:
    """Return mapping of localized device status dropdown labels to canonical keys."""
    mapping = {
        _("All"): "All",
        _("Up"): "Up",
        _("Down"): "Down",
    }
    if include_unknown:
        mapping[_("Unknown")] = "Unknown"
    return mapping


def _canonical_device_status(val: str) -> str:
    """Normalize a localized or canonical status label to 'All', 'Up', 'Down', or 'Unknown'."""
    raw = (val or "").strip()
    if _is_all_filter(raw):
        return "All"
    for canonical in ("Up", "Down", "Unknown"):
        if raw.lower() in (canonical.lower(), _(canonical).lower()):
            return canonical
    return raw


def device_os_filter_map(os_values: Sequence[str]) -> Dict[str, str]:
    """Return mapping of localized OS filter labels to canonical SwitchOS values."""
    mapping: Dict[str, str] = {_("All"): "All"}
    for val in os_values:
        clean = (val or "").strip()
        if not clean:
            continue
        disp = _("Unknown") if clean == "Unknown" else clean
        if disp not in mapping:
            mapping[disp] = clean
    return mapping


def _canonical_os_filter(val: str) -> str:
    """Normalize a localized OS filter label ('All' or 'Unknown') to its canonical SwitchOS value."""
    raw = (val or "").strip()
    if _is_all_filter(raw):
        return "All"
    if raw.lower() in ("unknown", _("Unknown").lower()):
        return "Unknown"
    return raw


def filter_device_hosts(
    hosts: Sequence[Any],
    name_q: str = "",
    ip_q: str = "",
    os_q: str = "All",
    group_q: str = "",
    status_q: str = "All",
) -> Tuple[List[Tuple[int, Any]], List[Any]]:
    """Filter hosts by Device, IP, OS Type, Group, and Status, plus uncached status candidates."""
    n_q = (name_q or "").strip().lower()
    i_q = (ip_q or "").strip().lower()
    g_q = (group_q or "").strip().lower()
    canon_os = _canonical_os_filter(os_q)
    canon_st = _canonical_device_status(status_q)
    base_matched: List[Tuple[int, Any]] = []
    for idx, h in enumerate(hosts):
        if n_q and n_q not in h.name.lower():
            continue
        if i_q and i_q not in h.ip.lower():
            continue
        if canon_os != "All" and h.os_type.value != canon_os:
            continue
        if g_q and g_q not in (h.folder_path or "").lower():
            continue
        base_matched.append((idx, h))

    if canon_st == "All":
        return base_matched, []

    matched = [(idx, h) for idx, h in base_matched if h.ping_status == canon_st]
    uncached = (
        [h for _idx, h in base_matched if h.ping_status == "Unknown"]
        if canon_st != "Unknown"
        else []
    )
    return matched, uncached


def build_device_filter_bar(
    parent: tk.Misc,
    os_values: Sequence[str],
    on_change: Callable[[], None],
    device_var: tk.StringVar,
    ip_var: tk.StringVar,
    os_var: tk.StringVar,
    group_var: tk.StringVar,
    status_var: tk.StringVar,
) -> ttk.Frame:
    """Build the unified single-row (Device, IP Address, OS Type, Group, Status) filter bar."""
    flt = ttk.Frame(parent)
    flt.columnconfigure(1, weight=1)
    flt.columnconfigure(7, weight=1)

    ttk.Label(flt, text=_("Device:")).grid(row=0, column=0, padx=(0, 4))
    e_dev = ttk.Entry(flt, textvariable=device_var, width=15)
    e_dev.grid(row=0, column=1, sticky=tk.EW, padx=(0, 8))
    e_dev.bind("<KeyRelease>", lambda _e: on_change())

    ttk.Label(flt, text=_("IP Address:")).grid(row=0, column=2, padx=(0, 4))
    e_ip = ttk.Entry(flt, textvariable=ip_var, width=14)
    e_ip.grid(row=0, column=3, padx=(0, 8))
    e_ip.bind("<KeyRelease>", lambda _e: on_change())

    ttk.Label(flt, text=_("OS Type:")).grid(row=0, column=4, padx=(0, 4))
    os_choices = list(device_os_filter_map(os_values).keys())
    cb_os = ttk.Combobox(
        flt, textvariable=os_var, values=os_choices, state="readonly", width=13
    )
    cb_os.grid(row=0, column=5, padx=(0, 8))
    cb_os.bind("<<ComboboxSelected>>", lambda _e: on_change())

    ttk.Label(flt, text=_("Group:")).grid(row=0, column=6, padx=(0, 4))
    e_grp = ttk.Entry(flt, textvariable=group_var, width=15)
    e_grp.grid(row=0, column=7, sticky=tk.EW, padx=(0, 8))
    e_grp.bind("<KeyRelease>", lambda _e: on_change())

    ttk.Label(flt, text=_("Status:")).grid(row=0, column=8, padx=(0, 4))
    cb_st = ttk.Combobox(
        flt,
        textvariable=status_var,
        values=list(device_status_filter_map(include_unknown=True).keys()),
        state="readonly",
        width=13,
    )
    cb_st.grid(row=0, column=9)
    cb_st.bind("<<ComboboxSelected>>", lambda _e: on_change())
    return flt


def _attach_auto_scrollbars(
    widget: Any,
    y_sb: Optional[ttk.Scrollbar] = None,
    x_sb: Optional[ttk.Scrollbar] = None,
) -> Callable[[], None]:
    """Toggle grid scrollbars so they show only when content overflows the widget bounds."""

    def _sync(sb: ttk.Scrollbar, first: str, last: str) -> None:
        sb.set(first, last)
        # Skip grid activation while widget is still unlaid out at 1x1 pixels
        if widget.winfo_height() <= 2 or widget.winfo_width() <= 2:
            if sb.winfo_manager() == "grid":
                sb.grid_remove()
            return
        try:
            f_val = float(first)
            l_val = float(last)
            needs_sb = not (f_val <= 1e-6 and l_val >= 1.0 - 1e-6)
        except ValueError:
            needs_sb = False
        if needs_sb:
            if sb.winfo_manager() != "grid":
                sb.grid()
        else:
            if sb.winfo_manager() == "grid":
                sb.grid_remove()

    def _refresh_all(_event=None) -> None:
        if not widget.winfo_exists():
            return
        if y_sb is not None:
            f, last_val = widget.yview()
            _sync(y_sb, str(f), str(last_val))
        if x_sb is not None:
            f, last_val = widget.xview()
            _sync(x_sb, str(f), str(last_val))

    if y_sb is not None:
        y_sb.grid_remove()
        widget.configure(yscrollcommand=lambda f, l: _sync(y_sb, f, l))
    if x_sb is not None:
        x_sb.grid_remove()
        widget.configure(xscrollcommand=lambda f, l: _sync(x_sb, f, l))
    widget.bind("<Configure>", lambda _e: widget.after_idle(_refresh_all), add="+")
    widget.bind("<Map>", lambda _e: widget.after_idle(_refresh_all), add="+")
    return _refresh_all


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


class TablePaginator(ttk.Frame):
    """Reusable table footer providing record count summary and page navigation."""

    def __init__(
        self,
        parent: tk.Misc,
        on_page_change: Callable[[], None],
        default_size: int = 25,
        page_sizes: Tuple[int, ...] = (10, 25, 50, 100),
        foreground: Optional[str] = None,
        show_summary: bool = True,
    ) -> None:
        super().__init__(parent)
        self._on_page_change = on_page_change
        self.default_size = default_size
        self.current_page = 1
        self.total_pages = 1
        self.total_items = 0

        lbl_kwargs: Dict[str, Any] = {"text": ""}
        if foreground is not None:
            lbl_kwargs["foreground"] = foreground
        self.summary_lbl = ttk.Label(self, **lbl_kwargs)
        if show_summary:
            self.summary_lbl.pack(side=tk.LEFT)

        nav = ttk.Frame(self)
        nav.pack(side=tk.RIGHT)

        ttk.Label(nav, text=_("Rows:")).pack(side=tk.LEFT, padx=(0, 4))
        self.page_size_var = tk.StringVar(value=str(default_size))
        self.size_combo = ttk.Combobox(
            nav,
            textvariable=self.page_size_var,
            values=[str(s) for s in page_sizes],
            state="readonly",
            width=4,
        )
        self.size_combo.pack(side=tk.LEFT, padx=(0, 10))
        self.size_combo.bind("<<ComboboxSelected>>", self._on_size_changed)

        self.first_btn = ttk.Button(nav, text="|<", width=3, command=self.first_page)
        self.first_btn.pack(side=tk.LEFT, padx=(0, 2))
        self.prev_btn = ttk.Button(nav, text="<", width=3, command=self.prev_page)
        self.prev_btn.pack(side=tk.LEFT, padx=(0, 6))

        self.page_lbl = ttk.Label(nav, text="")
        self.page_lbl.pack(side=tk.LEFT, padx=(0, 6))

        self.next_btn = ttk.Button(nav, text=">", width=3, command=self.next_page)
        self.next_btn.pack(side=tk.LEFT, padx=(0, 2))
        self.last_btn = ttk.Button(nav, text=">|", width=3, command=self.last_page)
        self.last_btn.pack(side=tk.LEFT)

        self._update_controls()

    @property
    def page_size(self) -> int:
        """Return currently selected rows per page."""
        try:
            return max(1, int(self.page_size_var.get()))
        except ValueError:
            return self.default_size

    def reset_page(self) -> None:
        """Reset current page index back to page 1."""
        self.current_page = 1

    def first_page(self) -> None:
        if self.current_page != 1:
            self.current_page = 1
            self._on_page_change()

    def prev_page(self) -> None:
        if self.current_page > 1:
            self.current_page -= 1
            self._on_page_change()

    def next_page(self) -> None:
        if self.current_page < self.total_pages:
            self.current_page += 1
            self._on_page_change()

    def last_page(self) -> None:
        if self.current_page != self.total_pages:
            self.current_page = self.total_pages
            self._on_page_change()

    def _on_size_changed(self, _event=None) -> None:
        self.current_page = 1
        self._on_page_change()

    def _update_controls(self) -> None:
        self.page_lbl.configure(
            text=_("Page {cur} of {total}").format(
                cur=self.current_page, total=self.total_pages
            )
        )
        prev_state = tk.NORMAL if self.current_page > 1 else tk.DISABLED
        next_state = tk.NORMAL if self.current_page < self.total_pages else tk.DISABLED
        self.first_btn.configure(state=prev_state)
        self.prev_btn.configure(state=prev_state)
        self.next_btn.configure(state=next_state)
        self.last_btn.configure(state=next_state)

    def paginate(self, items: Sequence[_T]) -> List[_T]:
        """Slice items for the active page and refresh navigation controls."""
        size = self.page_size
        self.total_items = len(items)
        self.total_pages = max(1, (self.total_items + size - 1) // size)
        self.current_page = max(1, min(self.current_page, self.total_pages))
        self._update_controls()
        start = (self.current_page - 1) * size
        return list(items[start : start + size])
