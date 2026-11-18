"""About application information modal dialog."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Optional
import webbrowser

from pssh_ui import __app_name__, __version__
from pssh_ui.i18n import _
from pssh_ui.paths import get_assets_dir, get_repository_url


class AboutDialog(tk.Toplevel):
    """Information dialog displaying app icon, name, version, and clickable Git repository URL."""

    def __init__(self, parent: tk.Misc, dark_mode: bool = False) -> None:
        super().__init__(parent)
        self.title(_("About {app}").format(app=__app_name__))
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        frame = ttk.Frame(self, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)

        self.repo_url = get_repository_url()
        self._about_icon_img: Optional[tk.PhotoImage] = None
        about_png = get_assets_dir() / "pssh-ui-about.png"
        if about_png.is_file():
            try:
                self._about_icon_img = tk.PhotoImage(file=str(about_png))
                ttk.Label(frame, image=self._about_icon_img).pack(pady=(0, 10))
            except tk.TclError:
                pass

        ttk.Label(frame, text=f"{__app_name__}", font=("Segoe UI", 16, "bold")).pack()
        ttk.Label(
            frame,
            text=f"{__version__} — {_('Config & Audit Automation')}",
            foreground="#cbd5e1" if dark_mode else "#475569",
        ).pack(pady=(2, 12))

        ttk.Label(frame, text=_("Repository:")).pack()
        self.repo_link_lbl = ttk.Label(
            frame,
            text=self.repo_url,
            foreground="#60a5fa" if dark_mode else "#007fff",
            font=("Segoe UI", 10, "underline"),
            cursor="hand2",
        )
        self.repo_link_lbl.pack(pady=(2, 16))
        self.repo_link_lbl.bind("<Button-1>", lambda _e: webbrowser.open(self.repo_url))

        ttk.Button(frame, text=_("Close"), style="Accent.TButton", command=self.destroy).pack()
        self.update_idletasks()
        self.minsize(max(380, self.winfo_reqwidth() + 24), max(250, self.winfo_reqheight() + 12))
