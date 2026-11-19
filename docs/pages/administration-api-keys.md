# API Keys (`/administration/api-keys`)

## Metadata
* **UI Routes**: `GET /administration/api-keys`
* **API Routes**: `GET /api/auth/api-keys`, `POST /api/auth/api-keys`, `DELETE /api/auth/api-keys/<id>`
* **Required RBAC Permissions**: `api_keys:manage` (own API keys) or `users:manage` + `api_keys:manage` (generate/revoke keys for other users)
* **User Guide Slug**: `/user-guide/administration-api-keys/`
* **Window Title**: `[[=page_title]] - aether` (`API Keys - aether`)

## Files Owned
* Template: `aethernms/templates/administration/api_keys.html`, `aethernms/templates/layout.html`
* Script: `aethernms/static/js/api_keys.js`, `aethernms/static/js/core.js`
* Backend: `aethernms/api/auth.py`, `aethernms/auth.py`, `aethernms/db.py`

## Carbon UI Layout & Components
* **Outside-Tile Page Header (`.anms-page-header`)**: Breadcrumb (`aether / Administration / API Keys`), `<h1>API Keys</h1>`, subtitle.
* **Disabled External API Notification** (`#apikeys-disabled-banner`): Warning notification shown when `api_enabled=False`, featuring a tertiary/ghost action link (`<a href="/administration/settings" class="cds--btn cds--btn--tertiary cds--btn--sm">Go to System Settings</a>`).
* **Generate API Key Tile**: Key Name (`#new-key-name`), optional Role Scope (`#new-key-role-wrap` / `#new-key-role`), optional Owner (`#new-key-user-wrap` / `#new-key-user`), **Generate Key** button (`#btn-gen-key`), and one-time reveal banner (`#new-key-banner` / `#new-key-value` / `#btn-copy-key`).
* **Carbon DataTable Toolbar** inside `.anms-table-container`: Search (`#apikeys-dt-search`), **Filter** popover (`#apikeys-filter-btn` / `#apikeys-filter-popover` by Role `#flt-key-role`), active filter tags, and **Revoke** actions table.

## Behavioral Decisions & Invariants
* **No Hover Underline on Notification Link**: `a.cds--btn` inside `#apikeys-disabled-banner` (`.cds--inline-notification a.cds--btn`) explicitly suppresses `text-decoration: underline` on `:hover` / `:focus`.
* **Hash-Only Storage**: Plaintext API tokens (`aethernms_...`) are displayed **only once** immediately after creation (`POST /api/auth/api-keys`); SQLite/external DB stores only the SHA-256 hash + prefix.
* **External API Gate**: Generated API keys authenticate `X-API-Key` or `Authorization: Bearer ...` on `/api/*` **only when** `api_enabled=True` AND client IP matches `api_allowed_ips`.

## Verification
* `tests/test_rest_api.py` (API key creation, SHA-256 verification, External API gate + IP allowlist `403`/`200`, CSS no-underline check)
