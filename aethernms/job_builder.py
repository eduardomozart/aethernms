"""Job preparation helpers: platform filtering, command rendering, assigned models/groups, and validation."""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from aethernms.i18n import _
from aethernms.models import HostEntry
from aethernms.netmiko_catalog import (
    get_supported_platforms,
    is_supported_platform,
    resolve_netmiko_device_type,
)
from aethernms.parser import parse_commands
from aethernms.variables import extract_variables, render_template, validate_variable_values


def get_assigned_models(hosts: List[HostEntry]) -> List[str]:
    """Return sorted unique hardware model names currently assigned to at least one device."""
    return sorted(
        {h.model.strip() for h in hosts if h.model and h.model.strip()},
        key=str.lower,
    )


def get_assigned_groups(hosts: List[HostEntry]) -> List[str]:
    """Return sorted unique group/folder names currently assigned to at least one device."""
    return sorted(
        {h.folder_path.strip() for h in hosts if h.folder_path and h.folder_path.strip()},
        key=str.lower,
    )


def discover_used_platforms(
    snippets: Optional[Sequence] = None,
    hosts: Optional[Sequence[HostEntry]] = None,
    jobs: Optional[Sequence] = None,
) -> List[str]:
    """
    Collect distinct Netmiko platform strings referenced by loaded snippets,
    registered devices, or job records (prioritizing active platforms for filter dropdowns).
    """
    found: set[str] = set()
    for s in snippets or ():
        val = (getattr(s, "device_type", "") or "").strip()
        if val:
            found.add(val)
    for h in hosts or ():
        val = (getattr(h, "os_type", "") or "").strip()
        if val:
            found.add(val)
    for j in jobs or ():
        val = (getattr(j, "device_type", "") or "").strip()
        if val:
            found.add(val)
    return sorted(found, key=str.lower)


def job_platform_choices(snippets: Optional[Sequence] = None) -> List[str]:
    """
    Return all Netmiko-supported platforms with snippet-backed platforms prioritized first
    so operators see ready-to-run platforms immediately alongside full multi-vendor coverage.
    """
    all_platforms = get_supported_platforms()
    snippet_platforms = sorted(
        {
            (getattr(s, "device_type", "") or "").strip()
            for s in (snippets or ())
            if is_supported_platform(getattr(s, "device_type", ""))
        },
        key=str.lower,
    )
    remaining = [p for p in all_platforms if p not in set(snippet_platforms)]
    return snippet_platforms + remaining


def filter_hosts_by_platform(hosts: List[HostEntry], platform: str) -> List[HostEntry]:
    """Return hosts matching `platform` (or all hosts if blank)."""
    target = (platform or "").strip().lower()
    if not target:
        return list(hosts)
    return [h for h in hosts if (h.os_type or "").strip().lower() == target]


def build_commands_for_job(
    raw_commands: str,
    values: Dict[str, str],
    hosts: List[HostEntry],
) -> Dict[str, List[str]]:
    """Render variables and parse CLI commands per target host (no custom wrappers)."""
    cmd_map: Dict[str, List[str]] = {}
    for host in hosts:
        rendered = render_template(raw_commands, values, host=host)
        cmd_map[host.unique_key] = parse_commands(rendered)
    return cmd_map


def validate_job_inputs(
    raw_commands: str,
    selected_hosts: List[HostEntry],
    values: Dict[str, str],
    username: str,
    password: str,
) -> List[str]:
    """Validate target hosts, protocol support, credentials, regex parameters, and commands."""
    errors: List[str] = []

    if not selected_hosts:
        errors.append(_("Select at least one target device matching this Netmiko platform."))
    if not (username or "").strip():
        errors.append(_("Username is required."))
    if not password:
        errors.append(_("Password is required."))

    for host in selected_hosts:
        try:
            resolve_netmiko_device_type(host.os_type, host.protocol)
        except ValueError as exc:
            errors.append(f"{host.display_label} ({host.ip}): {exc}")

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
