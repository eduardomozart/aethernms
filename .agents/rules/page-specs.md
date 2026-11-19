# Per-Page Specifications Rule (`docs/pages/*.md`)

Every application page and modal in `aethernms` has a canonical specification in `docs/pages/`.

## Mandatory Workflow for Agents

1. **Read First**: Before modifying any HTML template, modal, JS controller, page CSS rule, or backing REST API endpoint, **always read the corresponding specification** in `docs/pages/<page>.md` (plus `docs/developer-guide/ui-shell.md` for shared shell components).
2. **Respect Invariants**: Never regress documented constraints (read-only built-in snippets/system roles, per-user language/theme, `?edit=me` self-service guard, friendly Netmiko platform labels, DataTable Filter popover toolbar, `.open` + `.is-visible` modal visibility, no button checkmark icons).
3. **Update Together**: Whenever a page's routes, RBAC permissions, UI structure, or behavioral invariants change, update the matching `docs/pages/<page>.md` file in the same change.

## Route-to-Specification Mapping

| Route(s) | Specification File | Help Guide Slug |
|---|---|---|
| `/setup`, `/setup/info`, `/setup/test-db` | `docs/pages/setup.md` | `/user-guide/getting-started/` |
| `/login`, `/logout`, `/account/password` | `docs/pages/login.md` | `/user-guide/getting-started/` |
| `/`, `/jobs`, `/api/jobs*` | `docs/pages/jobs.md` | `/user-guide/jobs/` |
| `/snippets`, `/api/snippets*`, `/api/variables/parse` | `docs/pages/snippets.md` | `/user-guide/snippets-and-variables/` |
| `/devices`, `/api/devices*`, `/api/airwave/*` | `docs/pages/devices.md` | `/user-guide/devices/` |
| `/administration/settings`, `/api/settings` | `docs/pages/administration-settings.md` | `/user-guide/administration-settings/` |
| `/administration/users`, `/administration/users?edit=me`, `/api/users*` | `docs/pages/administration-users.md` | `/user-guide/administration-users/` |
| `/administration/roles`, `/api/roles*` | `docs/pages/administration-roles.md` | `/user-guide/administration-roles/` |
| `/administration/api-keys`, `/api/auth/api-keys*` | `docs/pages/administration-api-keys.md` | `/user-guide/administration-api-keys/` |
| `/api/docs`, `/swagger`, `/api/openapi.json` | `docs/pages/api-docs.md` | `/user-guide/rest-api/` |

## Cross-Cutting Developer Specs
* `docs/developer-guide/architecture.md` — Runtime storage (`~/.aethernms`), PyDAL multi-backend engine config, RBAC, Netmiko runner, assets.
* `docs/developer-guide/ui-shell.md` — 48px dark header, 256px brand zone + full-height search bar, SideNav Rail, `.anms-page-header`, DataTable toolbars, modals, and window title conventions.
* `docs/developer-guide/localization.md` — GNU gettext / Babel workflow, `web_strings.py`, zero-FOUC SSR `T(...)` rendering, `#anms-initial-i18n`, and Transifex mapping.
