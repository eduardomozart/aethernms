# REST API & Swagger Documentation

**`pssh-ui`** exposes every GUI backend action through an authenticated JSON REST API served by **Py4Web**, documented automatically via **OpenAPI 3.0.3** and an interactive **Swagger UI**.

---

## 1. Interactive Swagger UI & OpenAPI Schema

When `pssh-ui` is running (default `http://127.0.0.1:8080`):

| Endpoint | Description |
| :--- | :--- |
| **`GET /api/docs`** (alias **`GET /swagger`**) | Interactive Swagger UI (with built-in offline OpenAPI explorer fallback when no internet CDN is reachable). |
| **`GET /api/openapi.json`** | Raw OpenAPI 3.0.3 specification JSON (importable into Postman, Insomnia, or SDK code generators). |

---

## 2. Authentication

All `/api/*` endpoints (except `/api/openapi.json`, `/api/i18n`, and `/api/auth/{status,setup,login,logout}`) require authentication via one of three methods:

1. **API Key Header (recommended for scripts & CI/CD):**
   ```http
   X-API-Key: pssh_<your_token>
   ```
2. **Bearer Token Header:**
   ```http
   Authorization: Bearer pssh_<your_token>
   ```
3. **Browser Session Cookie:**
   Signed Py4Web `pssh_ui_session` cookie obtained via `POST /api/auth/setup` (first run) or `POST /api/auth/login`.

Create and revoke API keys from the **API Keys** button (`🔑`) in the top header bar or via `POST /api/auth/api-keys`. Keys are hashed with SHA-256 in SQLite; the plaintext token is shown once upon creation.

For headless / automated deployments, you may pre-seed the initial administrator account before first boot using environment variables:

```bash
PSSH_UI_ADMIN_USER=admin
PSSH_UI_ADMIN_PASSWORD=StrongPassword123!
python main.py --host 0.0.0.0 --port 8080
```

---

## 3. Endpoints Overview

| Area | Method & Path | Purpose |
| :--- | :--- | :--- |
| **Auth** | `GET /api/auth/status` | Check whether initial admin setup is needed or current user is signed in |
| **Auth** | `POST /api/auth/setup` | Create the first administrator account (when DB has 0 users) |
| **Auth** | `POST /api/auth/login` / `POST /api/auth/logout` | Sign in / sign out with session cookie |
| **Auth** | `POST /api/auth/password` | Change the authenticated user's password |
| **Auth** | `GET / POST /api/auth/api-keys`, `DELETE /api/auth/api-keys/{id}` | List, generate, or revoke personal API keys |
| **Metadata** | `GET /api/meta`, `GET /api/i18n` | Supported Netmiko platforms, native protocols, app version, and UI translations |
| **Settings** | `GET / PUT /api/settings` | Read or update Appearance, Execution Defaults, Connection Defaults, and AirWave OS mappings |
| **Devices** | `GET / POST /api/devices`, `PUT / DELETE /api/devices/{id}` | Manage devices (enforces AirWave read-only identity fields & native Netmiko protocols) |
| **Devices** | `POST /api/devices/ping` | Run concurrent ICMP reachability probes and persist `"Up"` / `"Down"` statuses |
| **AirWave** | `POST /api/airwave/fetch`, `POST /api/airwave/import` | Fetch live AirWave inventory XML and merge selected switches with optional custom OS mappings |
| **Snippets** | `GET / POST /api/snippets`, `PUT / DELETE /api/snippets/{id}` | Manage Config and Audit snippets stored in SQLite |
| **Snippets** | `POST /api/snippets/import`, `GET /api/snippets/{id}/export` | Import or export portable `<Snippet>` XML files |
| **Variables** | `POST /api/variables/parse` | Extract `${...}` template variables, validate values, and preview masked rendered commands |
| **Jobs** | `GET / POST /api/jobs`, `GET / DELETE /api/jobs/{job_id}` | List jobs, create and launch a new Netmiko Config/Audit job, inspect status, or delete finished jobs |
| **Jobs** | `POST /api/jobs/{job_id}/stop` | Signal cancellation to a running background job |
| **Logs** | `GET /api/jobs/{job_id}/results/{result_id}/log` | Fetch per-device execution log JSON from SQLite (append `?download=1` to download `.log` plain text) |

---

## 4. Examples (`curl` & Python)

### List Devices
```bash
curl -s http://127.0.0.1:8080/api/devices \
  -H "X-API-Key: pssh_YOUR_API_KEY"
```

### Launch a Config Job
```bash
curl -s -X POST http://127.0.0.1:8080/api/jobs \
  -H "Content-Type: application/json" \
  -H "X-API-Key: pssh_YOUR_API_KEY" \
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

BASE = "http://127.0.0.1:8080"
HEADERS = {"Authorization": "Bearer pssh_YOUR_API_KEY"}

job_id = "a1b2c3d4e5"
while True:
    job = requests.get(f"{BASE}/api/jobs/{job_id}", headers=HEADERS).json()
    if job["status"] != "Running":
        break
    time.sleep(1)

for res in job["results"]:
    log_text = requests.get(
        f"{BASE}/api/jobs/{job_id}/results/{res['id']}/log?download=1",
        headers=HEADERS,
    ).text
    print(f"=== {res['host_name']} ({res['status']}) ===\n{log_text}")
```
