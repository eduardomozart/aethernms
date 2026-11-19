# Sign In (`/login`)

## Metadata
* **UI Routes**: `GET /login`
* **Auth Endpoints**: `POST /login`, `POST /logout`, `POST /account/password`
* **Access**: Public when initialized (`!_needs_setup`); redirects (`302`) to `/setup` when uninitialized, or `/jobs` if already signed in (`GET /login`).
* **User Guide Slug**: `/user-guide/getting-started/`
* **Window Title**: `[[=page_title]] - aether` (`Sign In - aether`)

## Files Owned
* Template: `aethernms/templates/login.html`, `aethernms/templates/partials/header.html` (`header_mode="login"`), `aethernms/templates/partials/head_icons.html`
* Stylesheet: `aethernms/static/css/aethernms-carbon.css`
* Backend: `aethernms/web_app.py`, `aethernms/db.py`, `aethernms/api/auth.py`

## Carbon UI Layout & Components
* Standalone shell (`header_mode="login"`) with centered `.login-card`.
* Brand lockup (`.anms-brand-lockup` with `--lg` wordmark **ÆTHER** and **NMS** subtitle) followed directly by `#auth-heading` (**Sign In**).
* Inline notification banner (`#auth-error`) for localized authentication errors.
* Form (`#auth-form`): `#auth-username`, `#auth-password`, hidden `#confirm-wrap`, and compact primary submit button (`#auth-submit.login-submit-btn`).

## Behavioral Decisions & Invariants
* **No Login Subtitle**: Do NOT display any marketing subtitle (such as `"Config & Audit Automation"`) on `/login`.
* **Compact Sign-In Button**: `.login-submit-btn` uses compact Carbon button width (no `width: 100%` full-card stretch).
* **Mandatory `= ` Prefix in Renoir Attributes**: `data-needs-setup="[[='true' if needs_setup else 'false']]"` must evaluate with `[[=...]]` so the form targets `POST /login` (never `/setup` silently).
* **Case-Insensitive Username Login**: `DatabaseStore.authenticate_user()` matches `LOWER(username)` and verifies PBKDF2 password hashes + `is_active` status. `_ensure_db_loaded(ctx)` lazy-reloads `db_config.json` before authentication if needed.
* **Browser Language Localization**: Localized SSR strings via `[[=T(...)]]` + `#anms-initial-i18n` and client fallback against `navigator.languages` via `/i18n?lang=...`.
* **External API Separation**: Interactive username/password login lives strictly on `/login` (`aethernms_session` cookie); `/api/*` rejects unauthenticated calls unless a valid `X-API-Key` / Bearer token passes API gate + IP allowlist.

## Verification
* `tests/test_rest_api.py` (login flow, case-insensitive username, logout -> login roundtrip, `data-needs-setup` attribute check)
