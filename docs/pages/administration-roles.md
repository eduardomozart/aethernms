# Roles (`/administration/roles`)

## Metadata
* **UI Routes**: `GET /administration/roles`
* **API Routes**: `GET /api/roles`, `POST /api/roles`, `PUT /api/roles/<id>`, `DELETE /api/roles/<id>`
* **Required RBAC Permissions**: `roles:manage` (`403` Forbidden otherwise)
* **User Guide Slug**: `/user-guide/administration-roles/`
* **Window Title**: `[[=page_title]] - aether` (`Roles - aether`)

## Files Owned
* Templates: `aethernms/templates/administration/roles.html`, `aethernms/templates/modals/role_editor.html`, `aethernms/templates/layout.html`
* Script: `aethernms/static/js/roles.js`, `aethernms/static/js/core.js`
* Backend: `aethernms/api/roles.py`, `aethernms/auth.py`, `aethernms/db.py`

## Carbon UI Layout & Components
* **Outside-Tile Page Header (`.anms-page-header`)**: Breadcrumb (`aether / Administration / Roles`), `<h1>Roles</h1>`, subtitle.
* **Carbon DataTable Toolbar** inside `.anms-table-container`: Search (`#roles-dt-search`), **Filter** popover (`#roles-filter-btn` / `#roles-filter-popover` for Role Type `#flt-role-type`: All / System / Custom), active filter chips (`#roles-active-filters`), and **Add Role** (`#btn-add-role`).
* **Roles DataTable** (`#roles-tbody`): Role Name, System / Custom Tag, Translated Description, Assigned Permissions, Actions (**View** for System roles; **Edit** / **Delete** for Custom roles).
* **Role Editor Modal** (`#modal-role-editor`): Role Name, Description, granular Permission checklist (`ALL_PERMISSIONS`). In View mode for system roles, inputs and **Save** are disabled with an explicit read-only banner.

## Behavioral Decisions & Invariants
* **System Roles Strictly Read-Only**: Default built-in roles (`Admin`, `Operator`, `Viewer` with `is_system=True`) cannot be edited or deleted via UI or API (`DatabaseStore.update_role`/`delete_role` raise `ValueError`; `PUT`/`DELETE /api/roles/<id>` return HTTP `403`).
* **Translatable Role Descriptions**: Exact `DEFAULT_ROLES` descriptions live in `aethernms/web_strings.py`, are serialized cleanly in `/api/roles`, and render translated via `t(role.description)` in `roles.js` and `#modal-role-editor`.
* **Visible Modals**: Opening View/Add/Edit Role modals uses `openModal('modal-role-editor')` toggling both `.open` and `.is-visible`.
* **Safe Deletion**: Custom roles actively assigned to users cannot be deleted until reassigned.

## Verification
* `tests/test_rest_api.py` (system role read-only `403`, custom role CRUD, translated descriptions in pt-BR)
