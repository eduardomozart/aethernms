# Changelog

All notable changes to **pssh-ui** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Py4Web + SQLite (`PyDAL`) Web Application Architecture**: Refactored the desktop application into a multi-user browser web app (`pssh_ui/web_app.py`, `pssh_ui/db.py`, `pssh_ui/app.py`, `apps/_default/__init__.py`) backed by a single WAL-mode SQLite database at `%APPDATA%\pssh-ui\pssh_ui.db` (Windows) / `~/.pssh-ui/pssh_ui.db` (Linux/macOS), with automatic one-time migration from legacy `settings.xml`, `devices.xml`, `jobs.xml`, and `session.xml`.
- **IBM Carbon Design System (v11) Multi-Page UI**: Rebuilt the frontend using Py4Web Renoir template inheritance (`layout.html` + `/jobs`, `/snippets`, `/devices` pages + `pssh_ui/templates/modals/*.html` partials + `login.html`) and modular JavaScript (`core.js`, `jobs.js`, `snippets.js`, `devices.js`), styled with IBM Carbon v11 `g10` (Light) and `g100` (Dark) tokens while preserving the **AirWave Config & Audit Jobs** layout, dynamic step wizard, syntax-highlighted CLI previews, and global `Esc` modal close behavior.
- **Authentication & Personal API Keys (`pssh_ui/auth.py`)**: Added first-run administrator setup (`/login`, plus `PSSH_UI_ADMIN_USER` / `PSSH_UI_ADMIN_PASSWORD` env bootstrap), PBKDF2-HMAC-SHA256 password hashing, signed Py4Web session cookies, and SHA-256 hashed personal API keys (`X-API-Key` / `Authorization: Bearer <token>`).
- **Authenticated REST API & Interactive Swagger UI (`pssh_ui/openapi_spec.py`, `pssh_ui/templates/swagger.html`, `wiki/REST-API.md`)**: Exposed every GUI capability through `/api/...` JSON endpoints (jobs, devices, ICMP ping, AirWave fetch/import, snippets CRUD + XML import/export, variable parsing, settings, and per-device SQLite logs with `?download=1`), documented via OpenAPI 3.0.3 (`GET /api/openapi.json`) and Swagger UI (`GET /api/docs` / `GET /swagger`) with an offline interactive explorer fallback.
- **SQLite-Backed Snippets & Per-Device Logs**: Auto-seeded bundled `snippets/<vendor>/<platform>/*.xml` into SQLite with SHA-256 upgrade tracking (preserving user edits and deletions) alongside XML Import/Export; stored formatted per-device execution transcripts inside SQLite `job_result.formatted_log` for in-browser viewing and `.log` downloads.
- Native **Netmiko** (`netmiko>=4.5.0`) automation engine supporting all non-serial platforms from `netmiko.ssh_dispatcher.CLASS_MAPPER` and their native `SSH` / `Telnet` drivers (`pssh_ui/netmiko_catalog.py`, `pssh_ui/ssh_runner.py`).
- Global **Default Protocol** (`SSH` / `Telnet`), **Default SSH Port** (`22`), and **Default Telnet Port** (`23`) preferences under **Connection Defaults** in **Settings (`⚙`)**, positioned below **Execution Defaults**, clarifying they apply only when creating devices manually or importing devices from AirWave, and can always be overridden per device.
- Automatic AirWave **OS Type → Netmiko Platform** mapping (`AOS-S` → `aruba_procurve`, `AOS-CX` → `aruba_aoscx`, plus persisted custom OS mappings), prompting (`Map Unmatched AirWave Models to Netmiko`) only when selected devices have no match.

### Changed
- Removed `tkinter`, `sv-ttk`, `pillow`, and XML-only state/shared-snippets-folder storage (`pssh_ui/tabs/`, `pssh_ui/dialogs/`, `settings_store.py`, `session_store.py`) in favor of **Py4Web**, **SQLite (`PyDAL`)**, and **IBM Carbon v11**.
- Changed the non-Windows user data directory from `~/.config/pssh-ui` to `~/.pssh-ui`.
- Replaced `paramiko` and custom `<DeviceModel>` XML prompt/wrapper profiles with native Netmiko drivers (`ConnectHandler`, `config_mode`, `send_config_set`, `send_command`, `exit_config_mode`, `save_config`).
- Renamed bundled snippet folders and `<DeviceType>` tags to Netmiko platform naming (`snippets/aruba/aruba_procurve/`, `snippets/aruba/aruba_aoscx/`) while seamlessly normalizing legacy `AOS-S` / `AOS-CX` inputs.
- Enforced strictly Netmiko-supported platforms and native protocols across UI and REST API; kept AirWave **Import** empty until **Fetch Inventory** runs and enforced read-only **Device Name**, **IP Address**, **Model**, and **Group** for AirWave-managed devices while keeping **Netmiko Platform**, **Protocol**, and **Port** editable.
- Switched Windows release packaging in `.github/workflows/release.yml` to portable PyInstaller `--onedir` archive `pssh-ui-win-x64.zip` collecting `py4web`, `pydal`, `yatl`, `ombott`, `renoir`, `rocket3`, `netmiko`, templates, static assets, snippets, locales, and documentation without extracting into `%TEMP%` on launch.

### Fixed
- Avoided duplicating connection/authentication exception lines into `--- Detected Errors ---` while preserving them in `--- Connection / Execution Exception ---` and the raw terminal transcript.
- Normalized VT100 control sequences, carriage returns, backspaces, and pager artifacts in captured session transcripts (`clean_terminal_text`).
- Prevented login, enable, AirWave, and `${var|password}` secret values from ever being persisted in SQLite and masked runtime secrets in Netmiko `session_log`.
- Hardened background job workers so unexpected execution errors cleanly finalize the job as `Failed` instead of leaving it stuck in `Running`.

## [1.0.0] - 2026-11-17

### Added
- Initial release of **pssh-ui** (`tkinter`/`ttk` + `Sun-Valley-ttk-theme` + `paramiko`) for parallel SSH configuration and audit automation across managed switches.
- 4-tab workspace (**Jobs**, **Snippets**, **Devices**, **Device Models**) with Light/Dark OS auto-detection, language auto-detection, **Add Job** wizard, and Aruba **AirWave** XML import.
- Parameterized XML snippet system (`${var|type|regex}` and `${var|["Item 1", "Item 2"]}`), drop-in `DeviceModel` XML profiles (`ArubaOS-CX`, `ArubaOS-S`), per-switch timestamped logs without plaintext credential persistence, and `gettext`/Babel localization.

[Unreleased]: https://github.com/eduardomozart/pssh-ui/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/eduardomozart/pssh-ui/releases/tag/v1.0.0
