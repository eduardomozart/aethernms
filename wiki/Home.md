# Welcome to `aethernms` (ÆTHER NMS)

**`aethernms`** (**ÆTHER NMS**) is a multiplatform Python web application built with **Py4Web**, **PyDAL**, **IBM Carbon Design System (v11)**, **`netmiko`**, and **`airwaveapiclient`** for running parallel SSH and Telnet configuration and audit jobs across network devices from a role-based web interface and authenticated REST API.

## Documentation Sections

* **[User Guide](User-Guide)** — Installation, first-run 3-step `/setup`, daily workflows (**Jobs**, **Snippets**, **Devices**, **Administration**), and **REST API & Swagger**.
* **[Getting Started](Getting-Started)** — Installing dependencies, running Initial Setup (`/setup`), signing in, and locating `~/.aethernms` configuration files.
* **[Jobs](Jobs)** — Creating Config and Audit automation jobs, passing dynamic variables, monitoring progress live, and downloading wire logs.
* **[Snippets & Variables](Snippets-and-Variables)** — Using read-only built-in templates, creating/importing/exporting custom XML snippets, and parameterizing commands with `${var|type|regex}` rules.
* **[Devices](Devices)** — Managing manual devices, friendly Netmiko platform names (e.g., `ArubaOS-S`, `ArubaOS-CX`), ICMP ping checks, and HPE Aruba AirWave imports.
* **[Administration: System Settings](Administration-Settings)** — Execution/connection defaults, External REST API IP allowlist, read-only Database Backend summary, and AirWave OS mappings.
* **[Administration: Users](Administration-Users)** — Account lifecycle, role assignments, personal Language/Theme preferences, and clicking your username (`?edit=me`) to edit your profile.
* **[Administration: Roles](Administration-Roles)** — Understanding built-in read-only roles (`Admin`, `Operator`, `Viewer`) and creating custom RBAC roles.
* **[Administration: API Keys](Administration-API-Keys)** — Issuing and revoking scoped API tokens (`aethernms_...`) for external automation.
* **[REST API & Swagger](REST-API)** — Enabling external API access safely, using `X-API-Key` / `Bearer` authentication, and exploring endpoints via Swagger UI.

## Key Capabilities at a Glance

| Capability | Description |
| :--- | :--- |
| **3-Step First-Run Setup (`/setup`)** | Guides **Database Backend** selection & automatic connection verification, **Administrator Account** creation, and **Review & Complete** without creating premature `.db` files. |
| **Multi-Backend PyDAL Persistence** | Defaults to local WAL-mode **SQLite** (`~/.aethernms/aethernms.db`) and supports **PostgreSQL**, **MySQL / MariaDB**, **MSSQL**, **Oracle**, and custom PyDAL URIs. |
| **IBM Carbon v11 Workspace** | Dark 48px global header with **ÆTHER NMS** wordmark, aligned full-height **Global Device Search**, expandable left **SideNav Rail**, per-user Light (`white`) / Dark (`g100`) themes, and contextual **Help** links. |
| **RBAC & Secure External REST API** | Read-only system roles (`Admin`, `Operator`, `Viewer`) plus custom roles, per-user localization & theme, scoped `aethernms_...` API keys, and IP-allowlisted Swagger UI (`/api/docs`). |
| **Native Netmiko Multi-Platform Engine** | Supports every non-serial Netmiko driver with friendly display labels (e.g., `ArubaOS-S`) and automatic built-in template seeding. |
