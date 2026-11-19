# REST API & Swagger Documentation (`/api/docs`)

**`aethernms`** (**ÆTHER NMS**) exposes every workspace workflow through an authenticated JSON REST API documented with **OpenAPI 3.0.3** and interactive **Swagger UI**.

## 1. Enabling External API Access & Swagger UI

For security, **External REST API & Swagger UI** are **disabled by default** (`api_enabled = False`) and restricted to `127.0.0.1, ::1` (`api_allowed_ips`).

1. Complete initial setup at **`/setup`**, sign in as an Administrator, and open **Administration → System Settings**.
2. Toggle **External REST API & Swagger UI** to **Enabled**.
3. Configure **Allowed IP Addresses / CIDRs** (comma-separated IPv4/IPv6 addresses, CIDR subnets like `10.0.0.0/8`, or `*`).
4. Click **Save Settings**, then open **API Docs (Swagger)** (`GET /api/docs` or `GET /swagger`) or fetch **`GET /api/openapi.json`**.

> Note: Interactive Web UI password login lives strictly on `/login` and `/setup`. External `/api/*` clients and Swagger UI authenticate via API Keys only. While unconfigured, `/api/*` endpoints return HTTP `503` with `{"setup_required": true}`.

## 2. Authentication

All external `/api/*` requests require a valid API key (created under **Administration → API Keys** or via `POST /api/auth/api-keys`) from an allowed IP:

1. **API Key Header (recommended):**
   ```http
   X-API-Key: aethernms_<your_token>
   ```
2. **Bearer Token Header:**
   ```http
   Authorization: Bearer aethernms_<your_token>
   ```

API keys can optionally bind to a specific RBAC role (`role_name`) or inherit their owning user's role. Keys are stored as SHA-256 digests; the plaintext token is displayed once upon creation.

## 3. Endpoints Overview

| Area | Method & Path | Purpose |
| :--- | :--- | :--- |
| **Setup** | `GET /setup/info`, `POST /setup/test-db`, `POST /setup` | Inspect DB engine/driver readiness, test connectivity, and perform initial setup (locked out with `403` once Admin exists) |
| **Auth & Keys** | `GET /api/auth/status` | Verify API key identity, effective role, and granted permissions |
| **Auth & Keys** | `GET / POST /api/auth/api-keys`, `DELETE /api/auth/api-keys/{id}` | List, generate, or revoke scoped REST API keys |
| **RBAC** | `GET / POST /api/users`, `PUT / DELETE /api/users/{id}` | Manage user accounts (`users:manage`) or update own profile (`?edit=me` scope) |
| **RBAC** | `GET / POST /api/roles`, `PUT / DELETE /api/roles/{id}` | Manage custom RBAC roles (`roles:manage`; built-in system roles return `403`) |
| **Metadata** | `GET /api/meta`, `GET /api/i18n`, `GET /i18n` | Supported Netmiko platforms + friendly labels, native protocols, icons, and UI translations |
| **Settings** | `GET / PUT /api/settings` | Read or update Execution/Connection Defaults, External API & IP allowlist, AirWave mappings, and read-only `db_engine` / `db_uri_masked` |
| **Devices** | `GET / POST /api/devices`, `PUT / DELETE /api/devices/{id}`, `GET /api/devices/search` | Manage devices and run global device search (`?q=...&limit=...`) |
| **Devices** | `POST /api/devices/ping` | Run concurrent ICMP reachability probes and persist `"Up"` / `"Down"` statuses |
| **AirWave** | `POST /api/airwave/fetch`, `POST /api/airwave/import` | Fetch live AirWave inventory XML and merge selected switches with optional custom OS mappings |
| **Snippets** | `GET / POST /api/snippets`, `PUT / DELETE /api/snippets/{id}` | Manage custom snippets (read-only built-in snippets return `403` on modify/delete) |
| **Snippets** | `POST /api/snippets/import`, `GET /api/snippets/{id}/export` | Import or export portable `<Snippet>` XML files |
| **Variables** | `POST /api/variables/parse` | Extract `${...}` template variables, validate values, and preview masked rendered commands |
| **Jobs** | `GET / POST /api/jobs`, `GET / DELETE /api/jobs/{job_id}`, `POST /api/jobs/{job_id}/stop` | List, launch, inspect, cancel, or delete Netmiko Config/Audit jobs |
| **Logs** | `GET /api/jobs/{job_id}/results/{result_id}/log` | Fetch per-device execution log JSON (append `?download=1` to download `.log` plain text) |

## 4. Examples (`curl` & Python)

### List Devices
```bash
curl -s http://127.0.0.1:8000/api/devices \
  -H "X-API-Key: aethernms_YOUR_API_KEY"
```

### Launch a Config Job
```bash
curl -s -X POST http://127.0.0.1:8000/api/jobs \
  -H "Content-Type: application/json" \
  -H "X-API-Key: aethernms_YOUR_API_KEY" \
  -d '{
    "name": "Configure NTP",
    "job_type": "Config",
    "device_type": "aruba_procurve",
    "commands_raw": "ntp server ${NTP Server}\nntp enable",
    "values": {"NTP Server": "10.0.0.10"},
    "device_ids": [1, 2],
    "username": "netops",
    "password": "YOUR_SSH_PASSWORD",
    "schedule_sequence": "Concurrent",
    "max_parallel": 10,
    "include_write": true
  }'
```

### Poll Job Completion & Download Per-Device `.log`
```python
import time
import requests

BASE = "http://127.0.0.1:8000"
HEADERS = {"Authorization": "Bearer aethernms_YOUR_API_KEY"}

job_id = "a1b2c3d4e5"
while True:
    job = requests.get(f"{BASE}/api/jobs/{job_id}", headers=HEADERS).json()
    if job["status"] != "Running":
        break
    time.sleep(1)

for res in job["results"]:
    log_res = requests.get(
        f"{BASE}/api/jobs/{job_id}/results/{res['id']}/log?download=1",
        headers=HEADERS,
    )
    print(f"=== {res['host_name']} ({res['host_ip']}) ===")
    print(log_res.text)
```
