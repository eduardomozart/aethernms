"""Command script parsing (! comments) and Aruba CLI error detection."""

from __future__ import annotations

import re
from typing import Dict, List, Tuple


ERROR_PATTERNS: List[Tuple[str, re.Pattern[str]]] = [
    ("invalid_input", re.compile(r"(?:^|\s)Invalid input:", re.IGNORECASE)),
    ("cx_invalid", re.compile(r"^%\s*Invalid\b", re.IGNORECASE)),
    ("ambiguous", re.compile(r"(?:Ambiguous input:|^%\s*Ambiguous\b)", re.IGNORECASE)),
    ("incomplete", re.compile(r"(?:Incomplete input|^%\s*Command incomplete\b)", re.IGNORECASE)),
    ("unknown_cmd", re.compile(r"Unknown command", re.IGNORECASE)),
    ("exec_error", re.compile(r"(?:^Error:\s*|Operation failed|Commit failed)", re.IGNORECASE)),
    ("not_found", re.compile(r"(?:does not exist|No such user|not found)", re.IGNORECASE)),
    (
        "auth_error",
        re.compile(
            r"(?:Permission denied|Authorization failed|Authentication failed|Access denied)",
            re.IGNORECASE,
        ),
    ),
    ("rejected", re.compile(r"(?:Unable to |Cannot )", re.IGNORECASE)),
    (
        "ssh_comm",
        re.compile(r"(?:Connection timed out|Timed out waiting|SSH connection error)", re.IGNORECASE),
    ),
]


def _error_info(code: str) -> Tuple[str, str]:
    """Return canonical English (reason, suggestion) for a CLI error rule code."""
    catalog = {
        "invalid_input": (
            "Invalid CLI input",
            "Check command syntax, Switch OS (AOS-S vs AOS-CX), and configuration context (e.g., configure terminal).",
        ),
        "cx_invalid": (
            "Invalid command or parameter",
            "Verify ArubaOS-CX syntax and confirm the switch is in the required configuration context.",
        ),
        "ambiguous": (
            "Ambiguous command",
            "Spell out the full command keyword so it is unambiguous.",
        ),
        "incomplete": (
            "Incomplete command",
            "Provide all required command parameters on the same line.",
        ),
        "unknown_cmd": (
            "Unknown command",
            "Verify this command is supported by the target firmware and switch OS.",
        ),
        "exec_error": (
            "Execution error",
            "Review the switch output around this line and check configuration prerequisites.",
        ),
        "not_found": (
            "Target entity not found",
            "The referenced user, VLAN, or object does not exist on this switch.",
        ),
        "auth_error": (
            "Authentication / Authorization failure",
            "Verify SSH credentials and confirm the account has Manager / admin privileges.",
        ),
        "rejected": (
            "Command rejected by switch",
            "Check switch state or prerequisites required before executing this command.",
        ),
        "ssh_comm": (
            "SSH communication error",
            "Verify reachability, SSH service status on the switch, or increase timeout settings.",
        ),
    }
    return catalog.get(code, ("CLI error", "Check device output for details."))


def parse_commands(raw_text: str) -> List[str]:
    """
    Parse raw script text into executable CLI commands.
    - Blank lines are skipped.
    - Lines starting with '!' are treated as comments and skipped.
    - '!' characters inside command arguments/quoted strings are preserved intact.
    """
    if not raw_text:
        return []

    commands: List[str] = []
    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("!"):
            continue
        commands.append(line)
    return commands


def detect_output_errors(output_text: str) -> List[Dict[str, object]]:
    """
    Scan switch CLI output line-by-line and return structured error diagnostics:
      [{'line_no': int, 'text': str, 'reason': str, 'suggestion': str}, ...]
    """
    if not output_text:
        return []

    findings: List[Dict[str, object]] = []
    for line_no, raw_line in enumerate(output_text.splitlines(), start=1):
        cleaned = raw_line.strip()
        if not cleaned or cleaned.startswith("!"):
            continue
        for code, pattern in ERROR_PATTERNS:
            if pattern.search(cleaned):
                reason, suggestion = _error_info(code)
                findings.append(
                    {
                        "line_no": line_no,
                        "text": cleaned,
                        "reason": reason,
                        "suggestion": suggestion,
                    }
                )
                break
    return findings


def validate_audit_regex(output_text: str, audit_regex_text: str) -> List[Dict[str, object]]:
    """
    Validate expected RegEx pattern(s) against combined switch CLI output.
    Non-empty lines (ignoring lines starting with '!') are evaluated with re.MULTILINE;
    any pattern not found (or invalid regex syntax) is returned as a structured error finding.
    """
    patterns = [
        line.strip()
        for line in (audit_regex_text or "").splitlines()
        if line.strip() and not line.strip().startswith("!")
    ]
    if not patterns:
        return []

    text = output_text or ""
    last_line_no = max(1, len(text.splitlines()))
    findings: List[Dict[str, object]] = []

    for pat_str in patterns:
        try:
            compiled = re.compile(pat_str, re.MULTILINE)
        except re.error as exc:
            findings.append(
                {
                    "line_no": last_line_no,
                    "text": pat_str,
                    "reason": f"Invalid audit RegEx: {exc}",
                    "suggestion": "Correct the regular expression syntax in Audit Validation RegEx.",
                }
            )
            continue

        if compiled.search(text) is None:
            findings.append(
                {
                    "line_no": last_line_no,
                    "text": pat_str,
                    "reason": "Expected audit RegEx not found in output",
                    "suggestion": f"Switch output did not match the required audit pattern: {pat_str}",
                }
            )

    return findings
