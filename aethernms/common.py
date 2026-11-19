"""Shared pure-Python localization formatters and device filtering helpers."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence, Tuple

from aethernms.i18n import _, ngettext
from aethernms.models import SnippetType


def _snippet_type_label(st: SnippetType | str) -> str:
    """Return translated UI display label for a SnippetType enum or canonical string."""
    val = st.value if isinstance(st, SnippetType) else str(st)
    if val == SnippetType.CONFIG.value:
        return _("Config")
    if val == SnippetType.AUDIT.value:
        return _("Audit and Remediate")
    return _(val)


_OP_ERR_RE = re.compile(r"^(\d+)\s+errors?(?:\(s\))?\s+detected(?::\s*(.+))?$")
_OP_AUDIT_RE = re.compile(r"^Audit failed \((\d+)\s+RegEx patterns?(?:\(s\))?\s+not matched\)$")
_OP_DONE_RE = re.compile(r"^Completed \((\d+)\s+commands?\)$")
_OP_SKIP_OS_RE = re.compile(r"^Skipped \(no commands for (.+)\)$")


def _translate_error_reason(reason: str) -> str:
    """Translate canonical English CLI/audit diagnostic reasons for UI display."""
    cleaned = (reason or "").strip()
    mapping = {
        "Invalid CLI input": _("Invalid CLI input"),
        "Invalid command or parameter": _("Invalid command or parameter"),
        "Ambiguous command": _("Ambiguous command"),
        "Incomplete command": _("Incomplete command"),
        "Unknown command": _("Unknown command"),
        "Execution error": _("Execution error"),
        "Target entity not found": _("Target entity not found"),
        "Authentication / Authorization failure": _("Authentication / Authorization failure"),
        "rejected": _("Command rejected by switch"),
        "Command rejected by switch": _("Command rejected by switch"),
        "SSH communication error": _("SSH communication error"),
        "Communication error": _("Communication error"),
        "CLI error": _("CLI error"),
        "Expected audit RegEx not found in output": _("Expected audit RegEx not found in output"),
    }
    if cleaned in mapping:
        return mapping[cleaned]
    if cleaned.startswith("Invalid audit RegEx:"):
        detail = cleaned.split(":", 1)[1].strip()
        return _("Invalid audit RegEx: {err}").format(err=detail)
    return cleaned


def format_operation_result_ui(operation_result: str) -> str:
    """Format canonical English HostExecutionResult.operation_result for the active UI locale."""
    raw = (operation_result or "").strip()
    if not raw:
        return ""

    m_err = _OP_ERR_RE.match(raw)
    if m_err:
        count = int(m_err.group(1))
        prefix = ngettext("%d error detected", "%d errors detected", count) % count
        reason = (m_err.group(2) or "").strip()
        return f"{prefix}: {_translate_error_reason(reason)}" if reason else prefix

    m_aud = _OP_AUDIT_RE.match(raw)
    if m_aud:
        count = int(m_aud.group(1))
        return (
            ngettext(
                "Audit failed (%d RegEx pattern not matched)",
                "Audit failed (%d RegEx patterns not matched)",
                count,
            )
            % count
        )

    m_done = _OP_DONE_RE.match(raw)
    if m_done:
        count = int(m_done.group(1))
        return ngettext("Completed (%d command)", "Completed (%d commands)", count) % count

    m_skip = _OP_SKIP_OS_RE.match(raw)
    if m_skip:
        return _("Skipped (no commands for {os})").format(os=m_skip.group(1))

    fixed = {
        "Audit failed": _("Audit failed"),
        "Executing...": _("Executing..."),
        "Cancelled by operator": _("Cancelled by operator"),
        "Cancelled before start": _("Cancelled before start"),
        "Authentication failed": _("Authentication failed"),
        "SSH connection error": _("SSH connection error"),
        "Connection error": _("Connection error"),
        "Unexpected worker error": _("Unexpected worker error"),
    }
    return fixed.get(raw, raw)


def _is_all_filter(val: str) -> bool:
    """Return True if a filter dropdown value represents 'All' (canonical or translated)."""
    return (val or "").strip() in ("", "All", _("All"))


def _status_label(canonical: str) -> str:
    """Return localized display label for canonical device statuses ('Up', 'Down', 'Unknown')."""
    val = (canonical or "").strip()
    if val in ("Up", "Down", "Unknown"):
        return _(val)
    return val


def _canonical_device_status(val: str) -> str:
    """Normalize a localized or canonical status label to 'All', 'Up', 'Down', or 'Unknown'."""
    raw = (val or "").strip()
    if _is_all_filter(raw):
        return "All"
    for canonical in ("Up", "Down", "Unknown"):
        if raw.lower() in (canonical.lower(), _(canonical).lower()):
            return canonical
    return raw


def _canonical_os_filter(val: str) -> str:
    """Normalize a localized OS/platform filter label to its canonical key."""
    raw = (val or "").strip()
    if _is_all_filter(raw):
        return "All"
    if raw.lower() in ("unmapped", _("Unmapped").lower(), "unknown", _("Unknown").lower()):
        return "Unmapped"
    return raw


def filter_device_hosts(
    hosts: Sequence[Any],
    name_q: str = "",
    ip_q: str = "",
    os_q: str = "All",
    group_q: str = "",
    status_q: str = "All",
) -> Tuple[List[Tuple[int, Any]], List[Any]]:
    """Filter device hosts by name, IP, Netmiko platform, group, and live ping status."""
    nq = (name_q or "").strip().lower()
    iq = (ip_q or "").strip().lower()
    oq = _canonical_os_filter(os_q)
    gq = (group_q or "").strip().lower()
    sq = _canonical_device_status(status_q)

    indexed: List[Tuple[int, Any]] = []
    filtered: List[Any] = []
    for idx, h in enumerate(hosts):
        if nq and nq not in (h.name or "").lower():
            continue
        if iq and iq not in (h.ip or "").lower():
            continue
        if oq != "All":
            if oq == "Unmapped":
                if (h.os_type or "").strip():
                    continue
            elif (h.os_type or "").strip().lower() != oq.lower():
                continue
        if gq and gq not in (h.folder_path or "").lower():
            continue
        if sq != "All" and (h.ping_status or "Unknown") != sq:
            continue
        indexed.append((idx, h))
        filtered.append(h)
    return indexed, filtered
