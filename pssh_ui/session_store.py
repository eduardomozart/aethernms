"""XML session save/restore for devices, jobs, and non-secret parameters (no passwords)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional, Set
import xml.etree.ElementTree as ET

from pssh_ui.models import (
    AirWaveFilter,
    AppSettings,
    HostEntry,
    HostExecutionResult,
    JobRecord,
    ScheduleSequence,
    SessionData,
    SnippetType,
    SwitchOS,
    parse_device_type,
)
from pssh_ui.paths import get_session_path
from pssh_ui.variables import extract_variables


DEFAULT_SESSION_PATH = get_session_path()


def _parse_bool(raw: str | None, default: bool = False) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in ("true", "1", "yes", "on")


def _parse_int(raw: str | None, default: int) -> int:
    try:
        return int(raw) if raw is not None else default
    except ValueError:
        return default


def _parse_float(raw: str | None, default: float) -> float:
    try:
        return float(raw) if raw is not None else default
    except ValueError:
        return default


def _enum_by_value(enum_cls, raw: str | None, default):
    val = (raw or "").strip().lower()
    for member in enum_cls:
        if member.value.lower() == val:
            return member
    return default


def save_session_xml(
    session: SessionData,
    file_path: Path | str = DEFAULT_SESSION_PATH,
    secret_param_names: Optional[Iterable[str]] = None,
) -> Path:
    """
    Save session state (devices, jobs, and non-password parameters) as XML.
    Global preferences live in settings.xml; password-typed fields are NEVER persisted.
    """
    out_path = Path(file_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    secret_names: Set[str] = set(secret_param_names or ())
    for job in session.jobs:
        for spec in extract_variables(f"{job.commands_raw}\n{job.audit_regex}"):
            if spec.is_secret:
                secret_names.add(spec.name)

    root = ET.Element("PsshSession", version="2.0")

    meta = ET.SubElement(root, "Metadata")
    ET.SubElement(meta, "SavedAt").text = datetime.now().isoformat(timespec="seconds")

    params_el = ET.SubElement(root, "Parameters")
    for key, val in sorted((session.variable_values or {}).items()):
        if key in secret_names:
            continue
        p_el = ET.SubElement(params_el, "Param", name=str(key))
        p_el.text = "" if val is None else str(val)

    hosts_el = ET.SubElement(root, "Devices")
    for host in session.hosts:
        ET.SubElement(
            hosts_el,
            "Device",
            name=host.name or "",
            ip=host.ip or "",
            os=host.os_type.value,
            model=host.model or "",
            firmware=host.firmware or "",
            folder_id=str(host.folder_id) if host.folder_id is not None else "",
            folder_path=host.folder_path or "",
            device_category=host.device_category or "",
            serial_number=host.serial_number or "",
            airwave_status=host.airwave_status or "",
            device_role=host.device_role or "",
            enabled="true" if host.enabled else "false",
            port=str(host.port),
        )

    jobs_el = ET.SubElement(root, "Jobs")
    for job in session.jobs:
        j_el = ET.SubElement(
            jobs_el,
            "Job",
            id=job.job_id,
            name=job.name,
            job_type=job.job_type.value,
            device_type=job.device_type.value,
            status=job.status,
            creation_time=job.creation_time,
            start_time=job.start_time,
            end_time=job.end_time,
            snippet_name=job.snippet_name,
            model_name=job.model_name,
            max_parallel=str(job.max_parallel),
            schedule_sequence=job.schedule_sequence.value,
            log_dir=job.log_dir,
        )
        ET.SubElement(j_el, "Description").text = job.description or ""
        ET.SubElement(j_el, "CommandsRaw").text = job.commands_raw or ""
        ET.SubElement(j_el, "CommandsRendered").text = job.commands_rendered or ""
        if job.audit_regex:
            ET.SubElement(j_el, "AuditRegex").text = job.audit_regex
        pm_el = ET.SubElement(j_el, "ParametersMasked")
        for pk, pv in sorted((job.parameters_masked or {}).items()):
            val_safe = "••••••••" if pk in secret_names else str(pv or "")
            ET.SubElement(pm_el, "Param", name=str(pk)).text = val_safe
        res_list_el = ET.SubElement(j_el, "Results")
        for res in job.results:
            ET.SubElement(
                res_list_el,
                "DeviceResult",
                name=res.host.name or "",
                ip=res.host.ip or "",
                os=res.host.os_type.value,
                port=str(res.host.port),
                status=res.status,
                started_at=res.started_at,
                finished_at=res.finished_at,
                operation_result=res.operation_result,
                log_path=res.log_path,
            )

    tree = ET.ElementTree(root)
    ET.indent(tree, space="    ", level=0)
    xml_str = ET.tostring(root, encoding="utf-8").decode("utf-8")
    with out_path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write('<?xml version="1.0" encoding="utf-8"?>\n')
        fh.write(xml_str)
        fh.write("\n")

    return out_path


def _parse_devices_container(root: ET.Element) -> list[HostEntry]:
    """Read devices from <Devices><Device .../></Devices> or legacy <Hosts><Host .../></Hosts>."""
    hosts: list[HostEntry] = []
    container = root.find("Devices")
    tag_name = "Device"
    if container is None:
        container = root.find("Hosts")
        tag_name = "Host"
    if container is None:
        return hosts

    for h in container.findall(tag_name):
        attrs = h.attrib
        ip = (attrs.get("ip") or "").strip()
        name = (attrs.get("name") or "").strip()
        if not ip and not name:
            continue
        fid = (attrs.get("folder_id") or "").strip()
        hosts.append(
            HostEntry(
                name=name,
                ip=ip,
                os_type=parse_device_type(attrs.get("os"), SwitchOS.UNKNOWN),
                model=attrs.get("model", ""),
                firmware=attrs.get("firmware", ""),
                folder_id=fid if fid else None,
                folder_path=attrs.get("folder_path", ""),
                device_category=attrs.get("device_category", ""),
                serial_number=attrs.get("serial_number", ""),
                airwave_status=attrs.get("airwave_status", "Manual"),
                device_role=attrs.get("device_role", ""),
                enabled=_parse_bool(attrs.get("enabled"), True),
                port=_parse_int(attrs.get("port"), 22),
            )
        )
    return hosts


def load_session_xml(file_path: Path | str = DEFAULT_SESSION_PATH) -> SessionData:
    """Load SessionData (devices, jobs, and non-password parameters) from XML."""
    in_path = Path(file_path)
    tree = ET.parse(in_path)
    root = tree.getroot()
    if root.tag != "PsshSession":
        raise ValueError(f"Invalid session XML root tag <{root.tag}>; expected <PsshSession>.")

    def _child_text(parent: ET.Element | None, tag: str, default: str = "") -> str:
        if parent is None:
            return default
        el = parent.find(tag)
        if el is not None and el.text is not None:
            return el.text
        return default

    variable_values: dict[str, str] = {}
    params_el = root.find("Parameters")
    if params_el is not None:
        for p in params_el.findall("Param"):
            name = (p.attrib.get("name") or "").strip()
            if name:
                variable_values[name] = p.text or ""

    hosts = _parse_devices_container(root)

    jobs: list[JobRecord] = []
    jobs_el = root.find("Jobs")
    if jobs_el is not None:
        for j in jobs_el.findall("Job"):
            attrs = j.attrib
            cmd_raw = _child_text(j, "CommandsRaw", "")
            secret_names = {s.name for s in extract_variables(cmd_raw) if s.is_secret}

            pm: dict[str, str] = {}
            pm_el = j.find("ParametersMasked")
            if pm_el is not None:
                for p in pm_el.findall("Param"):
                    pname = (p.attrib.get("name") or "").strip()
                    if pname:
                        pm[pname] = "••••••••" if pname in secret_names else (p.text or "")

            res_list: list[HostExecutionResult] = []
            res_el = j.find("Results")
            if res_el is not None:
                result_nodes = res_el.findall("DeviceResult") or res_el.findall("HostResult")
                for hr in result_nodes:
                    ha = hr.attrib
                    host_obj = HostEntry(
                        name=ha.get("name", ""),
                        ip=ha.get("ip", ""),
                        os_type=parse_device_type(ha.get("os"), SwitchOS.UNKNOWN),
                        port=_parse_int(ha.get("port"), 22),
                    )
                    log_path = ha.get("log_path", "")
                    res_list.append(
                        HostExecutionResult(
                            host=host_obj,
                            status=ha.get("status", "Pending"),
                            started_at=ha.get("started_at", ""),
                            finished_at=ha.get("finished_at", ""),
                            operation_result=ha.get("operation_result", ""),
                            log_path=log_path,
                        )
                    )

            jobs.append(
                JobRecord(
                    job_id=attrs.get("id", ""),
                    name=attrs.get("name", "Config Job"),
                    job_type=_enum_by_value(SnippetType, attrs.get("job_type"), SnippetType.CONFIG),
                    device_type=parse_device_type(attrs.get("device_type"), SwitchOS.AOS_S),
                    status=attrs.get("status", "Success"),
                    creation_time=attrs.get("creation_time", ""),
                    start_time=attrs.get("start_time", ""),
                    end_time=attrs.get("end_time", ""),
                    description=_child_text(j, "Description", ""),
                    snippet_name=attrs.get("snippet_name", ""),
                    model_name=attrs.get("model_name", ""),
                    commands_raw=cmd_raw,
                    commands_rendered=_child_text(j, "CommandsRendered", "") or cmd_raw,
                    audit_regex=_child_text(j, "AuditRegex", ""),
                    max_parallel=max(1, _parse_int(attrs.get("max_parallel"), 10)),
                    schedule_sequence=_enum_by_value(
                        ScheduleSequence,
                        attrs.get("schedule_sequence"),
                        ScheduleSequence.CONCURRENT,
                    ),
                    log_dir=attrs.get("log_dir", ""),
                    parameters_masked=pm,
                    results=res_list,
                )
            )

    # Strip any secret values if an older session.xml stored them under <Parameters>
    all_secret_names: Set[str] = set()
    for job in jobs:
        for spec in extract_variables(f"{job.commands_raw}\n{job.audit_regex}"):
            if spec.is_secret:
                all_secret_names.add(spec.name)
    for sec_name in all_secret_names:
        variable_values.pop(sec_name, None)

    return SessionData(
        variable_values=variable_values,
        hosts=hosts,
        jobs=jobs,
    )


def migrate_legacy_settings_from_session(session_xml_path: Path | str) -> Optional[AppSettings]:
    """
    Extract global settings from a legacy v1.0 session.xml when settings.xml
    does not yet exist on disk. Returns None if no legacy settings are present.
    """
    in_path = Path(session_xml_path)
    if not in_path.is_file():
        return None
    try:
        root = ET.parse(in_path).getroot()
    except Exception:
        return None

    exec_el = root.find("ExecutionSettings")
    aw_el = root.find("AirWave")
    meta = root.find("Metadata")
    if exec_el is None and aw_el is None:
        return None

    def _ct(parent: ET.Element | None, tag: str, default: str = "") -> str:
        if parent is None:
            return default
        el = parent.find(tag)
        return el.text if (el is not None and el.text is not None) else default

    flt_el = aw_el.find("Filters") if aw_el is not None else None
    return AppSettings(
        language="auto",
        theme_mode="auto",
        ssh_username=_ct(exec_el, "SshUsername", ""),
        ssh_port=_parse_int(_ct(exec_el, "SshPort", "22"), 22),
        schedule_sequence=_enum_by_value(
            ScheduleSequence,
            _ct(exec_el, "ScheduleSequence", ScheduleSequence.CONCURRENT.value),
            ScheduleSequence.CONCURRENT,
        ),
        max_parallel=max(1, _parse_int(_ct(exec_el, "MaxParallel", "10"), 10)),
        command_timeout=max(1, int(_parse_float(_ct(exec_el, "CommandTimeout", "15"), 15.0))),
        connect_timeout=max(1, int(_parse_float(_ct(exec_el, "ConnectTimeout", "10"), 10.0))),
        airwave_url=_ct(aw_el, "Url", ""),
        airwave_username=_ct(aw_el, "Username", ""),
        airwave_verify_ssl=_parse_bool(_ct(aw_el, "VerifySSL", "false"), False),
        airwave_filters=AirWaveFilter(
            folder=_ct(flt_el, "Folder", ""),
            category=_ct(flt_el, "Category", "switch"),
            model=_ct(flt_el, "Model", ""),
            os_filter=_ct(flt_el, "OSFilter", "All") or "All",
            status_filter=_ct(flt_el, "StatusFilter", "All") or "All",
            search_query=_ct(flt_el, "SearchQuery", ""),
            include_stacked=False,
        ),
    )
