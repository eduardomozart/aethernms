# User Guide

This guide walks network engineers and administrators through installing **`aethernms`** (**ÆTHER NMS**), completing first-run configuration, managing device inventory, authoring parameterized snippets, executing parallel Config/Audit jobs, and administering users and external REST access.

## Workspace Layout & Navigation

1. **48px Dark Global Header (`ÆTHER NMS`)**:
   * **Navigation Toggle**: Pins or expands the left **SideNav Rail** (`48px` collapsed icon rail that also expands smoothly on hover or focus).
   * **Global Device Search**: Live search across device Name, IP, Model, Group, Netmiko Platform, and Serial Number. Press `Enter` or select a match to open filtered results on **Devices**.
   * **API Docs (Swagger)**: Visible when **External REST API & Swagger UI** is enabled in System Settings.
   * **Help (`?`)**: Opens the User Guide page specific to the screen you are currently viewing.
   * **Username Profile Link**: Clicking your username opens **Administration → Users** directly in self-edit mode (`?edit=me`) so you can update your Display Name, Language, Theme, and Password.
   * **Sign Out**: Ends your browser session cleanly.
2. **Outside-Tile Page Header & Carbon DataTables**:
   * Every page displays breadcrumbs and its `<h1>` title above the main content tiles.
   * All tables include an inline **Carbon DataTable Toolbar** with live search, a **Filter** popover panel (**Apply** / **Reset filters**), dismissible active filter chips, and primary actions.

## User Guide Chapters

| Topic | Summary |
| :--- | :--- |
| **[Getting Started](Getting-Started)** | Installation, CLI flags, environment overrides, 3-step `/setup`, and signing in |
| **[Jobs](Jobs)** | Running Config & Audit jobs, filling dynamic variables, inspecting live logs |
| **[Snippets & Variables](Snippets-and-Variables)** | Read-only built-in templates, custom XML snippets, `${...}` variable types & regexes |
| **[Devices](Devices)** | Adding devices manually, friendly Netmiko platforms, Ping sweeps, AirWave import |
| **[System Settings](Administration-Settings)** | Connection/execution defaults, AirWave OS mapping, External API allowlist |
| **[Users](Administration-Users)** | User accounts, per-user Language & Theme preferences, `?edit=me` self-service |
| **[Roles](Administration-Roles)** | Built-in read-only roles vs custom RBAC permission roles |
| **[API Keys](Administration-API-Keys)** | Issuing scoped tokens for CI/CD, Ansible, or Swagger UI |
| **[REST API & Swagger](REST-API)** | Swagger UI, OpenAPI 3.0.3 schema, and `curl`/Python automation examples |
