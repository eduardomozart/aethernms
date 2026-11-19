# Snippets & Variable Templates

All built-in command snippets (`snippets/<vendor>/<platform>/*.xml`, e.g., `snippets/aruba/aruba_procurve/*.xml` and `snippets/aruba/aruba_aoscx/*.xml`) are automatically seeded into the application's **SQLite** database (`snippet` table) with SHA-256 upgrade tracking. Because `pssh-ui` runs as a web application, all authenticated users automatically share the central snippet catalog in SQLite, while **XML Import (`POST /api/snippets/import`)** and **XML Export (`GET /api/snippets/{id}/export`)** preserve full file-level portability.

---

## 1. Netmiko Platform Targeting (`<DeviceType>`)

Each `<Snippet>` specifies a native **Netmiko Platform** (such as `aruba_procurve`, `aruba_aoscx`, `cisco_ios`, `juniper_junos`, `arista_eos`, `hp_comware`, etc.) under `<DeviceType>`. Netmiko handles login prompts, pager dismissal (`no page` / `terminal length 0`), configuration mode entry/exit (`configure terminal` / `end`), and configuration saving natively per driver — snippets only contain the clean task commands:

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

Older snippets containing legacy `<DeviceType>AOS-S</DeviceType>` or `<DeviceType>AOS-CX</DeviceType>` are normalized automatically to `aruba_procurve` and `aruba_aoscx` on import or seeding.

---

## 2. Comment Syntax & Audit RegEx (`!`)

* Lines whose first non-whitespace character is `!` are treated as comments in both `Commands` and `Audit Validation RegEx` (highlighted in green and skipped at runtime).
* For **Audit and Remediate** snippets/jobs, each non-empty line in **`<AuditRegex>`** (also editable in Step 1 of **Add Job**) is compiled with `re.MULTILINE` and checked against the combined device CLI output. If any pattern is not matched, that device fails with an explicit audit diagnostic.

---

## 3. Parameterized Variables (`${...}`)

Variables support **uppercase letters, spaces, accents, and punctuation**, plus optional HTML-like **input types**, **regex validation**, and **Python list dropdown options**:

| Syntax | Control Rendered | Behavior & Validation |
| --- | --- | --- |
| `${Variable}` | Text input | Defaults to `text`; requires non-empty input |
| `${Variable\|text\|^[A-Za-z0-9_.-]{1,32}$}` | Text input | Validated via `re.fullmatch()` |
| `${Auth Password\|password\|^.{8,64}$}` | Masked password + **Show/Hide** | Explicitly marks value as secret (`is_secret=True`), never saved in SQLite |
| `${VLAN ID\|number}` / `${Email\|email}` / `${Endpoint\|url}` / `${Phone\|tel}` | Text input | HTML-like type validation or custom `\|type\|regex` |
| `${Mode\|["Access", "Core"]}` or `${Mode\|select\|["Access", "Core"]}` | Read-only `<select>` dropdown | Restricts input strictly to the listed items |
| `${Variable\|regex}` *(backwards-compatible)* | Text input | Defaults to `text` validated with `regex` |

### Built-in Host Context Variables
Commands and `<AuditRegex>` rules may reference per-device runtime variables:
* `${device_name}` — Device hostname
* `${device_ip}` — Device management IP
* `${host_model}` — Hardware model string
