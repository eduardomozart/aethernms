# Snippets, Device Models & Variable Templates

All command snippets (`snippets/<vendor>/<os>/*.xml`) and device models (`model/<vendor>/*.xml`) are shipped with the application, seeded into user config storage (`%APPDATA%\pssh-ui` / `~/.config/pssh-ui`) in packaged `.exe` builds with SHA-256 upgrade tracking, and discovered dynamically from XML without editing source code. Neither `<Snippet>` nor `<DeviceModel>` XML files include a `<Folder>` tag — the hierarchy is derived directly from their directory path.

---

## 1. Device Models (`model/`)

Each `<DeviceModel>` XML defines automation behavior and common task wrappers so Config snippets do not need to hardcode `configure terminal`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<DeviceModel version="1.0">
    <Name>ArubaOS-CX</Name>
    <DeviceType>AOS-CX</DeviceType>
    <Vendor>Aruba</Vendor>
    <Description>ArubaOS-CX switches</Description>
    <CliPromptRegex>(?:^|\n)[ \t]*[A-Za-z0-9_.:-]+(?:\([^)\r\n]+\))?[#>][ \t]*$</CliPromptRegex>
    <UsernamePromptRegex>(?:Username|Login|User)\s*:</UsernamePromptRegex>
    <PasswordPromptRegex>(?:Enable\s+password|Password)\s*:</PasswordPromptRegex>
    <EnableCommand>enable</EnableCommand>
    <EnablePromptRegex>(?:^|\n)[ \t]*[A-Za-z0-9_.:-]+(?:\([^)\r\n]+\))?#\s*$</EnablePromptRegex>
    <EnablePasswordPromptRegex>(?:Enable\s+password|Password)\s*:</EnablePasswordPromptRegex>
    <PagerPromptRegex>(?:Press any key to continue|--\s*MORE\s*--|Press &lt;SPACE&gt; to continue)</PagerPromptRegex>
    <PagerDismissKey> </PagerDismissKey>
    <DisablePagingCommand>no page</DisablePagingCommand>
    <PreConfigCommands>configure terminal</PreConfigCommands>
    <PostConfigCommands>end</PostConfigCommands>
    <WriteCommand>write memory</WriteCommand>
    <PreAuditCommands />
    <PostAuditCommands />
</DeviceModel>
```

Adding a new platform requires only creating matching XML files under `model/` and `snippets/` (or using the **Device Models** / **Snippets** tabs) — `<DeviceType>` strings are discovered automatically across the entire UI.

---

## 2. Comment Syntax & Audit RegEx (`!`)

* Lines whose first non-whitespace character is `!` are treated as comments in both `Commands` and `Audit Validation RegEx` (highlighted in green and skipped at runtime).
* For **Audit and Remediate** snippets/jobs, each non-empty line in **`<AuditRegex>`** (also editable in Step 1) is compiled with `re.MULTILINE` and checked against the combined switch CLI output. If any pattern is not matched, that switch fails with an explicit audit diagnostic.

---

## 3. Parameterized Variables (`${...}`)

Variables support **uppercase letters, spaces, accents, and punctuation**, plus optional HTML-like **input types**, **regex validation**, and **Python list dropdown options**:

| Syntax | Widget Rendered | Behavior & Validation |
| --- | --- | --- |
| `${Variable}` | Text input (`Entry`) | Defaults to `text`; requires non-empty input |
| `${Variable\|text\|^[A-Za-z0-9_.-]{1,32}$}` | Text input (`Entry`) | Validated via `re.fullmatch()` |
| `${Auth Password\|password\|^.{8,64}$}` | Masked input + **Show** | Explicitly marks value as secret (`is_secret=True`), never saved plaintext |
| `${VLAN ID\|number}` / `${Email\|email}` / `${Endpoint\|url}` / `${Phone\|tel}` | Text input (`Entry`) | HTML-like type validation or custom `\|type\|regex` |
| `${Mode\|["Access", "Core"]}` or `${Mode\|select\|["Access", "Core"]}` | Read-only dropdown (`Combobox`) | Restricts input strictly to the listed items |
| `${Variable\|regex}` *(backwards-compatible)* | Text input (`Entry`) | Defaults to `text` validated with `regex` |

### Bundled ArubaOS-CX Split Snippets
ArubaOS-CX includes dedicated standalone snippets for SNMPv3 (`snmpv3_user.xml`), SNMPv3 Audit (`audit_snmpv3.xml` with `<AuditRegex>`), **NTP (`ntp_config.xml`)**, and **Syslog (`syslog_config.xml`)**, without embedding `configure terminal` inside snippet commands.

### Built-in Host Context Variables
Commands and `<AuditRegex>` rules may reference per-device runtime variables:
* `${device_name}` — Switch hostname
* `${device_ip}` — Switch management IP
* `${host_model}` — Hardware model string
