# Jobs (`/jobs` and `/`)

## Metadata
* **UI Routes**: `GET /`, `GET /jobs`
* **API Routes**: `GET /api/jobs`, `POST /api/jobs`, `GET /api/jobs/<job_uid>`, `POST /api/jobs/<job_uid>/stop`, `DELETE /api/jobs/<job_uid>`, `GET /api/jobs/<job_uid>/results/<result_id>/log`
* **Required RBAC Permissions**: `jobs:read` (view page, list jobs, inspect logs), `jobs:run` (**Add Job** & **Stop** running jobs), `jobs:delete` (**Delete** finished jobs)
* **User Guide Slug**: `/user-guide/jobs/`
* **Window Title**: `[[=page_title]] - aether` (`Jobs - aether`)

## Files Owned
* Templates: `aethernms/templates/jobs.html`, `aethernms/templates/modals/add_job.html`, `aethernms/templates/modals/device_log.html`, `aethernms/templates/layout.html`
* Script: `aethernms/static/js/jobs.js`, `aethernms/static/js/core.js`
* Backend: `aethernms/api/jobs.py`, `aethernms/job_builder.py`, `aethernms/ssh_runner.py`, `aethernms/parser.py`, `aethernms/logger.py`

## Carbon UI Layout & Components
* **Outside-Tile Page Header (`.anms-page-header`)**: Breadcrumb (`aether / Jobs`), `<h1>Jobs</h1>`, and page description above `.cds--tile` content.
* **Carbon DataTable Toolbar** inside `.anms-table-container`:
  * Inline search (`#jobs-dt-search`), clear button, **Filter** popover (`#jobs-filter-btn` / `#jobs-filter-popover` filtering Type `#flt-job-type`, Netmiko Platform `#flt-job-os`, Status `#flt-job-status`), active filter chips (`#jobs-active-filters`), and **Add Job** button (`#btn-add-job`).
* **Jobs DataTable** (`#jobs-tbody`, `#jobs-pagination`): Job Name, Type (`Config`/`Audit`), Platform (friendly label, e.g. `ArubaOS-S`), Status tag, Progress, Created, Actions (Stop / Delete).
* **Job Details Panel** (`#job-details-card`): Carbon Tabs (`Details` `#job-subtab-details` / `Devices` `#job-subtab-devices`) showing metric summary, description, CLI preview, Audit RegEx if applicable, per-device result status, and **View Log** button opening `#modal-log`.
* **Modals**: `#modal-add-job` (3-tab/section wizard: Job Setup, Dynamic Variables `${var|...}`, Target Devices filtered by selected Netmiko platform) and `#modal-log` (formatted wire log viewer).

## Behavioral Decisions & Invariants
* **Friendly Platform Display Names**: Both DataTable rows, filter dropdown `#flt-job-os`, and `#modal-add-job` platform selector show friendly names (`ArubaOS-S` for `aruba_procurve`, etc.) while keeping canonical Netmiko keys (`os_type`) in API payloads.
* **Visible Carbon Modals**: Opening `#modal-add-job` or `#modal-log` uses `openModal()` (toggling both `.open` and `.is-visible`).
* **DataTable Filtering Only**: No fixed top filter bar; all search/facets live in the Carbon DataTable Toolbar + popover + removable chips.
* **Secret Protection**: Job parameter persistence redacts `${var|password}` secrets and Netmiko wire logs filter device passwords.

## Verification
* `tests/test_rest_api.py::test_settings_devices_airwave_snippets_and_jobs_rest_workflow`
* `tests/test_job_builder.py`, `tests/test_ssh_runner.py`
