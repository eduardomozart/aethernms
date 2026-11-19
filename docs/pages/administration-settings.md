# System Settings (`/administration/settings`)

## Metadata
* **UI Routes**: `GET /administration/settings` (plus `GET /administration` redirect for authorized users)
* **API Routes**: `GET /api/settings`, `PUT /api/settings`
* **Required RBAC Permissions**: `system:settings` (`403` Forbidden otherwise)
* **User Guide Slug**: `/user-guide/administration-settings/`
* **Window Title**: `[[=page_title]] - aether` (`System Settings - aether`)

## Files Owned
* Template: `aethernms/templates/administration/settings.html`, `aethernms/templates/layout.html`
* Script: `aethernms/static/js/settings.js`, `aethernms/static/js/core.js`
* Backend: `aethernms/api/settings.py`, `aethernms/db.py`, `aethernms/db_config.py`, `aethernms/web_app.py`

## Carbon UI Layout & Components
* **Outside-Tile Page Header (`.anms-page-header`)**: Breadcrumb (`aether / Administration / System Settings`), `<h1>System Settings</h1>`, subtitle, and right-aligned **Save Settings** (`#btn-save-settings`) without any checkmark icon.
* **Configuration Tiles**:
  * **Connection & Execution Defaults**: Default SSH Username (`#set-user`), Default Protocol (`#set-proto`), SSH Port (`#set-ssh-port`), Telnet Port (`#set-telnet-port`), Max Parallel Executions (`#set-parallel`), Connect Timeout (`#set-conn-to`), Command Timeout (`#set-cmd-to`), Execution Order.
  * **Database Backend (Read-Only)**: `#set-db-engine`, `#set-db-uri` (masked credentials via `mask_dal_uri()`).
  * **External REST API & Swagger UI**: `#set-api-enabled` / `#set-api-switch` toggle (disabled by default), `#set-api-allowed-ips` (`127.0.0.1, ::1` default), live client IP (`#set-client-ip`), and conditional `/api/docs` link (`#set-swagger-link`).
  * **AirWave Integration**: Server URL, Username, SSL Verification, and custom OS-to-Netmiko platform mapping editor (displaying friendly platform labels alongside Netmiko keys).

## Behavioral Decisions & Invariants
* **No Appearance Section in System Settings**: UI Language and Color Theme live exclusively per user (`auth_user.language`, `auth_user.theme_mode`) under **Users** (`/administration/users` or `/administration/users?edit=me`), never here.
* **No Button Checkmark**: `#btn-save-settings` has no `checkmark-filled` icon.
* **External API Locked By Default**: Fresh installs default to `api_enabled=False` and `api_allowed_ips="127.0.0.1, ::1"`.
* **Read-Only Masked DB Configuration**: Database engine and masked URI cannot be modified in Settings; credentials remain redacted everywhere.
* **Zero Plaintext Passwords**: AirWave / SSH passwords are never returned or stored in plaintext in SQLite/external DBs.

## Verification
* `tests/test_rest_api.py` (settings RBAC `403`, masked `db_uri_masked`, IP allowlist validation, external API toggle)
