"""Execution logging under logs/YYYY-MM-DD_HH-MM-SS/<hostname-or-switch-ip>.log."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
from typing import Optional

from aethernms.models import HostEntry, HostExecutionResult
from aethernms.paths import get_logs_dir


DEFAULT_LOGS_DIR = get_logs_dir()


def format_run_timestamp(dt: Optional[datetime] = None) -> str:
    """Format run directory timestamp as YYYY-MM-DD_HH-MM-SS."""
    target = dt or datetime.now()
    return target.strftime("%Y-%m-%d_%H-%M-%S")


def create_run_log_dir(
    base_dir: Path | str = DEFAULT_LOGS_DIR,
    dt: Optional[datetime] = None,
) -> Path:
    """Create and return logs/YYYY-MM-DD_HH-MM-SS directory."""
    run_dir = Path(base_dir) / format_run_timestamp(dt)
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def sanitize_log_filename(host: HostEntry) -> str:
    """Return a filesystem-safe '<hostname-or-switch-ip>.log' filename."""
    identifier = (host.name or "").strip() or (host.ip or "").strip() or "unknown_host"
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", identifier).strip(". ")
    safe = safe or "unknown_host"
    return f"{safe}.log"


def format_host_log(result: HostExecutionResult) -> str:
    """
    Format execution metadata, connection method, detected errors, and terminal output
    into the canonical per-device log transcript (stored in SQLite or exported as .log).
    """
    conn_desc = result.connection_method or (
        f"{result.host.protocol.value} ({result.host.os_type or '-'})"
    )

    lines = [
        "=" * 78,
        f"Host Name       : {result.host.name or '(unnamed)'}",
        f"IP Address      : {result.host.ip}:{result.host.port}",
        f"Connection      : {conn_desc}",
        f"Netmiko Platform: {result.host.os_type or '-'}",
        f"Model / FW      : {result.host.model or '-'} / {result.host.firmware or '-'}",
        f"Status          : {result.status}",
        f"Operation Result: {result.operation_result}",
        f"Started At      : {result.started_at}",
        f"Finished At     : {result.finished_at}",
        "=" * 78,
    ]

    if result.exception_message:
        lines.extend(["", "--- Connection / Execution Exception ---", result.exception_message])

    if result.error_lines:
        lines.extend(["", "--- Detected Errors ---"])
        for err in result.error_lines:
            lines.append(
                f"Line {err['line_no']}: {err['text']}  [{err['reason']}] -> {err['suggestion']}"
            )

    lines.extend(
        [
            "",
            f"--- Raw {result.host.protocol.value} Terminal Output ---",
            result.raw_output or "(No output captured)",
            "",
        ]
    )
    return "\n".join(lines)


def write_host_log(result: HostExecutionResult, run_dir: Path | str) -> str:
    """
    Write execution metadata, connection method, detected errors, and terminal output
    to `logs/YYYY-MM-DD_HH-MM-SS/<hostname-or-switch-ip>.log`.
    """
    out_dir = Path(run_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_file = out_dir / sanitize_log_filename(result.host)
    formatted = format_host_log(result)
    result.formatted_log = formatted
    log_file.write_text(formatted, encoding="utf-8")
    result.log_path = str(log_file)
    return str(log_file)
