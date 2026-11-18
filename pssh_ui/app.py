"""Main application window shell combining tabs, preferences, and session persistence."""

from __future__ import annotations

from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk
from typing import Any, Dict, List, Optional, Tuple

from pssh_ui import __app_name__, __version__
from pssh_ui.i18n import _, available_languages, set_language
from pssh_ui.job_builder import discover_device_types
from pssh_ui.model_store import ModelStore
from pssh_ui.models import AppSettings, DeviceModel, HostEntry, SessionData, Snippet
from pssh_ui.os_integration import detect_os_language, detect_os_theme
from pssh_ui.paths import get_assets_dir
from pssh_ui.ping_checker import PingMonitor
from pssh_ui.session_store import (
    DEFAULT_SESSION_PATH,
    load_session_xml,
    migrate_legacy_settings_from_session,
    save_session_xml,
)
from pssh_ui.settings_store import (
    DEFAULT_SETTINGS_PATH,
    load_settings_xml,
    save_settings_xml,
)
from pssh_ui.snippet_store import SnippetStore
from pssh_ui.dialogs.about_dialog import AboutDialog
from pssh_ui.common import apply_cli_syntax_highlighting, apply_sun_valley_theme
from pssh_ui.tabs.devices_tab import DevicesTabMixin
from pssh_ui.tabs.jobs_tab import JobsTabMixin
from pssh_ui.tabs.models_tab import ModelsTabMixin
from pssh_ui.dialogs.settings_dialog import SettingsDialog
from pssh_ui.tabs.snippets_tab import SnippetsTabMixin


class PsshApp(JobsTabMixin, SnippetsTabMixin, DevicesTabMixin, ModelsTabMixin):
    """Main application shell composing Jobs, Snippets, Devices, and Device Models tabs."""

    def __init__(
        self,
        root: tk.Tk,
        snippet_store: Optional[SnippetStore] = None,
        model_store: Optional[ModelStore] = None,
        session_path: Optional[Path | str] = None,
        settings_path: Optional[Path | str] = None,
        os_theme_override: Optional[str] = None,
        os_lang_override: Optional[str] = None,
    ) -> None:
        self.root = root
        self.snippet_store = snippet_store or SnippetStore()
        self.snippet_store.seed_defaults()
        self.snippet_store.ensure_default_folders()
        self.model_store = model_store or ModelStore()
        self.model_store.seed_defaults()
        self.session_path = Path(session_path) if session_path else DEFAULT_SESSION_PATH
        self.settings_path = Path(settings_path) if settings_path else DEFAULT_SETTINGS_PATH
        self._os_theme_override = os_theme_override
        self._os_lang_override = os_lang_override

        self.settings = self._load_initial_settings()
        self.session = self._load_initial_session()
        self._apply_effective_preferences()

        self.ssh_password: str = ""
        self.snippets: List[Snippet] = []
        self.device_models: List[DeviceModel] = []
        self.selected_job_id: Optional[str] = (
            self.session.jobs[0].job_id if self.session.jobs else None
        )
        self.active_tab_index: int = 0
        self.running_jobs: Dict[str, threading.Event] = {}
        self.ui_queue: queue.Queue = queue.Queue()
        self._ping_queue: queue.Queue = queue.Queue()
        self._ping_monitor = PingMonitor(self._ping_queue)
        self._ping_timer_id: Optional[str] = None
        self._visible_device_rows: Dict[str, Tuple[str, HostEntry]] = {}
        self._app_icon_img: Optional[tk.PhotoImage] = None
        self._header_logo_img: Optional[tk.PhotoImage] = None

        self._apply_window_icon()
        apply_sun_valley_theme(self.root, self.theme_mode)
        self._reload_snippets_data()
        self._reload_models_data()
        self._build_layout()
        self._refresh_all_views()
        self.root.after(100, self._poll_ui_queue)

    def _apply_window_icon(self) -> None:
        assets = get_assets_dir()
        ico_path = assets / "pssh-ui.ico"
        png_path = assets / "pssh-ui.png"
        if sys.platform.startswith("win") and ico_path.is_file():
            try:
                self.root.iconbitmap(default=str(ico_path))
                return
            except tk.TclError:
                pass
        if png_path.is_file():
            try:
                self._app_icon_img = tk.PhotoImage(file=str(png_path))
                self.root.iconphoto(True, self._app_icon_img)
            except tk.TclError:
                pass

    def _discovered_os_values(self) -> List[str]:
        return discover_device_types(self.device_models, self.snippets, self.session.hosts)

    def _load_initial_settings(self) -> AppSettings:
        if self.settings_path.is_file():
            try:
                return load_settings_xml(self.settings_path)
            except Exception:
                pass
        if self.session_path.is_file():
            migrated = migrate_legacy_settings_from_session(self.session_path)
            if migrated is not None:
                try:
                    save_settings_xml(migrated, self.settings_path)
                except Exception:
                    pass
                return migrated
        return AppSettings()

    def _load_initial_session(self) -> SessionData:
        if self.session_path.is_file():
            try:
                return load_session_xml(self.session_path)
            except Exception:
                pass
        return SessionData()

    def _apply_effective_preferences(self) -> None:
        mode = (self.settings.theme_mode or "auto").lower()
        if mode in ("light", "dark"):
            self.theme_mode = mode
        else:
            self.theme_mode = self._os_theme_override or detect_os_theme()

        langs = available_languages()
        saved_lang = self.settings.language or "auto"
        if saved_lang != "auto" and saved_lang in langs:
            effective_lang = saved_lang
        else:
            effective_lang = self._os_lang_override or detect_os_language(langs)
        set_language(effective_lang)

    def _auto_save_settings(self) -> None:
        try:
            save_settings_xml(self.settings, self.settings_path)
        except Exception:
            pass

    def _auto_save_session(self) -> None:
        try:
            save_session_xml(self.session, self.session_path)
        except Exception:
            pass

    def _is_dark(self) -> bool:
        return self.theme_mode == "dark"

    def _total_fg(self) -> str:
        """Return crisp black (light theme) or white (dark theme) for table record totals."""
        return "#ffffff" if self._is_dark() else "#000000"

    def _build_layout(self) -> None:
        self.root.title(f"{__app_name__} {__version__} — {_('Config & Audit Automation')}")
        self.root.geometry("1220x820")
        self.root.minsize(960, 640)

        self._stop_devices_ping_timer()
        for child in self.root.winfo_children():
            child.destroy()

        # Header Bar with app logo, title, Config & Audit Automation subtitle, Info button, and Cog button
        header = ttk.Frame(self.root, padding=(14, 10))
        header.pack(fill=tk.X)

        title_col = ttk.Frame(header)
        title_col.pack(side=tk.LEFT)
        header_png = get_assets_dir() / "pssh-ui-header.png"
        if header_png.is_file():
            try:
                self._header_logo_img = tk.PhotoImage(file=str(header_png))
                self.header_logo_lbl = ttk.Label(title_col, image=self._header_logo_img)
                self.header_logo_lbl.pack(side=tk.LEFT, padx=(0, 8))
            except tk.TclError:
                self.header_logo_lbl = None
        else:
            self.header_logo_lbl = None

        ttk.Label(title_col, text=f"{__app_name__}", font=("Segoe UI", 14, "bold")).pack(
            side=tk.LEFT
        )
        self.header_subtitle_lbl = ttk.Label(
            title_col,
            text="  |  " + _("Config & Audit Automation"),
            foreground="#cbd5e1" if self._is_dark() else "#64748b",
        )
        self.header_subtitle_lbl.pack(side=tk.LEFT, pady=(2, 0))

        right_ctrl = ttk.Frame(header)
        right_ctrl.pack(side=tk.RIGHT)

        self.about_btn = ttk.Button(
            right_ctrl,
            text="ⓘ",
            width=3,
            command=self._open_about_dialog,
        )
        self.about_btn.pack(side=tk.LEFT, padx=(0, 6))

        self.settings_btn = ttk.Button(
            right_ctrl,
            text="⚙",
            width=3,
            command=self._open_settings_dialog,
        )
        self.settings_btn.pack(side=tk.LEFT)

        # Primary 4 Tabs: Jobs (default), Snippets, Devices, Device Models
        self.main_notebook = ttk.Notebook(self.root)
        self.main_notebook.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))

        self.tab_jobs = ttk.Frame(self.main_notebook, padding=10)
        self.tab_snippets = ttk.Frame(self.main_notebook, padding=10)
        self.tab_devices = ttk.Frame(self.main_notebook, padding=10)
        self.tab_models = ttk.Frame(self.main_notebook, padding=10)

        self.main_notebook.add(self.tab_jobs, text=_("Jobs"))
        self.main_notebook.add(self.tab_snippets, text=_("Snippets"))
        self.main_notebook.add(self.tab_devices, text=_("Devices"))
        self.main_notebook.add(self.tab_models, text=_("Device Models"))

        self._build_jobs_tab()
        self._build_snippets_tab()
        self._build_devices_tab()
        self._build_models_tab()

        if 0 <= self.active_tab_index < 4:
            self.main_notebook.select(self.active_tab_index)
        self.main_notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

    def _on_tab_changed(self, _event=None) -> None:
        try:
            self.active_tab_index = self.main_notebook.index(self.main_notebook.select())
        except tk.TclError:
            pass
        if self._is_devices_tab_active():
            self._trigger_devices_ping_sweep()
        else:
            self._stop_devices_ping_timer()

    def _open_about_dialog(self) -> None:
        dlg = AboutDialog(self.root, dark_mode=self._is_dark())
        self.root.wait_window(dlg)

    def _open_settings_dialog(self) -> None:
        dlg = SettingsDialog(self.root, self.settings)
        self.root.wait_window(dlg)
        if not dlg.result:
            return
        self.settings = dlg.result
        self._apply_effective_preferences()
        apply_sun_valley_theme(self.root, self.theme_mode)
        self._build_layout()
        self._refresh_all_views()
        self._auto_save_settings()

    def _reload_snippets_data(self) -> None:
        self.snippets = self.snippet_store.load_all_snippets()

    def _reload_models_data(self) -> None:
        self.device_models = self.model_store.load_all_models()

    def _refresh_all_views(self) -> None:
        self._refresh_jobs_tree()
        self._refresh_job_details()
        self._refresh_snippets_table()
        self._refresh_devices_tree()
        self._refresh_models_table()

    def _set_readonly_text_content(
        self, widget: tk.Text, content: str, highlight_cli: bool = False
    ) -> None:
        widget.configure(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert("1.0", content)
        if highlight_cli:
            apply_cli_syntax_highlighting(widget)
        widget.configure(state=tk.DISABLED)


def main() -> None:
    """Entry point launching the Sun-Valley-styled GUI."""
    root = tk.Tk()
    PsshApp(root)
    root.mainloop()
