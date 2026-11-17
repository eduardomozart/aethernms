"""AirWave device discovery, OS classification (AOS-S vs AOS-CX), and filtering."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple
import urllib3

from airwaveapiclient import APList, AirWaveAPIClient, FolderList

from pssh_ui.models import AirWaveFilter, HostEntry, SwitchOS


urllib3.disable_warnings()


AOS_CX_FIRMWARE_PREFIXES = (
    "FL.",
    "PL.",
    "ML.",
    "LL.",
    "TL.",
    "XL.",
    "GL.",
    "RL.",
    "SL.",
    "DL.",
    "VL.",
    "WL.",
    "10.",
)
AOS_S_FIRMWARE_PREFIXES = (
    "YA.",
    "YB.",
    "YC.",
    "WB.",
    "WC.",
    "KB.",
    "KA.",
    "K.",
    "RA.",
    "T.",
    "N.",
    "M.",
    "H.",
    "16.",
    "15.",
)
AOS_CX_MODEL_TOKENS = (
    "CX",
    "6000",
    "6100",
    "6200",
    "6300",
    "6400",
    "8100",
    "8320",
    "8325",
    "8360",
    "8400",
    "9300",
    "10000",
)
AOS_S_MODEL_TOKENS = (
    "PROCURVE",
    "AOS-S",
    "2530",
    "2540",
    "2610",
    "2620",
    "2810",
    "2910",
    "2920",
    "2930",
    "3500",
    "3800",
    "3810",
    "5400",
    "5406",
    "5412",
)


def infer_switch_os(
    model: str = "",
    firmware: str = "",
) -> SwitchOS:
    """Classify a switch as AOS-S or AOS-CX using firmware branch and hardware model."""
    fw_upper = (firmware or "").strip().upper()
    model_upper = (model or "").strip().upper()

    if fw_upper.startswith(AOS_CX_FIRMWARE_PREFIXES) or re.match(r"^[A-Z]{2}\.10\.", fw_upper):
        return SwitchOS.AOS_CX
    if fw_upper.startswith(AOS_S_FIRMWARE_PREFIXES):
        return SwitchOS.AOS_S

    if any(token in model_upper for token in AOS_CX_MODEL_TOKENS):
        return SwitchOS.AOS_CX
    if any(token in model_upper for token in AOS_S_MODEL_TOKENS):
        return SwitchOS.AOS_S

    return SwitchOS.UNKNOWN


def get_stacked_base_name(name: str) -> Optional[str]:
    """Return Commander base name if device name has a VSF -N suffix (N >= 2)."""
    if not name:
        return None
    match = re.search(r"-([2-9]|[1-9]\d+)$", name.strip())
    if not match:
        return None
    return name.strip()[: match.start()]


def is_stacked_device(name: str, all_device_names: Optional[Set[str]] = None) -> bool:
    """Return True if a device is a VSF/stacked member sharing the Commander's name."""
    base_name = get_stacked_base_name(name)
    if not base_name:
        return False
    if all_device_names is None:
        return True
    return base_name in all_device_names


def parse_airwave_folders(folder_xml: str) -> Dict[str, Dict[str, Any]]:
    """
    Parse AirWave folder_list.xml into {folder_id: {'name', 'parent_id', 'folder_path'}}.
    """
    if not folder_xml or not folder_xml.strip():
        return {}

    fl = FolderList(folder_xml)
    folders: Dict[str, Dict[str, Any]] = {}
    all_names: Dict[str, str] = {}
    all_parents: Dict[str, Optional[str]] = {}

    for node in fl:
        fid = str(node.get("@id") or node.get("id") or "").strip()
        fname = str(node.get("name") or "").strip()
        if fid:
            all_names[fid] = fname
            pid = str(node.get("parent_id") or node.get("parent") or "").strip()
            all_parents[fid] = pid if pid and pid != "0" else None

    for fid, name in all_names.items():
        if name and name.lower() == "top":
            continue
        folders[fid] = {
            "name": name or "Unknown Folder",
            "parent_id": all_parents.get(fid),
        }

    for fid, fdata in folders.items():
        path_names = [fdata["name"]]
        curr = fdata["parent_id"]
        visited = {fid}
        while curr and curr not in visited:
            visited.add(curr)
            if curr in all_names and all_names[curr].lower() != "top":
                path_names.append(all_names[curr])
            curr = all_parents.get(curr)
        path_names.reverse()
        fdata["folder_path"] = " > ".join(path_names)

    return folders


def _extract_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return str(value.get("#text") or value.get("name") or "").strip()
    return str(value).strip()


def _extract_folder_id(ap: Dict[str, Any]) -> Optional[str]:
    folder_field = ap.get("folder")
    fid = None
    if isinstance(folder_field, dict):
        fid = folder_field.get("@id") or folder_field.get("id")
    elif folder_field:
        fid = str(folder_field)
    if not fid:
        fid = ap.get("@folder_id") or ap.get("folder_id") or ap.get("ap_folder_id")
    return str(fid).strip() if fid else None


def _split_csv_filters(raw: str) -> List[str]:
    if not raw:
        return []
    return [part.strip().lower() for part in raw.split(",") if part.strip()]


def _matching_folder_ids(folders: Dict[str, Dict[str, Any]], query: str) -> Set[str]:
    """Return folder IDs (and all descendants) matching a folder ID, name, or breadcrumb path."""
    target = query.strip()
    target_lower = target.lower()
    matched: Set[str] = set()

    for fid, fdata in folders.items():
        fname = str(fdata.get("name", "")).lower()
        fpath = str(fdata.get("folder_path", "")).lower()
        if fid == target or target_lower == fname or target_lower in fpath:
            matched.add(fid)

    # Expand recursively to include child folders of matched parents
    changed = True
    while changed:
        changed = False
        for fid, fdata in folders.items():
            if fid not in matched and fdata.get("parent_id") in matched:
                matched.add(fid)
                changed = True

    return matched


def parse_airwave_devices(
    ap_xml: str,
    folders: Optional[Dict[str, Dict[str, Any]]] = None,
    filters: Optional[AirWaveFilter] = None,
) -> Tuple[List[HostEntry], int]:
    """
    Parse AirWave ap_list.xml and return (filtered HostEntry list, total parsed count).
    """
    if not ap_xml or not ap_xml.strip():
        return [], 0

    ap_list = APList(ap_xml)
    folders = folders or {}
    flt = filters or AirWaveFilter()

    all_device_names: Set[str] = set()
    device_ips: Dict[str, str] = {}
    device_folders: Dict[str, str] = {}

    for ap in ap_list:
        raw_name = _extract_text(ap.get("name"))
        if raw_name and not raw_name.startswith("(id:"):
            all_device_names.add(raw_name)
            dev_ip = _extract_text(ap.get("lan_ip") or ap.get("ip") or ap.get("remote_lan_ip"))
            if dev_ip:
                device_ips[raw_name] = dev_ip
            fid = _extract_folder_id(ap)
            if fid:
                device_folders[raw_name] = fid

    folder_filter_ids: Optional[Set[str]] = None
    if flt.folder and flt.folder.strip():
        folder_filter_ids = _matching_folder_ids(folders, flt.folder)

    category_tokens = _split_csv_filters(flt.category)
    model_tokens = _split_csv_filters(flt.model)
    search_token = (flt.search_query or "").strip().lower()

    hosts: List[HostEntry] = []
    total_devices = len(ap_list)

    for ap in ap_list:
        name = _extract_text(ap.get("name"))
        if not name or name.startswith("(id:"):
            continue

        is_stacked = is_stacked_device(name, all_device_names)
        base_commander = get_stacked_base_name(name) if is_stacked else None

        raw_ip = _extract_text(ap.get("lan_ip") or ap.get("ip") or ap.get("remote_lan_ip"))
        commander_ip = device_ips.get(base_commander, "") if base_commander else ""

        is_stacked_duplicate = is_stacked and (
            not raw_ip or (commander_ip and raw_ip == commander_ip)
        )
        if is_stacked_duplicate and not flt.include_stacked:
            continue

        ip = raw_ip or (commander_ip if is_stacked and base_commander else "")
        if not ip:
            continue

        folder_id = _extract_folder_id(ap)
        if not folder_id and is_stacked and base_commander:
            folder_id = device_folders.get(base_commander)

        folder_path = ""
        if folder_id and folder_id in folders:
            folder_path = folders[folder_id].get("folder_path", "")

        if folder_filter_ids is not None:
            if folder_id in folder_filter_ids:
                pass
            elif flt.folder.strip().lower() in folder_path.lower():
                pass
            else:
                continue

        device_category = _extract_text(ap.get("device_category"))
        if category_tokens:
            if not any(tok in device_category.lower() for tok in category_tokens):
                continue

        model = _extract_text(ap.get("model"))
        if model_tokens:
            if not any(tok in model.lower() for tok in model_tokens):
                continue

        firmware = _extract_text(ap.get("firmware"))
        os_type = infer_switch_os(model=model, firmware=firmware)
        if flt.os_filter and flt.os_filter != "All":
            if os_type.value.lower() != flt.os_filter.strip().lower():
                continue

        is_up_raw = _extract_text(ap.get("is_up")).lower()
        aw_status = "Up" if is_up_raw == "true" else ("Down" if is_up_raw == "false" else "Unknown")
        if flt.status_filter and flt.status_filter != "All":
            if aw_status.lower() != flt.status_filter.strip().lower():
                continue

        serial_number = _extract_text(ap.get("serial_number"))
        role = _extract_text(ap.get("operating_mode"))
        if not role and is_stacked:
            role = "Member"

        if search_token:
            haystack = " ".join([name, ip, model, firmware, serial_number, folder_path]).lower()
            if search_token not in haystack:
                continue

        hosts.append(
            HostEntry(
                name=name,
                ip=ip,
                os_type=os_type,
                model=model,
                firmware=firmware,
                folder_id=folder_id,
                folder_path=folder_path,
                device_category=device_category,
                serial_number=serial_number,
                airwave_status=aw_status,
                device_role=role,
                enabled=True,
                port=22,
            )
        )

    hosts.sort(key=lambda h: (h.name.lower(), h.ip))
    return hosts, total_devices


def normalize_airwave_url(url_or_host: str) -> str:
    """Normalize an AirWave server IP/hostname into an HTTPS URL."""
    cleaned = (url_or_host or "").strip()
    if not cleaned:
        raise ValueError("AirWave server URL or IP is required.")
    if not cleaned.startswith(("http://", "https://")):
        return f"https://{cleaned}"
    return cleaned


def fetch_airwave_inventory(
    url: str,
    username: str,
    password: str,
    verify_ssl: bool = False,
) -> Tuple[Dict[str, Dict[str, Any]], str]:
    """
    Authenticate against AirWave and return (folders_dict, raw_ap_list_xml).
    Always logs out cleanly after fetching.
    """
    normalized_url = normalize_airwave_url(url)
    client = AirWaveAPIClient(
        username=username,
        password=password,
        url=normalized_url,
        verify=verify_ssl,
    )
    login_res = client.login()
    if login_res is None or login_res.status_code != 200:
        code = getattr(login_res, "status_code", "N/A")
        raise RuntimeError(f"AirWave login failed (HTTP {code}).")

    try:
        folder_res = client.folder_list()
        folder_xml = folder_res.text if folder_res is not None else ""
        if "<amp:amp_folder_list" not in folder_xml and "<folder" not in folder_xml:
            raise RuntimeError("Unexpected folder_list.xml response from AirWave (check credentials).")
        folders = parse_airwave_folders(folder_xml)

        ap_res = client.ap_list()
        ap_xml = ap_res.text if ap_res is not None else ""
        if "<amp:amp_ap_list" not in ap_xml:
            raise RuntimeError("Unexpected ap_list.xml response from AirWave.")
        return folders, ap_xml
    finally:
        try:
            client.logout()
        except Exception:
            pass
