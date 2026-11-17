"""Job preparation helpers: OS-based switch filtering, model wrappers, assigned models/groups, and validation."""

from __future__ import annotations

from typing import Dict, List, Optional

from pssh_ui.i18n import _
from pssh_ui.models import DeviceModel, HostEntry, SnippetType, SwitchOS
from pssh_ui.parser import parse_commands
from pssh_ui.variables import extract_variables, render_template, validate_variable_values


def get_assigned_models(hosts: List[HostEntry]) -> List[str]:
    """
    Return sorted unique switch model names currently assigned to at least one device.
    Models with zero device assignments are automatically omitted.
    """
    return sorted(
        {h.model.strip() for h in hosts if h.model and h.model.strip()},
        key=str.lower,
    )


def get_assigned_groups(hosts: List[HostEntry]) -> List[str]:
    """
    Return sorted unique group/folder names currently assigned to at least one device.
    Groups with zero device assignments are automatically omitted.
    """
    return sorted(
        {h.folder_path.strip() for h in hosts if h.folder_path and h.folder_path.strip()},
        key=str.lower,
    )


def discover_device_types(
    models: Optional[List[DeviceModel]] = None,
    snippets: Optional[List] = None,
    hosts: Optional[List[HostEntry]] = None,
) -> List[str]:
    """
    Dynamically collect all OS/DeviceType values defined by loaded Model XMLs,
    Snippet XMLs, and registered Devices so new vendor XMLs appear automatically
    with zero Python code changes.
    """
    found: set[str] = set()
    for m in models or ():
        val = (m.device_type.value if hasattr(m.device_type, "value") else str(m.device_type)).strip()
        if val and val != SwitchOS.UNKNOWN.value:
            found.add(val)
    for s in snippets or ():
        val = (s.device_type.value if hasattr(s.device_type, "value") else str(s.device_type)).strip()
        if val and val != SwitchOS.UNKNOWN.value:
            found.add(val)
    for h in hosts or ():
        val = (h.os_type.value if hasattr(h.os_type, "value") else str(h.os_type)).strip()
        if val and val != SwitchOS.UNKNOWN.value:
            found.add(val)
    if not found:
        return [SwitchOS.AOS_S.value, SwitchOS.AOS_CX.value]
    return sorted(
        found,
        key=lambda v: (0 if v == SwitchOS.AOS_S.value else (1 if v == SwitchOS.AOS_CX.value else 2), v.lower()),
    )


def filter_hosts_by_os(hosts: List[HostEntry], device_type: SwitchOS) -> List[HostEntry]:
    """
    Return hosts matching the snippet/job SwitchOS.
    If device_type is Unknown, return all hosts.
    """
    if device_type == SwitchOS.UNKNOWN:
        return list(hosts)
    return [h for h in hosts if h.os_type == device_type]


def wrap_commands_with_model(
    commands: List[str],
    job_type: SnippetType = SnippetType.CONFIG,
    device_model: Optional[DeviceModel] = None,
    include_write_command: bool = False,
) -> List[str]:
    """
    Wrap parsed snippet commands with a DeviceModel's common pre/post commands
    (e.g., 'configure terminal' ... 'end' for Config tasks, optionally appending
    the model's write/save command when requested, or audit wrappers for Audit tasks)
    without duplicating boundary lines already present in the snippet.
    """
    if not commands or device_model is None:
        return list(commands)

    if job_type == SnippetType.AUDIT:
        pre_raw = device_model.pre_audit_commands
        post_raw = device_model.post_audit_commands
    else:
        pre_raw = device_model.pre_config_commands
        post_raw = device_model.post_config_commands

    pre = parse_commands(pre_raw)
    post = parse_commands(post_raw)

    result = list(commands)
    if pre:
        first_lower = result[0].strip().lower()
        pre_last_lower = pre[-1].strip().lower()
        if first_lower != pre_last_lower:
            result = pre + result
    if post:
        last_lower = result[-1].strip().lower()
        post_first_lower = post[0].strip().lower()
        if last_lower != post_first_lower:
            result = result + post
    if include_write_command and job_type == SnippetType.CONFIG and device_model.write_command:
        write_cmds = parse_commands(device_model.write_command)
        for wc in write_cmds:
            if not result or result[-1].strip().lower() != wc.strip().lower():
                result.append(wc)
    return result


def build_commands_for_job(
    raw_commands: str,
    values: Dict[str, str],
    hosts: List[HostEntry],
    job_type: SnippetType = SnippetType.CONFIG,
    device_model: Optional[DeviceModel] = None,
    include_write_command: bool = False,
) -> Dict[str, List[str]]:
    """Render variables, parse CLI commands, and apply DeviceModel lifecycle wrappers per switch."""
    cmd_map: Dict[str, List[str]] = {}
    for host in hosts:
        rendered = render_template(raw_commands, values, host=host)
        parsed = parse_commands(rendered)
        cmd_map[host.unique_key] = wrap_commands_with_model(
            parsed,
            job_type=job_type,
            device_model=device_model,
            include_write_command=include_write_command,
        )
    return cmd_map


def validate_job_inputs(
    raw_commands: str,
    selected_hosts: List[HostEntry],
    values: Dict[str, str],
    ssh_username: str,
    ssh_password: str,
) -> List[str]:
    """Validate target hosts, credentials, regex/type parameters, and commands for a job."""
    errors: List[str] = []

    if not selected_hosts:
        errors.append(_("Select at least one target switch matching this snippet OS."))
    if not (ssh_username or "").strip():
        errors.append(_("SSH Username is required."))
    if not ssh_password:
        errors.append(_("SSH Password is required."))

    specs = extract_variables(raw_commands)
    var_errors = validate_variable_values(specs, values or {})
    for msg in var_errors.values():
        errors.append(msg)

    if selected_hosts:
        cmd_map = build_commands_for_job(raw_commands, values or {}, selected_hosts)
        if all(len(cmds) == 0 for cmds in cmd_map.values()):
            errors.append(
                _("No executable commands found (check script contents or '!' comments).")
            )
    elif not parse_commands(raw_commands):
        errors.append(_("Commands cannot be empty."))

    return errors
