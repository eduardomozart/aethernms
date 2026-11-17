# pssh-ui

Multiplatform GUI application (`tkinter`/`ttk` + [Sun-Valley-ttk-theme](https://github.com/rdbende/Sun-Valley-ttk-theme) + `paramiko`) for parallel batch SSH configuration and audit automation across managed network switches.

## Key Features

- **Native OS Defaults & `settings.xml`**: Automatically defaults to **Auto (OS Default)** for Windows and macOS Light/Dark themes and OS language, customizable from the cog (**⚙**) dialog with **`%APPDATA%\pssh-ui`** (Windows) and **`~/.config/pssh-ui`** (Linux/macOS) state storage.
- **4-Tab Workspace (`Jobs`, `Snippets`, `Devices`, `Device Models`)**:
  - **Jobs (Default)**: Circular 4-step wizard (`Config Command` → `Parameters` → `Select Device` → `Confirm`) with inline row actions (`⏹`/`🗑`), bold Job Details metrics (`Total`, `Success`, `Failed`), optional write-command toggle, and per-switch **Devices** log access (`📄`).
  - **Snippets**: Hierarchical OS-specific XML templates (`snippets/<vendor>/<os>/`) with syntax highlighting, **Audit Validation RegEx**, and XML import/export.
  - **Devices**: Manage switches, dynamically track assigned hardware models and groups, and run row-level edit/delete actions.
  - **Device Models**: Distributed `model/<vendor>/*.xml` profiles handling `Username:` / `Password:` / `Enable` automation prompts and common `Pre-Config` / `Post-Config` / `Write` command wrappers (`configure terminal`, `end`, `write memory`) — supporting new vendors/OSes via drop-in XML files without source code edits.
- **Parameterized Templates (`${var|type|regex}` & `${var|["Item 1", "Item 2"]}`)**: Supports uppercase letters, spaces, accents, HTML-like types (`text`, `password`, `number`, `email`, `url`, `select`), regex validation, and `!` comments.
- **Timestamped Logs & Password-Free State**: Writes per-switch logs to `logs/YYYY-MM-DD_HH-MM-SS/<hostname-or-switch-ip>.log` without ever persisting SSH, Enable, or `|password|` values to disk.
- **Multi-Language & Transifex Ready**: Drop-in `.po` support powered by `gettext`/Babel (no source edits required for new languages) and `.tx/config`.

## Quick Start

```bash
pip install -r requirements.txt
python main.py
```

## Running Tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -v
```

## Documentation

Full User Guide, Snippets & Models reference, Developer Design Choices, and Localization instructions are available in the **[Wiki (`docs/`)](docs/Home.md)**.
