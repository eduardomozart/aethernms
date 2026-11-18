"""Core domain models and data structures for pssh-ui."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class SwitchOS(str, Enum):
    """Supported Aruba switch operating systems."""

    AOS_S = "AOS-S"
    AOS_CX = "AOS-CX"
    UNKNOWN = "Unknown"


class CustomOS(str):
    """Dynamic OS identifier loaded from external XML models/snippets while preserving .value."""

    @property
    def value(self) -> str:
        """Return string value matching SwitchOS Enum interface."""
        return str(self)


def parse_device_type(raw: Optional[str], default: Optional[SwitchOS] = None) -> SwitchOS | CustomOS:
    """
    Resolve an OS/DeviceType XML string to SwitchOS when known, otherwise preserve
    the custom string cleanly as CustomOS so new XML models/snippets work without code edits.
    """
    cleaned = (raw or "").strip()
    if not cleaned:
        return default if default is not None else SwitchOS.UNKNOWN
    for member in SwitchOS:
        if member.value.lower() == cleaned.lower():
            return member
    return CustomOS(cleaned)


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
    """Reusable CLI command snippet stored as XML in snippets/<vendor>/<os>/."""

    name: str
    folder: str = "aruba/aoss"
    snippet_type: SnippetType = SnippetType.CONFIG
    device_type: SwitchOS = SwitchOS.AOS_S
    severity: SnippetSeverity = SnippetSeverity.INFO
    description: str = ""
    commands: str = ""
    audit_regex: str = ""
    created_at: str = ""
    file_path: Optional[str] = None

    @property
    def relative_id(self) -> str:
        """Return a stable relative identifier using forward slashes."""
        if self.file_path:
            from pathlib import Path

            name = Path(self.file_path).name
            return f"{self.folder.strip('/')}/{name}" if self.folder else name
        return f"{self.folder.strip('/')}/{self.name}" if self.folder else self.name


@dataclass
class DeviceModel:
    """Automation personality and common CLI wrapper commands for a switch OS/platform."""

    name: str
    device_type: SwitchOS = SwitchOS.AOS_S
    vendor: str = "Aruba"
    folder: str = "aruba"
    description: str = ""
    cli_prompt_regex: str = r"(?:^|\n)[ \t]*[A-Za-z0-9_.:-]+(?:\([^)\r\n]+\))?[#>][ \t]*$"
    username_prompt_regex: str = r"(?:^|\n)[ \t]*(?:Username|Login|User)\s*:[ \t]*$"
    password_prompt_regex: str = r"(?:^|\n)[ \t]*(?:Enable\s+password|Password)\s*:[ \t]*$"
    enable_command: str = "enable"
    enable_prompt_regex: str = r"(?:^|\n)[ \t]*[A-Za-z0-9_.:-]+(?:\([^)\r\n]+\))?#\s*$"
    enable_password_prompt_regex: str = (
        r"(?:^|\n)[ \t]*(?:Enable\s+password|Password)\s*:[ \t]*$"
    )
    pager_prompt_regex: str = (
        r"(?:Press any key to continue|--\s*MORE\s*--|Press <SPACE> to continue)"
    )
    pager_dismiss_key: str = " "
    disable_paging_command: str = "no page"
    pre_config_commands: str = "configure terminal"
    post_config_commands: str = "end"
    write_command: str = "write memory"
    pre_audit_commands: str = ""
    post_audit_commands: str = ""
    file_path: Optional[str] = None


@dataclass
class HostEntry:
    """Represents a target switch device."""

    name: str
    ip: str
    os_type: SwitchOS = SwitchOS.UNKNOWN
    model: str = ""
    firmware: str = ""
    folder_id: Optional[str] = None
    folder_path: str = ""
    device_category: str = ""
    serial_number: str = ""
    airwave_status: str = "Manual"
    device_role: str = ""
    enabled: bool = True
    port: int = 22
    ping_status: str = "Unknown"

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
    """Aggregated SSH execution result for one target switch."""

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


@dataclass
class JobRecord:
    """Represents a deployment or audit job displayed in the Jobs table."""

    job_id: str
    name: str
    job_type: SnippetType = SnippetType.CONFIG
    device_type: SwitchOS = SwitchOS.AOS_S
    status: str = "Running"  # "Running", "Success", "Failed"
    creation_time: str = ""
    start_time: str = ""
    end_time: str = ""
    description: str = ""
    snippet_name: str = ""
    model_name: str = ""
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
    os_filter: str = "All"  # "All", "AOS-S", "AOS-CX"
    status_filter: str = "All"  # "All", "Up", "Down"
    search_query: str = ""
    include_stacked: bool = False


@dataclass
class AppSettings:
    """Global application settings stored in settings.xml (never stores passwords)."""

    language: str = "auto"  # "auto" or locale code (e.g. "en", "pt_BR", "es")
    theme_mode: str = "auto"  # "auto", "light", "dark"
    ssh_username: str = ""
    ssh_port: int = 22
    schedule_sequence: ScheduleSequence = ScheduleSequence.CONCURRENT
    max_parallel: int = 10
    command_timeout: int = 15
    connect_timeout: int = 10
    airwave_url: str = ""
    airwave_username: str = ""
    airwave_verify_ssl: bool = False
    airwave_filters: AirWaveFilter = field(default_factory=AirWaveFilter)


@dataclass
class SessionData:
    """Workspace session state stored in session.xml (devices, jobs, non-secret params)."""

    variable_values: Dict[str, str] = field(default_factory=dict)
    hosts: List[HostEntry] = field(default_factory=list)
    jobs: List[JobRecord] = field(default_factory=list)
