# Changelog

All notable changes to **pssh-ui** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Live page-scoped ICMP reachability probing (`PingMonitor`) with on-the-fly **Status** filtering in the **Devices** tab and Step 3 (**Select Device**) of **Add Job**, plus **OK/Cancel** confirmation listing unreachable selected device names and IPs.
- Job **Replay (`↻`)** row action in the **Jobs** tab to reopen **Add Job** pre-filled with commands, target devices, non-secret parameters, write option (`include_write` persisted in `session.xml`), and execution settings.
- Table pagination (`TablePaginator`) and auto-hiding scrollbars across tables and text editors.
- Upgrade-safe template library seeding using SHA-256 tracking for bundled snippets and device models, along with **Import/Export Device Model** actions and **Audit Validation RegEx** (`Audit and Remediate`) support.
- Separate built-in `ArubaOS-S NTP` (`snippets/aruba/aoss/ntp_config.xml`) and `ArubaOS-S Syslog` (`snippets/aruba/aoss/syslog_config.xml`) snippet templates.
- In-repo `wiki/` documentation pages and `.github/workflows/wiki.yml` automation to publish documentation updates to the GitHub Wiki.
- Transifex Git integration, automated `.pot` extraction workflow (`.github/workflows/updatepot.yml`), and expanded Brazilian Portuguese (`pt_BR`) translations including 3-form `Plural-Forms` handling via `gettext.c2py`.

### Changed
- Refactored the monolithic GUI into modular `pssh_ui/app.py`, `pssh_ui/tabs/`, `pssh_ui/dialogs/`, and `pssh_ui/common.py` components.
- Renamed `ArubaSSHClient` to `PSSHClient` (`pssh_ui/ssh_runner.py`).
- Filtered **Add Job** snippets by **Job Type**, automatically skipped the **Parameters** step when no template variables exist, and ensured new non-replay jobs start with empty parameter fields instead of reusing previous session values.
- Updated Step 4 (**Confirm**) of **Add Job** to preview only rendered template commands without model wrappers (`no page`, `configure terminal`, `end`), display the selected model's write command in `Run write command ({cmd})` (hiding the checkbox when none is defined) without adding it to the read-only preview, and rename sequential execution to `Sequential (1 device at a time)`.
- Executed paging suppression (`DisablePagingCommand`, e.g., `no page`) as a tracked SSH step that aborts on failure while counting only rendered template commands in the UI `Completed (N commands)` summary.
- Kept parser, SSH runner, and per-device `.log` output in canonical English (`--- Raw SSH Terminal Output ---` without per-command execution summaries) while translating status messages and error reasons in the UI (`format_operation_result_ui`).
- Unified AirWave import filters (`All` defaults, hierarchical folder selection, persistent multi-page row selection) with **Devices** filtering and separated AirWave inventory status from live reachability (`ping_status`).
- Simplified **Devices**, **Add Job**, and **AirWave Import** tables to show localized status text (`Up` / `Down` / `Unknown`) without overlay status orb icons.
- Ordered **Select Device** in **Add Job** so supported devices (matching the selected target OS) appear before unsupported devices.

### Fixed
- Anchored `UsernamePromptRegex` and `PasswordPromptRegex` and restricted credential prompt detection to incomplete lines ending in `:`, ignoring `Last login:` banners so usernames are not typed at active CLI prompts.
- Aborted remaining commands on first failed step (`Skipped`), stripped trailing idle CLI prompts from raw SSH transcripts, and ensured SSH channels always close on exit.
- Synchronized Step 2 (**Parameters**) entry values into `param_values` before Step 4 preview rendering and **Run Job** validation so pre-filled or untouched fields substitute cleanly and validate at Step 2.
- Fixed plural-form lookup in `.po` catalogs, cleaned up obsolete translation entries, and updated PyInstaller release build metadata injection.

## [1.0.0] - 2026-11-17

### Added
- Initial release of **pssh-ui** (`tkinter`/`ttk` + `Sun-Valley-ttk-theme` + `paramiko`) for parallel SSH configuration and audit automation across managed switches.
- 4-tab workspace (**Jobs**, **Snippets**, **Devices**, **Device Models**) with Light/Dark OS auto-detection, language auto-detection, **Add Job** wizard, and Aruba **AirWave** XML import.
- Parameterized XML snippet system (`${var|type|regex}` and `${var|["Item 1", "Item 2"]}`), drop-in `DeviceModel` XML profiles (`ArubaOS-CX`, `ArubaOS-S`), per-switch timestamped logs without plaintext credential persistence, and `gettext`/Babel localization.

[Unreleased]: https://github.com/eduardomozart/pssh-ui/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/eduardomozart/pssh-ui/releases/tag/v1.0.0
