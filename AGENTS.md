# `aethernms` Project Agent Guidelines

## Design System
- Follow the IBM Carbon Design System v11 rules defined in `.agents/rules/ibm-carbon-design.md` and the full verbatim IBM design specification in `DESIGN.md` (imported from `https://getdesign.md/ibm/design-md`).
- Never hand-copy or manually vendor IBM Carbon CSS, IBM Plex fonts, Carbon icons, or Swagger UI files. Manage all frontend dependencies declaratively through `composer.json` / `composer.lock` (`composer install`).

## Architecture & Security Conventions
- **Backend & Storage**: Py4Web (`aethernms/web_app.py`) + Multi-Backend PyDAL (`aethernms/db.py`, `aethernms/db_config.py`) + Netmiko (`aethernms/ssh_runner.py`, `aethernms/netmiko_catalog.py`) + 1-to-1 route-aligned REST modules (`aethernms/api/`). Default runtime directory is `~/.aethernms` (`%USERPROFILE%\.aethernms` on Windows; never `%APPDATA%` to avoid Microsoft Store Python MSIX virtualization).
- **Templates & SSR i18n**: Split Py4Web Renoir templates (`partials/header.html`, `partials/head_icons.html`, `layout.html`, `setup.html`, `login.html`, `jobs.html`, `snippets.html`, `devices.html`, `administration/*.html`, `modals/*.html`) rendered via `py4web.core.render(..., delimiters="[[ ]]")` with server-side `[[=T(...)]]` and `#anms-initial-i18n` hydration.
- **Per-User Appearance & Read-Only System Defaults**: Language and theme (`language`, `theme_mode`) are stored per `auth_user` (never global settings). Built-in snippets (`is_builtin=True`) and system roles (`Admin`, `Operator`, `Viewer` with `is_system=True`) are strictly read-only (`403` / `ValueError`).
- **RBAC & External API**: Enforce granular role permissions across UI and `/api/*` (with `?edit=me` self-profile mode on `/administration/users`). Keep External API (`X-API-Key` / `Authorization: Bearer`) and Swagger/OpenAPI endpoints (`/api/docs`, `/swagger`, `/api/openapi.json`) disabled by default (`api_enabled=False`) and gated by the IP/CIDR allowlist (`127.0.0.1, ::1` default). External API access requires an API Key only (interactive password auth lives on Web UI `/login` & `/setup`).
- **Secrets**: Never store device SSH/Telnet passwords, enable passwords, AirWave passwords, or `${var|password}` parameter values in plaintext in SQLite or external DBs.

## Per-Page Specifications (Mandatory)
- Follow `.agents/rules/page-specs.md`: before modifying any page template, modal, JS controller, or API handler for a UI view, **always read the corresponding specification in `docs/pages/<page>.md`** (and `docs/developer-guide/` for shared shell/localization/architecture rules), and update the spec alongside your changes.

## Verification
- After installing dependencies (`pip install -r requirements.txt -r requirements-dev.txt` and `composer install`), run `python -m pytest tests/ -v`.
- Keep `locales/aethernms.pot`, `locales/en/LC_MESSAGES/aethernms.po`, and `locales/pt_BR/LC_MESSAGES/aethernms.po` synchronized and compiled to `.mo` whenever user-facing strings change.
- Build GitHub Pages documentation (User Guide + Developer Guide) with `python scripts/build_docs.py --output _site --base-url /aethernms`.
