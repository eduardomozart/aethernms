#!/usr/bin/env python3
"""Static documentation site builder for aethernms (GitHub Pages).

Generates an IBM Carbon Design System (carbondesignsystem.com-inspired) static site
combining two top-level sections:
  1. User Guide      <- wiki/*.md
  2. Developer Guide <- docs/developer-guide/*.md + docs/pages/*.md

Zero external PyPI runtime dependencies (Python 3 stdlib only), reusing the repository's
Composer-managed @carbon/styles & @fontsource/ibm-plex-* assets when present.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import html
import json
from pathlib import Path
import re
import shutil
import sys
from typing import Dict, List, Optional, Tuple


ROOT_DIR = Path(__file__).resolve().parent.parent


@dataclass
class DocPage:
    """Single Markdown documentation page definition and rendered output."""

    section: str  # "home" | "user-guide" | "developer-guide"
    group: str
    title: str
    route: str  # Leading and trailing slash, e.g. "/user-guide/jobs/"
    source_path: Optional[Path]
    source_names: Tuple[str, ...] = ()
    markdown_text: str = ""
    html_body: str = ""
    toc: List[Tuple[int, str, str]] = field(default_factory=list)  # (level, id, label)
    plain_text: str = ""


def _slugify(text: str, seen: Optional[Dict[str, int]] = None) -> str:
    clean = re.sub(r"`([^`]+)`", r"\1", text)
    clean = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", clean)
    clean = clean.lower().strip()
    clean = re.sub(r"[^a-z0-9\s-]", "", clean)
    clean = re.sub(r"[\s_-]+", "-", clean).strip("-") or "section"
    if seen is not None:
        count = seen.get(clean, 0)
        seen[clean] = count + 1
        if count > 0:
            return f"{clean}-{count}"
    return clean


def _strip_markdown_inline(text: str) -> str:
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    return text.strip()


def _resolve_link(
    raw_url: str,
    base_url: str,
    alias_routes: Dict[str, str],
) -> Tuple[str, bool]:
    """Resolve internal wiki/docs links to target docs routes; return (url, external)."""
    url = raw_url.strip()
    if url.startswith(("http://", "https://", "mailto:", "#")):
        return url, url.startswith(("http://", "https://"))

    path_part, sep, frag = url.partition("#")
    anchor = f"#{frag}" if sep and frag else ""
    norm = path_part.replace("\\", "/").lstrip("./")
    while norm.startswith("../"):
        norm = norm[3:]

    if norm.startswith("images/") or norm.startswith("wiki/images/"):
        img_name = norm.split("images/", 1)[1]
        return f"{base_url}/images/{img_name}{anchor}", False

    if norm.startswith("assets/"):
        return f"{base_url}/{norm}{anchor}", False

    # Strip trailing .md or leading folders for alias lookup
    candidates = [
        norm,
        norm.lower(),
        norm.removesuffix(".md"),
        norm.removesuffix(".md").lower(),
        Path(norm).stem,
        Path(norm).stem.lower(),
    ]
    for cand in candidates:
        if cand in alias_routes:
            route = alias_routes[cand]
            return f"{base_url}{route}{anchor}", False

    return url, False


def _render_inline(
    text: str,
    base_url: str,
    alias_routes: Dict[str, str],
) -> str:
    """Render inline Markdown formatting safely without corrupting code spans or identifiers."""
    tokens: List[str] = []

    def _stash(rendered: str) -> str:
        idx = len(tokens)
        tokens.append(rendered)
        return f"\x00TOK{idx}\x00"

    # 1. Inline code spans first so inner underscores/asterisks are untouched
    def _code_sub(m: re.Match) -> str:
        return _stash(f"<code>{html.escape(m.group(1))}</code>")

    text = re.sub(r"`([^`]+)`", _code_sub, text)

    # 2. Images ![alt](url)
    def _img_sub(m: re.Match) -> str:
        alt = html.escape(m.group(1), quote=True)
        resolved, _ext = _resolve_link(m.group(2), base_url, alias_routes)
        return _stash(
            f'<figure class="cds-docs-figure"><img src="{html.escape(resolved, quote=True)}" '
            f'alt="{alt}" loading="lazy" />'
            + (f"<figcaption>{alt}</figcaption>" if alt else "")
            + "</figure>"
        )

    text = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)\)", _img_sub, text)

    # 3. Links [label](url)
    def _link_sub(m: re.Match) -> str:
        label_raw = m.group(1)
        resolved, external = _resolve_link(m.group(2), base_url, alias_routes)
        # Restore inline tokens in link text and apply bold/italic if needed
        inner = _apply_emphasis(html.escape(label_raw))
        for i, tok in enumerate(tokens):
            inner = inner.replace(f"\x00TOK{i}\x00", tok)
        attrs = ' target="_blank" rel="noopener noreferrer"' if external else ""
        return _stash(f'<a href="{html.escape(resolved, quote=True)}"{attrs}>{inner}</a>')

    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", _link_sub, text)

    escaped = html.escape(text, quote=False)
    escaped = _apply_emphasis(escaped)
    for i, tok in enumerate(tokens):
        escaped = escaped.replace(f"\x00TOK{i}\x00", tok)
    return escaped


def _apply_emphasis(escaped_text: str) -> str:
    escaped_text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped_text)
    escaped_text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", escaped_text)
    return escaped_text


def render_markdown(
    md_text: str,
    base_url: str,
    alias_routes: Dict[str, str],
) -> Tuple[str, Optional[str], List[Tuple[int, str, str]], str]:
    """Convert Markdown string into HTML, extracted H1 title, TOC tuples, and plain search text."""
    lines = md_text.replace("\r\n", "\n").split("\n")
    out: List[str] = []
    toc: List[Tuple[int, str, str]] = []
    seen_slugs: Dict[str, int] = {}
    doc_title: Optional[str] = None
    plain_parts: List[str] = []

    i = 0
    n = len(lines)

    def _is_table_sep(line: str) -> bool:
        stripped = line.strip()
        if "|" not in stripped:
            return False
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        return bool(cells) and all(re.fullmatch(r":?-{3,}:?", c) for c in cells)

    def _split_row(line: str) -> List[str]:
        return [c.strip() for c in line.strip().strip("|").split("|")]

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # Horizontal rule
        if re.fullmatch(r"(?:-{3,}|\*{3,}|_{3,})", stripped):
            out.append("<hr />")
            i += 1
            continue

        # Fenced code block
        fence_m = re.match(r"^```([A-Za-z0-9_+-]*)\s*$", stripped)
        if fence_m:
            lang = fence_m.group(1).lower()
            i += 1
            code_lines: List[str] = []
            while i < n and not re.match(r"^```\s*$", lines[i].strip()):
                code_lines.append(lines[i])
                i += 1
            if i < n:
                i += 1
            raw_code = "\n".join(code_lines)
            plain_parts.append(raw_code)
            if lang == "mermaid":
                out.append(f'<div class="cds-docs-mermaid-wrap"><pre class="mermaid">{html.escape(raw_code)}</pre></div>')
            else:
                lang_label = html.escape(lang or "text")
                out.append(
                    '<div class="cds-docs-code-block">'
                    f'<div class="cds-docs-code-bar"><span class="cds-docs-code-lang">{lang_label}</span>'
                    '<button type="button" class="cds-docs-copy-btn" data-copy-code>Copy</button></div>'
                    f'<pre><code class="language-{lang_label}">{html.escape(raw_code)}</code></pre>'
                    "</div>"
                )
            continue

        # Headings (# .. ####)
        head_m = re.match(r"^(#{1,4})\s+(.+?)\s*$", stripped)
        if head_m:
            level = len(head_m.group(1))
            raw_heading = head_m.group(2)
            label_plain = _strip_markdown_inline(raw_heading)
            plain_parts.append(label_plain)
            if level == 1 and doc_title is None:
                doc_title = label_plain
                i += 1
                continue
            slug = _slugify(label_plain, seen_slugs)
            if level in (2, 3):
                toc.append((level, slug, label_plain))
            rendered_h = _render_inline(raw_heading, base_url, alias_routes)
            out.append(
                f'<h{level} id="{html.escape(slug, quote=True)}">'
                f'{rendered_h}'
                f'<a class="cds-docs-anchor" href="#{html.escape(slug, quote=True)}" aria-label="Link to section">#</a>'
                f"</h{level}>"
            )
            i += 1
            continue

        # Markdown Table
        if "|" in stripped and i + 1 < n and _is_table_sep(lines[i + 1]):
            headers = _split_row(line)
            sep_cells = _split_row(lines[i + 1])
            aligns: List[str] = []
            for sc in sep_cells:
                if sc.startswith(":") and sc.endswith(":"):
                    aligns.append("center")
                elif sc.endswith(":"):
                    aligns.append("right")
                else:
                    aligns.append("left")
            i += 2
            rows: List[List[str]] = []
            while i < n and "|" in lines[i].strip() and lines[i].strip():
                rows.append(_split_row(lines[i]))
                i += 1
            plain_parts.append(" ".join(_strip_markdown_inline(c) for c in headers))
            thead = "".join(
                f'<th style="text-align:{aligns[idx] if idx < len(aligns) else "left"}">'
                f'{_render_inline(cell, base_url, alias_routes)}</th>'
                for idx, cell in enumerate(headers)
            )
            tbody_rows: List[str] = []
            for row in rows:
                plain_parts.append(" ".join(_strip_markdown_inline(c) for c in row))
                tds = "".join(
                    f'<td style="text-align:{aligns[idx] if idx < len(aligns) else "left"}">'
                    f'{_render_inline(row[idx] if idx < len(row) else "", base_url, alias_routes)}</td>'
                    for idx in range(len(headers))
                )
                tbody_rows.append(f"<tr>{tds}</tr>")
            out.append(
                '<div class="cds-docs-table-wrap"><table class="cds--data-table cds-docs-table">'
                f"<thead><tr>{thead}</tr></thead>"
                f"<tbody>{''.join(tbody_rows)}</tbody>"
                "</table></div>"
            )
            continue

        # Blockquote / Alert
        if stripped.startswith(">"):
            bq_lines: List[str] = []
            while i < n and lines[i].strip().startswith(">"):
                bq_lines.append(re.sub(r"^>\s?", "", lines[i].strip()))
                i += 1
            joined = " ".join(bq_lines)
            plain_parts.append(_strip_markdown_inline(joined))
            alert_m = re.match(r"^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*(.*)$", joined, re.I)
            if alert_m:
                kind = alert_m.group(1).lower()
                body_html = _render_inline(alert_m.group(2), base_url, alias_routes)
                out.append(
                    f'<div class="cds-docs-callout cds-docs-callout--{kind}">'
                    f'<strong>{html.escape(kind.upper())}:</strong> {body_html}</div>'
                )
            else:
                out.append(f"<blockquote>{_render_inline(joined, base_url, alias_routes)}</blockquote>")
            continue

        # Unordered or Ordered Lists (supports one nested sub-list level)
        ul_m = re.match(r"^(\s*)[*-]\s+(.+)$", line)
        ol_m = re.match(r"^(\s*)\d+\.\s+(.+)$", line)
        if ul_m or ol_m:
            list_tag = "ul" if ul_m else "ol"
            base_indent = len((ul_m or ol_m).group(1))
            items_html: List[str] = []
            while i < n:
                cur = lines[i]
                if not cur.strip():
                    if i + 1 < n and re.match(r"^\s*(?:[*-]|\d+\.)\s+", lines[i + 1]):
                        i += 1
                        continue
                    break
                cur_ul = re.match(r"^(\s*)[*-]\s+(.+)$", cur)
                cur_ol = re.match(r"^(\s*)\d+\.\s+(.+)$", cur)
                m = cur_ul or cur_ol
                if not m:
                    break
                ind = len(m.group(1))
                if ind > base_indent and items_html:
                    sub_tag = "ul" if cur_ul else "ol"
                    sub_items: List[str] = []
                    while i < n:
                        sc = lines[i]
                        sm = re.match(r"^(\s+)(?:[*-]|\d+\.)\s+(.+)$", sc)
                        if not sm or len(sm.group(1)) <= base_indent:
                            break
                        plain_parts.append(_strip_markdown_inline(sm.group(2)))
                        sub_items.append(f"<li>{_render_inline(sm.group(2), base_url, alias_routes)}</li>")
                        i += 1
                    items_html[-1] = items_html[-1][:-5] + f"<{sub_tag}>{''.join(sub_items)}</{sub_tag}></li>"
                    continue
                if (list_tag == "ul" and not cur_ul) or (list_tag == "ol" and not cur_ol):
                    break
                plain_parts.append(_strip_markdown_inline(m.group(2)))
                items_html.append(f"<li>{_render_inline(m.group(2), base_url, alias_routes)}</li>")
                i += 1
            out.append(f"<{list_tag}>{''.join(items_html)}</{list_tag}>")
            continue

        # Paragraph
        para_lines: List[str] = []
        while i < n:
            s = lines[i].strip()
            if (
                not s
                or s.startswith("#")
                or s.startswith("```")
                or s.startswith(">")
                or re.fullmatch(r"(?:-{3,}|\*{3,}|_{3,})", s)
                or re.match(r"^(?:[*-]|\d+\.)\s+", s)
                or ("|" in s and i + 1 < n and _is_table_sep(lines[i + 1]))
            ):
                break
            para_lines.append(s)
            i += 1
        para_text = " ".join(para_lines)
        plain_parts.append(_strip_markdown_inline(para_text))
        rendered_p = _render_inline(para_text, base_url, alias_routes)
        out.append(f"<p>{rendered_p}</p>")

    return "\n".join(out), doc_title, toc, re.sub(r"\s+", " ", " ".join(plain_parts)).strip()


def collect_pages(root_dir: Path) -> Tuple[List[DocPage], Dict[str, str]]:
    """Collect Home, User Guide (wiki/), and Developer Guide (docs/) pages."""
    wiki_dir = root_dir / "wiki"
    dev_dir = root_dir / "docs" / "developer-guide"
    pages_dir = root_dir / "docs" / "pages"

    user_guide_order = [
        ("User-Guide.md", "/user-guide/", "User Guide"),
        ("Getting-Started.md", "/user-guide/getting-started/", "Getting Started"),
        ("Jobs.md", "/user-guide/jobs/", "Jobs"),
        ("Snippets-and-Variables.md", "/user-guide/snippets-and-variables/", "Snippets & Variables"),
        ("Devices.md", "/user-guide/devices/", "Devices"),
        ("Administration-Settings.md", "/user-guide/administration-settings/", "System Settings"),
        ("Administration-Users.md", "/user-guide/administration-users/", "Users"),
        ("Administration-Roles.md", "/user-guide/administration-roles/", "Roles"),
        ("Administration-API-Keys.md", "/user-guide/administration-api-keys/", "API Keys"),
        ("REST-API.md", "/user-guide/rest-api/", "REST API & Swagger"),
    ]

    dev_core_order = [
        ("architecture.md", "/developer-guide/architecture/", "Architecture & Backend"),
        ("ui-shell.md", "/developer-guide/ui-shell/", "IBM Carbon UI Shell"),
        ("localization.md", "/developer-guide/localization/", "Localization & Transifex"),
    ]

    dev_pages_order = [
        ("setup.md", "/developer-guide/pages/setup/", "Setup (/setup)"),
        ("login.md", "/developer-guide/pages/login/", "Login (/login)"),
        ("jobs.md", "/developer-guide/pages/jobs/", "Jobs (/jobs)"),
        ("snippets.md", "/developer-guide/pages/snippets/", "Snippets (/snippets)"),
        ("devices.md", "/developer-guide/pages/devices/", "Devices (/devices)"),
        (
            "administration-settings.md",
            "/developer-guide/pages/administration-settings/",
            "System Settings (/administration/settings)",
        ),
        (
            "administration-users.md",
            "/developer-guide/pages/administration-users/",
            "Users (/administration/users)",
        ),
        (
            "administration-roles.md",
            "/developer-guide/pages/administration-roles/",
            "Roles (/administration/roles)",
        ),
        (
            "administration-api-keys.md",
            "/developer-guide/pages/administration-api-keys/",
            "API Keys (/administration/api-keys)",
        ),
        ("api-docs.md", "/developer-guide/pages/api-docs/", "API Docs (/api/docs)"),
    ]

    all_pages: List[DocPage] = []
    aliases: Dict[str, str] = {}

    # Home
    home_file = wiki_dir / "Home.md"
    home_md = home_file.read_text(encoding="utf-8") if home_file.is_file() else "# aethernms Documentation\n"
    all_pages.append(
        DocPage(
            section="home",
            group="Overview",
            title="Home",
            route="/",
            source_path=home_file if home_file.is_file() else None,
            source_names=("Home", "Home.md", "home", "wiki/Home.md"),
            markdown_text=home_md,
        )
    )

    # User Guide
    for filename, route, label in user_guide_order:
        p = wiki_dir / filename
        if not p.is_file():
            continue
        stem = p.stem
        all_pages.append(
            DocPage(
                section="user-guide",
                group="User Guide",
                title=label,
                route=route,
                source_path=p,
                source_names=(
                    filename,
                    filename.lower(),
                    stem,
                    stem.lower(),
                    f"wiki/{filename}",
                ),
                markdown_text=p.read_text(encoding="utf-8"),
            )
        )

    # Developer Guide Overview
    dev_overview_lines = [
        "# Developer Guide",
        "",
        "Technical architecture, IBM Carbon Design System v11 shell conventions, localization workflows, and per-page specifications for **`aethernms`**.",
        "",
        "## Core Engineering Specifications",
        "",
        "* [Architecture & Design Choices](/developer-guide/architecture/) — Py4Web + multi-backend PyDAL, `~/.aethernms` storage, RBAC, and Netmiko execution engine.",
        "* [IBM Carbon UI Shell](/developer-guide/ui-shell/) — 48px dark header, aligned global search, SideNav rail, outside-tile page headers, DataTable filter popovers, and modal visibility rules.",
        "* [Localization & Transifex](/developer-guide/localization/) — Gettext/Babel workflows, `web_strings.py`, and zero-FOUC SSR hydration.",
        "",
        "## Per-Page Specifications (`docs/pages/`)",
        "",
        "| Route | Specification |",
        "| :--- | :--- |",
    ]
    for filename, route, label in dev_pages_order:
        dev_overview_lines.append(f"| `{label}` | [{label}]({route}) |")

    all_pages.append(
        DocPage(
            section="developer-guide",
            group="Developer Guide",
            title="Developer Guide",
            route="/developer-guide/",
            source_path=None,
            source_names=("developer-guide", "docs", "docs/developer-guide"),
            markdown_text="\n".join(dev_overview_lines) + "\n",
        )
    )

    # Developer Guide core docs
    for filename, route, label in dev_core_order:
        p = dev_dir / filename
        if not p.is_file():
            continue
        stem = p.stem
        all_pages.append(
            DocPage(
                section="developer-guide",
                group="Core Architecture",
                title=label,
                route=route,
                source_path=p,
                source_names=(
                    filename,
                    stem,
                    f"docs/developer-guide/{filename}",
                    f"developer-guide/{filename}",
                ),
                markdown_text=p.read_text(encoding="utf-8"),
            )
        )

    # Per-page specs
    for filename, route, label in dev_pages_order:
        p = pages_dir / filename
        if not p.is_file():
            continue
        stem = p.stem
        all_pages.append(
            DocPage(
                section="developer-guide",
                group="Page Specifications",
                title=label,
                route=route,
                source_path=p,
                source_names=(
                    f"docs/pages/{filename}",
                    f"pages/{filename}",
                    route,
                ),
                markdown_text=p.read_text(encoding="utf-8"),
            )
        )

    for pg in all_pages:
        aliases[pg.route] = pg.route
        for alias in pg.source_names:
            aliases[alias] = pg.route
            aliases[alias.lower()] = pg.route

    return all_pages, aliases


def _copy_static_assets(root_dir: Path, out_dir: Path) -> Dict[str, bool]:
    """Copy Composer Carbon CSS/IBM Plex fonts, assets/, and wiki/images/ to output."""
    has_carbon_css = False
    vendor_src = root_dir / "aethernms" / "static" / "vendor" / "npm-asset"
    vendor_dst = out_dir / "vendor"

    styles_file = vendor_src / "carbon--styles" / "css" / "styles.min.css"
    if styles_file.is_file():
        dst = vendor_dst / "carbon--styles" / "css" / "styles.min.css"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(styles_file, dst)
        has_carbon_css = True

    for pkg, weights in (
        ("fontsource--ibm-plex-sans", ("300.css", "400.css", "500.css", "600.css")),
        ("fontsource--ibm-plex-mono", ("400.css", "500.css", "600.css")),
    ):
        src_pkg = vendor_src / pkg
        dst_pkg = vendor_dst / pkg
        if not src_pkg.is_dir():
            continue
        dst_pkg.mkdir(parents=True, exist_ok=True)
        for css_name in weights:
            css_file = src_pkg / css_name
            if css_file.is_file():
                shutil.copy2(css_file, dst_pkg / css_name)
        files_dir = src_pkg / "files"
        if files_dir.is_dir():
            shutil.copytree(files_dir, dst_pkg / "files", dirs_exist_ok=True)

    assets_src = root_dir / "assets"
    if assets_src.is_dir():
        shutil.copytree(assets_src, out_dir / "assets", dirs_exist_ok=True)

    images_src = root_dir / "wiki" / "images"
    if images_src.is_dir():
        shutil.copytree(images_src, out_dir / "images", dirs_exist_ok=True)

    return {"has_carbon_css": has_carbon_css}


def _docs_stylesheet() -> str:
    return """
:root {
  --cds-docs-bg: #ffffff;
  --cds-docs-layer-01: #f4f4f4;
  --cds-docs-hero-bg: #161616;
  --cds-docs-border: #e0e0e0;
  --cds-docs-text: #161616;
  --cds-docs-text-secondary: #525252;
  --cds-docs-blue: #0f62fe;
  --cds-docs-blue-hover: #0043ce;
}

* { box-sizing: border-box; border-radius: 0 !important; }
html, body {
  margin: 0;
  padding: 0;
  background: var(--cds-docs-bg);
  color: var(--cds-docs-text);
  font-family: "IBM Plex Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-size: 16px;
  line-height: 1.5;
  letter-spacing: 0;
  -webkit-font-smoothing: antialiased;
}
code, pre {
  font-family: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace !important;
}

/* Carbon Docs Header (48px fixed g100 shell) */
.cds-docs-header {
  position: fixed;
  top: 0; left: 0; right: 0;
  height: 48px;
  background: #161616;
  border-bottom: 1px solid #393939;
  color: #f4f4f4;
  z-index: 9000;
  display: flex;
  align-items: center;
}
.cds-docs-header__brand-zone {
  display: flex;
  align-items: center;
  height: 48px;
  width: 256px;
  flex: 0 0 256px;
}
.cds-docs-menu-btn {
  display: none;
  width: 48px;
  height: 48px;
  border: 0;
  background: transparent;
  color: #f4f4f4;
  cursor: pointer;
  align-items: center;
  justify-content: center;
}
.cds-docs-brand {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: 48px;
  padding: 0 16px;
  color: #f4f4f4;
  text-decoration: none;
}
.cds-docs-wordmark {
  font-weight: 600;
  letter-spacing: -2px;
  font-size: 20px;
  line-height: 1;
}
.cds-docs-sub {
  font-size: 12px;
  color: #c6c6c6;
  font-weight: 400;
}
.cds-docs-header-nav {
  display: flex;
  align-items: center;
  height: 48px;
}
.cds-docs-header-link {
  display: inline-flex;
  align-items: center;
  height: 48px;
  padding: 0 16px;
  color: #c6c6c6;
  text-decoration: none;
  font-size: 14px;
  border-bottom: 3px solid transparent;
}
.cds-docs-header-link:hover,
.cds-docs-header-link.active {
  color: #ffffff;
  background: #262626;
}
.cds-docs-header-link.active {
  border-bottom-color: #0f62fe;
}
.cds-docs-search-wrap {
  margin-left: auto;
  position: relative;
  height: 48px;
  width: min(360px, 40vw);
  border-left: 1px solid #393939;
}
.cds-docs-search-input {
  width: 100%;
  height: 48px;
  background: #262626;
  border: 0;
  padding: 0 40px 0 16px;
  color: #f4f4f4;
  font-size: 14px;
  outline: none;
}
.cds-docs-search-input::placeholder { color: #a8a8a8; }
.cds-docs-search-input:focus {
  background: #393939;
  box-shadow: inset 0 0 0 2px #ffffff;
}
.cds-docs-search-icon {
  position: absolute;
  right: 14px;
  top: 50%;
  transform: translateY(-50%);
  color: #c6c6c6;
  pointer-events: none;
}
.cds-docs-search-results {
  position: absolute;
  top: 48px;
  right: 0;
  left: 0;
  background: #262626;
  border: 1px solid #525252;
  max-height: 380px;
  overflow-y: auto;
  z-index: 9100;
}
.cds-docs-search-results.hidden { display: none; }
.cds-docs-search-item {
  display: block;
  padding: 10px 16px;
  color: #f4f4f4;
  text-decoration: none;
  border-bottom: 1px solid #393939;
}
.cds-docs-search-item:hover { background: #353535; }
.cds-docs-search-item-meta { font-size: 12px; color: #8d8d8d; display: block; }
.cds-docs-search-item-title { font-size: 14px; font-weight: 600; display: block; }

/* Left Fixed Sidebar (256px carbon docs tree) */
.cds-docs-sidenav {
  position: fixed;
  top: 48px;
  left: 0;
  bottom: 0;
  width: 256px;
  background: #ffffff;
  border-right: 1px solid #e0e0e0;
  overflow-y: auto;
  padding: 16px 0 32px;
  z-index: 8000;
}
.cds-docs-nav-top-link {
  display: block;
  padding: 9px 16px;
  color: #525252;
  text-decoration: none;
  font-size: 14px;
  font-weight: 600;
  border-left: 3px solid transparent;
}
.cds-docs-nav-top-link:hover { background: #f4f4f4; color: #161616; }
.cds-docs-nav-top-link.active {
  background: #f4f4f4;
  color: #161616;
  border-left-color: #0f62fe;
}
.cds-docs-nav-group-btn {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  background: transparent;
  border: 0;
  border-top: 1px solid #f4f4f4;
  font-size: 14px;
  font-weight: 600;
  color: #161616;
  cursor: pointer;
  text-align: left;
}
.cds-docs-nav-group-btn:hover { background: #f4f4f4; }
.cds-docs-nav-group-btn[aria-expanded="false"] + .cds-docs-nav-list { display: none; }
.cds-docs-nav-list {
  list-style: none;
  margin: 0;
  padding: 0 0 8px;
}
.cds-docs-nav-sublabel {
  padding: 8px 16px 4px 28px;
  font-size: 12px;
  font-weight: 600;
  color: #6f6f6f;
}
.cds-docs-nav-link {
  display: block;
  padding: 7px 16px 7px 28px;
  color: #525252;
  text-decoration: none;
  font-size: 14px;
  line-height: 1.35;
  border-left: 3px solid transparent;
}
.cds-docs-nav-link--deep { padding-left: 36px; font-size: 13px; }
.cds-docs-nav-link:hover { background: #e8e8e8; color: #161616; }
.cds-docs-nav-link.active {
  background: #e0e0e0;
  color: #161616;
  font-weight: 600;
  border-left-color: #0f62fe;
}

/* Main Content Area + Carbon Dark Hero + Two-Column Article & TOC */
.cds-docs-shell {
  margin-top: 48px;
  margin-left: 256px;
  min-height: calc(100vh - 48px);
  display: flex;
  flex-direction: column;
}
.cds-docs-hero {
  background: #161616;
  color: #f4f4f4;
  padding: 40px 48px 44px;
  border-bottom: 1px solid #262626;
}
.cds-docs-hero__eyebrow {
  font-size: 14px;
  color: #c6c6c6;
  margin-bottom: 12px;
}
.cds-docs-hero__title {
  margin: 0;
  font-size: clamp(32px, 4vw, 52px);
  font-weight: 300;
  line-height: 1.15;
  letter-spacing: 0;
  color: #ffffff;
}
.cds-docs-grid {
  flex: 1 0 auto;
  display: grid;
  grid-template-columns: minmax(0, 760px) 220px;
  gap: 48px;
  padding: 40px 48px 64px;
  align-items: start;
}
.cds-docs-article { min-width: 0; }
.cds-docs-article h2 {
  font-size: 28px;
  font-weight: 400;
  margin: 40px 0 16px;
  padding-top: 8px;
  line-height: 1.28;
}
.cds-docs-article h2:first-child { margin-top: 0; }
.cds-docs-article h3 {
  font-size: 20px;
  font-weight: 400;
  margin: 28px 0 12px;
  line-height: 1.35;
}
.cds-docs-article h4 {
  font-size: 16px;
  font-weight: 600;
  margin: 20px 0 8px;
}
.cds-docs-anchor {
  margin-left: 8px;
  color: #8d8d8d;
  text-decoration: none;
  opacity: 0;
  font-size: 0.8em;
}
h2:hover .cds-docs-anchor,
h3:hover .cds-docs-anchor { opacity: 1; }
.cds-docs-article p { margin: 0 0 16px; color: #161616; }
.cds-docs-article ul,
.cds-docs-article ol { margin: 0 0 18px; padding-left: 24px; }
.cds-docs-article li { margin-bottom: 6px; }
.cds-docs-article a { color: #0f62fe; text-decoration: none; }
.cds-docs-article a:hover { color: #0043ce; text-decoration: underline; }
.cds-docs-article code {
  background: #f4f4f4;
  border: 1px solid #e0e0e0;
  padding: 1px 5px;
  font-size: 13px;
}
.cds-docs-code-block {
  margin: 16px 0 24px;
  background: #f4f4f4;
  border: 1px solid #e0e0e0;
}
.cds-docs-code-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 12px;
  background: #e0e0e0;
  font-size: 12px;
  color: #525252;
}
.cds-docs-copy-btn {
  background: #161616;
  color: #ffffff;
  border: 0;
  padding: 3px 10px;
  font-size: 12px;
  cursor: pointer;
}
.cds-docs-copy-btn:hover { background: #393939; }
.cds-docs-code-block pre {
  margin: 0;
  padding: 16px;
  overflow-x: auto;
  font-size: 13px;
  line-height: 1.5;
}
.cds-docs-code-block pre code {
  background: transparent;
  border: 0;
  padding: 0;
}
.cds-docs-mermaid-wrap {
  margin: 16px 0 24px;
  padding: 16px;
  background: #f4f4f4;
  border: 1px solid #e0e0e0;
  overflow-x: auto;
}
.cds-docs-table-wrap { overflow-x: auto; margin: 16px 0 24px; }
.cds-docs-table { width: 100%; border-collapse: collapse; font-size: 14px; }
.cds-docs-table th {
  background: #e0e0e0;
  color: #161616;
  font-weight: 600;
  padding: 10px 14px;
  border-bottom: 1px solid #c6c6c6;
}
.cds-docs-table td {
  padding: 10px 14px;
  background: #ffffff;
  border-bottom: 1px solid #e0e0e0;
  vertical-align: top;
}
.cds-docs-article blockquote,
.cds-docs-callout {
  margin: 16px 0 20px;
  padding: 14px 18px;
  background: #f4f4f4;
  border-left: 3px solid #0f62fe;
}
.cds-docs-callout--warning { border-left-color: #f1c21b; background: #fcf4d6; }
.cds-docs-figure { margin: 16px 0 24px; }
.cds-docs-figure img { max-width: 100%; border: 1px solid #e0e0e0; display: block; }
.cds-docs-figure figcaption { font-size: 12px; color: #525252; margin-top: 6px; }
.cds-docs-article hr { border: 0; border-top: 1px solid #e0e0e0; margin: 32px 0; }

/* Sticky Right TOC ("On this page") */
.cds-docs-toc {
  position: sticky;
  top: 72px;
  border-left: 1px solid #e0e0e0;
  padding-left: 16px;
}
.cds-docs-toc__title {
  font-size: 12px;
  font-weight: 600;
  color: #525252;
  margin: 0 0 10px;
}
.cds-docs-toc__list { list-style: none; margin: 0; padding: 0; }
.cds-docs-toc__link {
  display: block;
  padding: 4px 0;
  font-size: 13px;
  color: #525252;
  text-decoration: none;
}
.cds-docs-toc__link--sub { padding-left: 12px; }
.cds-docs-toc__link:hover { color: #0f62fe; }

/* Previous / Next Tiles + Footer */
.cds-docs-pager {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  border-top: 1px solid #393939;
  background: #262626;
}
.cds-docs-pager-tile {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  min-height: 112px;
  padding: 20px 32px;
  color: #f4f4f4;
  text-decoration: none;
  border-right: 1px solid #393939;
}
.cds-docs-pager-tile:hover { background: #353535; }
.cds-docs-pager-dir { font-size: 12px; color: #c6c6c6; }
.cds-docs-pager-title { font-size: 20px; font-weight: 400; color: #ffffff; }
.cds-docs-footer {
  background: #161616;
  color: #c6c6c6;
  padding: 24px 48px;
  font-size: 13px;
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 12px;
}
.cds-docs-footer a { color: #78a9ff; text-decoration: none; }

@media (max-width: 1120px) {
  .cds-docs-grid { grid-template-columns: minmax(0, 1fr); padding: 32px 24px 48px; }
  .cds-docs-toc { display: none; }
}
@media (max-width: 960px) {
  .cds-docs-header__brand-zone { width: auto; flex: 0 0 auto; }
  .cds-docs-menu-btn { display: inline-flex; }
  .cds-docs-header-nav { display: none; }
  .cds-docs-sidenav { transform: translateX(-100%); transition: transform 0.16s ease; }
  .cds-docs-sidenav.open { transform: translateX(0); box-shadow: 0 4px 16px rgba(0, 0, 0, 0.25); }
  .cds-docs-shell { margin-left: 0; }
  .cds-docs-hero { padding: 28px 24px; }
  .cds-docs-pager { grid-template-columns: 1fr; }
}
""".strip()


def _render_html_page(
    page: DocPage,
    all_pages: List[DocPage],
    prev_page: Optional[DocPage],
    next_page: Optional[DocPage],
    base_url: str,
    has_carbon_css: bool,
) -> str:
    user_pages = [p for p in all_pages if p.section == "user-guide"]
    dev_overview = [p for p in all_pages if p.section == "developer-guide" and p.group == "Developer Guide"]
    dev_core = [p for p in all_pages if p.section == "developer-guide" and p.group == "Core Architecture"]
    dev_specs = [p for p in all_pages if p.section == "developer-guide" and p.group == "Page Specifications"]

    def nav_items(items: List[DocPage], extra_cls: str = "") -> str:
        out: List[str] = []
        for item in items:
            active = " active" if item.route == page.route else ""
            out.append(
                f'<li><a class="cds-docs-nav-link{extra_cls}{active}" href="{html.escape(base_url + item.route, quote=True)}">'
                f"{html.escape(item.title)}</a></li>"
            )
        return "\n".join(out)

    ug_expanded = "true" if page.section in ("home", "user-guide") else "false"
    dg_expanded = "true" if page.section == "developer-guide" else "false"

    carbon_links = ""
    if has_carbon_css:
        carbon_links = (
            f'<link rel="stylesheet" href="{base_url}/vendor/carbon--styles/css/styles.min.css" />\n'
            f'  <link rel="stylesheet" href="{base_url}/vendor/fontsource--ibm-plex-sans/300.css" />\n'
            f'  <link rel="stylesheet" href="{base_url}/vendor/fontsource--ibm-plex-sans/400.css" />\n'
            f'  <link rel="stylesheet" href="{base_url}/vendor/fontsource--ibm-plex-sans/600.css" />\n'
            f'  <link rel="stylesheet" href="{base_url}/vendor/fontsource--ibm-plex-mono/400.css" />\n'
        )

    toc_html = ""
    if page.toc:
        toc_items = "\n".join(
            f'<li><a class="cds-docs-toc__link{" cds-docs-toc__link--sub" if lvl == 3 else ""}" '
            f'href="#{html.escape(slug, quote=True)}">{html.escape(lbl)}</a></li>'
            for lvl, slug, lbl in page.toc
        )
        toc_html = (
            '<aside class="cds-docs-toc" aria-label="On this page">'
            '<p class="cds-docs-toc__title">On this page</p>'
            f'<ul class="cds-docs-toc__list">{toc_items}</ul>'
            "</aside>"
        )

    prev_html = (
        f'<a class="cds-docs-pager-tile" href="{html.escape(base_url + prev_page.route, quote=True)}">'
        f'<span class="cds-docs-pager-dir">Previous</span>'
        f'<span class="cds-docs-pager-title">{html.escape(prev_page.title)}</span></a>'
        if prev_page
        else '<div class="cds-docs-pager-tile"></div>'
    )
    next_html = (
        f'<a class="cds-docs-pager-tile" href="{html.escape(base_url + next_page.route, quote=True)}">'
        f'<span class="cds-docs-pager-dir">Next</span>'
        f'<span class="cds-docs-pager-title">{html.escape(next_page.title)}</span></a>'
        if next_page
        else '<div class="cds-docs-pager-tile"></div>'
    )

    page_doc_title = f"{page.title} - aethernms Docs" if page.route != "/" else "aethernms Docs"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(page_doc_title)}</title>
  <link rel="icon" type="image/svg+xml" href="{base_url}/assets/aethernms.svg" />
  <link rel="icon" href="{base_url}/assets/favicon.ico" sizes="any" />
  <link rel="apple-touch-icon" href="{base_url}/assets/apple-touch-icon.png" />
  {carbon_links}<link rel="stylesheet" href="{base_url}/assets/docs.css" />
</head>
<body>
  <header class="cds-docs-header">
    <div class="cds-docs-header__brand-zone">
      <button type="button" id="docs-menu-btn" class="cds-docs-menu-btn" aria-label="Toggle navigation">
        <svg width="20" height="20" viewBox="0 0 32 32" fill="currentColor" aria-hidden="true">
          <path d="M4 6h24v2H4zm0 9h24v2H4zm0 9h24v2H4z"/>
        </svg>
      </button>
      <a class="cds-docs-brand" href="{base_url}/">
        <span class="cds-docs-wordmark">ÆTHER</span>
        <span class="cds-docs-sub">NMS Docs</span>
      </a>
    </div>

    <nav class="cds-docs-header-nav" aria-label="Primary documentation sections">
      <a class="cds-docs-header-link{" active" if page.section == "user-guide" else ""}" href="{base_url}/user-guide/">User Guide</a>
      <a class="cds-docs-header-link{" active" if page.section == "developer-guide" else ""}" href="{base_url}/developer-guide/">Developer Guide</a>
      <a class="cds-docs-header-link" href="https://github.com/eduardomozart/aethernms" target="_blank" rel="noopener noreferrer">GitHub</a>
    </nav>

    <div class="cds-docs-search-wrap">
      <input id="docs-search-input" class="cds-docs-search-input" type="search" placeholder="Search documentation..." aria-label="Search documentation" autocomplete="off" />
      <svg class="cds-docs-search-icon" width="16" height="16" viewBox="0 0 32 32" fill="currentColor" aria-hidden="true">
        <path d="M29 27.586l-7.552-7.552a11.018 11.018 0 1 0-1.414 1.414L27.586 29zM4 13a9 9 0 1 1 9 9 9.01 9.01 0 0 1-9-9z"/>
      </svg>
      <div id="docs-search-results" class="cds-docs-search-results hidden"></div>
    </div>
  </header>

  <aside id="docs-sidenav" class="cds-docs-sidenav" aria-label="Documentation navigation">
    <a class="cds-docs-nav-top-link{" active" if page.route == "/" else ""}" href="{base_url}/">Overview</a>

    <button type="button" class="cds-docs-nav-group-btn" aria-expanded="{ug_expanded}" data-nav-group>
      <span>User Guide</span>
      <span>▾</span>
    </button>
    <ul class="cds-docs-nav-list">
      {nav_items(user_pages)}
    </ul>

    <button type="button" class="cds-docs-nav-group-btn" aria-expanded="{dg_expanded}" data-nav-group>
      <span>Developer Guide</span>
      <span>▾</span>
    </button>
    <ul class="cds-docs-nav-list">
      {nav_items(dev_overview)}
      {nav_items(dev_core)}
      <li class="cds-docs-nav-sublabel">Per-Page Specifications</li>
      {nav_items(dev_specs, " cds-docs-nav-link--deep")}
    </ul>
  </aside>

  <main class="cds-docs-shell">
    <div class="cds-docs-hero">
      <div class="cds-docs-hero__eyebrow">{html.escape(page.group)}</div>
      <h1 class="cds-docs-hero__title">{html.escape(page.title)}</h1>
    </div>

    <div class="cds-docs-grid">
      <article class="cds-docs-article">
        {page.html_body}
      </article>
      {toc_html}
    </div>

    <div class="cds-docs-pager">
      {prev_html}
      {next_html}
    </div>

    <footer class="cds-docs-footer">
      <span><strong>ÆTHER NMS</strong> — Built with IBM Carbon Design System v11 &amp; Py4Web</span>
      <span>
        <a href="{base_url}/user-guide/">User Guide</a> ·
        <a href="{base_url}/developer-guide/">Developer Guide</a> ·
        <a href="https://github.com/eduardomozart/aethernms" target="_blank" rel="noopener noreferrer">Repository</a>
      </span>
    </footer>
  </main>

  <script>
    window.__DOCS_BASE = {json.dumps(base_url)};
  </script>
  <script src="{base_url}/assets/docs.js"></script>
</body>
</html>
"""


def _docs_script() -> str:
    return """
(function () {
  "use strict";
  const base = window.__DOCS_BASE || "";

  // Mobile drawer toggle
  const menuBtn = document.getElementById("docs-menu-btn");
  const sidenav = document.getElementById("docs-sidenav");
  if (menuBtn && sidenav) {
    menuBtn.addEventListener("click", () => sidenav.classList.toggle("open"));
  }

  // Collapsible nav groups
  document.querySelectorAll("[data-nav-group]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const exp = btn.getAttribute("aria-expanded") === "true";
      btn.setAttribute("aria-expanded", exp ? "false" : "true");
    });
  });

  // Copy code buttons
  document.querySelectorAll("[data-copy-code]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const codeEl = btn.closest(".cds-docs-code-block").querySelector("code");
      if (!codeEl || !navigator.clipboard) return;
      try {
        await navigator.clipboard.writeText(codeEl.textContent || "");
        const prev = btn.textContent;
        btn.textContent = "Copied";
        setTimeout(() => { btn.textContent = prev; }, 1400);
      } catch (_e) {}
    });
  });

  // Client-side full-text documentation search
  const searchInput = document.getElementById("docs-search-input");
  const resultsBox = document.getElementById("docs-search-results");
  let searchIndex = null;

  async function ensureIndex() {
    if (searchIndex !== null) return searchIndex;
    try {
      const res = await fetch(base + "/search-index.json");
      searchIndex = res.ok ? await res.json() : [];
    } catch (_e) {
      searchIndex = [];
    }
    return searchIndex;
  }

  function escHtml(s) {
    return String(s || "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
  }

  if (searchInput && resultsBox) {
    searchInput.addEventListener("input", async () => {
      const q = searchInput.value.trim().toLowerCase();
      if (!q) {
        resultsBox.classList.add("hidden");
        resultsBox.innerHTML = "";
        return;
      }
      const idx = await ensureIndex();
      const hits = idx
        .filter((item) =>
          (item.title || "").toLowerCase().includes(q) ||
          (item.group || "").toLowerCase().includes(q) ||
          (item.body || "").toLowerCase().includes(q)
        )
        .slice(0, 8);
      if (!hits.length) {
        resultsBox.innerHTML = '<div class="cds-docs-search-item"><span class="cds-docs-search-item-meta">No matching documentation pages</span></div>';
      } else {
        resultsBox.innerHTML = hits
          .map(
            (h) =>
              `<a class="cds-docs-search-item" href="${base}${h.route}">` +
              `<span class="cds-docs-search-item-meta">${escHtml(h.sectionLabel)} · ${escHtml(h.group)}</span>` +
              `<span class="cds-docs-search-item-title">${escHtml(h.title)}</span></a>`
          )
          .join("");
      }
      resultsBox.classList.remove("hidden");
    });

    document.addEventListener("click", (ev) => {
      if (!searchInput.contains(ev.target) && !resultsBox.contains(ev.target)) {
        resultsBox.classList.add("hidden");
      }
    });
  }

  // Optional progressive-enhancement Mermaid rendering
  if (document.querySelector(".mermaid")) {
    const s = document.createElement("script");
    s.type = "module";
    s.textContent =
      "import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';" +
      "mermaid.initialize({ startOnLoad: true, theme: 'neutral' });";
    document.body.appendChild(s);
  }
})();
""".strip()


def build_site(
    root_dir: Path = ROOT_DIR,
    output_dir: Path = ROOT_DIR / "_site",
    base_url: str = "/aethernms",
) -> List[Path]:
    """Build complete Carbon-styled static documentation site into output_dir."""
    norm_base = base_url.rstrip("/")
    if norm_base == "/":
        norm_base = ""

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    asset_info = _copy_static_assets(root_dir, output_dir)
    assets_dir = output_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    (assets_dir / "docs.css").write_text(_docs_stylesheet(), encoding="utf-8")
    (assets_dir / "docs.js").write_text(_docs_script(), encoding="utf-8")

    pages, aliases = collect_pages(root_dir)
    for pg in pages:
        body_html, parsed_h1, toc, plain_text = render_markdown(
            pg.markdown_text, norm_base, aliases
        )
        pg.html_body = body_html
        if parsed_h1 and pg.group != "Page Specifications":
            pg.title = parsed_h1
        pg.toc = toc
        pg.plain_text = plain_text

    written: List[Path] = []
    search_index: List[Dict[str, str]] = []

    for idx, pg in enumerate(pages):
        prev_pg = pages[idx - 1] if idx > 0 else None
        next_pg = pages[idx + 1] if idx + 1 < len(pages) else None
        html_doc = _render_html_page(
            pg,
            pages,
            prev_pg,
            next_pg,
            norm_base,
            asset_info["has_carbon_css"],
        )
        rel = pg.route.strip("/")
        dest = (output_dir / rel / "index.html") if rel else (output_dir / "index.html")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(html_doc, encoding="utf-8")
        written.append(dest)

        section_label = (
            "Overview"
            if pg.section == "home"
            else ("User Guide" if pg.section == "user-guide" else "Developer Guide")
        )
        search_index.append(
            {
                "title": pg.title,
                "sectionLabel": section_label,
                "group": pg.group,
                "route": pg.route,
                "body": pg.plain_text[:4000],
            }
        )

    # Search index, .nojekyll, and 404 fallback
    search_file = output_dir / "search-index.json"
    search_file.write_text(json.dumps(search_index, ensure_ascii=False, indent=2), encoding="utf-8")
    written.append(search_file)

    nojekyll = output_dir / ".nojekyll"
    nojekyll.write_text("", encoding="utf-8")
    written.append(nojekyll)

    not_found_pg = DocPage(
        section="home",
        group="404",
        title="Page Not Found",
        route="/404.html",
        source_path=None,
        html_body=(
            f"<p>The requested documentation page does not exist. "
            f'Continue to the <a href="{norm_base}/user-guide/">User Guide</a> '
            f'or <a href="{norm_base}/developer-guide/">Developer Guide</a>.</p>'
        ),
    )
    not_found_file = output_dir / "404.html"
    not_found_file.write_text(
        _render_html_page(not_found_pg, pages, None, None, norm_base, asset_info["has_carbon_css"]),
        encoding="utf-8",
    )
    written.append(not_found_file)
    return written


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build aethernms GitHub Pages documentation site.")
    parser.add_argument("--output", default="_site", help="Output directory (default: _site)")
    parser.add_argument(
        "--base-url",
        default="/aethernms",
        help="Site base path prefix (default: /aethernms; pass '' for root preview)",
    )
    args = parser.parse_args(argv)
    out = Path(args.output)
    if not out.is_absolute():
        out = ROOT_DIR / out
    written = build_site(ROOT_DIR, out, base_url=args.base_url)
    print(f"Built {len(written)} documentation artifacts into {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
