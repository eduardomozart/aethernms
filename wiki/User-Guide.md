# User Guide

## 1. Installation & Startup

### From Release Binary (Windows)
Download `pssh-ui-x64.exe` from the repository's **GitHub Releases** page and run it directly.

### From Source
```bash
pip install -r requirements.txt
python main.py
```

*Requires Python **3.10+** with `tkinter` enabled (`python3-tk` on Debian/Ubuntu).*

---

## 2. Configuration Directory & Template Storage

`pssh-ui` stores user configuration state, logs, and editable XML libraries cleanly by OS:

* **Windows Packaged App**: `%APPDATA%\pssh-ui\` (`settings.xml`, `session.xml`, `logs/`, plus persistent `snippets/` and `model/` folders seeded from built-in defaults)
* **Linux / macOS Packaged App**: `~/.config/pssh-ui/` (or `$XDG_CONFIG_HOME/pssh-ui/`, containing `settings.xml`, `session.xml`, `logs/`, `snippets/`, and `model/`)
* **Running from Source**: uses `%APPDATA%\pssh-ui\` / `~/.config/pssh-ui/` for `settings.xml`, `session.xml`, and `logs/`, while reading/writing `snippets/` and `model/` directly in the repository checkout.
* **Safe Template Upgrades**: Built-in XML templates are tracked via SHA-256 hashes (`.seed_manifest.json`). On executable upgrades, unedited built-in templates update automatically, user deletions remain respected, and user-edited XMLs stay intact (writing a `.xml.new` sidecar beside modified files if updated upstream).
* Additional XML files dropped into `snippets/` or `model/` (or imported via **Import Snippet** / **Import Device Model**) are discovered automatically at startup with zero code changes.

---

## 3. Header Controls & Settings (`ⓘ` and `⚙`)

* By default, both **Language** and **Dark Theme** default to **Auto (OS Default)** on Windows and macOS.
* Click **`ⓘ`** (to the left of **`⚙`**) in the top-right header to view the app icon, version, and clickable Git repository link.
* Click **`⚙`** in the top-right header to open **Settings**:
  * **Appearance**: Choose **Language** (`Auto (OS Default)`, `English`, `Português (Brasil)`, or any `.po` catalog placed under `locales/`) and **Dark Theme** (`Auto (OS Default)`, `Light`, `Dark`).
  * **SSH & Execution Defaults**: Configure integer **Default SSH Port**, **Max Parallel Executions**, **Connect Timeout (s)**, and **Command Timeout (s)** (persisted in `settings.xml`, never storing passwords).

---

## 4. Workspace Tabs (`Jobs`, `Snippets`, `Devices`, `Device Models`)

### `Device Models` Tab
* Manage XML driver definitions in `model/<vendor>/*.xml`:
  * Prompt/automation regexes (`CLI Prompt RegEx`, `Username Prompt RegEx`, `Password Prompt RegEx`, `Enable Command`, `Enable Password Prompt RegEx`, `Pager / Banner RegEx`, `Disable Paging Command`).
  * Common task command wrappers (`Pre-Config Commands` like `configure terminal`, `Post-Config Commands` like `end`, `Write / Save Command` like `write memory`, and `Pre/Post Audit Commands`) so individual **Config** snippets stay clean without repeating `configure terminal`.
* Use **Import Device Model**, **Export Device Model**, row icons (**`✎`** Edit, **`🗑`** Delete), or **+ Add Model** to customize or create platform models.

### `Devices` Tab
* Import switches via **Import from AirWave...** or click **+ Add Device** to add switches manually (`Device Name`, `IP Address`, `Model`, `Switch OS`, `Group`, `SSH Port`).
* Use row icons (**`✎`** Edit, **`🗑`** Delete) on each device row and filter dynamically by **Device**, **IP Address**, **OS Type**, **Group**, or live **Status**.

### `Snippets` Tab
* Browse, filter, **Import Snippet**, **Export Snippet**, edit (**`✎`**), or delete (**`🗑`**) XML command templates.
* Choosing **Audit and Remediate** reveals the **Audit Validation RegEx** textarea (`1 pattern per line`). Lines starting with `!` are ignored.

---

## 5. Creating & Running Jobs (`Jobs` Tab)

Click **+ Add Job** to open the wizard (clickable circular step numbers allow returning to previous steps at any time without advancing ahead):

1. **Config Command**: Select `Job Type` (`Config` / `Audit and Remediate` — filters `Snippets *` cleanly and resets selection), enter `Job Name` (starts empty), choose `Device Type` & `Device Model`, and pick a **Snippet** (blank by default until chosen). Customize commands in the syntax-highlighted editor; for `Audit and Remediate`, review or add patterns in **Audit Validation RegEx**.
2. **Parameters** *(shown only when Commands or Audit RegEx include `${...}` variables)*: Fill inputs rendered dynamically (`Entry`, masked `|password|` with **Show**, or read-only list `Dropdown`), with live **`✓`** / **`✗`** validation indicators.
3. **Select Device**: Shows **Snippet Target OS** and all registered devices with per-column filters.
4. **Confirm**: Enter **SSH Username**, **SSH Password**, optional **Enable Password**, integer **SSH Port** / **Max Parallel Executions**, optionally check **Run write command (`write memory`)** (shown when supported by the Device Model on Config jobs), review read-only **Resulting Commands**, and click **Run Job**.

---

## 6. Inspecting Jobs, Actions & Logs

* **Jobs** rows provide inline **`⏹`** (stop running) and **`🗑`** (delete finished) action buttons.
* **Job Details**:
  * **Details** *(default)*: Displays bold **Devices** counters (`Total`, `✓ Success`, `⚠ Failed`), borderless **Description**, **Config Commands**, and **Audit Validation RegEx** (when applicable).
  * **Devices**: Lists per-switch status (`Device`, `IP Address`, `Status`, `Start Time`, `End Time`, `Operation Result`, `Log`), **Open Logs Folder**, and a **`📄`** icon on every row to open the switch `.log` file (or error viewer).
