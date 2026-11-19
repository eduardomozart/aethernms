# Changelog

All notable changes to **aethernms (ÆTHER NMS)** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **3-Step First-Run Setup Guide (`/setup`) & Multi-Backend PyDAL Support (`aethernms/db_config.py`, `aethernms/templates/setup.html`, `aethernms/static/js/setup.js`)**:
  - Added multi-backend PyDAL configuration supporting **SQLite (Local — Default)**, **PostgreSQL** (`postgres://`), **MySQL / MariaDB** (`mysql://`), **Microsoft SQL Server (MSSQL)** (`mssql4://` with ODBC driver support), **Oracle Database** (`oracle://`), and **Custom PyDAL URI**, complete with live `importlib.util.find_spec` driver detection, `pip install` hints, URL-encoded credentials (`decode_credentials=True`), password masking (`mask_dal_uri`), live connection testing (`POST /setup/test-db`), and `db_config.json` / `AETHERNMS_DB_URI` / `--db-uri` persistence.
  - Added uninitialized startup mode (`ctx.db = None`) without premature `.db` file creation, redirecting unconfigured UI routes to `/setup`, returning HTTP `503` `{"setup_required": true}` on `/api/*`, hot-swapping `ctx.db` live upon `POST /setup`, and permanently locking out `/setup*` once an Admin account exists.
  - Added read-only `db_engine` and `db_uri_masked` fields to `GET /api/settings` and a read-only **Database Backend** section in `administration/settings.html`.
- **RBAC Administration, Scoped API Keys, External API Allowlist & Global Device Search**:
  - Renamed project and package to **`aethernms`** with granular permissions (`jobs:*`, `snippets:*`, `devices:*`, `airwave:import`, `system:settings`, `users:manage`, `roles:manage`, `api_keys:manage`), built-in `Admin`, `Operator`, and `Viewer` roles plus custom roles (`/administration/roles`), user management (`/administration/users`), and scoped `aethernms_...` API keys (`/administration/api-keys`).
  - Gated External API (`X-API-Key` / `Authorization: Bearer`) and Swagger/OpenAPI endpoints (`/api/docs`, `/swagger`, `/api/openapi.json`) behind `api_enabled=False` and `api_allowed_ips` (`127.0.0.1, ::1`) defaults under **Administration → System Settings**.
  - Added Global Device Search (`/api/devices/search`) directly in the 48px Carbon header shell.
- **IBM Carbon Design System v11 & Typographic Wordmark (`ÆTHER NMS`)**:
  - Replaced legacy PNG header/card logos with the **ÆTHER** (`letter-spacing: -3px`) + **NMS** typographic wordmark inside a single shared header partial (`aethernms/templates/partials/header.html`) embedded via `[[include 'partials/header.html']]` across `layout.html`, `login.html`, `setup.html`, `forbidden.html`, and `swagger.html`.
  - Managed `@carbon/styles` v11, `@fontsource/ibm-plex-sans`, `@fontsource/ibm-plex-mono`, `@iconify-json/carbon`, and `swagger-ui-dist` declaratively through `composer.json` / `composer.lock`.
- **Py4Web + SQLite (`PyDAL`) Web Application Architecture & REST API**:
  - Refactored the desktop application into a multi-user browser web app (`aethernms/web_app.py`, `aethernms/db.py`, `aethernms/app.py`, `aethernms/api/*.py`, `apps/_default/__init__.py`) with automatic one-time migration from legacy `settings.xml`, `devices.xml`, `jobs.xml`, and `session.xml`.
  - Exposed every GUI capability through `/api/...` JSON endpoints documented via OpenAPI 3.0.3 (`GET /api/openapi.json`) and Swagger UI (`GET /api/docs` / `GET /swagger`) with an offline interactive explorer fallback.
- Native **Netmiko** (`netmiko>=4.5.0`) automation engine supporting all non-serial platforms from `netmiko.ssh_dispatcher.CLASS_MAPPER` and their native `SSH` / `Telnet` drivers (`aethernms/netmiko_catalog.py`, `aethernms/ssh_runner.py`).
- Global **Default Protocol** (`SSH` / `Telnet`), **Default SSH Port** (`22`), and **Default Telnet Port** (`23`) preferences under **Connection Defaults** in **System Settings**.
- Automatic AirWave **OS Type → Netmiko Platform** mapping (`AOS-S` → `aruba_procurve`, `AOS-CX` → `aruba_aoscx`, plus persisted custom OS mappings), prompting (`Map Unmatched AirWave Models to Netmiko`) only when selected devices have no match.

### Changed
- Guarded SQLite-specific `adapter_args={"timeout": 15.0}` and `PRAGMA` statements (`journal_mode=WAL`, `busy_timeout=15000`, `foreign_keys=ON`) behind `if self.is_sqlite:` in `DatabaseStore`, storing PyDAL `.table` metadata in `<runtime_root>/dal_meta` for non-SQLite backends.
- Removed `tkinter`, `sv-ttk`, `pillow`, and XML-only state/shared-snippets-folder storage in favor of **Py4Web**, **PyDAL**, and **IBM Carbon v11**.
- Switched user data directory uniformly to `~/.aethernms` (`%USERPROFILE%\.aethernms` on Windows and `~/.aethernms` on Linux/macOS, with optional `AETHERNMS_CONFIG_DIR` override) to prevent Microsoft Store (MSIX) `%APPDATA%` virtualization on Windows.
- Replaced `paramiko` and custom `<DeviceModel>` XML prompt/wrapper profiles with native Netmiko drivers.
- Enforced strictly Netmiko-supported platforms and native protocols across UI and REST API, locking AirWave identity fields (**Device Name**, **IP Address**, **Model**, **Group**) as read-only while keeping **Netmiko Platform**, **Protocol**, and **Port** editable.

### Fixed
- Fixed missing `=` Renoir output prefixes in `login.html` (`data-needs-setup`) and `layout.html` (`aria-expanded`) so template expressions render `"true"` / `"false"` accurately instead of empty strings, preventing login forms from posting to `/login` when initial setup is required.
- Fixed `/i18n` and browser `navigator.languages` / `navigator.language` resolution in `login.html` and `setup.js` so messages such as `"Initial administrator setup is required first."` localize according to the browser's active language.
- Avoided duplicating connection/authentication exception lines into `--- Detected Errors ---` while preserving them in `--- Connection / Execution Exception ---` and the raw terminal transcript.
- Normalized VT100 control sequences, carriage returns, backspaces, and pager artifacts in captured session transcripts (`clean_terminal_text`).
- Prevented login, enable, AirWave, and `${var|password}` secret values (as well as database credentials in URIs/logs) from being exposed in plaintext.
- Hardened background job workers so unexpected execution errors cleanly finalize the job as `Failed` instead of leaving it stuck in `Running`.

## [1.0.0] - 2026-11-17

### Added
- Initial desktop release (`tkinter`/`ttk` + `Sun-Valley-ttk-theme` + `paramiko`) for parallel SSH configuration and audit automation across managed switches.
- 4-tab workspace (**Jobs**, **Snippets**, **Devices**, **Device Models**) with Light/Dark OS auto-detection, language auto-detection, **Add Job** wizard, and Aruba **AirWave** XML import.
- Parameterized XML snippet system (`${var|type|regex}` and `${var|["Item 1", "Item 2"]}`), drop-in `DeviceModel` XML profiles (`ArubaOS-CX`, `ArubaOS-S`), per-switch timestamped logs without plaintext credential persistence, and `gettext`/Babel localization.

[Unreleased]: https://github.com/eduardomozart/aethernms/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/eduardomozart/aethernms/releases/tag/v1.0.0
