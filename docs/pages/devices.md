# Devices (`/devices`)

## Metadata
* **UI Routes**: `GET /devices`, `GET /devices?q=<search>`
* **API Routes**: `GET /api/devices`, `POST /api/devices`, `PUT /api/devices/<id>`, `DELETE /api/devices/<id>`, `GET /api/devices/search`, `POST /api/devices/ping`, `POST /api/airwave/fetch`, `POST /api/airwave/import`
* **Required RBAC Permissions**: `devices:read` (inventory list, global search, ping), `devices:write` (add/edit/delete manual devices), `airwave:import` (open AirWave modal & import devices)
* **User Guide Slug**: `/user-guide/devices/`
* **Window Title**: `[[=page_title]] - aether` (`Devices - aether`)

## Files Owned
* Templates: `aethernms/templates/devices.html`, `aethernms/templates/modals/device_editor.html`, `aethernms/templates/modals/airwave_import.html`, `aethernms/templates/modals/unmapped_models.html`, `aethernms/templates/layout.html`
* Script: `aethernms/static/js/devices.js`, `aethernms/static/js/core.js`
* Backend: `aethernms/api/devices.py`, `aethernms/api/airwave.py`, `aethernms/airwave_importer.py`, `aethernms/ping_checker.py`, `aethernms/netmiko_catalog.py`

## Carbon UI Layout & Components
* **Outside-Tile Page Header (`.anms-page-header`)**: Breadcrumb (`aether / Devices`), `<h1>Devices</h1>`, subtitle.
* **Global Search Sync**: Navigating from header global search (`/devices?q=...`) shows active query banner `#dev-global-query-banner` (`#btn-clear-global-query`).
* **Carbon DataTable Toolbar** inside `.anms-table-container`:
  * Search (`#devices-dt-search`), **Filter** popover (`#devices-filter-btn` / `#devices-filter-popover` filtering Platform `#flt-dev-os`, Group `#flt-dev-group`, Reachability Status `#flt-dev-status`), active filter tags (`#devices-active-filters`), **Ping Devices** (`#btn-ping-devices`), **Import AirWave** (`#btn-open-airwave`), and **Add Device** (`#btn-add-device`).
* **Modals**: `#modal-device` (create/edit manual device with protocol SSH/Telnet/Disabled & friendly Netmiko platform selector), `#modal-airwave` (fetch & map AirWave AMP inventory), and `#modal-unmapped` (review unmapped AirWave models).

## Behavioral Decisions & Invariants
* **Friendly Platform Names (`ArubaOS-S`, etc.)**: Displayed across the Devices DataTable, Filter popover (`#flt-dev-os`), and `#modal-device` selector; backend continues storing canonical Netmiko driver keys.
* **AirWave Source Protection**: AirWave-sourced devices track source ownership and expose platform mapping cleanly via AirWave OS mappings.
* **Visible Modals & Clean DataTable Filtering**: No static filter row above the table; all modal triggers use `openModal(...)` toggling `.open` + `.is-visible`.
* **Header Global Search Integration**: Header global search bar queries `/api/devices/search` live and links directly to `/devices?q=...` or edits devices smoothly.

## Verification
* `tests/test_rest_api.py`, `tests/test_airwave_importer.py`, `tests/test_ping_checker.py`, `tests/test_netmiko_catalog.py`
