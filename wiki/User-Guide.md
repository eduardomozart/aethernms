# User Guide

## 1. Installation & Startup

### From Portable Release Archive (Windows)
1. Download `pssh-ui-win-x64.zip` from the repository's **GitHub Releases** page.
2. Extract the archive anywhere on your computer (all runtime libraries live inside the extracted folder without unpacking into `%TEMP%` on launch).
3. Launch `pssh-ui-x64.exe` (or run `pssh-ui-x64.exe --open-browser`) and visit `http://127.0.0.1:8080`.

### From Source
```bash
pip install -r requirements.txt
python main.py --open-browser
```

Optional CLI flags:
* `--host` (default `127.0.0.1`; pass `0.0.0.0` to expose on your LAN)
* `--port` (default `8080`)
* `--db-path` (override the default SQLite database location)
* `--open-browser` (open the default web browser automatically after startup)

You can also serve the app directly with the Py4Web CLI:
```bash
py4web run apps --host 127.0.0.1 --port 8080
```

*Requires Python **3.10+** — no Node.js build step or desktop GUI toolkit is required.*

---

## 2. First-Run Administrator Setup & Authentication

1. On first launch (when the SQLite database has no users), visiting `http://127.0.0.1:8080` redirects to **`/login`** in **Initial Administrator Setup** mode.
2. Choose a username and password (minimum 6 characters) and click **Create Administrator**.
3. Alternatively, pre-provision the initial admin via environment variables before first start:
   ```bash
   PSSH_UI_ADMIN_USER=admin
   PSSH_UI_ADMIN_PASSWORD=StrongPassword123!
   ```
4. Once signed in, click **API Keys (`🔑`)** in the top header bar to generate personal API keys (`X-API-Key` or `Authorization: Bearer`) for scripts/CI automation or change your account password.

---

## 3. SQLite Database & Legacy XML Migration

All persistent state — accounts, hashed API keys, settings, snippets, devices, jobs, and per-device execution logs — is stored in a single SQLite database (`WAL` mode):

* **Windows**: `%APPDATA%\pssh-ui\pssh_ui.db`
* **Linux / macOS**: `~/.pssh-ui/pssh_ui.db`
* **Automatic Legacy Migration**: When upgrading from an older XML-based desktop release, `pssh-ui` automatically imports existing `settings.xml`, `devices.xml`, `jobs.xml` (or legacy `session.xml`), and referenced `.log` files into SQLite on first boot whenever the corresponding tables are empty.
* **Built-in Snippet Seeding**: Bundled XML templates under `snippets/<vendor>/<platform>/` are automatically seeded into the SQLite `snippet` table using SHA-256 upgrade tracking — unedited defaults auto-update on upgrades, deleted built-ins stay deleted, and user-edited snippets are never overwritten.

---

## 4. Header Controls & Global Defaults (`API Docs`, `API Keys`, `ⓘ`, `⚙`, `Sign Out`)

* **API Docs (Swagger)** opens **`/api/docs`** in a new tab with interactive OpenAPI 3.0.3 documentation.
* **API Keys (`🔑`)** manages personal REST API tokens and account password updates.
* **`ⓘ`** displays app version and clickable repository URL.
* **`⚙` (Settings)** organizes global preferences cleanly in order:
  1. **Appearance**: **Language** (`Auto (OS Default)`, `English`, `Português (Brasil)`, or any `.po` catalog placed under `locales/`) and **Dark Theme** (`Auto (OS Default)`, `Light` Carbon `g10`, `Dark` Carbon `g100`).
  2. **Execution Defaults**: **Default Username**, **Max Parallel Executions**, **Connect Timeout (s)**, and **Command Timeout (s)**.
  3. **Connection Defaults**: **Default Protocol** (`SSH` / `Telnet`), **Default SSH Port** (`22`), and **Default Telnet Port** (`23`).
     * **Note**: Default protocol and ports apply only when creating devices manually or importing devices from AirWave, and can always be overridden per device.
* Pressing **`Esc`** closes the topmost open modal cleanly via its **Cancel** / **Close** action.

---

## 5. Workspace Tabs (`Jobs`, `Snippets`, `Devices`)

### `Devices` Tab
* **Manual Devices (`+ Add Device`)**: Register devices selecting strictly from supported Netmiko platforms (e.g., `aruba_procurve`, `aruba_aoscx`, `cisco_ios`, `juniper_junos`, etc.) and the protocols natively supported by Netmiko for that platform (`SSH` and/or `Telnet`). New entries start with the global **Default Protocol** and corresponding **Default SSH/Telnet Port**.
* **Import from AirWave...**:
  * The device list remains empty on modal open until credentials (URL, username, password) are entered and **Fetch Inventory** succeeds.
  * AirWave's reported **OS Type** (plus firmware/hardware heuristics and any previously saved custom associations) is mapped automatically to its native Netmiko platform (`AOS-S` → `aruba_procurve`, `AOS-CX` → `aruba_aoscx`, etc.) using global default connection settings (restricted to protocols natively supported by Netmiko for each platform).
  * Only if one or more checked devices have no automatic match does the **Map Unmatched AirWave Models to Netmiko** modal prompt you to associate each unmatched AirWave OS / hardware model before completing the import (saved in SQLite for future imports).
* **Editing Devices (`✎`)**:
  * For **AirWave-managed devices**, **Device Name**, **IP Address**, **Model**, and **Group** are read-only; **Netmiko Platform**, **Protocol**, and **Port** remain editable so you can customize per-device connection parameters.
  * For **manual devices**, all fields are editable (constrained to valid Netmiko platforms and natively supported protocols).
* Filter dynamically by **Device**, **IP Address**, **OS Type** (Netmiko platform), **Group**, or live **Status**, and click **Refresh Status** to probe ICMP reachability on demand.

### `Snippets` Tab
* Browse, filter, **Add Snippet**, **Import Snippet** (XML), **Export Snippet** (XML), edit (**`✎`**), or delete (**`🗑`**) command templates stored in SQLite and shared automatically with every authenticated web user.
* Choosing **Audit and Remediate** reveals the **Audit Validation RegEx** textarea (`1 pattern per line`). Lines starting with `!` are ignored.

---

## 6. Creating & Running Jobs (`Jobs` Tab)

Click **+ Add Job** to open the Carbon Progress Indicator wizard (clickable step badges allow returning to previous steps at any time without jumping ahead):

1. **Config Command**: Select `Job Type` (`Config` / `Audit and Remediate` — filters `Snippets *` cleanly and resets selection), enter `Job Name`, choose **Netmiko Platform**, and pick a **Snippet** (optional). Customize commands in the editor; for `Audit and Remediate`, review or add patterns in **Audit Validation RegEx**.
2. **Parameters** *(shown only when Commands or Audit RegEx include `${...}` variables)*: Fill inputs rendered dynamically (`text`, masked `password` with **Show/Hide**, or read-only `select` dropdown), validated live via `/api/variables/parse`.
3. **Select Device**: Shows **Snippet Target Platform** and all registered devices with their `Protocol:Port` and live ICMP reachability status, sorting matching-platform devices ahead of incompatible platforms.
4. **Confirm**: Enter **Username**, **Password**, optional **Enable Password**, **Max Parallel Executions** (or toggle **Sequential**), optionally check **Save configuration** (`netmiko` native `save_config()` on Config jobs), review read-only **Resulting Commands**, and click **Run Job**. Each host connects using the **Protocol** and **Port** configured on its **Devices** entry.

---

## 7. Inspecting Jobs, Actions & SQLite Logs

* **Jobs** rows provide inline **`↻`** (replay), **`⏹`** (stop running), and **`🗑`** (delete finished) action buttons.
* **Job Details**:
  * **Details** *(default)*: Displays **Devices** counters (`Total`, `✓ Success`, `⚠ Failed`), **Description**, syntax-highlighted **Config Commands**, and **Audit Validation RegEx** (when applicable).
  * **Devices**: Lists per-device status (`Device`, `IP Address` including `IP:Port (Protocol)`, `Status`, `Start Time`, `End Time`, `Operation Result`, `Log`) with live background polling while a job is running.
* **Device Log Modal & `.log` Download**: Click the **`📄`** button on any device result row to view the full execution log stored in SQLite (with highlighted error lines, `Connection`, `Netmiko Platform`, and `IP:Port` headers) or click **Download .log** (`/api/jobs/{job_id}/results/{result_id}/log?download=1`).
