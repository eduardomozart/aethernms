"""Paramiko interactive SSH runner and parallel batch executor for ArubaOS-S and ArubaOS-CX."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
import re
import secrets
import threading
import time
from typing import Callable, Dict, List, Optional

import paramiko

from pssh_ui.i18n import _
from pssh_ui.logger import create_run_log_dir, write_host_log
from pssh_ui.models import (
    CommandStepResult,
    DeviceModel,
    HostEntry,
    HostExecutionResult,
    ScheduleSequence,
    SwitchOS,
)
from pssh_ui.parser import detect_output_errors, validate_audit_regex


ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07|\x1b[=>]")
CLI_PROMPT_END_RE = re.compile(
    r"(?:^|\n)[ \t]*[A-Za-z0-9_.:-]+(?:\([^)\r\n]+\))?[#>][ \t]*$"
)
ENABLE_PROMPT_END_RE = re.compile(
    r"(?:^|\n)[ \t]*[A-Za-z0-9_.:-]+(?:\([^)\r\n]+\))?#[ \t]*$"
)
USERNAME_PROMPT_RE = re.compile(r"(?:Username|Login|User)\s*:", re.IGNORECASE)
PASSWORD_PROMPT_RE = re.compile(r"(?:Enable\s+password|Password)\s*:", re.IGNORECASE)
PRESS_ANY_KEY_RE = re.compile(r"Press any key to continue", re.IGNORECASE)
MORE_PAGER_RE = re.compile(r"(?:--\s*MORE\s*--|Press <SPACE> to continue)", re.IGNORECASE)

# ArubaOS-S `snmpv3 enable` interactive initialization prompts when no initial user exists
SNMPV3_AUTH_PASS_RE = re.compile(
    r"(?:Enter|Re-enter)\s+authentication\s+password\s*:", re.IGNORECASE
)
SNMPV3_PRIV_PASS_RE = re.compile(
    r"(?:Enter|Re-enter)\s+privacy\s+password\s*:", re.IGNORECASE
)
SNMPV3_SHA_PROMPT_RE = re.compile(
    r"Would you like to create a user that uses SHA\?\s*\[y/n\]", re.IGNORECASE
)
SNMPV3_RESTRICT_PROMPT_RE = re.compile(
    r"Would you like to restrict SNMPv1 and SNMPv2c[^\]]*\[y/n\]", re.IGNORECASE
)


def clean_terminal_text(text: str) -> str:
    """Strip ANSI escape codes and normalize carriage returns from raw SSH stream."""
    no_ansi = ANSI_ESCAPE_RE.sub("", text or "")
    normalized = no_ansi.replace("\r\n", "\n").replace("\r", "\n")
    return normalized


def _timestamp_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _compile_optional_regex(
    expr: str,
    default: Optional[re.Pattern[str]] = None,
) -> Optional[re.Pattern[str]]:
    cleaned = (expr or "").strip()
    if not cleaned:
        return default
    try:
        return re.compile(cleaned, re.IGNORECASE)
    except re.error:
        return default


class ArubaSSHClient:
    """Executes CLI command batches over an interactive Paramiko shell on Aruba switches."""

    def __init__(
        self,
        connect_timeout: float = 10.0,
        command_timeout: float = 15.0,
        poll_interval: float = 0.05,
        ssh_client_factory: Optional[Callable[[], paramiko.SSHClient]] = None,
    ) -> None:
        self.connect_timeout = max(1.0, float(connect_timeout))
        self.command_timeout = max(1.0, float(command_timeout))
        self.poll_interval = max(0.01, float(poll_interval))
        self._ssh_client_factory = ssh_client_factory or paramiko.SSHClient

    def _recv_available(self, channel) -> str:
        """Drain currently buffered output from a Paramiko channel."""
        chunks: List[str] = []
        while channel.recv_ready():
            data = channel.recv(65535)
            if not data:
                break
            chunks.append(data.decode("utf-8", errors="replace"))
        return "".join(chunks)

    def _read_until_prompt(
        self,
        channel,
        timeout: float,
        cancel_event: Optional[threading.Event] = None,
        handle_snmpv3_init: bool = True,
        username: str = "",
        password: str = "",
        enable_password: str = "",
        device_model: Optional[DeviceModel] = None,
        is_enable_phase: bool = False,
    ) -> tuple[str, bool]:
        """
        Read channel output until an Aruba CLI prompt appears or timeout/EOF occurs.
        Handles banners/pagers, DeviceModel interactive credential/enable prompts,
        and optional 'snmpv3 enable' initial-user wizard prompts.
        Returns (cleaned_text, timed_out).
        """
        raw_buffer = ""
        cleaned = ""
        deadline = time.monotonic() + timeout
        temp_init_secret = f"Tmp{secrets.token_hex(6)}!"
        handled_prompts_len = 0
        auth_replies = 0

        prompt_re = (
            _compile_optional_regex(device_model.cli_prompt_regex, CLI_PROMPT_END_RE)
            if device_model
            else CLI_PROMPT_END_RE
        ) or CLI_PROMPT_END_RE
        pager_re = (
            _compile_optional_regex(device_model.pager_prompt_regex, MORE_PAGER_RE)
            if device_model
            else MORE_PAGER_RE
        )
        pager_key = (
            (device_model.pager_dismiss_key if device_model else " ") or " "
        )
        user_re = (
            _compile_optional_regex(device_model.username_prompt_regex, USERNAME_PROMPT_RE)
            if device_model
            else None
        )
        pwd_re = (
            _compile_optional_regex(device_model.password_prompt_regex, PASSWORD_PROMPT_RE)
            if device_model
            else None
        )
        en_pwd_re = (
            _compile_optional_regex(
                device_model.enable_password_prompt_regex, PASSWORD_PROMPT_RE
            )
            if device_model
            else None
        )

        while True:
            if cancel_event is not None and cancel_event.is_set():
                return cleaned, True

            chunk = self._recv_available(channel)
            if chunk:
                raw_buffer += chunk
                cleaned = clean_terminal_text(raw_buffer)
                tail = cleaned[handled_prompts_len:]

                if (pager_re and pager_re.search(tail)) or PRESS_ANY_KEY_RE.search(tail):
                    channel.send(pager_key)
                    handled_prompts_len = len(cleaned)
                    deadline = time.monotonic() + timeout
                    continue

                if handle_snmpv3_init:
                    if SNMPV3_AUTH_PASS_RE.search(tail) or SNMPV3_PRIV_PASS_RE.search(tail):
                        channel.send(temp_init_secret + "\n")
                        handled_prompts_len = len(cleaned)
                        deadline = time.monotonic() + timeout
                        continue
                    if SNMPV3_SHA_PROMPT_RE.search(tail) or SNMPV3_RESTRICT_PROMPT_RE.search(tail):
                        channel.send("n\n")
                        handled_prompts_len = len(cleaned)
                        deadline = time.monotonic() + timeout
                        continue

                if auth_replies < 4:
                    if user_re and user_re.search(tail) and username:
                        channel.send(username + "\n")
                        auth_replies += 1
                        handled_prompts_len = len(cleaned)
                        deadline = time.monotonic() + timeout
                        continue
                    if is_enable_phase and en_pwd_re and en_pwd_re.search(tail):
                        secret_val = enable_password or password
                        if secret_val:
                            channel.send(secret_val + "\n")
                            auth_replies += 1
                            handled_prompts_len = len(cleaned)
                            deadline = time.monotonic() + timeout
                            continue
                    if pwd_re and pwd_re.search(tail) and password:
                        channel.send(password + "\n")
                        auth_replies += 1
                        handled_prompts_len = len(cleaned)
                        deadline = time.monotonic() + timeout
                        continue

                if prompt_re.search(cleaned):
                    return cleaned, False

            if getattr(channel, "closed", False) or (
                hasattr(channel, "exit_status_ready") and channel.exit_status_ready()
            ):
                # Drain any remaining bytes
                final_chunk = self._recv_available(channel)
                if final_chunk:
                    raw_buffer += final_chunk
                    cleaned = clean_terminal_text(raw_buffer)
                return cleaned, not bool(prompt_re.search(cleaned))

            if time.monotonic() >= deadline:
                return cleaned, True

            time.sleep(self.poll_interval)

    def execute_commands(
        self,
        host: HostEntry,
        username: str,
        password: str,
        commands: List[str],
        cancel_event: Optional[threading.Event] = None,
        audit_regex: str = "",
        enable_password: str = "",
        device_model: Optional[DeviceModel] = None,
    ) -> HostExecutionResult:
        """Connect to a switch via SSH, handle enable/paging/credentials, run commands, and audit."""
        result = HostExecutionResult(
            host=host,
            status="Running",
            commands_run=list(commands),
            started_at=_timestamp_str(),
        )

        if not commands:
            result.status = "Success"
            result.finished_at = _timestamp_str()
            result.operation_result = _("Skipped (no commands for {os})").format(
                os=host.os_type.value
            )
            return result

        client = self._ssh_client_factory()
        transcript_parts: List[str] = []
        prompt_re = (
            _compile_optional_regex(device_model.cli_prompt_regex, CLI_PROMPT_END_RE)
            if device_model
            else CLI_PROMPT_END_RE
        ) or CLI_PROMPT_END_RE
        enable_prompt_re = (
            _compile_optional_regex(device_model.enable_prompt_regex, ENABLE_PROMPT_END_RE)
            if device_model
            else ENABLE_PROMPT_END_RE
        ) or ENABLE_PROMPT_END_RE

        try:
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                hostname=host.ip,
                port=int(host.port or 22),
                username=username,
                password=password,
                timeout=self.connect_timeout,
                look_for_keys=False,
                allow_agent=False,
            )

            channel = client.invoke_shell(term="vt100", width=220, height=1000)
            channel.settimeout(self.connect_timeout)

            banner_text, banner_timeout = self._read_until_prompt(
                channel,
                timeout=self.connect_timeout,
                cancel_event=cancel_event,
                username=username,
                password=password,
                enable_password=enable_password,
                device_model=device_model,
            )
            if banner_text:
                transcript_parts.append(banner_text)
            if banner_timeout and not prompt_re.search(banner_text):
                channel.send("\n")
                retry_text, retry_timeout = self._read_until_prompt(
                    channel,
                    timeout=min(5.0, self.connect_timeout),
                    cancel_event=cancel_event,
                    username=username,
                    password=password,
                    enable_password=enable_password,
                    device_model=device_model,
                )
                if retry_text:
                    transcript_parts.append(retry_text)
                if retry_timeout and not prompt_re.search(retry_text):
                    raise TimeoutError(_("Timed out waiting for initial switch CLI prompt."))
                banner_text = retry_text

            # Escalate to privileged mode ('enable') if model configures it and prompt is not already '#'
            enable_cmd = device_model.enable_command.strip() if device_model else ""
            if enable_cmd and not enable_prompt_re.search(banner_text):
                channel.send(enable_cmd + "\n")
                en_out, _en_to = self._read_until_prompt(
                    channel,
                    timeout=min(5.0, self.command_timeout),
                    cancel_event=cancel_event,
                    username=username,
                    password=password,
                    enable_password=enable_password,
                    device_model=device_model,
                    is_enable_phase=True,
                )
                if en_out:
                    transcript_parts.append(en_out)

            # Disable pagination cleanly per DeviceModel (default 'no page')
            disable_paging = (
                device_model.disable_paging_command.strip()
                if device_model is not None
                else "no page"
            )
            if disable_paging:
                channel.send(disable_paging + "\n")
                nopage_out, _nopage_timed_out = self._read_until_prompt(
                    channel,
                    timeout=min(5.0, self.command_timeout),
                    cancel_event=cancel_event,
                    username=username,
                    password=password,
                    enable_password=enable_password,
                    device_model=device_model,
                )
                if nopage_out:
                    transcript_parts.append(nopage_out)

            # Execute user commands step-by-step
            for idx, cmd in enumerate(commands, start=1):
                if cancel_event is not None and cancel_event.is_set():
                    result.step_results.append(
                        CommandStepResult(
                            index=idx,
                            command=cmd,
                            result="Skipped",
                            suggestion=_("Cancelled by operator."),
                            begin_time=_timestamp_str(),
                            finish_time=_timestamp_str(),
                        )
                    )
                    continue

                begin_ts = _timestamp_str()
                channel.send(cmd + "\n")
                step_out, timed_out = self._read_until_prompt(
                    channel,
                    timeout=self.command_timeout,
                    cancel_event=cancel_event,
                    handle_snmpv3_init=(host.os_type != SwitchOS.AOS_CX),
                    username=username,
                    password=password,
                    enable_password=enable_password,
                    device_model=device_model,
                )
                finish_ts = _timestamp_str()
                if step_out:
                    transcript_parts.append(step_out)

                step_errors = detect_output_errors(step_out)
                if timed_out:
                    step_status = "Failed"
                    suggestion = _("Timed out waiting for switch prompt after {sec:.0f}s.").format(
                        sec=self.command_timeout
                    )
                elif step_errors:
                    step_status = "Failed"
                    first_err = step_errors[0]
                    suggestion = f"{first_err['reason']}: {first_err['suggestion']}"
                else:
                    step_status = "Succeeded"
                    suggestion = ""

                result.step_results.append(
                    CommandStepResult(
                        index=idx,
                        command=cmd,
                        result=step_status,
                        suggestion=suggestion,
                        begin_time=begin_ts,
                        finish_time=finish_ts,
                        output_snippet=step_out,
                    )
                )

            result.raw_output = "\n".join(part.rstrip("\n") for part in transcript_parts if part)
            cli_errors = detect_output_errors(result.raw_output)
            audit_errors = validate_audit_regex(result.raw_output, audit_regex)
            result.error_lines = cli_errors + audit_errors

            failed_steps = [s for s in result.step_results if s.result == "Failed"]
            if cancel_event is not None and cancel_event.is_set():
                result.status = "Failed"
                result.operation_result = _("Cancelled by operator")
            elif failed_steps or result.error_lines:
                result.status = "Failed"
                if audit_errors and not failed_steps and not cli_errors:
                    result.operation_result = _(
                        "Audit failed ({count} RegEx pattern(s) not matched)"
                    ).format(count=len(audit_errors))
                else:
                    err_count = max(len(failed_steps), len(cli_errors)) + len(audit_errors)
                    result.operation_result = _("{count} error(s) detected").format(count=err_count)
            else:
                result.status = "Success"
                result.operation_result = _("Completed ({count} commands)").format(
                    count=len(commands)
                )

        except paramiko.AuthenticationException as exc:
            result.status = "Failed"
            result.exception_message = f"Authentication failed: {exc}"
            result.operation_result = _("Authentication failed")
            result.raw_output = "\n".join(
                [p for p in transcript_parts if p] + [result.exception_message]
            )
            result.error_lines = detect_output_errors(result.raw_output)
        except Exception as exc:
            result.status = "Failed"
            result.exception_message = f"SSH connection error: {exc}"
            result.operation_result = str(exc) or _("SSH connection error")
            result.raw_output = "\n".join(
                [p for p in transcript_parts if p] + [result.exception_message]
            )
            result.error_lines = detect_output_errors(result.raw_output)
        finally:
            result.finished_at = _timestamp_str()
            try:
                client.close()
            except Exception:
                pass

        return result


class BatchSSHExecutor:
    """Runs SSH command batches concurrently or sequentially across multiple switches."""

    def __init__(
        self,
        client_factory: Optional[Callable[[], ArubaSSHClient]] = None,
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
        device_model: Optional[DeviceModel] = None,
    ) -> tuple[Path, List[HostExecutionResult]]:
        """
        Execute commands across `hosts` and write logs to `logs/YYYY-MM-DD_HH-MM-SS/`.
        Returns (run_log_dir, results_list).
        """
        if self._logs_base_dir is not None:
            run_dir = create_run_log_dir(base_dir=self._logs_base_dir, dt=run_timestamp)
        else:
            run_dir = create_run_log_dir(dt=run_timestamp)

        if not hosts:
            return run_dir, []

        if schedule_sequence == ScheduleSequence.SEQUENTIAL:
            workers = 1
        else:
            workers = max(1, min(int(max_parallel), len(hosts)))

        log_lock = threading.Lock()
        results_by_key: Dict[str, HostExecutionResult] = {}

        def _worker(host: HostEntry) -> HostExecutionResult:
            if cancel_event is not None and cancel_event.is_set():
                cancelled = HostExecutionResult(
                    host=host,
                    status="Failed",
                    operation_result=_("Cancelled before start"),
                    started_at=_timestamp_str(),
                    finished_at=_timestamp_str(),
                )
                with log_lock:
                    write_host_log(cancelled, run_dir)
                if on_host_complete:
                    on_host_complete(cancelled)
                return cancelled

            if on_host_start:
                on_host_start(host)

            client = (
                self._client_factory()
                if self._client_factory is not None
                else ArubaSSHClient(
                    connect_timeout=connect_timeout,
                    command_timeout=command_timeout,
                )
            )
            host_commands = commands_by_host.get(host.unique_key, [])
            host_audit_regex = (audit_regex_by_host or {}).get(host.unique_key, "")
            exec_kwargs: Dict[str, object] = {}
            if host_audit_regex:
                exec_kwargs["audit_regex"] = host_audit_regex
            if enable_password:
                exec_kwargs["enable_password"] = enable_password
            if device_model is not None:
                exec_kwargs["device_model"] = device_model
            res = client.execute_commands(
                host=host,
                username=username,
                password=password,
                commands=host_commands,
                cancel_event=cancel_event,
                **exec_kwargs,  # type: ignore[arg-type]
            )
            with log_lock:
                write_host_log(res, run_dir)
            if on_host_complete:
                on_host_complete(res)
            return res

        with ThreadPoolExecutor(max_workers=workers) as pool:
            future_map = {pool.submit(_worker, host): host for host in hosts}
            for future in as_completed(future_map):
                host = future_map[future]
                try:
                    res = future.result()
                except Exception as exc:
                    res = HostExecutionResult(
                        host=host,
                        status="Failed",
                        exception_message=str(exc),
                        operation_result=str(exc) or _("Unexpected worker error"),
                        started_at=_timestamp_str(),
                        finished_at=_timestamp_str(),
                    )
                    with log_lock:
                        write_host_log(res, run_dir)
                    if on_host_complete:
                        on_host_complete(res)
                results_by_key[host.unique_key] = res

        ordered_results = [results_by_key[h.unique_key] for h in hosts if h.unique_key in results_by_key]
        return run_dir, ordered_results
