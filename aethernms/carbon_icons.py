"""Official IBM Carbon SVG icon loader backed by Composer's @iconify-json/carbon package."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

from aethernms.paths import get_static_dir


_ICON_CACHE: Optional[Dict[str, str]] = None

# Compact subset of icons sent to frontend JS via /api/meta for dynamic table/toolbar rendering.
UI_JS_ICON_NAMES = (
    "add",
    "api",
    "checkmark-filled",
    "chevron-down",
    "chevron-left",
    "chevron-right",
    "close",
    "cloud-download",
    "code",
    "copy",
    "document",
    "download",
    "edit",
    "error-filled",
    "information",
    "key",
    "locked",
    "logout",
    "menu",
    "network-4",
    "page-first",
    "page-last",
    "password",
    "renew",
    "search",
    "security",
    "settings",
    "settings-services",
    "stop-outline",
    "task",
    "trash-can",
    "upload",
    "user-avatar",
    "user-multiple",
    "view",
    "view-off",
    "warning-filled",
)


def _icons_json_path() -> Path:
    return get_static_dir() / "vendor" / "npm-asset" / "iconify-json--carbon" / "icons.json"


def _load_icon_map() -> Dict[str, str]:
    global _ICON_CACHE
    if _ICON_CACHE is not None:
        return _ICON_CACHE

    path = _icons_json_path()
    mapping: Dict[str, str] = {}
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            icons = raw.get("icons") or {}
            aliases = raw.get("aliases") or {}
            for k, v in icons.items():
                if isinstance(v, dict) and isinstance(v.get("body"), str):
                    mapping[k] = v["body"]
            for ak, av in aliases.items():
                if isinstance(av, dict) and av.get("parent") in mapping:
                    mapping[ak] = mapping[av["parent"]]
        except Exception:
            mapping = {}
    _ICON_CACHE = mapping
    return mapping


def reset_icon_cache() -> None:
    """Clear the cached icon table (useful in tests or after composer install)."""
    global _ICON_CACHE
    _ICON_CACHE = None


def get_icon_body(name: str) -> str:
    """Return raw inner SVG markup for a Carbon icon name (empty string if missing)."""
    return _load_icon_map().get((name or "").strip(), "")


def carbon_icon(name: str, size: int = 16, css_class: str = "") -> str:
    """Render an official IBM Carbon inline SVG icon (`viewBox='0 0 32 32'`)."""
    body = get_icon_body(name)
    cls_attr = f' class="{css_class}"' if css_class else ""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" '
        f'width="{int(size)}" height="{int(size)}" fill="currentColor" '
        f'focusable="false" aria-hidden="true"{cls_attr}>{body}</svg>'
    )


def export_ui_icon_subset() -> Dict[str, str]:
    """Export only the SVG inner bodies needed by browser JS modules."""
    icons = _load_icon_map()
    return {name: icons[name] for name in UI_JS_ICON_NAMES if name in icons}
