"""Tests for execution logging at logs/YYYY-MM-DD_HH-MM-SS/<hostname-or-switch-ip>.log."""

from datetime import datetime
from pathlib import Path

from pssh_ui.logger import create_run_log_dir, sanitize_log_filename, write_host_log
from pssh_ui.models import CommandStepResult, HostEntry, HostExecutionResult, SwitchOS


def test_log_directory_uses_yyyy_mm_dd_hh_mm_ss_and_host_filename(tmp_path: Path):
    dt = datetime(2026, 11, 17, 15, 30, 45)
    run_dir = create_run_log_dir(base_dir=tmp_path / "logs", dt=dt)
    assert run_dir.name == "2026-11-17_15-30-45"
    assert run_dir.is_dir()

    host_named = HostEntry(name="SW/CORE:01", ip="10.0.0.1", os_type=SwitchOS.AOS_CX)
    assert sanitize_log_filename(host_named) == "SW_CORE_01.log"

    host_ip_only = HostEntry(name="", ip="10.0.0.2", os_type=SwitchOS.AOS_S)
    assert sanitize_log_filename(host_ip_only) == "10.0.0.2.log"

    result = HostExecutionResult(
        host=host_ip_only,
        status="Failed",
        operation_result="1 command error(s) detected",
        started_at="2026-11-17 15:30:45",
        finished_at="2026-11-17 15:30:47",
        step_results=[
            CommandStepResult(
                index=1,
                command="badcmd",
                result="Failed",
                suggestion="Invalid CLI input",
            )
        ],
        error_lines=[
            {
                "line_no": 2,
                "text": "Invalid input: badcmd",
                "reason": "Invalid CLI input",
                "suggestion": "Check syntax",
            }
        ],
        raw_output="Switch# badcmd\nInvalid input: badcmd\nSwitch#",
    )

    log_path = Path(write_host_log(result, run_dir))
    assert log_path.name == "10.0.0.2.log"
    assert log_path.parent.name == "2026-11-17_15-30-45"
    content = log_path.read_text(encoding="utf-8")
    assert "Invalid input: badcmd" in content
    assert "10.0.0.2:22" in content
    assert "[01] (Failed) badcmd" in content
