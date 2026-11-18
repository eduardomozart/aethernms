"""Tests for OS user config directories (%APPDATA%/pssh-ui, ~/.config/pssh-ui) and git repo discovery."""

from pathlib import Path

import pssh_ui.paths as paths_mod
from pssh_ui.paths import (
    bundled_models_dir,
    bundled_snippets_dir,
    get_assets_dir,
    get_config_dir,
    get_locales_dir,
    get_models_dir,
    get_repository_url,
    get_snippets_dir,
    normalize_git_remote_url,
    seed_bundled_templates,
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


def test_frozen_paths_use_user_config_and_sha256_template_upgrades(monkeypatch, tmp_path: Path):
    mei_dir = tmp_path / "_MEI"
    (mei_dir / "snippets" / "aruba").mkdir(parents=True)
    (mei_dir / "model" / "aruba").mkdir(parents=True)
    (mei_dir / "assets").mkdir(parents=True)
    (mei_dir / "locales").mkdir(parents=True)
    user_cfg = tmp_path / "user_cfg"

    monkeypatch.setattr(paths_mod, "is_frozen", lambda: True)
    monkeypatch.setattr(paths_mod.sys, "_MEIPASS", str(mei_dir), raising=False)
    monkeypatch.setattr(paths_mod, "get_config_dir", lambda *a, **kw: user_cfg)

    assert get_assets_dir() == mei_dir / "assets"
    assert get_locales_dir() == mei_dir / "locales"
    assert bundled_snippets_dir() == mei_dir / "snippets"
    assert bundled_models_dir() == mei_dir / "model"
    assert get_snippets_dir() == user_cfg / "snippets"
    assert get_models_dir() == user_cfg / "model"

    # Initial seed
    src = tmp_path / "bundle_v1"
    dst = tmp_path / "user_snippets"
    (src / "aruba").mkdir(parents=True)
    (src / "aruba" / "auto_upd.xml").write_text("<Snippet>v1</Snippet>\n", encoding="utf-8")
    (src / "aruba" / "user_edit.xml").write_text("<Snippet>v1</Snippet>\n", encoding="utf-8")
    (src / "aruba" / "deleted_by_user.xml").write_text("<Snippet>del</Snippet>\n", encoding="utf-8")

    assert seed_bundled_templates(src, dst) == []
    assert (dst / ".seed_manifest.json").is_file()
    assert (dst / "aruba" / "auto_upd.xml").is_file()

    # User edits one file, deletes another, and leaves auto_upd untouched
    (dst / "aruba" / "user_edit.xml").write_text("<Snippet>custom</Snippet>\n", encoding="utf-8")
    (dst / "aruba" / "deleted_by_user.xml").unlink()

    # Simulated .exe upgrade (v2)
    src_v2 = tmp_path / "bundle_v2"
    (src_v2 / "aruba").mkdir(parents=True)
    (src_v2 / "aruba" / "auto_upd.xml").write_text("<Snippet>v2</Snippet>\n", encoding="utf-8")
    (src_v2 / "aruba" / "user_edit.xml").write_text("<Snippet>v2</Snippet>\n", encoding="utf-8")
    (src_v2 / "aruba" / "deleted_by_user.xml").write_text("<Snippet>del</Snippet>\n", encoding="utf-8")
    (src_v2 / "aruba" / "brand_new.xml").write_text("<Snippet>new</Snippet>\n", encoding="utf-8")

    sidecars = seed_bundled_templates(src_v2, dst)
    assert sidecars == ["aruba/user_edit.xml"]
    # Unedited file auto-updates silently
    assert (dst / "aruba" / "auto_upd.xml").read_text(encoding="utf-8") == "<Snippet>v2</Snippet>\n"
    # User-edited file stays intact + .xml.new conflict reference created
    assert (dst / "aruba" / "user_edit.xml").read_text(encoding="utf-8") == "<Snippet>custom</Snippet>\n"
    assert (dst / "aruba" / "user_edit.xml.new").read_text(encoding="utf-8") == "<Snippet>v2</Snippet>\n"
    # Deleted default stays deleted, brand-new default appears
    assert not (dst / "aruba" / "deleted_by_user.xml").exists()
    assert (dst / "aruba" / "brand_new.xml").is_file()
