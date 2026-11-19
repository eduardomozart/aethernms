"""Tests for GitHub Pages Carbon-styled documentation builder (scripts/build_docs.py)."""

from __future__ import annotations

import json
from pathlib import Path

from aethernms.web_app import PAGE_META_MAP
from scripts.build_docs import ROOT_DIR, build_site


def test_build_docs_generates_user_and_developer_guides(tmp_path: Path):
    out_dir = tmp_path / "_site"
    written = build_site(ROOT_DIR, out_dir, base_url="/aethernms")
    assert len(written) > 15

    assert (out_dir / ".nojekyll").is_file()
    assert (out_dir / "404.html").is_file()
    assert (out_dir / "index.html").is_file()
    assert (out_dir / "assets" / "docs.css").is_file()
    assert (out_dir / "assets" / "docs.js").is_file()
    assert (out_dir / "assets" / "aethernms.svg").is_file()

    # Every PAGE_META_MAP contextual Help link target must exist under /user-guide/
    for page_key, (_title, help_path) in PAGE_META_MAP.items():
        rel = help_path.strip("/")
        target = (out_dir / rel / "index.html") if rel else (out_dir / "index.html")
        assert target.is_file(), f"Missing generated help page for {page_key}: {target}"
        ug_html = target.read_text(encoding="utf-8")
        assert "pssh-ui" not in ug_html.lower()
        assert "%APPDATA%" not in ug_html

    # Developer Guide core docs and all 10 per-page specifications
    assert (out_dir / "developer-guide" / "index.html").is_file()
    for core_slug in ("architecture", "ui-shell", "localization"):
        assert (out_dir / "developer-guide" / core_slug / "index.html").is_file()
    for page_slug in (
        "setup",
        "login",
        "jobs",
        "snippets",
        "devices",
        "administration-settings",
        "administration-users",
        "administration-roles",
        "administration-api-keys",
        "api-docs",
    ):
        pg = out_dir / "developer-guide" / "pages" / page_slug / "index.html"
        assert pg.is_file(), f"Missing developer page spec: {pg}"
        html_txt = pg.read_text(encoding="utf-8")
        assert "User Guide" in html_txt
        assert "Developer Guide" in html_txt
        assert "pssh-ui" not in html_txt.lower()

    # Search index covers both sections
    idx = json.loads((out_dir / "search-index.json").read_text(encoding="utf-8"))
    sections = {item["sectionLabel"] for item in idx}
    assert {"User Guide", "Developer Guide"}.issubset(sections)
