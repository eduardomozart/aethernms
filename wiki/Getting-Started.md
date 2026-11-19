# Getting Started (`/setup` & `/login`)

## 1. Installation & Startup

### From Source
```bash
pip install -r requirements.txt
composer install
python main.py --open-browser
```

Optional CLI flags:
* `--host` (default `127.0.0.1`; pass `0.0.0.0` to bind all interfaces)
* `--port` (default `8000`)
* `--db-path` (custom local SQLite database file path)
* `--db-uri` (custom PyDAL URI, e.g., `postgres://user:pass@host:5432/aethernms`)
* `--open-browser` (launch your default web browser automatically)

Environment variable overrides:
* `AETHERNMS_CONFIG_DIR` — overrides the default runtime directory (`~/.aethernms` across Windows, Linux, and macOS).
* `AETHERNMS_DB_URI` — preconfigures the PyDAL database URI (overrides `db_config.json`).
* `AETHERNMS_DOCS_URL` — optional base URL for the contextual **Help** link in the header.
* `AETHERNMS_ADMIN_USER` / `AETHERNMS_ADMIN_PASSWORD` — optional headless Admin provisioning on startup.

You can also serve the app using the Py4Web CLI:
```bash
py4web run apps --host 127.0.0.1 --port 8000
```

## 2. First-Run 3-Step Setup Guide (`/setup`)

When starting with no configured database or Administrator account, `aethernms` displays `Setup required: http://127.0.0.1:8000/setup` and redirects any browser request to **`/setup`**. Localization automatically adapts to your browser language (`navigator.languages`).

1. **Step 1 — Database Backend**:
   * Choose **SQLite (Local — Default)** (`~/.aethernms/aethernms.db`), **PostgreSQL**, **MySQL / MariaDB**, **Microsoft SQL Server (MSSQL)**, **Oracle Database**, or **Custom PyDAL URI**.
   * External databases display live **Python Driver Status** (`Driver Installed` or `Driver Missing` with the exact `pip install ...` hint).
   * Click **Test Connection** at any time, or simply click **Next >**: clicking **Next >** automatically tests the database connection before advancing (unless the same unchanged parameters already passed a test).
2. **Step 2 — Administrator Account**:
   * Enter **Username**, optional **Display Name**, **Password** (minimum 6 characters), and **Confirm Password**.
3. **Step 3 — Review & Complete**:
   * Verify the selected engine, masked connection URI, Admin details, and built-in RBAC roles (`Admin`, `Operator`, `Viewer`).
   * Click **Complete** (**Concluir** in Portuguese).
   * `aethernms` initializes the schema, seeds built-in read-only Netmiko snippets and RBAC roles, saves `~/.aethernms/db_config.json`, signs you in automatically, redirects to **`/jobs`**, and permanently locks **`/setup`**.

## 3. Signing In (`/login`)

* Open `/login` and enter your **Username** (case-insensitive) and **Password**.
* After signing in, your personal **Language** and **Theme** preferences load automatically on every page.
