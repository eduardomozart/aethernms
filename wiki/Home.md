# Welcome to the `pssh-ui` Wiki

**`pssh-ui`** is a multiplatform Python GUI application (`tkinter`/`ttk` styled with `Sun-Valley-ttk-theme` + `paramiko` + `airwaveapiclient`) for executing parallel batch SSH configuration and audit automation across network switches.

---

## Wiki Navigation

* **[User Guide](User-Guide)** — Installation, OS config directories (`%APPDATA%\pssh-ui` & `~/.config/pssh-ui`), `Jobs` / `Snippets` / `Devices` / `Device Models` workflow, circular 4-step wizard, Audit RegEx validation, and per-switch logs.
* **[Snippets & Variables Reference](Snippets-and-Variables)** — Bundled hierarchical snippet & device model XMLs (extensible without editing source code), `${var|type|regex}` & `${var|["Item 1", "Item 2"]}` templates, and Audit RegEx checks.
* **[Developer Design Choices](Developer-Design-Choices)** — Architecture, `sv-ttk` Sun-Valley integration, Windows/macOS theme & language detection, `DeviceModel` SSH automation state machine, security decisions, and PyInstaller release workflow.
* **[Localization & Transifex](Localization-and-Transifex)** — Zero-code `.po` discovery, dynamic Babel native locale labels, `.pot` extraction, and community translations on **[Transifex](https://app.transifex.com/eduardomozart/pssh-ui/)**.

---

## Key Capabilities at a Glance

| Capability | Description |
| :--- | :--- |
| **OS-Matched Appearance & Locale** | Uses `Sun-Valley-ttk-theme` (`sv-ttk`) and defaults to **Auto (OS Default)** on Windows and macOS (`settings.xml` customizable via `⚙`). |
| **XML Device Models (`model/`)** | Abstracts vendor/OS prompt regexes, `Username:`/`Password:`/`Enable` escalation, paging suppression, common pre/post commands (`configure terminal`, `end`), and optional write command (`write memory`). |
| **Zero-Code Extensibility** | Drop new vendor/OS XML files into `model/` and `snippets/` (or drop Transifex `.po` catalogs into `locales/`) without modifying Python source code. |
| **Circular 4-Step Job Wizard** | Guided flow (`Config Command` → `Parameters` → `Select Device` → `Confirm`) with editable commands, Audit RegEx textarea, backward step navigation, and optional write checkbox. |
| **Audit Validation RegEx** | Validates switch CLI output against expected RegEx rules for `Audit and Remediate` jobs, flagging missing patterns as errors. |
| **Password-Free XML Persistence** | Stores user state in `%APPDATA%\pssh-ui` (Windows) or `~/.config/pssh-ui` (Linux/macOS) without saving SSH, API, or `|password|` values on disk. |
