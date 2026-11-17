"""Cross-platform OS theme (Light/Dark) and UI language detection (Windows & macOS)."""

from __future__ import annotations

import ctypes
import locale
import os
import subprocess
import sys
from typing import Iterable, Optional


def detect_os_theme(platform_name: Optional[str] = None) -> str:
    """
    Detect the active operating system appearance theme ('dark' or 'light').
    Supports Windows (Registry AppsUseLightTheme), macOS (AppleInterfaceStyle),
    and GNOME/Linux fallback.
    """
    plat = (platform_name or sys.platform).lower()

    if plat.startswith("win"):
        try:
            import winreg

            key_path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                value, _reg_type = winreg.QueryValueEx(key, "AppsUseLightTheme")
                return "light" if int(value) == 1 else "dark"
        except Exception:
            return "light"

    if plat == "darwin":
        try:
            res = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            if res.returncode == 0 and "dark" in res.stdout.lower():
                return "dark"
            return "light"
        except Exception:
            return "light"

    # Linux / freedesktop fallback
    try:
        res = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if res.returncode == 0 and "dark" in res.stdout.lower():
            return "dark"
    except Exception:
        pass
    return "light"


def _raw_os_locale_candidates(platform_name: Optional[str] = None) -> list[str]:
    """Gather candidate locale strings ordered by OS preference."""
    plat = (platform_name or sys.platform).lower()
    candidates: list[str] = []

    if plat.startswith("win"):
        try:
            lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            win_loc = locale.windows_locale.get(lang_id)
            if win_loc:
                candidates.append(win_loc)
        except Exception:
            pass

    if plat == "darwin":
        try:
            res = subprocess.run(
                ["defaults", "read", "-g", "AppleLocale"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            if res.returncode == 0 and res.stdout.strip():
                candidates.append(res.stdout.strip())
        except Exception:
            pass
        try:
            res = subprocess.run(
                ["defaults", "read", "-g", "AppleLanguages"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            if res.returncode == 0:
                for token in res.stdout.replace('"', "").replace(",", "").split():
                    if token not in ("(", ")"):
                        candidates.append(token)
                        break
        except Exception:
            pass

    for env_key in ("LC_ALL", "LC_MESSAGES", "LANG"):
        val = os.environ.get(env_key, "").strip()
        if val:
            candidates.append(val)

    try:
        loc_code, _enc = locale.getlocale()
        if loc_code:
            candidates.append(loc_code)
    except Exception:
        pass

    return candidates


def match_supported_language(
    raw_locale: str,
    supported_langs: Iterable[str],
) -> Optional[str]:
    """Match a raw OS locale (e.g. 'pt_BR.UTF-8' or 'pt-BR') against supported catalog codes."""
    supported = list(supported_langs)
    if not raw_locale:
        return None

    cleaned = raw_locale.split(".", 1)[0].split("@", 1)[0].replace("-", "_").strip()
    if not cleaned:
        return None

    lower_map = {code.lower(): code for code in supported}
    if cleaned.lower() in lower_map:
        return lower_map[cleaned.lower()]

    base = cleaned.split("_", 1)[0].lower()
    if base in lower_map:
        return lower_map[base]

    # Match e.g. 'pt' or 'pt_PT' -> 'pt_BR' when 'pt_BR' is available
    for code in supported:
        if code.lower().startswith(base + "_"):
            return code

    return None


def detect_os_language(
    supported_langs: Optional[Iterable[str]] = None,
    platform_name: Optional[str] = None,
) -> str:
    """Detect the best matching UI language code from the OS locale settings."""
    langs = list(supported_langs) if supported_langs is not None else ["en", "pt_BR"]
    for raw in _raw_os_locale_candidates(platform_name=platform_name):
        matched = match_supported_language(raw, langs)
        if matched:
            return matched
    return "en" if "en" in langs else (langs[0] if langs else "en")
