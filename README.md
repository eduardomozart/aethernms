<img src="assets/pssh-ui.png" width="96" height="96" align="top" alt="pssh-ui logo" />

# pssh-ui

[![Release Version](https://img.shields.io/github/v/release/eduardomozart/pssh-ui?style=for-the-badge&logo=github)](https://github.com/eduardomozart/pssh-ui/releases/latest)

Multiplatform desktop application for parallel SSH configuration and audit automation across managed network switches.

## Key Features

### Device Inventory & AirWave Import
Manage switches manually with **+ Add Device** or connect directly to **Aruba AirWave** via **Import from AirWave...** to browse the folder hierarchy, filter switches by name, IP, OS type, group, or status, and keep track of your active switch inventory.

![Devices Tab](wiki/images/devices.png)

### Reusable Command Snippets
Organize **Config** and **Audit and Remediate** command templates by switch OS, preview syntax-highlighted CLI scripts, import/export XML snippets, and customize commands before execution.

![Snippets Tab](wiki/images/snippets.png)

### Device Automation Profiles
Pre-configured **Device Models** (`ArubaOS-CX`, `ArubaOS-S (ProCurve)`, and custom models) handle login prompts, privilege escalation (`enable`), paging suppression, and configuration wrappers (`configure terminal` / `end`) automatically.

![Device Models Tab](wiki/images/device-models.png)

### Guided Task Creation Wizard
Run configuration or audit tasks across multiple switches through an intuitive step-by-step wizard:

1. **Config Command** — Pick **Config** or **Audit and Remediate**, set the task name, choose the target OS and device model, select a snippet, and adjust CLI commands as needed.

   ![Add Job - Config Command](wiki/images/add-job-step1-command.png)

2. **Parameters** — Automatically prompted whenever a snippet uses interactive variables, with real-time input validation (`✓`).

   ![Add Job - Parameters](wiki/images/add-job-step2-parameters.png)

3. **Select Device** — Filter by device, IP, OS type, group, or live ping status and check the target switches.

   ![Add Job - Select Device](wiki/images/add-job-step3-devices.png)

4. **Confirm & Run** — Enter SSH/Enable credentials, choose parallel or sequential execution, optionally run `write memory`, review the exact commands to be sent, and click **Run Job**.

   ![Add Job - Confirm](wiki/images/add-job-step4-confirm.png)

## Quick Start

```bash
pip install -r requirements.txt
python main.py
```

Prebuilt Windows binaries are available on the **[Releases](https://github.com/eduardomozart/pssh-ui/releases/latest)** page.

## Running Tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -v
```

## Documentation & Translations

Full guides and technical architecture details are available in the **[Wiki](https://github.com/eduardomozart/pssh-ui/wiki)** (published from [`wiki/`](wiki/)):
- **[User Guide](https://github.com/eduardomozart/pssh-ui/wiki/User-Guide)** — Detailed workflow, settings, and log inspection
- **[Snippets & Variables](https://github.com/eduardomozart/pssh-ui/wiki/Snippets-and-Variables)** — XML templates, parameterized inputs, and Audit RegEx rules
- **[Developer Design Choices](https://github.com/eduardomozart/pssh-ui/wiki/Developer-Design-Choices)** — Architecture, SSH PTY automation, OS config paths, security, and release packaging
- **[Localization & Transifex](https://github.com/eduardomozart/pssh-ui/wiki/Localization-and-Transifex)** — Multi-language `.po`/`.mo` catalog workflow

Help translate **`pssh-ui`** into more languages on **[Transifex](https://app.transifex.com/eduardomozart/pssh-ui/)**.
