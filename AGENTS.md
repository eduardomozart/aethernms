# `aethernms` Project Agent Guidelines

## Design System
- Follow the IBM Carbon Design System v11 rules defined in `.agents/rules/ibm-carbon-design.md` and the full verbatim IBM design specification in `DESIGN.md` (imported from `https://getdesign.md/ibm/design-md`).
- Never hand-copy or manually vendor IBM Carbon CSS, IBM Plex fonts, Carbon icons, or Swagger UI files. Manage all frontend dependencies declaratively through `composer.json` / `composer.lock` (`composer install`).

## Architecture & Security Conventions
- **Backend**: Py4Web (`aethernms/web_app.py`) + PyDAL WAL-mode SQLite (`aethernms/db.py`) + Netmiko (`aethernms/ssh_runner.py`, `aethernms/netmiko_catalog.py`) + 1-to-1 route-aligned REST modules (`aethernms/api/`).
- **Templates**: Split Py4Web Renoir templates (`layout.html`, `jobs.html`, `snippets.html`, `devices.html`, `administration/*.html`, `modals/*.html`) rendered via `py4web.core.render(..., delimiters="[[ ]]")`.
- **RBAC & External API**: Enforce granular role permissions across UI and `/api/*`. Keep External API (`X-API-Key` / `Authorization: Bearer`) and Swagger/OpenAPI endpoints (`/api/docs`, `/swagger`, `/api/openapi.json`) disabled by default (`api_enabled=False`) and gated by the IP/CIDR allowlist (`127.0.0.1, ::1` default). External API access requires an API Key only (interactive password auth lives on Web UI `/login` & `/setup`).
- **Secrets**: Never store device SSH/Telnet passwords, enable passwords, AirWave passwords, or `${var|password}` parameter values in plaintext in SQLite.

## Verification
- After installing dependencies (`pip install -r requirements.txt -r requirements-dev.txt` and `composer install`), run `python -m pytest tests/ -v`.
- Keep `locales/aethernms.pot`, `locales/en/LC_MESSAGES/aethernms.po`, and `locales/pt_BR/LC_MESSAGES/aethernms.po` synchronized and compiled to `.mo` whenever user-facing strings change.
