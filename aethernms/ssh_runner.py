"""Parallel & sequential Netmiko SSH/Telnet automation runner with clean terminal capture."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import io
from pathlib import Path
import re
import threading
from typing import Callable, Dict, List, Optional

from netmiko import ConnectHandler
from netmiko.exceptions import (
    ConfigInvalidException,
    NetmikoAuthenticationException,
    NetmikoTimeoutException,
    ReadTimeout,
)

from aethernms.logger import create_run_log_dir, format_host_log, write_host_log
from aethernms.models import (
    CommandStepResult,
    HostEntry,
    HostExecutionResult,
    ScheduleSequence,
    SnippetType,
)
from aethernms.netmiko_catalog import resolve_netmiko_device_type
from aethernms.parser import (
    CONFIG_ERROR_PATTERN,
    detect_output_errors,
    validate_audit_regex,
)


ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?=]*[A-Za-z]|\x1b\][^\x07]*\x07|\x1b[=>()]")
VT100_NEWLINE_RE = re.compile(r"\x1b\[\d+;\d+[Hf]|\x1b\[\d*E")
PAGER_ARTIFACT_RE = re.compile(
    r"(?:Press any key to continue|--\s*MORE\s*--|Press <SPACE> to continue)",
    re.IGNORECASE,
)


def clean_terminal_text(text: str) -> str:
    """Normalize CRLF/VT100 cursor positioning, strip ANSI codes, and resolve backspaces cleanly."""
    if not text:
        return ""
    text = text.replace("\r\n", "\n")
    text = VT100_NEWLINE_RE.sub("\n", text)
    text = ANSI_ESCAPE_RE.sub("", text)
    text = PAGER_ARTIFACT_RE.sub("", text)
    lines: List[str] = []
    for raw_line in text.split("\n"):
        if "\r" in raw_line:
            segments = raw_line.split("\r")
            raw_line = next((seg for seg in reversed(segments) if seg.strip()), segments[-1])
        buf: List[str] = []
        for ch in raw_line:
            if ch in ("\x08", "\x7f"):
                if buf:
                    buf.pop()
            elif ord(ch) >= 32 or ch == "\t":
                buf.append(ch)
        lines.append("".join(buf).rstrip())
    return "\n".join(lines)


def _timestamp_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _apply_exception_output(
    result: HostExecutionResult,
    captured_raw: str,
    exception_message: str,
    operation_result: str,
) -> None:
    """Record exception metadata and append it to raw output without flagging it in Detected Errors."""
    result.status = "Failed"
    result.exception_message = exception_message
    result.operation_result = operation_result
    raw_prefix = clean_terminal_text(captured_raw).rstrip("\n")
    result.raw_output = (
        f"{raw_prefix}\n{exception_message}" if raw_prefix else exception_message
    )
    result.error_lines = detect_output_errors(raw_prefix)


class PSSHClient:
    """Executes CLI command batches over SSH or Telnet via native Netmiko drivers."""

    def __init__(
        self,
        connect_timeout: float = 10.0,
        command_timeout: float = 15.0,
        poll_interval: float = 0.05,
        connect_handler_factory: Optional[Callable[..., object]] = None,
    ) -> None:
        self.connect_timeout = float(connect_timeout)
        self.command_timeout = float(command_timeout)
        self.poll_interval = float(poll_interval)
        self._connect_handler_factory = connect_handler_factory or ConnectHandler

    def execute_commands(
        self,
        host: HostEntry,
        username: str,
        password: str,
        commands: List[str],
        cancel_event: Optional[threading.Event] = None,
        audit_regex: str = "",
        enable_password: str = "",
        job_type: SnippetType = SnippetType.CONFIG,
        include_write: bool = False,
        template_command_count: Optional[int] = None,
    ) -> HostExecutionResult:
        """
        Connect to `host` over SSH or Telnet using Netmiko's native driver and
        execute configuration (`send_config_set`) or audit (`send_command`) steps.
        """
        result = HostExecutionResult(
            host=host,
            status="Running",
            commands_run=list(commands),
            started_at=_timestamp_str(),
        )
        session_buf = io.BytesIO()
        step_outputs: List[str] = []
        conn = None
        netmiko_driver = ""

        def _captured_raw() -> str:
            logged = session_buf.getvalue().decode("utf-8", errors="replace")
            if logged.strip():
                return logged
            return "\n".join(part for part in step_outputs if part)

        try:
            netmiko_driver = resolve_netmiko_device_type(host.os_type, host.protocol)
            result.connection_method = f"{host.protocol.value} ({netmiko_driver})"

            conn_kwargs = {
                "device_type": netmiko_driver,
                "host": host.ip,
                "port": int(host.port),
                "username": username,
                "password": password,
                "secret": enable_password or "",
                "conn_timeout": self.connect_timeout,
                "read_timeout_override": self.command_timeout,
                "session_log": session_buf,
                "session_log_record_writes": True,
            }
            conn = self._connect_handler_factory(**conn_kwargs)

            # Escalate to privileged mode when secret is supplied or before config mode
            should_check_enable = bool(enable_password) or (job_type == SnippetType.CONFIG)
            if should_check_enable:
                try:
                    if hasattr(conn, "check_enable_mode") and not conn.check_enable_mode():
                        if enable_password or hasattr(conn, "enable"):
                            conn.enable()
                except NotImplementedError:
                    pass

            in_config_mode = False
            if job_type == SnippetType.CONFIG and commands:
                try:
                    if hasattr(conn, "config_mode"):
                        cfg_banner = conn.config_mode()
                        if cfg_banner:
                            step_outputs.append(str(cfg_banner))
                        in_config_mode = True
                except NotImplementedError:
                    in_config_mode = False

            abort_reason: Optional[str] = None
            try:
                for idx, cmd in enumerate(commands, start=1):
                    if cancel_event is not None and cancel_event.is_set():
                        now_ts = _timestamp_str()
                        result.step_results.append(
                            CommandStepResult(
                                index=idx,
                                command=cmd,
                                result="Skipped",
                                suggestion="Cancelled by operator.",
                                begin_time=now_ts,
                                finish_time=now_ts,
                            )
                        )
                        continue

                    if abort_reason is not None:
                        now_ts = _timestamp_str()
                        result.step_results.append(
                            CommandStepResult(
                                index=idx,
                                command=cmd,
                                result="Skipped",
                                suggestion=abort_reason,
                                begin_time=now_ts,
                                finish_time=now_ts,
                            )
                        )
                        continue

                    begin_ts = _timestamp_str()
                    step_out = ""
                    timed_out = False
                    step_status = "Succeeded"
                    suggestion = ""

                    try:
                        if job_type == SnippetType.CONFIG:
                            step_out = conn.send_config_set(
                                [cmd],
                                enter_config_mode=not in_config_mode,
                                exit_config_mode=False,
                                read_timeout=self.command_timeout,
                                error_pattern=CONFIG_ERROR_PATTERN,
                            )
                            in_config_mode = True
                        else:
                            step_out = conn.send_command(
                                cmd,
                                read_timeout=self.command_timeout,
                                strip_prompt=False,
                                strip_command=False,
                            )
                    except ConfigInvalidException as exc:
                        step_out = str(exc)
                        step_status = "Failed"
                        suggestion = f"CLI configuration error: {exc}"
                    except (ReadTimeout, NetmikoTimeoutException) as exc:
                        step_out = str(exc)
                        timed_out = True
                        step_status = "Failed"
                        suggestion = (
                            f"Communication error: Timed out waiting for device response after "
                            f"{self.command_timeout:.0f}s."
                        )

                    finish_ts = _timestamp_str()
                    cleaned_step = clean_terminal_text(step_out)
                    if cleaned_step:
                        step_outputs.append(cleaned_step)

                    if not timed_out and step_status == "Succeeded":
                        step_errors = detect_output_errors(cleaned_step)
                        if step_errors:
                            step_status = "Failed"
                            first_err = step_errors[0]
                            suggestion = f"{first_err['reason']}: {first_err['suggestion']}"

                    result.step_results.append(
                        CommandStepResult(
                            index=idx,
                            command=cmd,
                            result=step_status,
                            suggestion=suggestion,
                            begin_time=begin_ts,
                            finish_time=finish_ts,
                            output_snippet=cleaned_step,
                        )
                    )
                    if step_status == "Failed":
                        abort_reason = "Aborted due to earlier command failure."
            finally:
                if in_config_mode and hasattr(conn, "exit_config_mode"):
                    try:
                        exit_out = conn.exit_config_mode()
                        if exit_out:
                            step_outputs.append(clean_terminal_text(str(exit_out)))
                    except Exception:
                        pass

            # Save running configuration natively when requested on Config jobs
            if (
                include_write
                and job_type == SnippetType.CONFIG
                and not (cancel_event is not None and cancel_event.is_set())
                and not any(s.result == "Failed" for s in result.step_results)
                and hasattr(conn, "save_config")
            ):
                try:
                    save_out = conn.save_config()
                    if save_out:
                        step_outputs.append(clean_terminal_text(str(save_out)))
                except NotImplementedError:
                    pass

            result.raw_output = clean_terminal_text(_captured_raw()).strip("\n")
            cli_errors = detect_output_errors(result.raw_output)
            audit_errors = validate_audit_regex(result.raw_output, audit_regex)
            result.error_lines = cli_errors + audit_errors

            failed_steps = [s for s in result.step_results if s.result == "Failed"]
            if cancel_event is not None and cancel_event.is_set():
                result.status = "Failed"
                result.operation_result = "Cancelled by operator"
            elif failed_steps or result.error_lines:
                result.status = "Failed"
                if audit_errors and not failed_steps and not cli_errors:
                    cnt = len(audit_errors)
                    noun = "pattern" if cnt == 1 else "patterns"
                    result.operation_result = f"Audit failed ({cnt} RegEx {noun} not matched)"
                else:
                    err_count = max(len(failed_steps), len(cli_errors)) + len(audit_errors)
                    err_word = "error" if err_count == 1 else "errors"
                    brief = ""
                    if cli_errors:
                        brief = str(cli_errors[0].get("reason") or "")
                    elif audit_errors:
                        brief = str(audit_errors[0].get("reason") or "")
                    elif failed_steps:
                        brief = str(failed_steps[0].suggestion or "").split(":", 1)[0].strip()
                    result.operation_result = (
                        f"{err_count} {err_word} detected: {brief}"
                        if brief
                        else f"{err_count} {err_word} detected"
                    )
            else:
                result.status = "Success"
                counted = (
                    template_command_count
                    if (template_command_count is not None and template_command_count > 0)
                    else len(commands)
                )
                noun = "command" if counted == 1 else "commands"
                result.operation_result = f"Completed ({counted} {noun})"

        except NetmikoAuthenticationException as exc:
            _apply_exception_output(
                result,
                _captured_raw(),
                f"Authentication failed: {exc}",
                "Authentication failed",
            )
        except (NetmikoTimeoutException, OSError, TimeoutError) as exc:
            _apply_exception_output(
                result,
                _captured_raw(),
                f"Connection error: {exc}",
                str(exc) or "Connection error",
            )
        except Exception as exc:
            _apply_exception_output(
                result,
                _captured_raw(),
                f"Connection error: {exc}",
                str(exc) or "Connection error",
            )
        finally:
            result.finished_at = _timestamp_str()
            if conn is not None and hasattr(conn, "disconnect"):
                try:
                    conn.disconnect()
                except Exception:
                    pass

        return result


class BatchSSHExecutor:
    """Runs Netmiko command batches concurrently or sequentially across multiple devices."""

    def __init__(
        self,
        client_factory: Optional[Callable[[], PSSHClient]] = None,
        logs_base_dir: Optional[Path | str] = None,
    ) -> None:
        self._client_factory = client_factory
        self._logs_base_dir = Path(logs_base_dir) if logs_base_dir else None

    def run_batch(
        self,
        hosts: List[HostEntry],
        username: str,
        password: str,
        commands_by_host: Dict[str, List[str]],
        max_parallel: int = 10,
        schedule_sequence: ScheduleSequence = ScheduleSequence.CONCURRENT,
        connect_timeout: float = 10.0,
        command_timeout: float = 15.0,
        cancel_event: Optional[threading.Event] = None,
        on_host_start: Optional[Callable[[HostEntry], None]] = None,
        on_host_complete: Optional[Callable[[HostExecutionResult], None]] = None,
        run_timestamp: Optional[datetime] = None,
        audit_regex_by_host: Optional[Dict[str, str]] = None,
        enable_password: str = "",
        job_type: SnippetType = SnippetType.CONFIG,
        include_write: bool = False,
        template_counts_by_host: Optional[Dict[str, int]] = None,
    ) -> tuple[Optional[Path], List[HostExecutionResult]]:
        """
        Execute commands across `hosts`, populating `formatted_log` on every result
        (and optionally writing `.log` files when `logs_base_dir` was provided).
        Returns (run_log_dir_or_none, results_list).
        """
        run_dir: Optional[Path] = (
            create_run_log_dir(base_dir=self._logs_base_dir, dt=run_timestamp)
            if self._logs_base_dir is not None
            else None
        )

        if not hosts:
            return run_dir, []

        workers = (
            1
            if schedule_sequence == ScheduleSequence.SEQUENTIAL
            else max(1, min(int(max_parallel), len(hosts)))
        )

        log_lock = threading.Lock()
        results_by_key: Dict[str, HostExecutionResult] = {}

        def _finalize_log(item: HostExecutionResult) -> None:
            item.formatted_log = format_host_log(item)
            if run_dir is not None:
                with log_lock:
                    write_host_log(item, run_dir)

        def _worker(host: HostEntry) -> HostExecutionResult:
            if cancel_event is not None and cancel_event.is_set():
                cancelled = HostExecutionResult(
                    host=host,
                    status="Failed",
                    operation_result="Cancelled before start",
                    connection_method=f"{host.protocol.value} ({host.os_type or '-'})",
                    started_at=_timestamp_str(),
                    finished_at=_timestamp_str(),
                )
                _finalize_log(cancelled)
                return cancelled

            if on_host_start is not None:
                on_host_start(host)

            client = (
                self._client_factory()
                if self._client_factory is not None
                else PSSHClient(
                    connect_timeout=connect_timeout,
                    command_timeout=command_timeout,
                )
            )
            host_cmds = commands_by_host.get(host.unique_key, [])
            host_audit_regex = (audit_regex_by_host or {}).get(host.unique_key, "")
            host_tpl_count = (template_counts_by_host or {}).get(host.unique_key)
            res = client.execute_commands(
                host=host,
                username=username,
                password=password,
                commands=host_cmds,
                cancel_event=cancel_event,
                audit_regex=host_audit_regex,
                enable_password=enable_password,
                job_type=job_type,
                include_write=include_write,
                template_command_count=host_tpl_count,
            )
            _finalize_log(res)
            return res

        with ThreadPoolExecutor(max_workers=workers) as pool:
            future_map = {pool.submit(_worker, host): host for host in hosts}
            for fut in as_completed(future_map):
                host = future_map[fut]
                try:
                    res = fut.result()
                except Exception as exc:
                    res = HostExecutionResult(
                        host=host,
                        status="Failed",
                        exception_message=str(exc),
                        operation_result="Unexpected worker error",
                        connection_method=f"{host.protocol.value} ({host.os_type or '-'})",
                        started_at=_timestamp_str(),
                        finished_at=_timestamp_str(),
                    )
                    _finalize_log(res)

                results_by_key[host.unique_key] = res
                if on_host_complete is not None:
                    on_host_complete(res)

        ordered = [results_by_key[h.unique_key] for h in hosts if h.unique_key in results_by_key]
        return run_dir, ordered
