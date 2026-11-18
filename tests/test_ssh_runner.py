"""Tests for Paramiko ArubaSSHClient and parallel BatchSSHExecutor."""

from datetime import datetime
from pathlib import Path
import threading
import time
from typing import List

import paramiko

from pssh_ui.common import format_operation_result_ui
from pssh_ui.i18n import get_language, set_language
from pssh_ui.logger import write_host_log
from pssh_ui.model_store import ModelStore
from pssh_ui.models import DeviceModel, HostEntry, ScheduleSequence, SwitchOS
from pssh_ui.ssh_runner import ArubaSSHClient, BatchSSHExecutor


class FakeChannel:
    """In-memory Paramiko shell channel simulator for ArubaOS-S and ArubaOS-CX."""

    def __init__(self, responses: dict, banner: str = "Press any key to continue\n", prompt: str = "Switch-Aruba# ") -> None:
        self._responses = responses
        self._prompt = prompt
        self._rx_chunks: List[bytes] = [banner.encode("utf-8")]
        self.sent_data: List[str] = []
        self.closed = False
        self._current_prompt = prompt

    def settimeout(self, _timeout: float) -> None:
        return None

    def recv_ready(self) -> bool:
        return len(self._rx_chunks) > 0

    def recv(self, _size: int) -> bytes:
        return self._rx_chunks.pop(0) if self._rx_chunks else b""

    def exit_status_ready(self) -> bool:
        return False

    def close(self) -> None:
        self.closed = True

    def send(self, data: str) -> int:
        self.sent_data.append(data)
        text = data.strip("\r\n")
        if data in (" ", "\n", "\r"):
            self._rx_chunks.append(self._current_prompt.encode("utf-8"))
            return len(data)

        if text == "configure terminal":
            self._current_prompt = "Switch-Aruba(config)# "
            self._rx_chunks.append(f"{text}\n{self._current_prompt}".encode("utf-8"))
        elif text in self._responses:
            reply = self._responses[text]
            self._rx_chunks.append(reply.encode("utf-8"))
        else:
            self._rx_chunks.append(f"{text}\n{self._current_prompt}".encode("utf-8"))
        return len(data)


class FakeSSHClient:
    """Mock Paramiko SSHClient backed by FakeChannel."""

    def __init__(self, channel: FakeChannel | None = None, auth_fail: bool = False) -> None:
        self.channel = channel
        self.auth_fail = auth_fail
        self.closed = False
        self.connect_kwargs = {}

    def set_missing_host_key_policy(self, _policy) -> None:
        return None

    def connect(self, **kwargs) -> None:
        self.connect_kwargs = kwargs
        if self.auth_fail:
            raise paramiko.AuthenticationException("Bad credentials")

    def invoke_shell(self, **_kwargs):
        return self.channel

    def close(self) -> None:
        self.closed = True


def test_aruba_ssh_client_handles_aoss_banner_no_page_and_errors():
    chan = FakeChannel(
        responses={
            "bad command": "bad command\nInvalid input: bad\nSwitch-Aruba(config)# ",
            "snmpv3 only": "snmpv3 only\nSwitch-Aruba(config)# ",
        }
    )
    fake_ssh = FakeSSHClient(channel=chan)
    client = ArubaSSHClient(poll_interval=0.005, ssh_client_factory=lambda: fake_ssh)

    host = HostEntry(name="SW-AOSS-01", ip="10.0.0.1", os_type=SwitchOS.AOS_S)
    res = client.execute_commands(
        host=host,
        username="admin",
        password="dummy_password",
        commands=["configure terminal", "bad command", "snmpv3 only"],
    )

    assert "no page\n" in chan.sent_data
    assert res.status == "Failed"
    assert len(res.step_results) == 3
    assert res.step_results[0].result == "Succeeded"
    assert res.step_results[1].result == "Failed"
    assert res.step_results[2].result == "Skipped"
    assert "Aborted" in res.step_results[2].suggestion
    assert "snmpv3 only\n" not in chan.sent_data
    assert "1 error detected: Invalid CLI input" in res.operation_result
    assert len(res.error_lines) == 1
    assert "Invalid input: bad" in res.error_lines[0]["text"]
    assert chan.closed is True
    assert fake_ssh.closed is True


def test_aruba_ssh_client_handles_snmpv3_init_prompts():
    class InitWizardChannel(FakeChannel):
        def send(self, data: str) -> int:
            self.sent_data.append(data)
            text = data.strip("\r\n")
            if text == "snmpv3 enable":
                self._rx_chunks.append(b"snmpv3 enable\nEnter authentication password: ")
            elif len(self.sent_data) >= 3 and self.sent_data[-2].strip() == "snmpv3 enable":
                self._rx_chunks.append(b"Would you like to create a user that uses SHA? [y/n]")
            elif text == "n":
                self._rx_chunks.append(b"\nSwitch-Aruba(config)# ")
            else:
                return super().send(data)
            return len(data)

    chan = InitWizardChannel(responses={}, banner="", prompt="Switch-Aruba(config)# ")
    client = ArubaSSHClient(poll_interval=0.005, ssh_client_factory=lambda: FakeSSHClient(channel=chan))
    host = HostEntry(name="SW-INIT", ip="10.0.0.9", os_type=SwitchOS.AOS_S)

    res = client.execute_commands(host, "admin", "dummy_pw", ["snmpv3 enable"])
    assert res.status == "Success"
    assert "n\n" in chan.sent_data


def test_aruba_ssh_client_reports_authentication_failure():
    client = ArubaSSHClient(
        poll_interval=0.005,
        ssh_client_factory=lambda: FakeSSHClient(auth_fail=True),
    )
    host = HostEntry(name="SW-AUTH", ip="10.0.0.5", os_type=SwitchOS.AOS_CX)
    res = client.execute_commands(host, "admin", "wrong_pw", ["show version"])
    assert res.status == "Failed"
    assert "Authentication failed" in res.operation_result
    assert len(res.error_lines) == 1


def test_batch_executor_respects_max_parallel_and_writes_logs(tmp_path: Path):
    active_lock = threading.Lock()
    active_count = 0
    peak_active = 0

    class TrackingClient(ArubaSSHClient):
        def execute_commands(self, host, username, password, commands, cancel_event=None):
            nonlocal active_count, peak_active
            with active_lock:
                active_count += 1
                peak_active = max(peak_active, active_count)
            time.sleep(0.05)
            with active_lock:
                active_count -= 1
            return super().execute_commands(host, username, password, [], cancel_event=cancel_event)

    hosts = [
        HostEntry(name=f"SW-{i:02d}", ip=f"10.0.0.{i}", os_type=SwitchOS.AOS_CX)
        for i in range(1, 7)
    ]
    cmd_map = {h.unique_key: ["show system"] for h in hosts}

    executor = BatchSSHExecutor(
        client_factory=lambda: TrackingClient(),
        logs_base_dir=tmp_path / "logs",
    )
    run_dt = datetime(2026, 11, 17, 16, 0, 0)
    run_dir, results = executor.run_batch(
        hosts=hosts,
        username="admin",
        password="dummy_password",
        commands_by_host=cmd_map,
        max_parallel=2,
        schedule_sequence=ScheduleSequence.CONCURRENT,
        run_timestamp=run_dt,
    )

    assert peak_active <= 2
    assert peak_active == 2
    assert run_dir.name == "2026-11-17_16-00-00"
    assert len(results) == 6
    for h in hosts:
        assert (run_dir / f"{h.name}.log").is_file()

    # Verify Sequential mode caps workers at 1
    peak_active = 0
    executor.run_batch(
        hosts=hosts[:3],
        username="admin",
        password="dummy_password",
        commands_by_host=cmd_map,
        max_parallel=5,
        schedule_sequence=ScheduleSequence.SEQUENTIAL,
        run_timestamp=run_dt,
    )
    assert peak_active == 1


def test_ssh_client_handles_enable_credentials_and_audit_regex():
    class EnableAndAuditChannel(FakeChannel):
        def send(self, data: str) -> int:
            self.sent_data.append(data)
            text = data.strip("\r\n")
            if text == "enable":
                self._rx_chunks.append(b"Password: ")
            elif text == "EnableSecret!99":
                self._current_prompt = "Switch-Aruba# "
                self._rx_chunks.append(b"\nSwitch-Aruba# ")
            elif text == "show snmpv3 users":
                self._rx_chunks.append(
                    b"show snmpv3 users\nUser: noc_ro | Auth: sha\nSwitch-Aruba# "
                )
            else:
                return super().send(data)
            return len(data)

    chan = EnableAndAuditChannel(responses={}, banner="Switch-Aruba> ", prompt="Switch-Aruba> ")
    client = ArubaSSHClient(poll_interval=0.005, ssh_client_factory=lambda: FakeSSHClient(channel=chan))
    host = HostEntry(name="SW-AUD", ip="10.0.0.15", os_type=SwitchOS.AOS_S)
    mdl = DeviceModel(name="ArubaOS-S", device_type=SwitchOS.AOS_S)

    ok_res = client.execute_commands(
        host=host,
        username="admin",
        password="ssh_pw",
        commands=["show snmpv3 users"],
        audit_regex="User:\\s+noc_ro",
        enable_password="EnableSecret!99",
        device_model=mdl,
    )
    assert "enable\n" in chan.sent_data
    assert "EnableSecret!99\n" in chan.sent_data
    assert ok_res.status == "Success"

    chan2 = EnableAndAuditChannel(responses={}, banner="Switch-Aruba> ", prompt="Switch-Aruba> ")
    client2 = ArubaSSHClient(poll_interval=0.005, ssh_client_factory=lambda: FakeSSHClient(channel=chan2))
    fail_res = client2.execute_commands(
        host=host,
        username="admin",
        password="ssh_pw",
        commands=["show snmpv3 users"],
        audit_regex="User:\\s+missing_user",
        enable_password="EnableSecret!99",
        device_model=mdl,
    )
    assert fail_res.status == "Failed"
    assert "Audit failed" in fail_res.operation_result
    assert fail_res.error_lines[0]["text"] == "User:\\s+missing_user"


def test_ssh_runner_ignores_last_login_banner_formats_same_line_and_keeps_english_logs(tmp_path: Path):
    class SplitBannerCXChannel(FakeChannel):
        def __init__(self, responses=None):
            super().__init__(responses=responses or {}, banner="", prompt="SW-CX-01# ")
            self._rx_chunks = [
                b"Last login: 2026-11-11 20:24:06 from 10.0.0.100\r\n",
                b'User "admin" has logged in 2 times in the past 30 days\r\n\r\nSW-CX-01# ',
            ]

        def send(self, data: str) -> int:
            self.sent_data.append(data)
            text = data.strip("\r\n")
            if text == "configure terminal":
                self._current_prompt = "SW-CX-01(config)# "
                self._rx_chunks.append(f"{text}\r\n{self._current_prompt}".encode("utf-8"))
            elif text == "end":
                self._current_prompt = "SW-CX-01# "
                self._rx_chunks.append(f"{text}\r\n{self._current_prompt}".encode("utf-8"))
            elif text in self._responses:
                self._rx_chunks.append(self._responses[text].encode("utf-8"))
            else:
                self._rx_chunks.append(f"{text}\r\n{self._current_prompt}".encode("utf-8"))
            return len(data)

    prev_lang = get_language()
    try:
        set_language("pt_BR")
        cx_model = next(
            m for m in ModelStore().load_all_models() if m.device_type == SwitchOS.AOS_CX
        )
        chan = SplitBannerCXChannel()
        fake_ssh = FakeSSHClient(channel=chan)
        client = ArubaSSHClient(poll_interval=0.005, ssh_client_factory=lambda: fake_ssh)
        host = HostEntry(name="SW-CX-01", ip="10.0.0.20", os_type=SwitchOS.AOS_CX)

        ok_res = client.execute_commands(
            host=host,
            username="admin",
            password="pw",
            commands=["configure terminal", "ntp server 1.1.1.1", "ntp enable", "end"],
            device_model=cx_model,
        )
        assert "admin\n" not in chan.sent_data
        assert ok_res.status == "Success"
        assert ok_res.operation_result == "Completed (4 commands)"
        raw_lines = ok_res.raw_output.splitlines()
        assert "SW-CX-01# configure terminal" in raw_lines
        assert "SW-CX-01(config)# ntp server 1.1.1.1" in raw_lines
        assert raw_lines[-1] == "SW-CX-01(config)# end"  # No dangling trailing bare prompt
        assert chan.closed is True and fake_ssh.closed is True

        # Failed step stays English in .log while UI display helper translates in pt_BR
        fail_chan = SplitBannerCXChannel(
            responses={"bad cmd": "bad cmd\r\n% Invalid input detected.\r\nSW-CX-01(config)# "}
        )
        fail_ssh = FakeSSHClient(channel=fail_chan)
        fail_client = ArubaSSHClient(poll_interval=0.005, ssh_client_factory=lambda: fail_ssh)
        fail_res = fail_client.execute_commands(
            host=host,
            username="admin",
            password="pw",
            commands=["configure terminal", "bad cmd", "ntp enable", "end"],
            device_model=cx_model,
        )
        assert fail_res.step_results[1].result == "Failed"
        assert fail_res.step_results[2].result == "Skipped"
        assert fail_res.step_results[3].result == "Skipped"
        assert "ntp enable\n" not in fail_chan.sent_data
        assert "end\n" not in fail_chan.sent_data
        assert fail_res.operation_result == "1 error detected: Invalid command or parameter"
        assert format_operation_result_ui(fail_res.operation_result) == (
            "1 erro detectado: Comando ou parâmetro inválido"
        )

        log_path = Path(write_host_log(fail_res, tmp_path))
        log_txt = log_path.read_text(encoding="utf-8")
        assert "Operation Result: 1 error detected: Invalid command or parameter" in log_txt
        assert "Aborted due to earlier command failure." in log_txt
        assert "Comando ou parâmetro inválido" not in log_txt
        assert "erro(s)" not in log_txt
    finally:
        set_language(prev_lang)
