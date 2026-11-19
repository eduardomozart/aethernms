"""Tests for unified ~/.aethernms user data directory, bundled assets/templates, and git repo discovery."""

from pathlib import Path

import aethernms.paths as paths_mod
from aethernms.paths import (
    bundled_snippets_dir,
    get_assets_dir,
    get_config_dir,
    get_db_path,
    get_devices_path,
    get_jobs_path,
    get_locales_dir,
    get_repository_url,
    get_settings_path,
    get_snippets_dir,
    get_static_dir,
    get_templates_dir,
    normalize_git_remote_url,
    seed_bundled_templates,
)


def test_get_config_dir_windows_and_posix(tmp_path: Path):
    win_cfg = get_config_dir(platform_name="win32", home_dir=tmp_path)
    assert win_cfg == tmp_path / ".aethernms"
    assert win_cfg.is_dir()

    linux_cfg = get_config_dir(platform_name="linux", home_dir=tmp_path)
    assert linux_cfg == tmp_path / ".aethernms"
    assert linux_cfg.is_dir()

    mac_cfg = get_config_dir(platform_name="darwin", home_dir=tmp_path)
    assert mac_cfg == tmp_path / ".aethernms"
    assert mac_cfg.is_dir()


def test_get_config_dir_respects_env_override(monkeypatch, tmp_path: Path):
    custom_cfg = tmp_path / "custom_runtime"
    monkeypatch.setenv("AETHERNMS_CONFIG_DIR", str(custom_cfg))
    resolved = get_config_dir()
    assert resolved == custom_cfg
    assert custom_cfg.is_dir()


def test_bundled_dirs_and_git_repo_url_extraction(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("AETHERNMS_CONFIG_DIR", raising=False)
    assert bundled_snippets_dir().is_dir()
    cfg_dir = get_config_dir()
    assert get_snippets_dir() == cfg_dir / "snippets"
    assert get_db_path() == cfg_dir / "aethernms.db"
    assert get_settings_path() == cfg_dir / "settings.xml"
    assert get_devices_path() == cfg_dir / "devices.xml"
    assert get_jobs_path() == cfg_dir / "jobs.xml"
    assert (get_templates_dir() / "layout.html").is_file()
    assert (get_templates_dir() / "partials" / "header.html").is_file()
    assert (get_templates_dir() / "partials" / "head_icons.html").is_file()
    assert (get_templates_dir() / "setup.html").is_file()
    assert (get_templates_dir() / "login.html").is_file()
    assert (get_templates_dir() / "jobs.html").is_file()
    assert (get_templates_dir() / "snippets.html").is_file()
    assert (get_templates_dir() / "devices.html").is_file()
    assert (get_templates_dir() / "administration" / "settings.html").is_file()
    assert (get_templates_dir() / "administration" / "users.html").is_file()
    assert (get_templates_dir() / "administration" / "roles.html").is_file()
    assert (get_templates_dir() / "administration" / "api_keys.html").is_file()
    assert (get_templates_dir() / "modals" / "add_job.html").is_file()
    assert (get_templates_dir() / "modals" / "user_editor.html").is_file()
    assert (get_templates_dir() / "swagger.html").is_file()
    assert (get_assets_dir() / "aethernms.svg").is_file()
    assert (get_assets_dir() / "favicon.ico").is_file()
    assert (get_assets_dir() / "apple-touch-icon.png").is_file()
    assert (get_assets_dir() / "site.webmanifest").is_file()
    assert (get_static_dir() / "css" / "aethernms-carbon.css").is_file()
    assert (get_static_dir() / "js" / "core.js").is_file()
    assert (get_static_dir() / "js" / "setup.js").is_file()
    assert (get_static_dir() / "js" / "jobs.js").is_file()
    assert (get_static_dir() / "js" / "snippets.js").is_file()
    assert (get_static_dir() / "js" / "devices.js").is_file()
    assert (get_static_dir() / "js" / "settings.js").is_file()

    assert normalize_git_remote_url("git@github.com:eduardomozart/aethernms.git") == "https://github.com/eduardomozart/aethernms"
    assert normalize_git_remote_url("https://github.com/eduardomozart/aethernms.git") == "https://github.com/eduardomozart/aethernms"

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
    (mei_dir / "locales").mkdir(parents=True)
    user_cfg = tmp_path / "user_cfg"

    monkeypatch.setattr(paths_mod, "is_frozen", lambda: True)
    monkeypatch.setattr(paths_mod.sys, "_MEIPASS", str(mei_dir), raising=False)
    monkeypatch.setattr(paths_mod, "get_config_dir", lambda *a, **kw: user_cfg)

    assert get_locales_dir() == mei_dir / "locales"
    assert bundled_snippets_dir() == mei_dir / "snippets"
    assert get_snippets_dir() == user_cfg / "snippets"

    src = tmp_path / "bundle_v1"
    dst = tmp_path / "user_snippets"
    (src / "aruba").mkdir(parents=True)
    (src / "aruba" / "auto_upd.xml").write_text("<Snippet>v1</Snippet>\n", encoding="utf-8")
    (src / "aruba" / "user_edit.xml").write_text("<Snippet>v1</Snippet>\n", encoding="utf-8")
    (src / "aruba" / "deleted_by_user.xml").write_text("<Snippet>del</Snippet>\n", encoding="utf-8")

    assert seed_bundled_templates(src, dst) == []
    assert (dst / ".seed_manifest.json").is_file()
    assert (dst / "aruba" / "auto_upd.xml").is_file()

    (dst / "aruba" / "user_edit.xml").write_text("<Snippet>custom</Snippet>\n", encoding="utf-8")
    (dst / "aruba" / "deleted_by_user.xml").unlink()

    src_v2 = tmp_path / "bundle_v2"
    (src_v2 / "aruba").mkdir(parents=True)
    (src_v2 / "aruba" / "auto_upd.xml").write_text("<Snippet>v2</Snippet>\n", encoding="utf-8")
    (src_v2 / "aruba" / "user_edit.xml").write_text("<Snippet>v2</Snippet>\n", encoding="utf-8")
    (src_v2 / "aruba" / "deleted_by_user.xml").write_text("<Snippet>del</Snippet>\n", encoding="utf-8")
    (src_v2 / "aruba" / "brand_new.xml").write_text("<Snippet>new</Snippet>\n", encoding="utf-8")

    sidecars = seed_bundled_templates(src_v2, dst)
    assert sidecars == ["aruba/user_edit.xml"]
    assert (dst / "aruba" / "auto_upd.xml").read_text(encoding="utf-8") == "<Snippet>v2</Snippet>\n"
    assert (dst / "aruba" / "user_edit.xml").read_text(encoding="utf-8") == "<Snippet>custom</Snippet>\n"
    assert (dst / "aruba" / "user_edit.xml.new").read_text(encoding="utf-8") == "<Snippet>v2</Snippet>\n"
    assert not (dst / "aruba" / "deleted_by_user.xml").exists()
    assert (dst / "aruba" / "brand_new.xml").is_file()


def test_frozen_paths_resolve_templates_and_static(monkeypatch, tmp_path: Path):
    mei_dir = tmp_path / "_MEI"
    (mei_dir / "aethernms" / "templates").mkdir(parents=True)
    (mei_dir / "aethernms" / "static").mkdir(parents=True)
    user_cfg = tmp_path / "user_cfg"
    monkeypatch.setattr(paths_mod, "is_frozen", lambda: True)
    monkeypatch.setattr(paths_mod.sys, "_MEIPASS", str(mei_dir), raising=False)
    monkeypatch.setattr(paths_mod, "get_config_dir", lambda *a, **kw: user_cfg)

    assert get_templates_dir() == mei_dir / "aethernms" / "templates"
    assert get_static_dir() == mei_dir / "aethernms" / "static"
    assert get_db_path() == user_cfg / "aethernms.db"
