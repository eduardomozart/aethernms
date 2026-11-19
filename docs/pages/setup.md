# Initial Setup Guide (`/setup`)

## Metadata
* **UI Routes**: `GET /setup`
* **API Routes**: `GET /setup/info`, `POST /setup/test-db`, `POST /setup`
* **Access / Lockout**: Accessible **only** while uninitialized (`ctx.db is None` or `ctx.db.user_count() == 0`). Redirects (`302`) to `/jobs` (authenticated) or `/login` (anonymous) on `GET /setup`, and returns `403` on `/setup/info`, `/setup/test-db`, `POST /setup` once setup finishes.
* **User Guide Slug**: `/user-guide/getting-started/`
* **Window Title**: `[[=page_title]] - aether` (`Initial Setup Guide - aether`)

## Files Owned
* Template: `aethernms/templates/setup.html`, `aethernms/templates/partials/header.html` (`header_mode="setup"`), `aethernms/templates/partials/head_icons.html`
* Script: `aethernms/static/js/setup.js`
* Stylesheet: `aethernms/static/css/aethernms-carbon.css`
* Backend: `aethernms/web_app.py`, `aethernms/db_config.py`, `aethernms/db.py`, `aethernms/paths.py`

## Carbon UI Layout & Components
* Standalone shell (`header_mode="setup"`) with 48px dark header and centered setup tile (`#setup-card`) using `anms-brand-lockup--lg`.
* **Carbon Progress Indicator** (`#setup-steps-bar`) across 3 steps:
  1. **Database Backend** (`#setup-step-1`): Engine select (`#setup-engine`), driver status pill (`#setup-driver-bar`), SQLite path (`#setup-sqlite-path`) defaulting to `~/.aethernms/aethernms.db`, external DB fields (`#setup-netdb-wrap`), custom URI field, **Test Connection** (`#btn-setup-test-db`), and **Next >** (`#btn-setup-step1-next`).
  2. **Administrator Account** (`#setup-step-2`): Username (`#setup-admin-user`), Display Name (`#setup-admin-display`), Password (`#setup-admin-pass`, min 6 chars), Confirm Password (`#setup-admin-confirm`), **< Back**, **Next >**.
  3. **Review & Complete** (`#setup-step-3`): Engine (`#sum-db-engine`), masked URI (`#sum-db-uri`), Admin username (`#sum-admin-user`), display name, Default RBAC Roles (`Admin, Operator, Viewer`), **< Back**, **Complete** (`#btn-setup-complete`).

## Behavioral Decisions & Invariants
* **No Premature `.db` Creation**: Starting without CLI/env DB config or `db_config.json` must keep `ctx.db = None` and write zero `.db` files until `POST /setup` succeeds.
* **Automatic DB Test on Advance**: Clicking **Next >** on Step 1 validates inputs and automatically executes `POST /setup/test-db` if parameters changed or no passing test ran since the last edit (`lastTestOk && lastTestedFingerprint === fp` skips duplicate requests).
* **No Built-In Snippets Opt-Out Toggle**: Built-in Netmiko snippets are **always** seeded on initial setup without a UI checkbox, and stored read-only (`is_builtin=True`).
* **No Button Checkmark Icon**: `#btn-setup-complete` displays **"Complete"** (localized to **"Concluir"** in `pt_BR`) with no `checkmark-filled` icon.
* **Default Config Path**: SQLite defaults to `~/.aethernms/aethernms.db` across Windows, Linux, and macOS (never `%APPDATA%` to avoid Microsoft Store Python MSIX virtualization).
* **Lock Safety & Persistence**: `AppContext.lock` is a re-entrant `threading.RLock`; `POST /setup` validates inputs, initializes `DatabaseStore`, seeds roles + built-in snippets, creates Admin user, saves `db_config.json`, hot-swaps `ctx.db`, and signs into `aethernms_session`.
* **Browser Language Localization**: SSR renders via `[[=T(...)]]` + `#anms-initial-i18n`, refined against `navigator.languages` via `/i18n?lang=...`.

## Verification
* `tests/test_rest_api.py::test_uninitialized_setup_guide_redirects_lockout_and_no_premature_db`
* `tests/test_db_config.py`
