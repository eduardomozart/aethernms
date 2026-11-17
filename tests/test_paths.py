"""Tests for OS user config directories (%APPDATA%/pssh-ui, ~/.config/pssh-ui) and git repo discovery."""

from pathlib import Path

from pssh_ui.paths import (
    get_assets_dir,
    get_config_dir,
    get_models_dir,
    get_repository_url,
    get_snippets_dir,
    normalize_git_remote_url,
)


def test_get_config_dir_windows_and_posix(tmp_path: Path):
    win_cfg = get_config_dir(platform_name="win32", home_dir=tmp_path)
    assert win_cfg == tmp_path / "AppData" / "Roaming" / "pssh-ui"
    assert win_cfg.is_dir()

    linux_cfg = get_config_dir(platform_name="linux", home_dir=tmp_path)
    assert linux_cfg == tmp_path / ".config" / "pssh-ui"
    assert linux_cfg.is_dir()

    mac_cfg = get_config_dir(platform_name="darwin", home_dir=tmp_path)
    assert mac_cfg == tmp_path / ".config" / "pssh-ui"
    assert mac_cfg.is_dir()


def test_bundled_dirs_and_git_repo_url_extraction(tmp_path: Path):
    assert get_snippets_dir().is_dir()
    assert get_models_dir().is_dir()
    assert (get_assets_dir() / "pssh-ui.ico").is_file()
    assert (get_assets_dir() / "pssh-ui-header.png").is_file()

    assert normalize_git_remote_url("git@github.com:eduardomozart/pssh-ui.git") == "https://github.com/eduardomozart/pssh-ui"
    assert normalize_git_remote_url("https://github.com/eduardomozart/pssh-ui.git") == "https://github.com/eduardomozart/pssh-ui"

    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text(
        '[remote "origin"]\n\turl = git@github.com:example-org/custom-fork.git\n',
        encoding="utf-8",
    )
    assert get_repository_url(repo_root=tmp_path) == "https://github.com/example-org/custom-fork"
