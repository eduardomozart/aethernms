"""Resource, repository URL, and OS user-data path resolution (%APPDATA%\\aethernms and ~/.aethernms)."""

from __future__ import annotations

import configparser
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from typing import List, Optional

from aethernms import __repo_url__


PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent
APP_DIR_NAME = "aethernms"


def is_frozen() -> bool:
    """Return True when running inside a PyInstaller executable bundle."""
    return bool(getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"))


def bundle_root() -> Path:
    """Return base directory containing bundled read-only assets, snippets, and locales."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS"))
    return PROJECT_ROOT


def get_config_dir(
    platform_name: Optional[str] = None,
    home_dir: Optional[Path] = None,
) -> Path:
    """
    Return the OS user data/configuration directory for XML state, logs, and default snippets:
      - Windows: %APPDATA%\\aethernms
      - Linux / macOS: ~/.aethernms
    """
    plat = (platform_name or sys.platform).lower()
    home = home_dir or Path.home()

    if plat.startswith("win"):
        base_env = os.environ.get("APPDATA", "").strip()
        base = Path(base_env) if (base_env and home_dir is None) else (home / "AppData" / "Roaming")
        target = base / APP_DIR_NAME
    else:
        target = home / f".{APP_DIR_NAME}"

    target.mkdir(parents=True, exist_ok=True)
    return target


def runtime_root() -> Path:
    """Return writable user configuration directory (%APPDATA%\\aethernms or ~/.aethernms)."""
    return get_config_dir()


def get_assets_dir() -> Path:
    """Return path to bundled icon/image assets."""
    return bundle_root() / "assets"


def get_locales_dir() -> Path:
    """Return path to gettext locales directory."""
    return bundle_root() / "locales"


def get_templates_dir() -> Path:
    """Return path to Py4Web HTML templates directory."""
    bundled = bundle_root() / "aethernms" / "templates"
    if bundled.is_dir():
        return bundled
    return PACKAGE_DIR / "templates"


def get_static_dir() -> Path:
    """Return path to static CSS/JS assets directory."""
    bundled = bundle_root() / "aethernms" / "static"
    if bundled.is_dir():
        return bundled
    return PACKAGE_DIR / "static"


def bundled_snippets_dir() -> Path:
    """Return read-only bundled default snippets directory (repo root or PyInstaller _MEIPASS)."""
    return bundle_root() / "snippets"


def get_snippets_dir() -> Path:
    """Return legacy default snippets directory (%APPDATA%\\aethernms\\snippets or ~/.aethernms/snippets)."""
    return get_config_dir() / "snippets"


def get_db_path() -> Path:
    """Return SQLite database path inside %APPDATA%\\aethernms or ~/.aethernms."""
    return runtime_root() / "aethernms.db"


def _normalized_sha256(path: Path) -> str:
    """Hash file contents with normalized LF line endings so CRLF/LF differences stay transparent."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def seed_bundled_templates(
    source_dir: Path,
    target_dir: Path,
    manifest_name: str = ".seed_manifest.json",
) -> List[str]:
    """
    Synchronize bundled XML defaults into a user-writable target directory using SHA-256 tracking:
      - Newly added defaults are copied and recorded in .seed_manifest.json.
      - Unmodified local copies automatically receive upstream updates across upgrades.
      - Deleted built-in files remain deleted across restarts and upgrades.
      - User-edited files with upstream changes remain intact alongside a `.xml.new` sidecar.
    Returns relative POSIX paths that produced `.xml.new` conflict sidecars.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    if not source_dir.is_dir() or source_dir.resolve() == target_dir.resolve():
        return []

    manifest_path = target_dir / manifest_name
    manifest: dict[str, str] = {}
    if manifest_path.is_file():
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                manifest = {str(k): str(v) for k, v in loaded.items()}
        except Exception:
            manifest = {}

    sidecars: List[str] = []
    for src in sorted(source_dir.rglob("*.xml")):
        rel = src.relative_to(source_dir).as_posix()
        src_hash = _normalized_sha256(src)
        dest = target_dir / rel
        prev_hash = manifest.get(rel)

        if prev_hash is None:
            if not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
            manifest[rel] = src_hash
            continue

        if not dest.is_file():
            # Previously seeded file was intentionally deleted by the user; respect deletion.
            continue

        local_hash = _normalized_sha256(dest)
        if local_hash == src_hash:
            manifest[rel] = src_hash
        elif local_hash == prev_hash:
            # Unedited bundled file: safe to update cleanly.
            shutil.copy2(src, dest)
            manifest[rel] = src_hash
        elif src_hash != prev_hash:
            # User customized local copy AND bundled default changed in new release.
            sidecar = dest.with_name(dest.name + ".new")
            shutil.copy2(src, sidecar)
            manifest[rel] = src_hash
            sidecars.append(rel)

    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return sidecars


def get_settings_path() -> Path:
    """Return user settings.xml path inside %APPDATA%\\aethernms or ~/.aethernms."""
    return runtime_root() / "settings.xml"


def get_devices_path() -> Path:
    """Return user devices.xml path inside %APPDATA%\\aethernms or ~/.aethernms."""
    return runtime_root() / "devices.xml"


def get_jobs_path() -> Path:
    """Return user jobs.xml path inside %APPDATA%\\aethernms or ~/.aethernms."""
    return runtime_root() / "jobs.xml"


def get_session_path() -> Path:
    """Return legacy session.xml path inside %APPDATA%\\aethernms or ~/.aethernms."""
    return runtime_root() / "session.xml"


def get_logs_dir() -> Path:
    """Return user logs directory inside %APPDATA%\\aethernms\\logs or ~/.aethernms/logs."""
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
    when available, falling back to `aethernms.__repo_url__`.
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
