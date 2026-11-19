"""End-to-end WSGI REST API, Setup Guide, RBAC, External API/IP Allowlist, Swagger/OpenAPI, and Job tests."""

from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from aethernms.ssh_runner import BatchSSHExecutor, PSSHClient
from aethernms.web_app import create_app


class _WSGIClient:
    """Minimal WSGI test client with automatic cookie persistence for Py4Web/ombott."""

    def __init__(self, wsgi_app: Any, remote_addr: str = "127.0.0.1") -> None:
        self.app = wsgi_app
        self.remote_addr = remote_addr
        self.cookies: Dict[str, str] = {}

    def request(
        self,
        method: str,
        path: str,
        json_body: Optional[Dict[str, Any]] = None,
        raw_body: Optional[bytes] = None,
        headers: Optional[Dict[str, str]] = None,
        use_cookies: bool = True,
        remote_addr: Optional[str] = None,
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
            "SERVER_PORT": "8000",
            "REMOTE_ADDR": remote_addr if remote_addr is not None else self.remote_addr,
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


def _make_test_client(
    tmp_path: Path,
    *,
    db_path: Optional[Path] = None,
    config_dir: Optional[Path] = None,
    seed_snippets: bool = True,
):
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
        db_path=db_path,
        config_dir=config_dir,
        executor_factory=_exec_factory,
        ping_fn=_fake_ping,
        airwave_fetch_fn=_fake_airwave,
        seed_snippets=seed_snippets,
        migrate_legacy_xml=False,
    )
    return _WSGIClient(app), ctx


def test_uninitialized_setup_guide_redirects_lockout_and_no_premature_db(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("AETHERNMS_DB_URI", raising=False)
    monkeypatch.delenv("AETHERNMS_ADMIN_USER", raising=False)
    monkeypatch.delenv("AETHERNMS_ADMIN_PASSWORD", raising=False)

    cfg_dir = tmp_path / "fresh_cfg"
    client, ctx = _make_test_client(tmp_path, config_dir=cfg_dir)

    # Uninitialized startup must NOT create any .db or db_config.json prematurely
    assert ctx.db is None
    assert not (cfg_dir / "aethernms.db").exists()
    assert not (cfg_dir / "db_config.json").exists()

    # All UI routes redirect cleanly to /setup
    for path in (
        "/",
        "/login",
        "/jobs",
        "/snippets",
        "/devices",
        "/administration",
        "/administration/settings",
        "/administration/users",
        "/administration/roles",
        "/administration/api-keys",
    ):
        code, hdrs, _ = client.request("GET", path)
        assert code in (302, 303), path
        assert hdrs.get("location", "").endswith("/setup"), (path, hdrs)

    # /api/* returns 503 setup_required while unconfigured
    for api_path in ("/api/auth/status", "/api/devices", "/api/settings", "/api/meta", "/api/openapi.json"):
        c_api, err_api = client.get_json(api_path)
        assert c_api == 503, api_path
        assert err_api["setup_required"] is True

    c_sw, _, _ = client.request("GET", "/api/docs")
    assert c_sw == 503

    # /i18n works cleanly with AppSettings() fallback while ctx.db is None,
    # and respects BCP-47 hyphenated / comma-separated browser navigator languages
    c_i18n, i18n_data = client.get_json("/i18n")
    assert c_i18n == 200
    assert isinstance(i18n_data["catalog"], dict)

    for q_lang in ("pt-BR", "pt-BR,pt,en-US"):
        c_pt, pt_data = client.get_json(f"/i18n?lang={q_lang}")
        assert c_pt == 200
        assert pt_data["effective_language"] == "pt_BR"
        assert (
            pt_data["catalog"]["Initial administrator setup is required first."]
            == "A configuração inicial do administrador é necessária primeiro."
        )

    # GET /setup & GET /setup/info work and use shared ÆTHER NMS wordmark header
    c_pg, _, body_pg = client.request("GET", "/setup?lang=pt_BR")
    assert c_pg == 200
    assert b"setup-card" in body_pg
    assert b"/static/js/setup.js" in body_pg
    assert b"anms-brand-wordmark" in body_pg
    assert "ÆTHER".encode("utf-8") in body_pg
    assert b"anms-brand-sub" in body_pg
    assert b"NMS" in body_pg
    assert "Concluir".encode("utf-8") in body_pg
    assert b"setup-seed-snippets" not in body_pg
    assert b"aethernms-header.png" not in body_pg
    assert b"aethernms.png" not in body_pg

    c_info, info = client.get_json("/setup/info")
    assert c_info == 200
    assert info["needs_setup"] is True
    assert info["db_configured"] is False
    engine_ids = [e["id"] for e in info["engines"]]
    assert engine_ids == ["sqlite", "postgres", "mysql", "mssql", "oracle", "custom"]

    # POST /setup/test-db succeeds for SQLite without creating an orphan .db file
    custom_db = cfg_dir / "custom_aethernms.db"
    c_tdb, tdb = client.post_json(
        "/setup/test-db",
        {"engine": "sqlite", "sqlite_path": str(custom_db)},
    )
    assert c_tdb == 200
    assert tdb["ok"] is True
    assert not custom_db.exists()
    assert not (cfg_dir / "aethernms.db").exists()

    # Invalid Admin fields fail BEFORE creating DB on disk
    c_short, _ = client.post_json(
        "/setup",
        {
            "engine": "sqlite",
            "sqlite_path": str(custom_db),
            "username": "admin",
            "password": "123",
            "confirm_password": "123",
        },
    )
    assert c_short == 400
    assert not custom_db.exists()

    c_mismatch, _ = client.post_json(
        "/setup",
        {
            "engine": "sqlite",
            "sqlite_path": str(custom_db),
            "username": "admin",
            "password": "StrongPassword123!",
            "confirm_password": "DifferentPassword123!",
        },
    )
    assert c_mismatch == 400
    assert not custom_db.exists()

    # Complete 3-step Setup -> initializes DB, seeds roles + snippets, writes db_config.json, hot-swaps ctx.db, sets session
    c_done, done = client.post_json(
        "/setup",
        {
            "engine": "sqlite",
            "sqlite_path": str(custom_db),
            "username": "admin",
            "display_name": "Primary Admin",
            "password": "StrongPassword123!",
            "confirm_password": "StrongPassword123!",
            "seed_snippets": True,
        },
    )
    assert c_done == 201
    assert done["authenticated"] is True
    assert done["username"] == "admin"
    assert done["role"] == "Admin"
    assert done["db_engine"] == "sqlite"
    assert done["redirect"] == "/jobs"
    assert custom_db.is_file()
    assert (cfg_dir / "db_config.json").is_file()
    assert ctx.db is not None
    assert len(ctx.db.list_snippets()) >= 1

    # Immediate authenticated access to /jobs without server restart (with shared ÆTHER NMS header)
    c_jobs, _, body_jobs = client.request("GET", "/jobs")
    assert c_jobs == 200
    assert b'id="view-jobs"' in body_jobs
    assert b"anms-brand-wordmark" in body_jobs
    assert "ÆTHER".encode("utf-8") in body_jobs
    assert b"aethernms-header.png" not in body_jobs

    # Setup endpoints are permanently locked out after completion
    c_s_pg, hdrs_s_pg, _ = client.request("GET", "/setup")
    assert c_s_pg in (302, 303)
    assert "/jobs" in hdrs_s_pg.get("location", "")
    c_s_info, _ = client.get_json("/setup/info")
    assert c_s_info == 403
    c_s_test, _ = client.post_json("/setup/test-db", {"engine": "sqlite"})
    assert c_s_test == 403
    c_s_post, _ = client.post_json("/setup", {"username": "rogue", "password": "Password123!"})
    assert c_s_post == 403

    # Restarting create_app(config_dir=cfg_dir) automatically reconnects via db_config.json
    client2, ctx2 = _make_test_client(tmp_path, config_dir=cfg_dir)
    assert ctx2.db is not None
    assert ctx2.db_source == "config_file"
    assert ctx2.db.user_count() == 1
    c_login_redir, hdrs_lr, _ = client2.request("GET", "/jobs")
    assert c_login_redir in (302, 303)
    assert "/login" in hdrs_lr.get("location", "")


def test_renoir_fixes_external_api_gate_rbac_and_global_search(tmp_path: Path):
    client, _ctx = _make_test_client(tmp_path, db_path=tmp_path / "aethernms.db")

    # DB exists (explicit --db-path) with 0 users -> / and /login redirect to /setup
    for p in ("/", "/login", "/jobs", "/snippets", "/devices"):
        c_ui, hdrs_ui, _ = client.request("GET", p)
        assert c_ui in (302, 303)
        assert "/setup" in hdrs_ui.get("location", "")

    # Complete initial Admin setup
    c_set, set_res = client.post_json(
        "/setup",
        {"username": "admin", "display_name": "NetOps Admin", "password": "Password123!"},
    )
    assert c_set == 201
    assert set_res["authenticated"] is True

    # Renoir fix check: layout.html renders aria-expanded="false" on /jobs, "true" on /administration/settings
    c_jobs, _, body_jobs = client.request("GET", "/jobs")
    assert c_jobs == 200
    assert b'id="sidenav-admin-toggle"' in body_jobs
    assert b'aria-expanded="false"' in body_jobs

    c_settings_pg, _, body_settings = client.request("GET", "/administration/settings")
    assert c_settings_pg == 200
    assert b'aria-expanded="true"' in body_settings
    assert b'id="set-db-engine"' in body_settings
    assert b'id="set-db-uri"' in body_settings

    # Read-only db_engine & db_uri_masked in GET /api/settings (ignored on PUT)
    c_gs, gs = client.get_json("/api/settings")
    assert c_gs == 200
    assert gs["api_enabled"] is False
    assert gs["db_engine"] == "sqlite"
    assert "aethernms.db" in gs["db_uri_masked"]

    c_ps, ps = client.put_json(
        "/api/settings",
        {"db_engine": "oracle", "db_uri_masked": "oracle://spoofed", "ssh_username": "ops"},
    )
    assert c_ps == 200
    assert ps["db_engine"] == "sqlite"
    assert "aethernms.db" in ps["db_uri_masked"]
    assert ps["ssh_username"] == "ops"

    # External API and Swagger are disabled by default -> 403
    c_spec_off, _ = client.get_json("/api/openapi.json")
    assert c_spec_off == 403
    for doc_path in ("/api/docs", "/swagger"):
        c_doc_off, _, _ = client.request("GET", doc_path)
        assert c_doc_off == 403

    # Create API key while External API is disabled (UI session allowed), then verify key is blocked until enabled
    c_key, key_obj = client.post_json("/api/auth/api-keys", {"name": "Automation"})
    assert c_key == 201
    token = key_obj["token"]
    assert token.startswith("aethernms_")

    c_ext_blocked, _ = client.get_json("/api/meta", headers={"X-API-Key": token}, use_cookies=False)
    assert c_ext_blocked == 403

    # Enable External API restricted to 127.0.0.1, ::1
    c_en, en_s = client.put_json(
        "/api/settings",
        {"api_enabled": True, "api_allowed_ips": "127.0.0.1, ::1"},
    )
    assert c_en == 200
    assert en_s["api_enabled"] is True

    # Swagger & OpenAPI now accessible from allowed IP, blocked from external IP
    c_spec, spec = client.get_json("/api/openapi.json")
    assert c_spec == 200
    assert spec["openapi"] == "3.0.3"
    assert "/api/devices/search" in spec["paths"]
    assert "ApiKeyHeader" in spec["components"]["securitySchemes"]

    c_doc_on, doc_hdrs, doc_body = client.request("GET", "/api/docs")
    assert c_doc_on == 200
    assert "text/html" in doc_hdrs.get("content-type", "")
    assert b"/api/openapi.json" in doc_body
    assert b"anms-brand-wordmark" in doc_body
    assert "ÆTHER".encode("utf-8") in doc_body
    assert b"aethernms-header.png" not in doc_body

    c_bad_ip, _ = client.get_json(
        "/api/meta",
        headers={"X-API-Key": token},
        use_cookies=False,
        remote_addr="203.0.113.50",
    )
    assert c_bad_ip == 403

    c_ok_xkey, meta = client.get_json("/api/meta", headers={"X-API-Key": token}, use_cookies=False)
    assert c_ok_xkey == 200
    assert meta["username"] == "admin"

    c_ok_bearer, i18n = client.get_json(
        "/api/i18n",
        headers={"Authorization": f"Bearer {token}"},
        use_cookies=False,
    )
    assert c_ok_bearer == 200
    assert isinstance(i18n["catalog"], dict)

    # Global Device Search (/api/devices/search)
    client.post_json(
        "/api/devices",
        {
            "name": "SW-CAMPUS-CORE",
            "ip": "10.99.1.10",
            "os_type": "aruba_aoscx",
            "model": "8360",
            "folder_path": "Campus/Core",
        },
    )
    c_srch, srch = client.get_json("/api/devices/search?q=8360")
    assert c_srch == 200
    assert len(srch["items"]) == 1
    assert srch["items"][0]["name"] == "SW-CAMPUS-CORE"

    # RBAC: Custom role & scoped API key enforcement
    c_role, role_obj = client.post_json(
        "/api/roles",
        {"name": "Device Reader", "permissions": ["devices:read"]},
    )
    assert c_role == 201
    c_usr, _ = client.post_json(
        "/api/users",
        {"username": "reader1", "password": "ReaderPass123!", "role": "Device Reader"},
    )
    assert c_usr == 201

    c_vkey, vkey = client.post_json(
        "/api/auth/api-keys",
        {"name": "Read-Only Key", "role_name": role_obj["name"]},
    )
    assert c_vkey == 201
    c_read_dev, _ = client.get_json(
        "/api/devices/search?q=CAMPUS",
        headers={"X-API-Key": vkey["token"]},
        use_cookies=False,
    )
    assert c_read_dev == 200
    c_write_dev, _ = client.post_json(
        "/api/devices",
        {"name": "DENIED", "ip": "10.0.0.99", "os_type": "aruba_procurve"},
        headers={"X-API-Key": vkey["token"]},
        use_cookies=False,
    )
    assert c_write_dev == 403

    # Logout -> login.html renders data-needs-setup="false", shared header wordmark,
    # navigator.language lookup for /i18n, and forbidden 403 HTML uses shared header partial
    client.post_json("/logout")
    c_lpg, _, lpg_body = client.request("GET", "/login")
    assert c_lpg == 200
    assert b'data-needs-setup="false"' in lpg_body
    assert b"anms-brand-wordmark" in lpg_body
    assert "ÆTHER".encode("utf-8") in lpg_body
    assert b"navigator.languages" in lpg_body
    assert b"navigator.language" in lpg_body
    assert b"aethernms-header.png" not in lpg_body
    assert b"aethernms.png" not in lpg_body

    c_rlog, _ = client.post_json("/login", {"username": "reader1", "password": "ReaderPass123!"})
    assert c_rlog == 200
    c_forb_users, _, forb_body = client.request("GET", "/administration/users")
    assert c_forb_users == 403
    assert b"anms-brand-wordmark" in forb_body
    assert "ÆTHER".encode("utf-8") in forb_body
    assert b"aethernms-header.png" not in forb_body

    # Re-login as Admin, change password, revoke key
    client.post_json("/logout")
    c_alog, _ = client.post_json("/login", {"username": "admin", "password": "Password123!"})
    assert c_alog == 200
    c_pw, _ = client.post_json(
        "/account/password",
        {"current_password": "Password123!", "new_password": "UpdatedPass456!"},
    )
    assert c_pw == 200
    c_rev, _ = client.delete_json(f"/api/auth/api-keys/{key_obj['id']}")
    assert c_rev == 200
    c_rev_chk, _ = client.get_json("/api/meta", headers={"X-API-Key": token}, use_cookies=False)
    assert c_rev_chk == 401


def test_settings_devices_airwave_snippets_and_jobs_rest_workflow(tmp_path: Path):
    client, _ctx = _make_test_client(tmp_path, db_path=tmp_path / "aethernms.db")
    c_set, _ = client.post_json("/setup", {"username": "admin", "password": "Password123!"})
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

    c_log, log_data = client.get_json(f"/api/jobs/{job_uid}/results/{res_row['id']}/log")
    assert c_log == 200
    assert "ntp server 10.1.1.1" in log_data["formatted_log"]
    assert log_data["filename"].endswith(".log")

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


def test_phase2_ui_rbac_readonly_appearance_and_assets(tmp_path: Path):
    client, ctx = _make_test_client(tmp_path, db_path=tmp_path / "aethernms.db")
    c_set, _ = client.post_json(
        "/setup",
        {"username": "admin", "display_name": "Primary Admin", "password": "Password123!"},
    )
    assert c_set == 201

    # Logout & login case-insensitively; verify /login omits marketing subtitle
    client.post_json("/logout")
    c_login_pg, _, login_body = client.request("GET", "/login")
    assert c_login_pg == 200
    assert b"Config &amp; Audit Automation" not in login_body
    c_login, login_data = client.post_json("/login", {"username": "ADMIN", "password": "Password123!"})
    assert c_login == 200
    assert login_data["username"] == "admin"

    # Friendly Netmiko platform labels
    c_meta, meta = client.get_json("/api/meta")
    assert c_meta == 200
    assert meta["platform_labels"]["aruba_procurve"] == "ArubaOS-S"
    assert meta["platform_labels"]["aruba_aoscx"] == "ArubaOS-CX"

    # Served brand assets & touch icons
    for asset_path in (
        "/assets/aethernms.svg",
        "/assets/favicon.ico",
        "/assets/apple-touch-icon.png",
        "/assets/site.webmanifest",
    ):
        c_asset, _, asset_bytes = client.request("GET", asset_path)
        assert c_asset == 200 and len(asset_bytes) > 0

    # Built-in snippets are read-only (403); custom snippets remain writable
    c_snips, snips_data = client.get_json("/api/snippets")
    assert c_snips == 200
    builtin_snips = [s for s in snips_data["items"] if s.get("is_builtin")]
    assert builtin_snips
    b_id = builtin_snips[0]["id"]
    c_edit_b, _ = client.put_json(f"/api/snippets/{b_id}", {"name": "Hacked", "commands": "show ver"})
    assert c_edit_b == 403
    c_del_b, _ = client.delete_json(f"/api/snippets/{b_id}")
    assert c_del_b == 403

    # Built-in system roles are read-only (403)
    c_roles, roles_data = client.get_json("/api/roles")
    assert c_roles == 200
    sys_roles = [r for r in roles_data["items"] if r.get("is_system")]
    assert {r["name"] for r in sys_roles} == {"Admin", "Operator", "Viewer"}
    for r in sys_roles:
        c_edit_r, _ = client.put_json(f"/api/roles/{r['id']}", {"name": r["name"], "description": "hacked"})
        assert c_edit_r == 403
        c_del_r, _ = client.delete_json(f"/api/roles/{r['id']}")
        assert c_del_r == 403

    # Per-user language & theme SSR hydration + window title + header help/user links
    c_me_upd, me_upd = client.put_json(
        "/api/users/1",
        {"language": "pt_BR", "theme_mode": "dark", "display_name": "Admin PT"},
    )
    assert c_me_upd == 200
    assert me_upd["language"] == "pt_BR"
    assert me_upd["theme_mode"] == "dark"

    c_jobs_pt, _, jobs_pt_body = client.request("GET", "/jobs")
    assert c_jobs_pt == 200
    assert b'lang="pt-BR"' in jobs_pt_body
    assert b'data-carbon-theme="g100"' in jobs_pt_body
    assert b"<title>Tarefas - aether</title>" in jobs_pt_body
    assert b'id="anms-initial-i18n"' in jobs_pt_body
    assert b'href="/administration/users?edit=me"' in jobs_pt_body
    assert b"/user-guide/jobs/" in jobs_pt_body
    assert b'id="hdr-about-btn"' not in jobs_pt_body

    # Non-admin self-profile (?edit=me) vs blocked full admin (/administration/users)
    c_new_u, reader_u = client.post_json(
        "/api/users",
        {
            "username": "viewer1",
            "display_name": "Viewer One",
            "password": "ViewerPass123!",
            "role": "Viewer",
            "language": "en",
            "theme_mode": "light",
        },
    )
    assert c_new_u == 201
    reader_id = reader_u["id"]

    client.post_json("/logout")
    c_rlog, _ = client.post_json("/login", {"username": "viewer1", "password": "ViewerPass123!"})
    assert c_rlog == 200

    c_full_forb, _, _ = client.request("GET", "/administration/users")
    assert c_full_forb == 403
    c_me_page, _, me_page_body = client.request("GET", "/administration/users?edit=me")
    assert c_me_page == 200
    assert b'id="view-admin-users"' in me_page_body

    c_self_ok, self_data = client.put_json(
        f"/api/users/{reader_id}",
        {"display_name": "Updated Viewer", "language": "pt_BR", "theme_mode": "dark"},
    )
    assert c_self_ok == 200
    assert self_data["display_name"] == "Updated Viewer"
    assert self_data["theme_mode"] == "dark"

    c_esc, _ = client.put_json(f"/api/users/{reader_id}", {"role": "Admin"})
    assert c_esc == 403
    assert ctx.db is not None

