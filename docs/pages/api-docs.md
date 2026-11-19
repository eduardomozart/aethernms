# API Docs / Swagger (`/api/docs` & `/swagger`)

## Metadata
* **UI Routes**: `GET /api/docs`, `GET /swagger`
* **Schema Route**: `GET /api/openapi.json`
* **Access Gate**: Enforced via `check_external_api_access(ctx)` — requires **both** `api_enabled=True` in System Settings AND client IP within `api_allowed_ips` (`127.0.0.1, ::1` default); returns `403` when disabled or disallowed, or `503` if setup is required.
* **User Guide Slug**: `/user-guide/rest-api/`
* **Window Title**: `[[=page_title]] - aether` (`API Docs (Swagger) - aether`)

## Files Owned
* Templates: `aethernms/templates/swagger.html`, `aethernms/templates/partials/header.html` (`header_mode="swagger"`), `aethernms/templates/partials/head_icons.html`
* Vendor Assets: `aethernms/static/vendor/npm-asset/swagger-ui-dist/` (`composer.json`)
* Backend: `aethernms/web_app.py`, `aethernms/api/openapi.py`, `aethernms/api/common.py`

## Carbon UI Layout & Components
* Standalone shell with dark 48px Carbon header (`header_mode="swagger"`) displaying **ÆTHER NMS** + `API Docs (Swagger)`, Help icon link, and **Return to Application** link (`/jobs`).
* Composer-managed `swagger-ui-dist` container (`#swagger-ui`) loading `/api/openapi.json` cleanly, plus built-in offline API key explorer (`#offline-explorer`, `#offline-api-key`) fallback.

## Behavioral Decisions & Invariants
* **API Key Only Security Scheme**: OpenAPI 3.0.3 defines `ApiKeyAuth` (`X-API-Key`) and `BearerAuth` (`Authorization: Bearer`). Swagger **Try it out** uses `request.credentials = "omit"` so it never piggybacks browser session cookies.
* **Header Visibility Toggle**: `#hdr-api-docs-link` in `partials/header.html` is visible only when `api_enabled=True`.
* **Declarative Composer Assets**: Never hand-copy Swagger UI files; load exclusively from `/static/vendor/npm-asset/swagger-ui-dist/`.
* **Schema Sync**: Keep `aethernms/api/openapi.py` synchronized whenever REST endpoints, read-only `403` error codes, self-edit user rules, or platform display fields change.

## Verification
* `tests/test_rest_api.py` (disabled by default `403`, enabled + allowlist `200`, OpenAPI 3.0.3 JSON paths validation, `/api/docs` HTML header & Composer script check)
