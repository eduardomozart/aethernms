"""Dynamic catalog of native Netmiko platforms, friendly display names, and supported transport protocols."""

from __future__ import annotations

from functools import lru_cache
from typing import Dict, List, Optional, Tuple

from aethernms.models import AppSettings, ConnectionProtocol


PLATFORM_FRIENDLY_NAMES: Dict[str, str] = {
    "a10": "A10 Networks",
    "accedian": "Accedian Skylight",
    "adtran_os": "ADTRAN AOS",
    "adva_fsp150f2": "ADVA FSP 150 F2",
    "adva_fsp150f3": "ADVA FSP 150 F3",
    "alaxala_ax26s": "Alaxala AX26S",
    "alaxala_ax36s": "Alaxala AX36S",
    "alcatel_aos": "Alcatel-Lucent AOS",
    "alcatel_sros": "Alcatel-Lucent SR OS",
    "allied_telesis_awplus": "Allied Telesis AlliedWare Plus",
    "apc_aos": "APC AOS",
    "apresia_aeos": "APRESIA AEOS",
    "arista_eos": "Arista EOS",
    "arris_cer": "ARRIS E6000 CER",
    "aruba_aoscx": "ArubaOS-CX",
    "aruba_os": "ArubaOS",
    "aruba_osswitch": "ArubaOS-Switch",
    "aruba_procurve": "ArubaOS-S",
    "asterfusion_asternos": "Asterfusion AsterNOS",
    "audiocode_66": "AudioCodes 6.6",
    "audiocode_72": "AudioCodes 7.2",
    "audiocode_shell": "AudioCodes Shell",
    "avara_aos": "Avara AOS",
    "avaya_ers": "Avaya ERS",
    "avaya_vsp": "Avaya VSP",
    "aviat_wtm": "Aviat WTM",
    "bintec_boss": "Bintec BOSS",
    "broadcom_icos": "Broadcom ICOS",
    "brocade_fastiron": "Brocade FastIron",
    "brocade_fos": "Brocade FOS",
    "brocade_netiron": "Brocade NetIron",
    "brocade_nos": "Brocade NOS",
    "brocade_vdx": "Brocade VDX",
    "brocade_vyos": "Brocade VyOS",
    "calix_b6": "Calix B6",
    "calix_exa": "Calix EXA",
    "casa_cmts": "Casa Systems CMTS",
    "cdot_cros": "C-DOT CROS",
    "centec_os": "Centec OS",
    "checkpoint_gaia": "Check Point Gaia",
    "ciena_saos": "Ciena SAOS",
    "ciena_saos10": "Ciena SAOS 10",
    "ciena_waveserver": "Ciena Waveserver",
    "cisco_ap": "Cisco AP",
    "cisco_apic": "Cisco APIC",
    "cisco_asa": "Cisco ASA",
    "cisco_ftd": "Cisco FTD",
    "cisco_ios": "Cisco IOS",
    "cisco_ioswlc": "Cisco IOS WLC",
    "cisco_nxos": "Cisco NX-OS",
    "cisco_s200": "Cisco Small Business 200",
    "cisco_s300": "Cisco Small Business 300",
    "cisco_s500": "Cisco Small Business 500",
    "cisco_tp": "Cisco TelePresence",
    "cisco_viptela": "Cisco Viptela",
    "cisco_wlc": "Cisco WLC",
    "cisco_xe": "Cisco IOS-XE",
    "cisco_xr": "Cisco IOS-XR",
    "cloudgenix_ion": "CloudGenix ION",
    "corelight_linux": "Corelight Linux",
    "coriant": "Coriant",
    "cumulus_linux": "Cumulus Linux",
    "dell_dnos6": "Dell DNOS6",
    "dell_dnos9": "Dell DNOS9",
    "dell_force10": "Dell Force10",
    "dell_isilon": "Dell EMC Isilon",
    "dell_os10": "Dell OS10",
    "dell_os6": "Dell OS6",
    "dell_os9": "Dell OS9",
    "dell_powerconnect": "Dell PowerConnect",
    "dell_sonic": "Dell SONiC",
    "digi_transport": "Digi TransPort",
    "dlink_ds": "D-Link DS",
    "edgecore_sonic": "Edgecore SONiC",
    "ekinops_ek360": "Ekinops EK360",
    "eltex": "Eltex",
    "eltex_esr": "Eltex ESR",
    "endace": "Endace OS",
    "enterasys": "Enterasys",
    "ericsson_ipos": "Ericsson IPOS",
    "ericsson_mltn63": "Ericsson MINI-LINK TN 6.3",
    "ericsson_mltn66": "Ericsson MINI-LINK TN 6.6",
    "extreme": "Extreme",
    "extreme_ers": "Extreme ERS",
    "extreme_exos": "Extreme EXOS",
    "extreme_netiron": "Extreme NetIron",
    "extreme_nos": "Extreme NOS",
    "extreme_slx": "Extreme SLX-OS",
    "extreme_tierra": "Extreme TierraOS",
    "extreme_vdx": "Extreme VDX",
    "extreme_vsp": "Extreme VSP",
    "extreme_wing": "Extreme WiNG",
    "f5_linux": "F5 Linux",
    "f5_ltm": "F5 BIG-IP LTM",
    "f5_tmsh": "F5 BIG-IP TMSH",
    "fiberstore_fsos": "FS FSOS",
    "fiberstore_fsosv2": "FS FSOSv2",
    "fiberstore_networkos": "FS NetworkOS",
    "flexvnf": "Versa FlexVNF",
    "fortinet": "Fortinet FortiOS",
    "fsas_sir": "Fujitsu Si-R",
    "fujitsu_sir": "Fujitsu Si-R (Legacy)",
    "furukawa_fitelnet": "Furukawa FITELnet",
    "garderos_grs": "Garderos GRS",
    "generic": "Generic CLI",
    "generic_termserver": "Generic Terminal Server",
    "genexis_solt33": "Genexis SOLT33",
    "h3c_comware": "H3C Comware",
    "hillstone_stoneos": "Hillstone StoneOS",
    "hioso_olt": "HiOSO OLT",
    "hirschmann_hios": "Hirschmann HiOS",
    "hp_comware": "HPE Comware",
    "hp_procurve": "HP ProCurve",
    "huawei": "Huawei",
    "huawei_olt": "Huawei OLT",
    "huawei_ont": "Huawei ONT",
    "huawei_smartax": "Huawei SmartAX",
    "huawei_smartaxmmi": "Huawei SmartAX MMI",
    "huawei_vrp": "Huawei VRP",
    "huawei_vrpv8": "Huawei VRPv8",
    "iij_seilos": "IIJ SEIL/OS",
    "infinera_packet": "Infinera Packet",
    "ipinfusion_ocnos": "IP Infusion OcNOS",
    "juniper": "Juniper",
    "juniper_junos": "Juniper Junos",
    "juniper_screenos": "Juniper ScreenOS",
    "keymile": "Keymile",
    "keymile_nos": "Keymile NOS",
    "lancom_lcossx4": "LANCOM LCOS SX 4",
    "lancom_lcossx5": "LANCOM LCOS SX 5",
    "linux": "Linux",
    "maipu": "Maipu MyPowerOS",
    "mellanox": "Mellanox",
    "mellanox_mlnxos": "Mellanox MLNX-OS",
    "mikrotik_routeros": "MikroTik RouterOS",
    "mikrotik_switchos": "MikroTik SwOS",
    "moxa_nos": "Moxa NOS",
    "mrv_lx": "MRV LX",
    "mrv_optiswitch": "MRV OptiSwitch",
    "nec_ix": "NEC IX",
    "netapp_cdot": "NetApp Clustered Data ONTAP",
    "netgear_prosafe": "Netgear ProSAFE",
    "netscaler": "Citrix NetScaler",
    "nokia_isam": "Nokia ISAM",
    "nokia_srl": "Nokia SR Linux",
    "nokia_sros": "Nokia SR OS",
    "oneaccess_oneos": "OneAccess OneOS",
    "opengear_linux": "Opengear Linux",
    "optilink_eolt11444": "Optilink EOLT11444",
    "optilink_eolt9702": "Optilink EOLT9702",
    "optilink_golt924": "Optilink GOLT924",
    "ovs_linux": "Open vSwitch Linux",
    "paloalto_panos": "Palo Alto PAN-OS",
    "perle_iolan": "Perle IOLAN",
    "pluribus": "Pluribus Netvisor ONE",
    "quanta_mesh": "QuantaMesh",
    "rad_etx": "RAD ETX",
    "raisecom": "Raisecom ROS",
    "raisecom_roap": "Raisecom ROAP",
    "raisecom_ros": "Raisecom ROS (Extended)",
    "ruckus_fastiron": "Ruckus FastIron",
    "ruijie_os": "Ruijie OS",
    "silverpeak_vxoa": "Aruba Silver Peak VXOA",
    "sixwind_os": "6WIND VSR OS",
    "smartoptics_dwdm": "Smartoptics DWDM",
    "sophos_sfos": "Sophos SFOS",
    "supermicro_smis": "Supermicro SMIS",
    "telcosystems_binos": "Telco Systems BiNOS",
    "teldat_cit": "Teldat CIT",
    "terminal_server": "Terminal Server",
    "tplink_jetstream": "TP-Link JetStream",
    "ubiquiti_edge": "Ubiquiti EdgeOS",
    "ubiquiti_edgerouter": "Ubiquiti EdgeRouter",
    "ubiquiti_edgeswitch": "Ubiquiti EdgeSwitch",
    "ubiquiti_unifiswitch": "Ubiquiti UniFi Switch",
    "vertiv_mph": "Vertiv MPH",
    "vyatta_vyos": "Vyatta VyOS",
    "vyos": "VyOS",
    "watchguard_fireware": "WatchGuard Fireware",
    "yamaha": "Yamaha RTX",
    "zpe_nodegrid": "ZPE Nodegrid",
    "zte_zxros": "ZTE ZXROS",
    "zyxel_os": "Zyxel OS",
}

_ACRONYM_TOKENS = {
    "a10": "A10",
    "aos": "AOS",
    "ap": "AP",
    "apic": "APIC",
    "asa": "ASA",
    "awplus": "AlliedWare Plus",
    "binos": "BiNOS",
    "boss": "BOSS",
    "cdot": "cDOT",
    "cer": "CER",
    "cit": "CIT",
    "cli": "CLI",
    "cmts": "CMTS",
    "cros": "CROS",
    "dnos6": "DNOS6",
    "dnos9": "DNOS9",
    "ds": "DS",
    "dwdm": "DWDM",
    "ek360": "EK360",
    "eos": "EOS",
    "ers": "ERS",
    "esr": "ESR",
    "etx": "ETX",
    "exa": "EXA",
    "exos": "EXOS",
    "f5": "F5",
    "fos": "FOS",
    "fsos": "FSOS",
    "ftd": "FTD",
    "gaia": "Gaia",
    "grs": "GRS",
    "h3c": "H3C",
    "hios": "HiOS",
    "hp": "HP",
    "hpe": "HPE",
    "icos": "ICOS",
    "iij": "IIJ",
    "iolan": "IOLAN",
    "ion": "ION",
    "ios": "IOS",
    "ioswlc": "IOS WLC",
    "ipos": "IPOS",
    "ix": "IX",
    "ltm": "LTM",
    "lx": "LX",
    "mlnxos": "MLNX-OS",
    "mmi": "MMI",
    "mph": "MPH",
    "mrv": "MRV",
    "nec": "NEC",
    "nos": "NOS",
    "nxos": "NX-OS",
    "ocnos": "OcNOS",
    "olt": "OLT",
    "ont": "ONT",
    "os": "OS",
    "os6": "OS6",
    "os9": "OS9",
    "os10": "OS10",
    "ovs": "OVS",
    "panos": "PAN-OS",
    "rad": "RAD",
    "roap": "ROAP",
    "ros": "ROS",
    "saos": "SAOS",
    "saos10": "SAOS 10",
    "sfos": "SFOS",
    "sir": "Si-R",
    "slx": "SLX",
    "smis": "SMIS",
    "sonic": "SONiC",
    "srl": "SR Linux",
    "sros": "SR OS",
    "tmsh": "TMSH",
    "tp": "TP",
    "tplink": "TP-Link",
    "vdx": "VDX",
    "vrp": "VRP",
    "vrpv8": "VRPv8",
    "vsp": "VSP",
    "vxoa": "VXOA",
    "vyos": "VyOS",
    "wlc": "WLC",
    "wtm": "WTM",
    "xe": "IOS-XE",
    "xr": "IOS-XR",
    "zpe": "ZPE",
    "zxros": "ZXROS",
}


def _humanize_platform_key(key: str) -> str:
    """Deterministically convert a Netmiko snake_case key into a readable product name."""
    parts = [p for p in (key or "").strip().lower().split("_") if p]
    if not parts:
        return ""
    out: List[str] = []
    for tok in parts:
        if tok in _ACRONYM_TOKENS:
            out.append(_ACRONYM_TOKENS[tok])
        elif tok.isdigit():
            out.append(tok)
        else:
            out.append(tok.capitalize())
    return " ".join(out)


def platform_display_name(platform: Optional[str]) -> str:
    """Return user-friendly display name for a Netmiko platform (e.g. 'aruba_procurve' -> 'ArubaOS-S')."""
    cleaned = (platform or "").strip().lower()
    if not cleaned:
        return ""
    if cleaned in PLATFORM_FRIENDLY_NAMES:
        return PLATFORM_FRIENDLY_NAMES[cleaned]
    return _humanize_platform_key(cleaned)


@lru_cache(maxsize=1)
def get_platform_labels() -> Dict[str, str]:
    """Return `{canonical_platform: friendly_name}` covering every supported Netmiko platform."""
    return {plat: platform_display_name(plat) for plat in get_supported_platforms()}


@lru_cache(maxsize=1)
def _platform_capabilities() -> Dict[str, Tuple[bool, bool]]:
    """
    Build {base_platform: (supports_ssh, supports_telnet)} directly from Netmiko's
    native `CLASS_MAPPER`, excluding serial-only drivers and non-connection dispatchers.
    """
    from netmiko.ssh_dispatcher import CLASS_MAPPER

    caps: Dict[str, Tuple[bool, bool]] = {}
    for raw_key in CLASS_MAPPER:
        if raw_key == "autodetect" or raw_key.endswith("_serial"):
            continue
        if raw_key.endswith("_telnet"):
            base = raw_key[:-7]
            has_ssh, _ = caps.get(base, (False, False))
            caps[base] = (has_ssh, True)
        elif raw_key.endswith("_ssh"):
            base = raw_key[:-4]
            _, has_telnet = caps.get(base, (False, False))
            caps[base] = (True, has_telnet)
        else:
            _, has_telnet = caps.get(raw_key, (False, False))
            caps[raw_key] = (True, has_telnet)
    return caps


def get_supported_platforms() -> List[str]:
    """Return sorted list of all native Netmiko base platforms supported over SSH/Telnet."""
    return sorted(_platform_capabilities().keys())


def is_supported_platform(platform: Optional[str]) -> bool:
    """Return True when `platform` is a supported base Netmiko platform."""
    cleaned = (platform or "").strip().lower()
    return bool(cleaned and cleaned in _platform_capabilities())


def canonical_platform(platform: Optional[str]) -> str:
    """Return canonical lowercase Netmiko platform string if supported, else ''."""
    cleaned = (platform or "").strip().lower()
    return cleaned if cleaned in _platform_capabilities() else ""


def get_supported_protocols(platform: Optional[str]) -> List[ConnectionProtocol]:
    """Return native Netmiko transport protocols supported for `platform`."""
    cleaned = canonical_platform(platform)
    if not cleaned:
        return [ConnectionProtocol.SSH]
    has_ssh, has_telnet = _platform_capabilities()[cleaned]
    protocols: List[ConnectionProtocol] = []
    if has_ssh:
        protocols.append(ConnectionProtocol.SSH)
    if has_telnet:
        protocols.append(ConnectionProtocol.TELNET)
    return protocols or [ConnectionProtocol.SSH]


def default_protocol_for_platform(
    platform: Optional[str],
    preferred: ConnectionProtocol = ConnectionProtocol.SSH,
) -> ConnectionProtocol:
    """Return `preferred` if natively supported for `platform`, else the platform's default."""
    supported = get_supported_protocols(platform)
    if preferred in supported:
        return preferred
    return supported[0]


def default_port_for_protocol(
    protocol: ConnectionProtocol,
    settings: Optional[AppSettings] = None,
) -> int:
    """Return global default TCP port for SSH or Telnet."""
    if protocol == ConnectionProtocol.TELNET:
        return int(settings.telnet_port) if settings is not None else 23
    return int(settings.ssh_port) if settings is not None else 22


def resolve_netmiko_device_type(
    platform: Optional[str],
    protocol: ConnectionProtocol = ConnectionProtocol.SSH,
) -> str:
    """
    Resolve `(platform, protocol)` to the exact native Netmiko `device_type` key
    registered in `CLASS_MAPPER`, raising `ValueError` if unsupported.
    """
    from netmiko.ssh_dispatcher import CLASS_MAPPER

    cleaned = canonical_platform(platform)
    if not cleaned:
        raw = (platform or "").strip()
        raise ValueError(
            f"Unsupported Netmiko platform: '{raw or 'Unmapped'}'."
        )

    if protocol == ConnectionProtocol.TELNET:
        telnet_key = f"{cleaned}_telnet"
        if telnet_key in CLASS_MAPPER:
            return telnet_key
        raise ValueError(
            f"Protocol 'Telnet' is not natively supported by Netmiko for '{cleaned}'."
        )

    if cleaned in CLASS_MAPPER:
        return cleaned
    ssh_key = f"{cleaned}_ssh"
    if ssh_key in CLASS_MAPPER:
        return ssh_key
    raise ValueError(
        f"Protocol 'SSH' is not natively supported by Netmiko for '{cleaned}'."
    )


def normalize_legacy_platform(
    raw: Optional[str],
) -> Tuple[str, Optional[ConnectionProtocol]]:
    """
    Normalize legacy OS names (`AOS-S`, `AOS-CX`, `Unknown`) or Netmiko
    driver keys (`*_telnet`, `*_ssh`) into `(base_platform, optional_protocol)`.
    """
    cleaned = (raw or "").strip()
    if not cleaned:
        return "", None
    low = cleaned.lower()
    if low in ("aos-s"):
        return "aruba_procurve", None
    if low in ("aos-cx"):
        return "aruba_aoscx", None
    if low in ("unknown", "unmapped"):
        return "", None

    caps = _platform_capabilities()
    if low.endswith("_telnet"):
        base = low[:-7]
        if base in caps and caps[base][1]:
            return base, ConnectionProtocol.TELNET
    if low.endswith("_ssh"):
        base = low[:-4]
        if base in caps and caps[base][0]:
            return base, ConnectionProtocol.SSH
    if low in caps:
        return low, None
    return "", None
