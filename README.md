# ÆTHER NMS

[![Release Version](https://img.shields.io/github/v/release/eduardomozart/aethernms?style=for-the-badge&logo=github)](https://github.com/eduardomozart/aethernms/releases/latest)

Multiplatform web application built with **Py4Web**, **PyDAL** (SQLite default + PostgreSQL, MySQL/MariaDB, MSSQL, Oracle, or Custom PyDAL URI), **IBM Carbon Design System (v11)**, and **Netmiko** for parallel SSH and Telnet configuration and audit automation across managed network devices — featuring an AirWave-inspired UI, granular RBAC, Global Device Search, and an authenticated **REST API** with interactive **OpenAPI 3.0.3 / Swagger UI** documentation.

## Key Features

### First-Run 3-Step Setup Guide & Multi-Backend PyDAL Persistence
- Starts cleanly without creating an empty `.db` file prematurely when unconfigured, redirecting visitors automatically to the 3-step **Initial Setup Guide (`/setup`)**:
  1. **Database Backend**: Choose **SQLite (Local — Default)** (`%USERPROFILE%\.aethernms\aethernms.db` on Windows or `~/.aethernms/aethernms.db` on Linux/macOS), **PostgreSQL**, **MySQL / MariaDB**, **Microsoft SQL Server (MSSQL)**, **Oracle Database**, or a **Custom PyDAL URI**, with live Python driver checks, `pip install` hints, and a **Test Connection** check.
  2. **Administrator Account**: Create the initial `Admin` user (bundled Netmiko snippets are automatically seeded as read-only templates).
  3. **Review & Complete**: Review the masked connection URI, persist `db_config.json`, hot-swap the live database connection without restarting, sign into `aethernms_session`, and lock `/setup` permanently.
- Supports `--db-uri` / `AETHERNMS_DB_URI` and `--db-path` / `AETHERNMS_CONFIG_DIR` overrides, automatic one-time migration from legacy XML files (`settings.xml`, `devices.xml`, `jobs.xml`, `session.xml`), and read-only `db_engine` / `db_uri_masked` inspection in **Administration → System Settings**.

### Py4Web + IBM Carbon Design System v11 Web UI
- Built with Composer-managed `@carbon/styles` v11, `@fontsource/ibm-plex-sans`, `@fontsource/ibm-plex-mono`, `@iconify-json/carbon`, and `swagger-ui-dist` (`White` light and `g100` dark themes, defaulting to **Auto (OS Default)**).
- Features an always-dark 48px Carbon UI Shell header (`partials/header.html`) with the **ÆTHER NMS** wordmark, **Global Device Search** bar (`/api/devices/search`), and a collapsible 256px SideNav (`Jobs`, `Snippets`, `Devices`, and expandable `Administration` submenu).
- Automatically localizes `/login` and `/setup` using the browser's `navigator.languages` / `navigator.language`.

### RBAC, External API Security & Interactive Swagger UI
- Granular Role-Based Access Control across UI and `/api/*` with built-in **Admin**, **Operator**, and **Viewer** roles plus custom roles (`/administration/roles`), user management (`/administration/users`), and scoped API Keys (`/administration/api-keys`, `X-API-Key` or `Authorization: Bearer aethernms_...`).
- **External API & Swagger UI** (`/api/docs`, `/swagger`, `/api/openapi.json`) are disabled by default (`api_enabled=False`) and restricted to an IP/CIDR allowlist (`127.0.0.1, ::1` default) under **Administration → System Settings**. External API clients authenticate exclusively via API keys.

### Netmiko Multi-Platform Engine & AirWave Import
- Backed directly by **Netmiko** (`CLASS_MAPPER`), supporting all non-serial Netmiko platforms (`aruba_procurve`, `aruba_aoscx`, `cisco_ios`, `juniper_junos`, `arista_eos`, `hp_comware`, etc.) over native `SSH` / `Telnet` drivers.
- Connects to **Aruba AirWave** via **Import from AirWave...**, auto-mapping **OS Type** and hardware models to native Netmiko platforms and keeping AirWave identity fields (**Device Name**, **IP Address**, **Model**, **Group**) read-only while allowing **Netmiko Platform**, **Protocol**, and **Port** edits.
- Stores **Config** and **Audit and Remediate** snippets centrally with SHA-256 upgrade tracking, XML import/export, `${var|type|regex}` & `${var|["A", "B"]}` parameterized variables, and per-device execution transcripts viewable in-browser or downloadable as `.log`.

## Quick Start

```bash
pip install -r requirements.txt
composer install
python main.py --open-browser
```

Open **`http://127.0.0.1:8000`** to launch the **3-Step Initial Setup Guide** (`/setup`). Once configured, Swagger UI (when enabled in **Administration → System Settings**) is available at **`http://127.0.0.1:8000/api/docs`**.

You can also serve the app via the Py4Web CLI:

```bash
py4web run apps --host 127.0.0.1 --port 8000
```

CLI options for `main.py`: `--host 127.0.0.1`, `--port 8000`, `--db-path /custom/path/aethernms.db`, `--db-uri postgres://user:pass@host:5432/aethernms`, `--open-browser`.

## Running Tests

```bash
pip install -r requirements-dev.txt
composer install
python -m pytest tests/ -v
```

## Documentation & Translations

Full guides, per-page architecture specs, and technical documentation are published on **[GitHub Pages Documentation](https://eduardomozart.github.io/aethernms/)** (built from [`wiki/`](wiki/) for the **User Guide** and [`docs/`](docs/) for the **Developer Guide**):
- **User Guide** ([`wiki/`](wiki/)) — Installation, 3-step `/setup` guide, multi-backend DB setup, per-user appearance, RBAC, AirWave rules, DataTable filtering, job wizard, log downloads, and REST API / Swagger UI
- **Developer Guide & Page Specs** ([`docs/`](docs/)) — Py4Web + multi-backend PyDAL architecture, Carbon v11 UI shell, per-page specifications (`docs/pages/*.md`), localization workflow, and security invariants

Help translate **`aethernms`** into more languages on **[Transifex](https://app.transifex.com/eduardomozart/aethernms/)** (using [`locales/aethernms.pot`](locales/aethernms.pot)).
