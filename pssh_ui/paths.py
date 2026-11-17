"""Resource, repository URL, and OS user-config path resolution (%APPDATA%\\pssh-ui and ~/.config/pssh-ui)."""

from __future__ import annotations

import configparser
import os
from pathlib import Path
import sys
from typing import Optional

from pssh_ui import __repo_url__


PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent
APP_DIR_NAME = "pssh-ui"


def is_frozen() -> bool:
    """Return True when running inside a PyInstaller executable bundle."""
    return bool(getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"))


def bundle_root() -> Path:
    """Return base directory containing bundled read-only assets, snippets, and models."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS"))
    return PROJECT_ROOT


def get_config_dir(
    platform_name: Optional[str] = None,
    home_dir: Optional[Path] = None,
) -> Path:
    """
    Return the OS user configuration/data directory for user XML state & logs and create it if missing:
      - Windows: %APPDATA%\\pssh-ui
      - Linux / macOS: ~/.config/pssh-ui (respects $XDG_CONFIG_HOME when set)
    """
    plat = (platform_name or sys.platform).lower()
    home = home_dir or Path.home()

    if plat.startswith("win"):
        base_env = os.environ.get("APPDATA", "").strip()
        base = Path(base_env) if (base_env and home_dir is None) else (home / "AppData" / "Roaming")
    else:
        xdg_env = os.environ.get("XDG_CONFIG_HOME", "").strip()
        base = Path(xdg_env) if (xdg_env and home_dir is None) else (home / ".config")

    target = base / APP_DIR_NAME
    target.mkdir(parents=True, exist_ok=True)
    return target


def runtime_root() -> Path:
    """Return writable user configuration directory (%APPDATA%\\pssh-ui or ~/.config/pssh-ui)."""
    return get_config_dir()


def get_assets_dir() -> Path:
    """Return path to bundled icon/image assets."""
    return bundle_root() / "assets"


def get_locales_dir() -> Path:
    """Return path to gettext locales directory."""
    return bundle_root() / "locales"


def get_snippets_dir() -> Path:
    """Return path to snippets directory distributed with the application/executable."""
    return bundle_root() / "snippets"


def get_models_dir() -> Path:
    """Return path to device models directory distributed with the application/executable."""
    return bundle_root() / "model"


def get_external_snippets_dir() -> Optional[Path]:
    """When frozen, also allow drop-in user snippet XMLs beside the executable."""
    if is_frozen():
        return Path(sys.executable).resolve().parent / "snippets"
    return None


def get_external_models_dir() -> Optional[Path]:
    """When frozen, also allow drop-in user model XMLs beside the executable."""
    if is_frozen():
        return Path(sys.executable).resolve().parent / "model"
    return None


def get_settings_path() -> Path:
    """Return user settings.xml path inside %APPDATA%\\pssh-ui or ~/.config/pssh-ui."""
    return runtime_root() / "settings.xml"


def get_session_path() -> Path:
    """Return user session.xml path inside %APPDATA%\\pssh-ui or ~/.config/pssh-ui."""
    return runtime_root() / "session.xml"


def get_logs_dir() -> Path:
    """Return user logs directory inside %APPDATA%\\pssh-ui\\logs or ~/.config/pssh-ui/logs."""
    logs_dir = runtime_root() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def normalize_git_remote_url(raw_url: str) -> str:
    """Normalize git SSH/HTTPS remote URL into a clickable HTTPS web URL."""
    url = (raw_url or "").strip()
    if not url:
        return __repo_url__
    if url.startswith("git@") and ":" in url:
        host_part, _sep, repo_part = url[4:].partition(":")
        url = f"https://{host_part}/{repo_part}"
    elif url.startswith("ssh://git@"):
        remainder = url[len("ssh://git@"):]
        url = f"https://{remainder}"
    if url.endswith(".git"):
        url = url[:-4]
    return url.rstrip("/")


def get_repository_url(repo_root: Optional[Path] = None) -> str:
    """
    Extract the HTTPS repository URL from the repository's `.git/config` origin remote
    when available, falling back to `pssh_ui.__repo_url__`.
    """
    root = repo_root or PROJECT_ROOT
    git_cfg = root / ".git" / "config"
    if git_cfg.is_file():
        parser = configparser.RawConfigParser()
        try:
            parser.read(git_cfg, encoding="utf-8")
            if parser.has_option('remote "origin"', "url"):
                return normalize_git_remote_url(parser.get('remote "origin"', "url"))
        except Exception:
            pass
    return normalize_git_remote_url(__repo_url__)
