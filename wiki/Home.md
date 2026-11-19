# Welcome to the `pssh-ui` Wiki

**`pssh-ui`** is a multiplatform Python web application built with **Py4Web**, **SQLite (`PyDAL`)**, **IBM Carbon Design System (v11)**, **`netmiko`**, and **`airwaveapiclient`** for executing parallel SSH and Telnet configuration and audit automation across network devices via both an AirWave-style browser UI and an authenticated REST API with Swagger UI.

---

## Wiki Navigation

* **[User Guide](User-Guide)** — Installation (`pssh-ui-win-x64.zip` or `python main.py`), initial admin setup, SQLite database storage (`%APPDATA%\pssh-ui\pssh_ui.db` & `~/.pssh-ui/pssh_ui.db`), global defaults, `Jobs` / `Snippets` / `Devices` workflow, AirWave OS mapping & read-only rules, dynamic job wizard, and execution logs.
* **[REST API & Swagger](REST-API)** — Interactive Swagger UI (`/api/docs` & `/swagger`), OpenAPI 3.0.3 schema (`/api/openapi.json`), API Keys (`X-API-Key` / `Bearer`), and automation examples.
* **[Snippets & Variables Reference](Snippets-and-Variables)** — Bundled XML templates auto-seeded into SQLite with SHA-256 upgrade tracking, XML import/export, `${var|type|regex}` & `${var|["Item 1", "Item 2"]}` templates, and Audit RegEx checks.
* **[Developer Design Choices](Developer-Design-Choices)** — Py4Web + PyDAL SQLite architecture, IBM Carbon v11 UI tokens, authentication & API keys, native Netmiko `CLASS_MAPPER` & `ConnectHandler` automation, security decisions, and PyInstaller release workflow.
* **[Localization & Transifex](Localization-and-Transifex)** — Zero-code `.po` discovery, dynamic Babel native locale labels, `.pot` extraction, and community translations on **[Transifex](https://app.transifex.com/eduardomozart/pssh-ui/)**.

---

## Key Capabilities at a Glance

| Capability | Description |
| :--- | :--- |
| **IBM Carbon v11 Web UI** | AirWave Config & Audit Jobs layout styled with Carbon `g10` (Light) and `g100` (Dark) tokens, defaulting to **Auto (OS Default)** for theme and language. |
| **Authenticated REST API & Swagger** | Full JSON REST API (`/api/...`) secured via Py4Web sessions or SHA-256 hashed API keys (`X-API-Key` / `Bearer`), documented live at `/api/docs` and `/api/openapi.json`. |
| **Single SQLite Database (`PyDAL`)** | Stores users, API keys, settings, snippets, devices, jobs, and per-device execution logs in `%APPDATA%\pssh-ui\pssh_ui.db` (Windows) or `~/.pssh-ui/pssh_ui.db` (Linux/macOS), with automatic one-time legacy XML migration. |
| **Native Netmiko Multi-Platform Support** | Dynamically discovers all non-serial Netmiko platforms (`CLASS_MAPPER`) and native `SSH` / `Telnet` transport drivers without custom prompt regexes or CLI wrappers. |
| **AirWave OS Mapping & Read-Only Safety** | Stays empty until inventory is fetched; auto-maps AirWave OS metadata to Netmiko (prompting only when unmatched) and locks Name, IP, Model, and Group as read-only while allowing Platform, Protocol, and Port edits. |
| **Dynamic Job Wizard & Password-Free State** | Guided flow (`Config Command` → `[Parameters]` → `Select Device` → `Confirm`) with syntax-highlighted editing, Audit RegEx checks, and strict scrubbing of device/AirWave/`|password|` secrets from SQLite. |
