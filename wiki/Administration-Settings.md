# Administration: System Settings (`/administration/settings`)

The **System Settings** page (`system:settings` permission required) controls global automation defaults, External REST API access controls, AirWave integration settings, and read-only database inspection.

## 1. Connection & Execution Defaults

* **Default SSH Username**: Default username pre-filled when launching new jobs.
* **Default Protocol** (`SSH` or `Telnet`), **Default SSH Port** (`22`), and **Default Telnet Port** (`23`): Applied to newly created or imported devices while remaining overridable per device.
* **Max Parallel Executions** (`1–64`), **Execution Order** (`Concurrent` or `Sequential`), **Connect Timeout (s)**, and **Command Timeout (s)**: Tune Netmiko execution concurrency and responsiveness across large fleets.

## 2. External REST API & Swagger UI

* **External REST API & Swagger UI** is **disabled by default** (`api_enabled = False`) for defense in depth.
* Enable it and configure **Allowed IP Addresses / CIDRs** (`127.0.0.1, ::1` by default; supports individual IPv4/IPv6 addresses, CIDR subnets like `10.0.0.0/8`, or `*`) to permit API-key access to `/api/*`, `/api/docs`, `/swagger`, and `/api/openapi.json`.
* Click **Save Settings** in the page header to persist changes. *(Note: Language and Theme preferences are configured per user under **Administration → Users** or by clicking your username in the header.)*

## 3. Database Backend (Read-Only)

* Displays the active **Database Engine** and **Connection URI** configured during Initial Setup (`db_config.json`) or via `AETHERNMS_DB_URI` / `--db-uri`.
* Passwords and ODBC secrets are automatically masked (`********`).
