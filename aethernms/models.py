"""Core domain models and data structures for aethernms."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class ConnectionProtocol(str, Enum):
    """Supported network transport protocols for Netmiko connections."""

    SSH = "SSH"
    TELNET = "Telnet"


class SnippetType(str, Enum):
    """Snippet classification."""

    CONFIG = "Config"
    AUDIT = "Audit and Remediate"


class SnippetSeverity(str, Enum):
    """Severity level for audit/remediation snippets."""

    INFO = "Info"
    WARNING = "Warning"
    MINOR = "Minor"
    MAJOR = "Major"
    CRITICAL = "Critical"


class ScheduleSequence(str, Enum):
    """Execution concurrency mode."""

    CONCURRENT = "Concurrent"
    SEQUENTIAL = "Sequential"


@dataclass
class VariableSpec:
    """Represents a template variable parsed from ${var}, ${var|type|regex}, or ${var|["A", "B"]}."""

    name: str
    field_type: str = "text"  # HTML-like input type ("text", "password", "number", "email", "select")
    regex: Optional[str] = None
    options: List[str] = field(default_factory=list)
    raw_tokens: List[str] = field(default_factory=list)

    @property
    def is_secret(self) -> bool:
        """Return True when the variable explicitly declares type='password'."""
        return self.field_type == "password"


@dataclass
class Snippet:
    """Reusable CLI command snippet stored as XML under snippets/."""

    name: str
    folder: str = "aruba/aruba_procurve"
    snippet_type: SnippetType = SnippetType.CONFIG
    device_type: str = "aruba_procurve"
    severity: SnippetSeverity = SnippetSeverity.INFO
    description: str = ""
    commands: str = ""
    audit_regex: str = ""
    created_at: str = ""
    file_path: Optional[str] = None
    id: Optional[int] = None

    @property
    def relative_id(self) -> str:
        """Return a stable relative identifier using forward slashes."""
        if self.file_path:
            name = Path(self.file_path).name
            return f"{self.folder.strip('/')}/{name}" if self.folder else name
        return f"{self.folder.strip('/')}/{self.name}" if self.folder else self.name


@dataclass
class HostEntry:
    """Represents a target network device."""

    name: str
    ip: str
    os_type: str = ""  # Canonical Netmiko platform (e.g. 'aruba_procurve', 'aruba_aoscx')
    protocol: ConnectionProtocol = ConnectionProtocol.SSH
    model: str = ""
    firmware: str = ""
    folder_id: Optional[str] = None
    folder_path: str = ""
    device_category: str = ""
    serial_number: str = ""
    airwave_status: str = "Manual"
    device_role: str = ""
    airwave_os: str = ""
    enabled: bool = True
    port: int = 22
    ping_status: str = "Unknown"
    id: Optional[int] = None

    @property
    def display_label(self) -> str:
        """Return hostname if available, otherwise IP address."""
        return self.name.strip() or self.ip.strip()

    @property
    def unique_key(self) -> str:
        """Return a deterministic host key used for per-host lookups."""
        return f"{self.ip.strip()}:{self.port}"


def is_airwave_host(host: HostEntry) -> bool:
    """Return True when the device originated from AirWave rather than manual entry."""
    st = (host.airwave_status or "").strip().lower()
    return bool(st and st != "manual") or host.folder_id is not None


@dataclass
class CommandStepResult:
    """Result for a single CLI command executed on a device."""

    index: int
    command: str
    result: str  # "Succeeded", "Failed", "Skipped"
    suggestion: str = ""
    begin_time: str = ""
    finish_time: str = ""
    output_snippet: str = ""


@dataclass
class HostExecutionResult:
    """Aggregated Netmiko execution result for one target device."""

    host: HostEntry
    status: str = "Pending"  # "Pending", "Running", "Success", "Failed"
    commands_run: List[str] = field(default_factory=list)
    step_results: List[CommandStepResult] = field(default_factory=list)
    raw_output: str = ""
    error_lines: List[Dict[str, Any]] = field(default_factory=list)
    operation_result: str = ""
    log_path: str = ""
    started_at: str = ""
    finished_at: str = ""
    exception_message: str = ""
    connection_method: str = ""  # e.g. "SSH (aruba_procurve)" or "Telnet (aruba_procurve_telnet)"
    formatted_log: str = ""
    id: Optional[int] = None


@dataclass
class JobRecord:
    """Represents a deployment or audit job displayed in the Jobs table."""

    job_id: str
    name: str
    job_type: SnippetType = SnippetType.CONFIG
    device_type: str = "aruba_procurve"
    status: str = "Running"  # "Running", "Success", "Failed"
    creation_time: str = ""
    start_time: str = ""
    end_time: str = ""
    description: str = ""
    snippet_name: str = ""
    commands_raw: str = ""
    commands_rendered: str = ""
    audit_regex: str = ""
    max_parallel: int = 10
    schedule_sequence: ScheduleSequence = ScheduleSequence.CONCURRENT
    include_write: bool = False
    log_dir: str = ""
    parameters_masked: Dict[str, str] = field(default_factory=dict)
    results: List[HostExecutionResult] = field(default_factory=list)


@dataclass
class AirWaveFilter:
    """Filters applied when importing devices from AirWave."""

    folder: str = ""
    category: str = "switch"
    name_filter: str = ""
    ip_filter: str = ""
    model: str = ""
    os_filter: str = "All"
    status_filter: str = "All"  # "All", "Up", "Down"
    search_query: str = ""
    include_stacked: bool = False


@dataclass
class AppSettings:
    """Global application settings stored in SQLite (never stores passwords)."""

    language: str = "auto"  # "auto" or locale code (e.g. "en", "pt_BR", "es")
    theme_mode: str = "auto"  # "auto", "light", "dark"
    ssh_username: str = ""
    default_protocol: ConnectionProtocol = ConnectionProtocol.SSH
    ssh_port: int = 22
    telnet_port: int = 23
    schedule_sequence: ScheduleSequence = ScheduleSequence.CONCURRENT
    max_parallel: int = 10
    command_timeout: int = 15
    connect_timeout: int = 10
    airwave_url: str = ""
    airwave_username: str = ""
    airwave_verify_ssl: bool = False
    airwave_filters: AirWaveFilter = field(default_factory=AirWaveFilter)
    airwave_os_mappings: Dict[str, str] = field(default_factory=dict)
    api_enabled: bool = False
    api_allowed_ips: str = "127.0.0.1, ::1"


@dataclass
class SessionData:
    """Workspace state stored in devices.xml and jobs.xml (no passwords)."""

    variable_values: Dict[str, str] = field(default_factory=dict)
    hosts: List[HostEntry] = field(default_factory=list)
    jobs: List[JobRecord] = field(default_factory=list)
