"""Tests for AirWave folder/device XML parsing, OS classification, and filtering."""

from httmock import HTTMock, urlmatch

from pssh_ui.airwave_importer import (
    build_folder_hierarchy_options,
    build_folder_options_from_hosts,
    fetch_airwave_inventory,
    host_matches_airwave_filter,
    infer_switch_os,
    parse_airwave_devices,
    parse_airwave_folders,
)
from pssh_ui.models import AirWaveFilter, HostEntry, SwitchOS, is_airwave_host


SAMPLE_FOLDER_XML = """<?xml version="1.0" encoding="utf-8"?>
<amp:amp_folder_list version="1" xmlns:amp="http://www.airwave.com">
  <folder id="1"><name>Top</name><parent_id>0</parent_id></folder>
  <folder id="10"><name>Campus</name><parent_id>1</parent_id></folder>
  <folder id="11"><name>Building A</name><parent_id>10</parent_id></folder>
  <folder id="12"><name>Building B</name><parent_id>10</parent_id></folder>
</amp:amp_folder_list>
"""

SAMPLE_AP_XML = """<?xml version="1.0" encoding="utf-8"?>
<amp:amp_ap_list version="1" xmlns:amp="http://www.airwave.com">
  <ap id="101">
    <name>SW-A-2930</name>
    <lan_ip>10.1.1.10</lan_ip>
    <device_category>switch</device_category>
    <model>Aruba 2930F-24G-PoE+</model>
    <firmware>WC.16.10.0017</firmware>
    <is_up>true</is_up>
    <operating_mode>Commander</operating_mode>
    <serial_number>SN101</serial_number>
    <folder id="11">Building A</folder>
  </ap>
  <ap id="102">
    <name>SW-A-2930-2</name>
    <lan_ip>10.1.1.10</lan_ip>
    <device_category>switch</device_category>
    <model>Aruba 2930F-24G-PoE+</model>
    <firmware>WC.16.10.0017</firmware>
    <is_up>true</is_up>
    <folder id="11">Building A</folder>
  </ap>
  <ap id="103">
    <name>SW-B-6300</name>
    <lan_ip>10.1.2.10</lan_ip>
    <device_category>switch</device_category>
    <model>Aruba 6300M</model>
    <firmware>FL.10.13.1000</firmware>
    <is_up>false</is_up>
    <serial_number>SN103</serial_number>
    <folder id="12">Building B</folder>
  </ap>
  <ap id="104">
    <name>AP-A-01</name>
    <lan_ip>10.1.1.50</lan_ip>
    <device_category>thin_ap</device_category>
    <model>AP 515</model>
    <firmware>8.10.0.0</firmware>
    <is_up>true</is_up>
    <folder id="11">Building A</folder>
  </ap>
</amp:amp_ap_list>
"""


def test_infer_switch_os():
    assert infer_switch_os("Aruba 2930F", "WC.16.10.0017") == SwitchOS.AOS_S
    assert infer_switch_os("HP 2530-24G", "YA.16.04.0008") == SwitchOS.AOS_S
    assert infer_switch_os("Aruba 6300M", "FL.10.13.1000") == SwitchOS.AOS_CX
    assert infer_switch_os("6200F", "") == SwitchOS.AOS_CX
    assert infer_switch_os("UnknownBox", "1.0") == SwitchOS.UNKNOWN


def test_parse_airwave_filters_and_stack_deduplication():
    folders = parse_airwave_folders(SAMPLE_FOLDER_XML)
    assert folders["1"]["folder_path"] == "Top"
    assert folders["10"]["folder_path"] == "Top > Campus"
    assert folders["11"]["folder_path"] == "Top > Campus > Building A"

    opts = build_folder_hierarchy_options(folders)
    assert opts == [
        ("Top", "1"),
        ("  Campus", "10"),
        ("    Building A", "11"),
        ("    Building B", "12"),
    ]

    # Default filter: category='switch', exclude VSF duplicate SW-A-2930-2
    hosts, total = parse_airwave_devices(
        SAMPLE_AP_XML,
        folders=folders,
        filters=AirWaveFilter(folder="Top", category="switch", include_stacked=False),
    )
    assert total == 4
    assert [h.name for h in hosts] == ["SW-A-2930", "SW-B-6300"]
    assert hosts[0].os_type == SwitchOS.AOS_S
    assert hosts[1].os_type == SwitchOS.AOS_CX

    # Name and IP filters
    by_name, _ = parse_airwave_devices(
        SAMPLE_AP_XML,
        folders=folders,
        filters=AirWaveFilter(name_filter="SW-A"),
    )
    assert [h.name for h in by_name] == ["SW-A-2930"]

    by_ip, _ = parse_airwave_devices(
        SAMPLE_AP_XML,
        folders=folders,
        filters=AirWaveFilter(ip_filter="10.1.2."),
    )
    assert [h.name for h in by_ip] == ["SW-B-6300"]

    # Recursive folder filter on parent "Campus" + OS filter AOS-CX
    cx_hosts, _ = parse_airwave_devices(
        SAMPLE_AP_XML,
        folders=folders,
        filters=AirWaveFilter(folder="Campus", category="switch", os_filter="AOS-CX"),
    )
    assert [h.name for h in cx_hosts] == ["SW-B-6300"]

    # Include stacked members
    with_stack, _ = parse_airwave_devices(
        SAMPLE_AP_XML,
        folders=folders,
        filters=AirWaveFilter(folder="Building A", category="switch", include_stacked=True),
    )
    assert [h.name for h in with_stack] == ["SW-A-2930", "SW-A-2930-2"]


def test_fetch_airwave_inventory_with_httmock():
    @urlmatch(netloc=r"airwave\.local")
    def mock_airwave(url, request):
        if url.path.endswith("is_cred_obfusc.json"):
            return {"status_code": 200, "content": '{"is_cred_obfuscation": false}'}
        if url.path.endswith("LOGIN"):
            return {"status_code": 200, "headers": {"X-BISCOTTI": "tok123"}, "content": "OK"}
        if url.path.endswith("folder_list.xml"):
            return {"status_code": 200, "content": SAMPLE_FOLDER_XML}
        if url.path.endswith("ap_list.xml"):
            return {"status_code": 200, "content": SAMPLE_AP_XML}
        return {"status_code": 404, "content": ""}

    with HTTMock(mock_airwave):
        folders, ap_xml = fetch_airwave_inventory("airwave.local", "admin", "dummy_pass")

    assert "11" in folders
    hosts, _ = parse_airwave_devices(ap_xml, folders=folders)
    assert len(hosts) == 2


def test_is_airwave_host_and_cached_host_filtering():
    manual = HostEntry(name="Manual-SW", ip="10.0.0.1", airwave_status="Manual")
    aw_s = HostEntry(
        name="SW-A",
        ip="10.1.1.10",
        os_type=SwitchOS.AOS_S,
        model="Aruba 2930F",
        folder_id="11",
        folder_path="Top > Campus > Building A",
        airwave_status="Up",
    )
    aw_cx = HostEntry(
        name="SW-B",
        ip="10.1.2.10",
        os_type=SwitchOS.AOS_CX,
        model="Aruba 6300M",
        folder_id="12",
        folder_path="Top > Campus > Building B",
        airwave_status="Down",
    )
    assert not is_airwave_host(manual)
    assert is_airwave_host(aw_s)
    assert is_airwave_host(aw_cx)

    assert build_folder_options_from_hosts([aw_s, aw_cx]) == [
        ("Top", "Top"),
        ("  Campus", "Top > Campus"),
        ("    Building A", "Top > Campus > Building A"),
        ("    Building B", "Top > Campus > Building B"),
    ]

    assert host_matches_airwave_filter(aw_s, AirWaveFilter(folder="Top > Campus"))
    assert host_matches_airwave_filter(aw_s, AirWaveFilter(name_filter="SW-A", os_filter="AOS-S"))
    assert not host_matches_airwave_filter(aw_s, AirWaveFilter(os_filter="AOS-CX"))
    assert not host_matches_airwave_filter(aw_cx, AirWaveFilter(status_filter="Up"))
    assert host_matches_airwave_filter(aw_cx, AirWaveFilter(ip_filter="10.1.2."))
