# Snippets & Variable Templates (`/snippets`)

All built-in command templates under `snippets/<vendor>/<platform>/*.xml` (such as `snippets/aruba/aruba_procurve/*.xml` and `snippets/aruba/aruba_aoscx/*.xml`) are automatically seeded into the database with SHA-256 upgrade tracking. Because `aethernms` runs as a shared web service, all authenticated users access the central snippet catalog, while **Import XML** (`POST /api/snippets/import`) and **Export XML** (`GET /api/snippets/{id}/export`) preserve full file portability.

## 1. Built-In Read-Only Templates vs Custom Snippets

* **Built-in Templates (`Built-in` badge)**: Bundled snippets are **read-only** (`is_builtin=True`) so future application updates can safely refresh official templates without overwriting user changes.
  * Clicking **View** on a built-in snippet opens its commands, variable previews, and description in read-only mode.
  * To customize a built-in workflow, export or copy its commands into a new custom snippet via **Add Snippet**.
* **Custom Snippets**: Snippets created via **Add Snippet** or **Import XML** (`snippets:write` permission) can be freely edited, exported, or deleted.

## 2. Netmiko Platform Targeting (`<DeviceType>`)

Each `<Snippet>` targets a canonical Netmiko platform under `<DeviceType>` (displayed with friendly names like `ArubaOS-S` for `aruba_procurve` and `ArubaOS-CX` for `aruba_aoscx` across the UI). Netmiko handles login prompts, pager suppression, privilege escalation, config mode, and `save_config()` natively per driver — snippets only contain task commands:

```xml
<?xml version="1.0" encoding="utf-8"?>
<Snippet version="1.0">
    <Name>ArubaOS-CX NTP</Name>
    <Type>Config</Type>
    <DeviceType>aruba_aoscx</DeviceType>
    <Severity>Info</Severity>
    <Description>Configure NTP server settings on ArubaOS-CX switches.</Description>
    <CreatedAt>2026-11-17T15:00:00</CreatedAt>
    <Commands>! Configure primary NTP server
ntp server ${NTP Server} minpoll 4 maxpoll 4 iburst
ntp enable</Commands>
</Snippet>
```

Legacy `<DeviceType>AOS-S</DeviceType>` and `<DeviceType>AOS-CX</DeviceType>` tags normalize automatically to `aruba_procurve` and `aruba_aoscx`.

## 3. Comment Syntax & Audit RegEx (`!`)

* Lines whose first non-whitespace character is `!` are treated as comments in both `Commands` and `Audit Validation RegEx` and skipped at runtime.
* For **Audit and Remediate** snippets/jobs, each non-empty line in **`<AuditRegex>`** is compiled with `re.MULTILINE` and checked against the device CLI output. Missing patterns mark that device as failed with a diagnostic message.

## 4. Parameterized Variables (`${...}`)

Variables support uppercase letters, spaces, accents, HTML-like **input types**, **regex validation**, and **list dropdowns**:

| Syntax | Control Rendered | Behavior & Validation |
| --- | --- | --- |
| `${Variable}` | Text input | Defaults to `text`; requires non-empty input |
| `${Variable\|text\|^[A-Za-z0-9_.-]{1,32}$}` | Text input | Validated via `re.fullmatch()` |
| `${Auth Password\|password\|^.{8,64}$}` | Masked password + **Show/Hide** | Marked secret (`is_secret=True`), never saved in the database |
| `${VLAN ID\|number}` / `${Email\|email}` / `${Endpoint\|url}` / `${Phone\|tel}` | Typed text input | Validated by type or custom `\|type\|regex` |
| `${Mode\|["Access", "Core"]}` or `${Mode\|select\|["Access", "Core"]}` | `<select>` dropdown | Restricts input strictly to the listed items |
| `${Variable\|regex}` *(backwards-compatible)* | Text input | Validates text against `regex` |

### Built-in Host Context Variables
Commands and `<AuditRegex>` rules may also reference per-device runtime variables:
* `${device_name}` — Device hostname
* `${device_ip}` — Device management IP
* `${host_model}` — Hardware model string
