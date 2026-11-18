"""Global application settings XML persistence (settings.xml, never stores passwords)."""

from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

from pssh_ui.models import AirWaveFilter, AppSettings, ScheduleSequence
from pssh_ui.paths import get_settings_path


DEFAULT_SETTINGS_PATH = get_settings_path()


def _parse_bool(raw: str | None, default: bool = False) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in ("true", "1", "yes", "on")


def _parse_int(raw: str | None, default: int) -> int:
    if raw is None:
        return default
    try:
        return int(float(raw.strip()))
    except ValueError:
        return default


def _enum_by_value(enum_cls, raw: str | None, default):
    val = (raw or "").strip().lower()
    for member in enum_cls:
        if member.value.lower() == val:
            return member
    return default


def save_settings_xml(
    settings: AppSettings,
    file_path: Path | str = DEFAULT_SETTINGS_PATH,
) -> Path:
    """Persist global application preferences to settings.xml without any passwords."""
    out_path = Path(file_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    root = ET.Element("PsshSettings", version="1.0")

    app_el = ET.SubElement(root, "Appearance")
    ET.SubElement(app_el, "Language").text = settings.language or "auto"
    ET.SubElement(app_el, "ThemeMode").text = settings.theme_mode or "auto"

    exec_el = ET.SubElement(root, "ExecutionDefaults")
    ET.SubElement(exec_el, "SshUsername").text = settings.ssh_username or ""
    ET.SubElement(exec_el, "SshPort").text = str(settings.ssh_port)
    ET.SubElement(exec_el, "ScheduleSequence").text = settings.schedule_sequence.value
    ET.SubElement(exec_el, "MaxParallel").text = str(max(1, int(settings.max_parallel)))
    ET.SubElement(exec_el, "CommandTimeout").text = str(max(1, int(settings.command_timeout)))
    ET.SubElement(exec_el, "ConnectTimeout").text = str(max(1, int(settings.connect_timeout)))

    aw_el = ET.SubElement(root, "AirWave")
    ET.SubElement(aw_el, "Url").text = settings.airwave_url or ""
    ET.SubElement(aw_el, "Username").text = settings.airwave_username or ""
    ET.SubElement(aw_el, "VerifySSL").text = "true" if settings.airwave_verify_ssl else "false"

    flt_el = ET.SubElement(aw_el, "Filters")
    flt = settings.airwave_filters
    ET.SubElement(flt_el, "Folder").text = flt.folder or ""
    ET.SubElement(flt_el, "Category").text = flt.category or "switch"
    ET.SubElement(flt_el, "NameFilter").text = flt.name_filter or ""
    ET.SubElement(flt_el, "IPFilter").text = flt.ip_filter or ""
    ET.SubElement(flt_el, "Model").text = flt.model or ""
    ET.SubElement(flt_el, "OSFilter").text = flt.os_filter or "All"
    ET.SubElement(flt_el, "StatusFilter").text = flt.status_filter or "All"
    ET.SubElement(flt_el, "SearchQuery").text = flt.search_query or ""

    tree = ET.ElementTree(root)
    ET.indent(tree, space="    ", level=0)
    xml_str = ET.tostring(root, encoding="utf-8").decode("utf-8")
    with out_path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write('<?xml version="1.0" encoding="utf-8"?>\n')
        fh.write(xml_str)
        fh.write("\n")

    return out_path


def load_settings_xml(file_path: Path | str = DEFAULT_SETTINGS_PATH) -> AppSettings:
    """Load AppSettings from settings.xml (returns defaults if file is missing)."""
    in_path = Path(file_path)
    if not in_path.is_file():
        return AppSettings()

    tree = ET.parse(in_path)
    root = tree.getroot()
    if root.tag != "PsshSettings":
        raise ValueError(f"Invalid settings XML root tag <{root.tag}>; expected <PsshSettings>.")

    def _child_text(parent: ET.Element | None, tag: str, default: str = "") -> str:
        if parent is None:
            return default
        el = parent.find(tag)
        if el is not None and el.text is not None:
            return el.text
        return default

    app_el = root.find("Appearance")
    exec_el = root.find("ExecutionDefaults")
    aw_el = root.find("AirWave")
    flt_el = aw_el.find("Filters") if aw_el is not None else None

    airwave_filters = AirWaveFilter(
        folder=_child_text(flt_el, "Folder", ""),
        category=_child_text(flt_el, "Category", "switch"),
        name_filter=_child_text(flt_el, "NameFilter", ""),
        ip_filter=_child_text(flt_el, "IPFilter", ""),
        model=_child_text(flt_el, "Model", ""),
        os_filter=_child_text(flt_el, "OSFilter", "All") or "All",
        status_filter=_child_text(flt_el, "StatusFilter", "All") or "All",
        search_query=_child_text(flt_el, "SearchQuery", ""),
        include_stacked=False,
    )

    return AppSettings(
        language=_child_text(app_el, "Language", "auto") or "auto",
        theme_mode=_child_text(app_el, "ThemeMode", "auto") or "auto",
        ssh_username=_child_text(exec_el, "SshUsername", ""),
        ssh_port=_parse_int(_child_text(exec_el, "SshPort", "22"), 22),
        schedule_sequence=_enum_by_value(
            ScheduleSequence,
            _child_text(exec_el, "ScheduleSequence", ScheduleSequence.CONCURRENT.value),
            ScheduleSequence.CONCURRENT,
        ),
        max_parallel=max(1, _parse_int(_child_text(exec_el, "MaxParallel", "10"), 10)),
        command_timeout=max(1, _parse_int(_child_text(exec_el, "CommandTimeout", "15"), 15)),
        connect_timeout=max(1, _parse_int(_child_text(exec_el, "ConnectTimeout", "10"), 10)),
        airwave_url=_child_text(aw_el, "Url", ""),
        airwave_username=_child_text(aw_el, "Username", ""),
        airwave_verify_ssl=_parse_bool(_child_text(aw_el, "VerifySSL", "false"), False),
        airwave_filters=airwave_filters,
    )
