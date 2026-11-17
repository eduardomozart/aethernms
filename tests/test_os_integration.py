"""Tests for cross-platform OS theme and language detection (Windows & macOS)."""

import sys
import types

from pssh_ui.os_integration import (
    detect_os_language,
    detect_os_theme,
    match_supported_language,
)


def test_detect_os_theme_windows_and_macos(monkeypatch):
    # Mock macOS dark and light
    class FakeProc:
        def __init__(self, rc, stdout):
            self.returncode = rc
            self.stdout = stdout

    monkeypatch.setattr(
        "pssh_ui.os_integration.subprocess.run",
        lambda *a, **kw: FakeProc(0, "Dark\n"),
    )
    assert detect_os_theme(platform_name="darwin") == "dark"

    monkeypatch.setattr(
        "pssh_ui.os_integration.subprocess.run",
        lambda *a, **kw: FakeProc(1, ""),
    )
    assert detect_os_theme(platform_name="darwin") == "light"

    # Mock Windows registry AppsUseLightTheme = 0 (dark) and 1 (light)
    class FakeKey:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    fake_winreg = types.SimpleNamespace(
        HKEY_CURRENT_USER=object(),
        OpenKey=lambda *_a: FakeKey(),
        QueryValueEx=lambda *_a: (0, 4),
    )
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)
    assert detect_os_theme(platform_name="win32") == "dark"

    fake_winreg.QueryValueEx = lambda *_a: (1, 4)
    assert detect_os_theme(platform_name="win32") == "light"


def test_match_supported_language_and_detect_os_language(monkeypatch):
    supported = ["en", "pt_BR"]
    assert match_supported_language("pt_BR.UTF-8", supported) == "pt_BR"
    assert match_supported_language("pt-BR", supported) == "pt_BR"
    assert match_supported_language("pt_PT", supported) == "pt_BR"
    assert match_supported_language("en_US.UTF-8", supported) == "en"
    assert match_supported_language("fr_FR", supported) is None

    monkeypatch.setattr(
        "pssh_ui.os_integration._raw_os_locale_candidates",
        lambda platform_name=None: ["pt_BR.UTF-8"],
    )
    assert detect_os_language(supported, platform_name="darwin") == "pt_BR"

    monkeypatch.setattr(
        "pssh_ui.os_integration._raw_os_locale_candidates",
        lambda platform_name=None: ["ja_JP.UTF-8"],
    )
    assert detect_os_language(supported, platform_name="darwin") == "en"
