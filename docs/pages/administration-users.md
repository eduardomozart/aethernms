# Users (`/administration/users` & `?edit=me`)

## Metadata
* **UI Routes**: `GET /administration/users`, `GET /administration/users?edit=me`
* **API Routes**: `GET /api/users`, `POST /api/users`, `PUT /api/users/<id>`, `DELETE /api/users/<id>`
* **Required RBAC Permissions**:
  * Full management (`/administration/users`): `users:manage`
  * Self-service profile (`/administration/users?edit=me` and `GET / PUT /api/users/<self_id>`): Any authenticated user (`403` returned on plain `/administration/users` without `?edit=me` when lacking `users:manage`).
* **User Guide Slug**: `/user-guide/administration-users/`
* **Window Title**: `[[=page_title]] - aether` (`Users - aether`)

## Files Owned
* Templates: `aethernms/templates/administration/users.html`, `aethernms/templates/modals/user_editor.html`, `aethernms/templates/layout.html`
* Script: `aethernms/static/js/users.js`, `aethernms/static/js/core.js`
* Backend: `aethernms/api/users.py`, `aethernms/web_app.py`, `aethernms/db.py`

## Carbon UI Layout & Components
* **Outside-Tile Page Header (`.anms-page-header`)**: Breadcrumb (`aether / Administration / Users`), `<h1>Users</h1>`, subtitle.
* **Carbon DataTable Toolbar** inside `.anms-table-container`: Search (`#users-dt-search`), **Filter** popover (`#users-filter-btn` / `#users-filter-popover` for Role `#flt-usr-role` & Status `#flt-usr-status`), active filter chips (`#users-active-filters`), and **Add User** (`#btn-add-user`, hidden for self-only non-admin users).
* **Users DataTable** (`#users-tbody`): Username, Display Name, Role, Appearance (`language` / `theme_mode`), Status, Actions (**Edit** / **Delete**).
* **User Editor Modal** (`#modal-user-editor`): Username, Display Name, Role select, **Language** (`auto` or catalog codes via Babel), **Theme** (`auto` / `light` / `dark`), Active checkbox, **Current Password** (required only when modifying own password), Password, Confirm Password.

## Behavioral Decisions & Invariants
* **Header Username Link Target**: Clicking `#hdr-user-link` in `partials/header.html` navigates directly to `/administration/users?edit=me`, automatically opening `#modal-user-editor` pre-loaded with the logged-in user's account.
* **Per-User Appearance Preferences**: Saving `language` and `theme_mode` on `auth_user` takes effect immediately for that user cleanly without affecting other users (eliminating FOUC via SSR on reload).
* **Non-Admin Self-Edit Guard**: Users without `users:manage` accessing `/administration/users?edit=me` see only their own account row, cannot click **Add User**, see disabled Role and Active controls inside `#modal-user-editor`, and `PUT /api/users/<self_id>` explicitly rejects attempts to elevate `role` or toggle `is_active` (`403`). Plain `/administration/users` without `?edit=me` returns `403`.
* **Case-Insensitive Username**: `create_user()` and `authenticate_user()` compare `LOWER(username)`.
* **Visible Modals**: `#modal-user-editor` opens/closes via `openModal()`/`closeModal()` (`.open` + `.is-visible`).

## Verification
* `tests/test_rest_api.py` (`?edit=me` non-admin access, plain `/administration/users` `403` for non-admin, self-update appearance + role escalation `403`, per-user SSR locale `<html lang=...>` & theme)
