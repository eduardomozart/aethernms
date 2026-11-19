<img src="assets/pssh-ui.png" width="96" height="96" align="top" alt="pssh-ui logo" />

# pssh-ui

[![Release Version](https://img.shields.io/github/v/release/eduardomozart/pssh-ui?style=for-the-badge&logo=github)](https://github.com/eduardomozart/pssh-ui/releases/latest)

Multiplatform web application built with **Py4Web**, **SQLite (`PyDAL`)**, **IBM Carbon Design System (v11)**, and **Netmiko** for parallel SSH and Telnet configuration and audit automation across managed network devices — featuring an AirWave Config & Audit Jobs interface and an authenticated **REST API** with interactive **OpenAPI 3.0.3 / Swagger UI** documentation.

## Key Features

### Py4Web + SQLite + IBM Carbon v11 Web UI
- Styled with the **IBM Carbon Design System (v11)** (`g10` Light and `g100` Dark themes, with **Auto (OS Default)** support) and laid out after **AirWave Config & Audit Jobs** (`Jobs`, `Snippets`, `Devices`).
- Backed by a single **SQLite** database (`%APPDATA%\pssh-ui\pssh_ui.db` on Windows or `~/.pssh-ui/pssh_ui.db` on Linux/macOS) storing users, hashed API keys, settings, seeded snippets, devices, jobs, and per-device execution logs — with automatic one-time migration from legacy XML state files (`settings.xml`, `devices.xml`, `jobs.xml`, `session.xml`).
- Protected by local administrator sign-in (with guided first-run administrator setup or `PSSH_UI_ADMIN_USER` / `PSSH_UI_ADMIN_PASSWORD` bootstrap) and per-user **API Keys** (`X-API-Key` or `Authorization: Bearer <token>`).

### Authenticated REST API & Interactive Swagger UI
- Every GUI workflow (creating/stopping/deleting jobs, managing devices & AirWave imports, managing & importing/exporting snippets, parsing `${...}` variables, running ICMP ping checks, downloading per-device `.log` transcripts, and updating settings) is exposed over JSON REST endpoints under `/api/...`.
- Open **`/api/docs`** (or **`/swagger`**) in your browser for interactive **Swagger UI** documentation, or fetch **`/api/openapi.json`** for the OpenAPI 3.0.3 specification.

### Netmiko Multi-Platform Engine & Connection Defaults
Backed directly by **Netmiko** (`CLASS_MAPPER`), `pssh-ui` supports all non-serial Netmiko platforms (such as `aruba_procurve`, `aruba_aoscx`, `cisco_ios`, `juniper_junos`, `arista_eos`, `hp_comware`, and more) using native SSH and Telnet drivers—without custom CLI prompt regexes or manual paging/config wrappers.

In **Settings (`⚙`) → Connection Defaults**, you can set **Default Protocol** (`SSH` / `Telnet`), **Default SSH Port** (`22`), and **Default Telnet Port** (`23`). These defaults apply only when creating devices manually or importing devices from AirWave, and can always be overridden per device.

### Device Inventory & AirWave Import
Manage switches manually with **+ Add Device** (restricted exclusively to Netmiko-supported platforms and their native protocols) or connect directly to **Aruba AirWave** via **Import from AirWave...**:
- Inventory stays empty until credentials are entered and **Fetch Inventory** completes.
- AirWave **OS Type**, firmware, and hardware metadata are mapped automatically to native Netmiko platforms (`AOS-S` → `aruba_procurve`, `AOS-CX` → `aruba_aoscx`, etc.), prompting manually only when an unmatched device is selected for import.
- Imported AirWave devices lock **Device Name**, **IP Address**, **Model**, and **Group** as read-only while leaving **Netmiko Platform**, **Protocol**, and **Port** editable.

### Reusable Command Snippets (SQLite + XML Import/Export)
Store and share **Config** and **Audit and Remediate** command templates centrally inside SQLite (auto-seeded from bundled `snippets/<vendor>/<platform>/*.xml` with SHA-256 upgrade tracking), preview syntax-highlighted CLI scripts, and import or export portable `<Snippet>` XML files via either the web UI or the REST API.

### Guided Task Creation Wizard
Run configuration or audit tasks across multiple devices through a dynamic Carbon Progress Indicator wizard:
1. **Config Command** — Pick **Config** or **Audit and Remediate**, enter a job name, choose the **Netmiko Platform**, select a snippet, and customize CLI commands (and **Audit Validation RegEx** for audit jobs).
2. **Parameters** — Shown automatically whenever a snippet uses `${var|type|regex}` or `${var|["A", "B"]}` interactive variables, with real-time validation.
3. **Select Device** — Filter by device, IP, platform, group, or live ICMP ping status and select target devices (`Protocol:Port`).
4. **Confirm & Run** — Enter device/enable credentials, choose parallel or sequential execution, optionally enable **Save configuration** (`save_config()`), review rendered commands, and click **Run Job** (with per-device transcripts stored in SQLite and viewable/downloadable as `.log`).

## Quick Start

```bash
pip install -r requirements.txt
python main.py --open-browser
```

Open **`http://127.0.0.1:8080`** for the web UI and **`http://127.0.0.1:8080/api/docs`** for Swagger UI. You can also run via the standard Py4Web CLI:

```bash
py4web run apps --host 127.0.0.1 --port 8080
```

CLI options for `main.py`: `--host 127.0.0.1`, `--port 8080`, `--db-path /custom/path/pssh_ui.db`, `--open-browser`.

Prebuilt portable Windows packages (`pssh-ui-win-x64.zip`) are available on the **[Releases](https://github.com/eduardomozart/pssh-ui/releases/latest)** page — extract the `.zip` archive anywhere and launch `pssh-ui-x64.exe` directly with no temporary-folder extraction.

## Running Tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -v
```

## Documentation & Translations

Full guides and technical architecture details are available in the **[Wiki](https://github.com/eduardomozart/pssh-ui/wiki)** (published from [`wiki/`](wiki/)):
- **[User Guide](https://github.com/eduardomozart/pssh-ui/wiki/User-Guide)** — Installation, first-time setup, global defaults, AirWave rules, job wizard, and SQLite log downloads
- **[REST API & Swagger](https://github.com/eduardomozart/pssh-ui/wiki/REST-API)** — OpenAPI 3.0.3, Swagger UI (`/api/docs`), API key authentication, and `curl`/Python examples
- **[Snippets & Variables](https://github.com/eduardomozart/pssh-ui/wiki/Snippets-and-Variables)** — SQLite-backed snippets, XML import/export, parameterized inputs, and Audit RegEx rules
- **[Developer Design Choices](https://github.com/eduardomozart/pssh-ui/wiki/Developer-Design-Choices)** — Py4Web + PyDAL SQLite architecture, Carbon v11 UI, Netmiko integration, security, and release packaging
- **[Localization & Transifex](https://github.com/eduardomozart/pssh-ui/wiki/Localization-and-Transifex)** — Multi-language `.po`/`.mo` catalog workflow

Help translate **`pssh-ui`** into more languages on **[Transifex](https://app.transifex.com/eduardomozart/pssh-ui/)**.
