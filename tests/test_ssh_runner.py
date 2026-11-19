"""Tests for Netmiko PSSHClient (SSH & Telnet) and parallel/sequential BatchSSHExecutor."""

from datetime import datetime
from pathlib import Path
import threading
import time
from typing import Any, Dict, List

from netmiko.exceptions import (
    ConfigInvalidException,
    NetmikoAuthenticationException,
    NetmikoTimeoutException,
)

from pssh_ui.common import format_operation_result_ui
from pssh_ui.i18n import get_language, set_language
from pssh_ui.logger import write_host_log
from pssh_ui.models import ConnectionProtocol, HostEntry, ScheduleSequence, SnippetType
from pssh_ui.ssh_runner import BatchSSHExecutor, PSSHClient, clean_terminal_text


class FakeNetmikoConnection:
    """In-memory Netmiko BaseConnection double supporting SSH/Telnet config & audit flows."""

    def __init__(
        self,
        *,
        responses: Dict[str, str] | None = None,
        prompt: str = "Switch-Aruba# ",
        in_enable: bool = True,
        save_output: str = "Writing configuration...",
        session_log=None,
    ) -> None:
        self.responses = responses or {}
        self.prompt = prompt
        self.in_enable = in_enable
        self.in_config = False
        self.save_output = save_output
        self.session_log = session_log
        self.calls: List[tuple[str, Any]] = []
        self.disconnected = False

    def _log(self, text: str) -> None:
        if self.session_log is not None:
            self.session_log.write(text.encode("utf-8"))

    def check_enable_mode(self) -> bool:
        self.calls.append(("check_enable_mode", self.in_enable))
        return self.in_enable

    def enable(self) -> str:
        self.calls.append(("enable", None))
        self.in_enable = True
        self._log("enable\nSwitch-Aruba# ")
        return ""

    def config_mode(self) -> str:
        self.calls.append(("config_mode", None))
        self.in_config = True
        self._log("configure terminal\nSwitch-Aruba(config)# ")
        return "configure terminal\nSwitch-Aruba(config)# "

    def exit_config_mode(self) -> str:
        self.calls.append(("exit_config_mode", None))
        self.in_config = False
        self._log("end\nSwitch-Aruba# ")
        return "end\nSwitch-Aruba# "

    def send_config_set(
        self,
        config_commands,
        *,
        enter_config_mode: bool = True,
        exit_config_mode: bool = True,
        read_timeout: float | None = None,
        error_pattern: str = "",
    ) -> str:
        cmds = list(config_commands or [])
        self.calls.append(("send_config_set", cmds))
        out_chunks: List[str] = []
        if enter_config_mode and not self.in_config:
            out_chunks.append(self.config_mode())
        for cmd in cmds:
            reply = self.responses.get(cmd, f"{cmd}\nSwitch-Aruba(config)# ")
            self._log(reply)
            out_chunks.append(reply)
            if reply == "__TIMEOUT__":
                raise NetmikoTimeoutException("Timed out waiting for switch")
            if error_pattern:
                import re

                if re.search(error_pattern, reply, flags=re.M):
                    raise ConfigInvalidException(
                        f"Invalid input detected at command: {cmd}, matched error: {reply.strip()}"
                    )
        if exit_config_mode and self.in_config:
            out_chunks.append(self.exit_config_mode())
        return "".join(out_chunks)

    def send_command(
        self,
        command_string: str,
        *,
        read_timeout: float = 10.0,
        strip_prompt: bool = True,
        strip_command: bool = True,
    ) -> str:
        self.calls.append(("send_command", command_string))
        reply = self.responses.get(command_string, f"{command_string}\nOK\n{self.prompt}")
        self._log(reply)
        return reply

    def save_config(self) -> str:
        self.calls.append(("save_config", None))
        self._log(f"write memory\n{self.save_output}\nSwitch-Aruba# ")
        return self.save_output

    def disconnect(self) -> None:
        self.calls.append(("disconnect", None))
        self.disconnected = True


def test_clean_terminal_text_normalizes_vt100_and_pagers():
    raw = "Aruba 2930F\r\nPress any key to continue\x1b[24;1HSwitch#\x08# "
    cleaned = clean_terminal_text(raw)
    assert "Press any key" not in cleaned
    assert "\x1b" not in cleaned
    lines = [line for line in cleaned.splitlines() if line]
    assert lines == ["Aruba 2930F", "Switch#"]


def test_pssh_client_config_telnet_aborts_on_error_and_records_steps(tmp_path: Path):
    captured_kwargs: Dict[str, Any] = {}

    def fake_factory(**kwargs):
        captured_kwargs.update(kwargs)
        return FakeNetmikoConnection(
            responses={
                "bad command": "bad command\nInvalid input: bad\nSwitch-Aruba(config)# ",
            },
            session_log=kwargs.get("session_log"),
        )

    client = PSSHClient(connect_handler_factory=fake_factory)
    host = HostEntry(
        name="SW-TELNET",
        ip="10.0.0.1",
        os_type="aruba_procurve",
        protocol=ConnectionProtocol.TELNET,
        port=23,
    )
    res = client.execute_commands(
        host=host,
        username="admin",
        password="secret",
        commands=["vlan 10", "bad command", "vlan 20"],
        job_type=SnippetType.CONFIG,
        include_write=True,
    )

    assert captured_kwargs["device_type"] == "aruba_procurve_telnet"
    assert captured_kwargs["port"] == 23
    assert res.connection_method == "Telnet (aruba_procurve_telnet)"
    assert res.status == "Failed"
    assert len(res.step_results) == 3
    assert res.step_results[0].result == "Succeeded"
    assert res.step_results[1].result == "Failed"
    assert res.step_results[2].result == "Skipped"
    assert "Aborted" in res.step_results[2].suggestion
    assert len(res.error_lines) == 1
    assert "Invalid CLI input" in res.error_lines[0]["reason"]

    log_txt = Path(write_host_log(res, tmp_path)).read_text(encoding="utf-8")
    assert "Connection      : Telnet (aruba_procurve_telnet)" in log_txt
    assert "--- Raw Telnet Terminal Output ---" in log_txt


def test_pssh_client_aoscx_config_save_and_audit_mode(tmp_path: Path):
    prev_lang = get_language()
    try:
        set_language("pt_BR")
        fake_conn_holder: List[FakeNetmikoConnection] = []

        def ok_factory(**kwargs):
            conn = FakeNetmikoConnection(session_log=kwargs.get("session_log"))
            fake_conn_holder.append(conn)
            return conn

        client = PSSHClient(connect_handler_factory=ok_factory)
        host = HostEntry(
            name="SW-CX-01",
            ip="10.0.0.20",
            os_type="aruba_aoscx",
            protocol=ConnectionProtocol.SSH,
            port=22,
        )
        ok_res = client.execute_commands(
            host=host,
            username="admin",
            password="pw",
            commands=["ntp server 1.1.1.1", "ntp enable"],
            job_type=SnippetType.CONFIG,
            include_write=True,
            template_command_count=2,
        )
        assert ok_res.status == "Success"
        assert ok_res.connection_method == "SSH (aruba_aoscx)"
        assert ok_res.operation_result == "Completed (2 commands)"
        assert format_operation_result_ui(ok_res.operation_result) == "Concluído (2 comandos)"
        call_names = [name for name, _arg in fake_conn_holder[0].calls]
        assert "config_mode" in call_names
        assert "exit_config_mode" in call_names
        assert "save_config" in call_names
        assert fake_conn_holder[0].disconnected is True

        # Audit mode uses send_command without entering config mode
        def audit_factory(**kwargs):
            return FakeNetmikoConnection(
                in_enable=False,
                responses={
                    "show snmpv3 users": "show snmpv3 users\nUser: noc_ro | Auth: sha\nSwitch-Aruba# "
                },
                session_log=kwargs.get("session_log"),
            )

        audit_client = PSSHClient(connect_handler_factory=audit_factory)
        host_pro = HostEntry(
            name="SW-PRO",
            ip="10.0.0.30",
            os_type="aruba_procurve",
            protocol=ConnectionProtocol.SSH,
        )
        aud_ok = audit_client.execute_commands(
            host=host_pro,
            username="admin",
            password="pw",
            commands=["show snmpv3 users"],
            audit_regex="User:\\s+noc_ro",
            enable_password="EnableSecret!99",
            job_type=SnippetType.AUDIT,
        )
        assert aud_ok.status == "Success"

        aud_fail = audit_client.execute_commands(
            host=host_pro,
            username="admin",
            password="pw",
            commands=["show snmpv3 users"],
            audit_regex="User:\\s+missing_user",
            enable_password="EnableSecret!99",
            job_type=SnippetType.AUDIT,
        )
        assert aud_fail.status == "Failed"
        assert "Audit failed" in aud_fail.operation_result
        assert aud_fail.error_lines[0]["text"] == "User:\\s+missing_user"
    finally:
        set_language(prev_lang)


def test_pssh_client_auth_failure_and_unsupported_telnet(tmp_path: Path):
    def auth_fail_factory(**_kwargs):
        raise NetmikoAuthenticationException("Bad credentials")

    client = PSSHClient(connect_handler_factory=auth_fail_factory)
    host = HostEntry(name="SW-AUTH", ip="10.0.0.5", os_type="aruba_aoscx")
    res = client.execute_commands(
        host, "admin", "wrong_pw", ["show version"], job_type=SnippetType.AUDIT
    )
    assert res.status == "Failed"
    assert res.operation_result == "Authentication failed"
    assert res.exception_message == "Authentication failed: Bad credentials"
    assert res.error_lines == []

    log_txt = Path(write_host_log(res, tmp_path)).read_text(encoding="utf-8")
    assert "--- Connection / Execution Exception ---\nAuthentication failed: Bad credentials" in log_txt
    assert "--- Detected Errors ---" not in log_txt
    assert "--- Raw SSH Terminal Output ---\nAuthentication failed: Bad credentials" in log_txt

    # Rejects Telnet cleanly on platforms that have no native Netmiko _telnet driver
    unsupported_host = HostEntry(
        name="SW-CX-TELNET",
        ip="10.0.0.6",
        os_type="aruba_aoscx",
        protocol=ConnectionProtocol.TELNET,
        port=23,
    )
    bad_proto_res = PSSHClient().execute_commands(
        unsupported_host, "admin", "pw", ["show version"], job_type=SnippetType.AUDIT
    )
    assert bad_proto_res.status == "Failed"
    assert "Telnet" in bad_proto_res.exception_message


def test_batch_executor_respects_max_parallel_and_writes_logs(tmp_path: Path):
    active_lock = threading.Lock()
    active_count = 0
    peak_active = 0

    class TrackingClient(PSSHClient):
        def execute_commands(self, host, username, password, commands, **kwargs):
            nonlocal active_count, peak_active
            with active_lock:
                active_count += 1
                peak_active = max(peak_active, active_count)
            time.sleep(0.05)
            with active_lock:
                active_count -= 1
            return super().execute_commands(host, username, password, [], **kwargs)

    hosts = [
        HostEntry(name=f"SW-{i}", ip=f"10.0.0.{i}", os_type="aruba_procurve")
        for i in range(1, 7)
    ]
    executor = BatchSSHExecutor(
        client_factory=lambda: TrackingClient(
            connect_handler_factory=lambda **kw: FakeNetmikoConnection(session_log=kw.get("session_log"))
        ),
        logs_base_dir=tmp_path / "logs",
    )
    run_dir, results = executor.run_batch(
        hosts=hosts,
        username="admin",
        password="pw",
        commands_by_host={h.unique_key: [] for h in hosts},
        max_parallel=2,
        schedule_sequence=ScheduleSequence.CONCURRENT,
        run_timestamp=datetime(2026, 11, 17, 16, 0, 0),
    )

    assert len(results) == 6
    assert peak_active <= 2
    assert (run_dir / "SW-1.log").is_file()
    assert all(r.log_path for r in results)
