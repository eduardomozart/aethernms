# Snippets (`/snippets`)

## Metadata
* **UI Routes**: `GET /snippets`
* **API Routes**: `GET /api/snippets`, `POST /api/snippets`, `PUT /api/snippets/<id>`, `DELETE /api/snippets/<id>`, `POST /api/snippets/import`, `GET /api/snippets/<id>/export`, `POST /api/variables/parse`
* **Required RBAC Permissions**: `snippets:read` (view list, view read-only templates, export XML), `snippets:write` (create/edit/delete custom user snippets, import XML)
* **User Guide Slug**: `/user-guide/snippets-and-variables/`
* **Window Title**: `[[=page_title]] - aether` (`Snippets - aether`)

## Files Owned
* Templates: `aethernms/templates/snippets.html`, `aethernms/templates/modals/snippet_editor.html`, `aethernms/templates/layout.html`
* Script: `aethernms/static/js/snippets.js`, `aethernms/static/js/core.js`
* Backend: `aethernms/api/snippets.py`, `aethernms/api/variables.py`, `aethernms/snippet_store.py`, `aethernms/variables.py`, `aethernms/db.py`

## Carbon UI Layout & Components
* **Outside-Tile Page Header (`.anms-page-header`)**: Breadcrumb (`aether / Snippets`), `<h1>Snippets</h1>`, subtitle.
* **Carbon DataTable Toolbar** inside `.anms-table-container`:
  * Search (`#snippets-dt-search`), **Filter** popover (`#snippets-filter-btn` / `#snippets-filter-popover` with Type `#flt-snip-type`, Severity `#flt-snip-sev`, Platform `#flt-snip-os`), active filter chips (`#snippets-active-filters`), **Import XML** (`#btn-import-snippet`), **Export XML** (`#btn-export-snippet`), and **Add Snippet** (`#btn-add-snippet`).
* **Snippets DataTable** (`#snippets-tbody`, `#snippets-pagination`): Folder/Name, Read-Only `"Built-in"` badge (`is_builtin`), Type, Severity, Netmiko Platform (friendly label), Actions (View for built-in; Edit/Delete for custom).
* **Modal** (`#modal-snippet`): Supports View mode (read-only inputs + disabled Save button + info notice for built-in snippets) and Edit/Add mode (live variable preview via `/api/variables/parse`).

## Behavioral Decisions & Invariants
* **Built-In Snippets Strictly Read-Only**: Seeded snippets (`is_builtin=True`) cannot be edited or deleted via UI or API (`DatabaseStore.update_snippet`/`delete_snippet` raise `ValueError`; `PUT`/`DELETE /api/snippets/<id>` return HTTP `403`). Users see a **View** action instead of Edit/Delete and are notified that built-in templates are read-only.
* **Friendly Netmiko Platform Names**: `#flt-snip-os`, snippet table cells, and `#modal-snippet` platform selector render friendly names (e.g., `ArubaOS-S`) while persisting canonical Netmiko keys (`platform` / `os_type`).
* **Visible Modals**: Uses `openModal('modal-snippet')` / `closeModal('modal-snippet')` toggling `.open` + `.is-visible`.
* **Safe XML Import/Export**: Custom snippets export/import cleanly via XML while refusing edits against built-in IDs.

## Verification
* `tests/test_db_and_migration.py::test_snippet_seeding_sha256_edits_deletes_and_xml_roundtrip`
* `tests/test_snippet_store.py`, `tests/test_variables.py`, `tests/test_rest_api.py`
