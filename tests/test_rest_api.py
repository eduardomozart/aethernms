"""End-to-end WSGI REST API, Authentication, Swagger/OpenAPI, and Job Execution tests for Py4Web app."""

from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from pssh_ui.ssh_runner import BatchSSHExecutor, PSSHClient
from pssh_ui.web_app import create_app


class _WSGIClient:
    """Minimal WSGI test client with automatic cookie persistence for Py4Web/ombott."""

    def __init__(self, wsgi_app: Any) -> None:
        self.app = wsgi_app
        self.cookies: Dict[str, str] = {}

    def request(
        self,
        method: str,
        path: str,
        json_body: Optional[Dict[str, Any]] = None,
        raw_body: Optional[bytes] = None,
        headers: Optional[Dict[str, str]] = None,
        use_cookies: bool = True,
    ) -> Tuple[int, Dict[str, str], bytes]:
        parts = urlsplit(path)
        body = raw_body or b""
        content_type = ""
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            content_type = "application/json"

        req_headers = dict(headers or {})
        if content_type and "Content-Type" not in req_headers:
            req_headers["Content-Type"] = content_type

        environ: Dict[str, Any] = {
            "REQUEST_METHOD": method.upper(),
            "PATH_INFO": parts.path,
            "QUERY_STRING": parts.query,
            "SERVER_NAME": "127.0.0.1",
            "SERVER_PORT": "8080",
            "SERVER_PROTOCOL": "HTTP/1.1",
            "wsgi.version": (1, 0),
            "wsgi.url_scheme": "http",
            "wsgi.input": BytesIO(body),
            "wsgi.errors": BytesIO(),
            "wsgi.multithread": True,
            "wsgi.multiprocess": False,
            "wsgi.run_once": False,
            "CONTENT_LENGTH": str(len(body)),
        }
        if "Content-Type" in req_headers:
            environ["CONTENT_TYPE"] = req_headers["Content-Type"]
        for hk, hv in req_headers.items():
            key = "HTTP_" + hk.upper().replace("-", "_")
            environ[key] = hv
        if use_cookies and self.cookies and "HTTP_COOKIE" not in environ:
            environ["HTTP_COOKIE"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())

        captured_status: List[str] = []
        captured_headers: List[Tuple[str, str]] = []

        def start_response(status: str, resp_headers: List[Tuple[str, str]], exc_info=None):
            captured_status.append(status)
            captured_headers.extend(resp_headers)

        chunks = list(self.app(environ, start_response))
        payload = b"".join(chunks)
        status_code = int(captured_status[0].split(" ", 1)[0]) if captured_status else 500

        hdr_map: Dict[str, str] = {}
        for k, v in captured_headers:
            lk = k.lower()
            if lk == "set-cookie" and use_cookies:
                cookie_pair = v.split(";", 1)[0].strip()
                if "=" in cookie_pair:
                    ck, cv = cookie_pair.split("=", 1)
                    if cv == "" or "max-age=0" in v.lower():
                        self.cookies.pop(ck.strip(), None)
                    else:
                        self.cookies[ck.strip()] = cv.strip()
            hdr_map[lk] = v
        return status_code, hdr_map, payload

    def get_json(self, path: str, **kwargs) -> Tuple[int, Any]:
        code, _hdrs, data = self.request("GET", path, **kwargs)
        return code, json.loads(data.decode("utf-8")) if data else None

    def post_json(self, path: str, body: Optional[Dict[str, Any]] = None, **kwargs) -> Tuple[int, Any]:
        code, _hdrs, data = self.request("POST", path, json_body=body or {}, **kwargs)
        return code, json.loads(data.decode("utf-8")) if data else None

    def put_json(self, path: str, body: Optional[Dict[str, Any]] = None, **kwargs) -> Tuple[int, Any]:
        code, _hdrs, data = self.request("PUT", path, json_body=body or {}, **kwargs)
        return code, json.loads(data.decode("utf-8")) if data else None

    def delete_json(self, path: str, **kwargs) -> Tuple[int, Any]:
        code, _hdrs, data = self.request("DELETE", path, **kwargs)
        return code, json.loads(data.decode("utf-8")) if data else None


class _FakeNetmikoConn:
    """Fake Netmiko connection for deterministic end-to-end REST job execution tests."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.prompt = "SW-TEST#"
        self.commands_seen: List[str] = []

    def find_prompt(self) -> str:
        return self.prompt

    def check_enable_mode(self) -> bool:
        return True

    def enable(self) -> str:
        return ""

    def config_mode(self) -> str:
        return "SW-TEST(config)#"

    def exit_config_mode(self) -> str:
        return "SW-TEST#"

    def send_command_timing(self, cmd: str, **kwargs) -> str:
        return self.send_command(cmd, **kwargs)

    def send_command(self, cmd: str, **kwargs) -> str:
        self.commands_seen.append(cmd)
        if "show running-config" in cmd:
            return "hostname SW-TEST\nntp server 10.1.1.1\n"
        if "show version" in cmd:
            return "ArubaOS-Switch WC.16.11.0005\n"
        return f"OK: {cmd}\n"

    def send_config_set(self, config_commands: List[str], **kwargs) -> str:
        self.commands_seen.extend(config_commands)
        return "\n".join(f"SW-TEST(config)# {c}" for c in config_commands) + "\n"

    def save_config(self) -> str:
        self.commands_seen.append("save_config")
        return "Configuration saved.\n"

    def disconnect(self) -> None:
        return None


_SAMPLE_AIRWAVE_XML = """<?xml version="1.0" encoding="utf-8"?>
<amp:amp_ap_list version="1" xmlns:amp="http://www.airwave.com">
  <ap id="101">
    <name>SW-AW-ACCESS-1</name>
    <lan_ip>10.50.0.10</lan_ip>
    <model>Aruba 2930F</model>
    <firmware>WC.16.11.0005</firmware>
    <folder id="10">Campus</folder>
    <device_category>switch</device_category>
    <serial_number>CN0001</serial_number>
    <is_up>true</is_up>
  </ap>
  <ap id="102">
    <name>SW-AW-UNMAPPED</name>
    <lan_ip>10.50.0.11</lan_ip>
    <model>MysterySwitch 9000</model>
    <firmware>1.0.0</firmware>
    <folder id="10">Campus</folder>
    <device_category>switch</device_category>
    <serial_number>CN0002</serial_number>
    <is_up>true</is_up>
    <operating_system>MysteryOS</operating_system>
  </ap>
</amp:amp_ap_list>
"""


def _make_test_client(tmp_path: Path):
    def _exec_factory():
        return BatchSSHExecutor(
            client_factory=lambda: PSSHClient(
                connect_handler_factory=lambda **kw: _FakeNetmikoConn(**kw)
            ),
            logs_base_dir=None,
        )

    def _fake_ping(ip: str) -> bool:
        return ip.endswith(".10") or ip.endswith(".1")

    def _fake_airwave(url: str, username: str, password: str, verify_ssl: bool = False):
        folders = {"10": {"id": "10", "name": "Campus", "parent_id": "0", "folder_path": "Campus"}}
        return folders, _SAMPLE_AIRWAVE_XML

    app, ctx = create_app(
        db_path=tmp_path / "pssh_ui.db",
        executor_factory=_exec_factory,
        ping_fn=_fake_ping,
        airwave_fetch_fn=_fake_airwave,
        seed_snippets=True,
        migrate_legacy_xml=False,
    )
    return _WSGIClient(app), ctx


def test_openapi_swagger_and_auth_lifecycle(tmp_path: Path):
    client, _ctx = _make_test_client(tmp_path)

    # OpenAPI & Swagger docs are publicly accessible
    code, spec = client.get_json("/api/openapi.json")
    assert code == 200
    assert spec["openapi"] == "3.0.3"
    assert "/api/jobs" in spec["paths"]
    assert "/api/devices" in spec["paths"]
    assert "/api/snippets/import" in spec["paths"]
    assert "ApiKeyHeader" in spec["components"]["securitySchemes"]
    assert "BearerAuth" in spec["components"]["securitySchemes"]

    for doc_path in ("/api/docs", "/swagger"):
        c, hdrs, body = client.request("GET", doc_path)
        assert c == 200
        assert "text/html" in hdrs.get("content-type", "")
        assert b"/api/openapi.json" in body

    # Unauthenticated UI routes redirect to /login; API returns 401
    for ui_path in ("/", "/jobs", "/snippets", "/devices"):
        c_ui, hdrs_ui, _ = client.request("GET", ui_path)
        assert c_ui in (302, 303)
        assert "/login" in hdrs_ui.get("location", "")

    c_unauth, err_unauth = client.get_json("/api/devices")
    assert c_unauth == 401
    assert "error" in err_unauth

    # Status shows initial setup required
    c_st, st = client.get_json("/api/auth/status")
    assert c_st == 200
    assert st["needs_setup"] is True
    assert st["authenticated"] is False

    # Complete first-time admin setup (auto-signs session in)
    c_set, set_res = client.post_json("/api/auth/setup", {"username": "admin", "password": "Password123!"})
    assert c_set == 201
    assert set_res["authenticated"] is True
    assert set_res["username"] == "admin"

    # Second setup attempt is rejected
    c_set2, _ = client.post_json("/api/auth/setup", {"username": "admin2", "password": "Password123!"})
    assert c_set2 == 400

    # Authenticated session renders each split page cleanly via Py4Web layout.html
    c_home, _, body_home = client.request("GET", "/")
    assert c_home == 200
    assert b'id="view-jobs"' in body_home
    assert b"/static/js/core.js" in body_home
    assert b"/static/js/jobs.js" in body_home
    assert b'id="modal-add-job"' in body_home
    assert b'id="view-snippets"' not in body_home
    assert b'id="view-devices"' not in body_home

    c_snips_pg, _, body_snips = client.request("GET", "/snippets")
    assert c_snips_pg == 200
    assert b'id="view-snippets"' in body_snips
    assert b'href="/snippets" aria-current="page"' in body_snips
    assert b"/static/js/snippets.js" in body_snips
    assert b'id="modal-snippet"' in body_snips
    assert b'id="modal-settings"' in body_snips
    assert b'id="view-jobs"' not in body_snips

    c_devs_pg, _, body_devs = client.request("GET", "/devices")
    assert c_devs_pg == 200
    assert b'id="view-devices"' in body_devs
    assert b'href="/devices" aria-current="page"' in body_devs
    assert b"/static/js/devices.js" in body_devs
    assert b'id="modal-airwave"' in body_devs
    assert b'id="modal-settings"' in body_devs
    assert b'id="view-jobs"' not in body_devs

    # Create API key, then logout and authenticate via X-API-Key & Bearer
    c_key, key_obj = client.post_json("/api/auth/api-keys", {"name": "Automation"})
    assert c_key == 201
    token = key_obj["token"]
    assert token.startswith("pssh_")

    c_out, _ = client.post_json("/api/auth/logout")
    assert c_out == 200
    c_after_out, _ = client.get_json("/api/devices")
    assert c_after_out == 401

    c_xkey, meta = client.get_json("/api/meta", headers={"X-API-Key": token}, use_cookies=False)
    assert c_xkey == 200
    assert meta["username"] == "admin"
    assert "aruba_procurve" in meta["platforms"]

    c_bearer, i18n = client.get_json(
        "/api/i18n",
        headers={"Authorization": f"Bearer {token}"},
        use_cookies=False,
    )
    assert c_bearer == 200
    assert isinstance(i18n["catalog"], dict)

    # Re-login with password and change password
    c_log, log_res = client.post_json("/api/auth/login", {"username": "admin", "password": "Password123!"})
    assert c_log == 200
    assert log_res["authenticated"] is True

    c_pw, _ = client.post_json(
        "/api/auth/password",
        {"current_password": "Password123!", "new_password": "UpdatedPass456!"},
    )
    assert c_pw == 200

    # Revoke API key and confirm rejection
    c_rev, _ = client.delete_json(f"/api/auth/api-keys/{key_obj['id']}")
    assert c_rev == 200
    c_rev_check, _ = client.get_json("/api/meta", headers={"X-API-Key": token}, use_cookies=False)
    assert c_rev_check == 401


def test_settings_devices_airwave_snippets_and_jobs_rest_workflow(tmp_path: Path):
    client, _ctx = _make_test_client(tmp_path)
    c_set, _ = client.post_json("/api/auth/setup", {"username": "admin", "password": "Password123!"})
    assert c_set == 201

    # 1. Settings update
    c_s, saved_s = client.put_json(
        "/api/settings",
        {
            "language": "en",
            "theme_mode": "dark",
            "ssh_username": "netops",
            "default_protocol": "SSH",
            "ssh_port": 22,
            "telnet_port": 23,
            "schedule_sequence": "Concurrent",
            "max_parallel": 8,
            "command_timeout": 20,
            "connect_timeout": 10,
        },
    )
    assert c_s == 200
    assert saved_s["theme_mode"] == "dark"
    assert saved_s["max_parallel"] == 8

    # 2. Devices CRUD & Ping
    c_dev, dev = client.post_json(
        "/api/devices",
        {
            "name": "SW-CORE-01",
            "ip": "10.0.0.1",
            "os_type": "aruba_procurve",
            "protocol": "SSH",
            "port": 22,
            "model": "2930F",
            "folder_path": "Top/Core",
        },
    )
    assert c_dev == 201
    dev_id = dev["id"]
    assert dev["is_airwave"] is False

    c_ping, ping_res = client.post_json("/api/devices/ping", {"device_ids": [dev_id]})
    assert c_ping == 200
    assert ping_res["by_id"][str(dev_id)] == "Up"

    # 3. AirWave Fetch & Import (with unmapped OS resolution & read-only enforcement)
    c_awf, awf = client.post_json(
        "/api/airwave/fetch",
        {"url": "https://amp.local", "username": "aw", "password": "pw", "verify_ssl": False},
    )
    assert c_awf == 200
    assert awf["total_records"] == 2
    assert len(awf["unmapped_groups"]) == 1
    assert awf["unmapped_groups"][0]["key"] == "MysteryOS"

    c_awi, awi = client.post_json(
        "/api/airwave/import",
        {
            "devices": awf["items"],
            "os_mappings": {"MysteryOS": "hp_comware"},
            "airwave_url": "https://amp.local",
            "airwave_username": "aw",
        },
    )
    assert c_awi == 200
    assert awi["imported"] == 2

    aw_dev = next(d for d in awi["items"] if d["name"] == "SW-AW-ACCESS-1")
    assert aw_dev["is_airwave"] is True
    # Attempt to overwrite read-only name/ip while changing port -> identity preserved, port updated
    c_aw_upd, aw_upd = client.put_json(
        f"/api/devices/{aw_dev['id']}",
        {
            "name": "SHOULD-NOT-CHANGE",
            "ip": "192.168.99.99",
            "os_type": "aruba_osswitch",
            "protocol": "SSH",
            "port": 2222,
        },
    )
    assert c_aw_upd == 200
    assert aw_upd["name"] == "SW-AW-ACCESS-1"
    assert aw_upd["ip"] == "10.50.0.10"
    assert aw_upd["os_type"] == "aruba_osswitch"
    assert aw_upd["port"] == 2222

    # 4. Snippets CRUD + XML Export/Import + Variable Parser
    c_sn_list, sn_list = client.get_json("/api/snippets")
    assert c_sn_list == 200
    assert len(sn_list["items"]) >= 1

    c_sn, sn = client.post_json(
        "/api/snippets",
        {
            "name": "API NTP Audit",
            "folder": "aruba/aruba_procurve",
            "snippet_type": "Audit and Remediate",
            "device_type": "aruba_procurve",
            "severity": "Major",
            "description": "Verify NTP server",
            "commands": "show running-config",
            "audit_regex": r"ntp server ${ntp_ip|\d+\.\d+\.\d+\.\d+}",
        },
    )
    assert c_sn == 201
    sn_id = sn["id"]

    c_exp, exp_hdrs, exp_xml = client.request("GET", f"/api/snippets/{sn_id}/export")
    assert c_exp == 200
    assert "application/xml" in exp_hdrs.get("content-type", "")
    assert b"API NTP Audit" in exp_xml

    c_imp, imp_sn = client.post_json(
        "/api/snippets/import",
        {"xml": exp_xml.decode("utf-8"), "filename": "api_ntp_audit.xml"},
    )
    assert c_imp == 201
    assert imp_sn["name"] == "API NTP Audit"

    c_vp, vp = client.post_json(
        "/api/variables/parse",
        {
            "commands": "configure\nntp server ${ntp_ip}\npassword ${pw|password}",
            "audit_regex": "",
            "values": {"ntp_ip": "10.1.1.1", "pw": "TopSecret!"},
        },
    )
    assert c_vp == 200
    assert vp["errors"] == {}
    assert "10.1.1.1" in vp["rendered_commands"]
    assert "TopSecret!" not in vp["rendered_commands"]
    assert "********" in vp["rendered_commands"]

    # 5. Create Audit Job -> wait for background thread -> inspect SQLite log JSON & download
    c_job, job = client.post_json(
        "/api/jobs",
        {
            "name": "NTP Compliance Audit",
            "job_type": "Audit and Remediate",
            "device_type": "aruba_procurve",
            "snippet_name": "API NTP Audit",
            "commands_raw": "show running-config",
            "audit_regex": r"ntp server ${ntp_ip|\d+\.\d+\.\d+\.\d+}",
            "values": {"ntp_ip": "10.1.1.1"},
            "device_ids": [dev_id],
            "username": "netops",
            "password": "sshpassword",
            "schedule_sequence": "Concurrent",
            "max_parallel": 2,
        },
    )
    assert c_job == 201
    job_uid = job["job_id"]

    # Poll until completed
    final_job = job
    for _ in range(50):
        c_g, final_job = client.get_json(f"/api/jobs/{job_uid}")
        assert c_g == 200
        if final_job["status"] != "Running":
            break
        time.sleep(0.05)

    assert final_job["status"] == "Success"
    assert len(final_job["results"]) == 1
    res_row = final_job["results"][0]
    assert res_row["status"] == "Success"
    assert res_row["has_log"] is True

    # Inspect JSON log endpoint
    c_log, log_data = client.get_json(f"/api/jobs/{job_uid}/results/{res_row['id']}/log")
    assert c_log == 200
    assert "ntp server 10.1.1.1" in log_data["formatted_log"]
    assert log_data["filename"].endswith(".log")

    # Download plain-text .log attachment
    c_dl, dl_hdrs, dl_bytes = client.request(
        "GET", f"/api/jobs/{job_uid}/results/{res_row['id']}/log?download=1"
    )
    assert c_dl == 200
    assert "attachment" in dl_hdrs.get("content-disposition", "")
    assert b"ntp server 10.1.1.1" in dl_bytes

    # 6. Create Config Job with include_write=True
    c_cfg, cfg_job = client.post_json(
        "/api/jobs",
        {
            "name": "Push Banner Config",
            "job_type": "Config",
            "device_type": "aruba_procurve",
            "commands_raw": "configure\nhostname ${host_name}",
            "values": {"host_name": "SW-CORE-01"},
            "device_ids": [dev_id],
            "username": "netops",
            "password": "sshpassword",
            "include_write": True,
        },
    )
    assert c_cfg == 201
    cfg_uid = cfg_job["job_id"]
    for _ in range(50):
        _, cfg_job = client.get_json(f"/api/jobs/{cfg_uid}")
        if cfg_job["status"] != "Running":
            break
        time.sleep(0.05)
    assert cfg_job["status"] == "Success"
    assert cfg_job["include_write"] is True

    # Delete finished job
    c_del, _ = client.delete_json(f"/api/jobs/{job_uid}")
    assert c_del == 200
    c_gone, _ = client.get_json(f"/api/jobs/{job_uid}")
    assert c_gone == 404
