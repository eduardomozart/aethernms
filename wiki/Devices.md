# Devices (`/devices`)

The **Devices** page manages your switch and router inventory, ICMP reachability state, Netmiko driver assignment, and AirWave synchronization.

## 1. Filtering, Global Search & Ping

* **Global Device Search** (top dark header): Searches device Name, IP, Model, Group, Platform, and Serial Number across the app and opens matching inventory via `/devices?q=...` (dismissible banner shown when active).
* **Carbon DataTable Toolbar**: Filter inline by keyword or open **Filter** to narrow by **Netmiko Platform**, **Group**, or **Status** (`Up` / `Down` / `Unknown`).
* **Ping Devices**: Runs concurrent ICMP reachability checks against filtered or selected devices and saves updated `"Up"` / `"Down"` statuses.

## 2. Adding & Editing Devices

* Click **Add Device** (`devices:write` permission) to register a switch manually, selecting its friendly **Netmiko Platform** (for example, `ArubaOS-S`, `ArubaOS-CX`, `Cisco IOS`) and transport protocol (**SSH**, **Telnet**, or **Disabled**).
* Device SSH/Telnet passwords and enable passwords are **never** stored in the database; credentials are supplied securely at job runtime or omitted for manual prompt workflows.

## 3. Importing from HPE Aruba AirWave (`Import AirWave`)

* Requires the `airwave:import` permission and configured AirWave server URL/username under **Administration → System Settings**.
* The modal table starts empty until you enter AirWave credentials and click **Fetch Inventory**.
* AirWave operating system strings are mapped automatically to Netmiko drivers (`AOS-S` → `aruba_procurve`, `AOS-CX` → `aruba_aoscx`). If any model cannot be mapped automatically, the **Unmapped Models** dialog prompts you to pick the right friendly Netmiko platform before saving.
* AirWave-managed devices lock **Device Name**, **IP Address**, **Model**, and **Group** as read-only while keeping **Netmiko Platform**, **Protocol**, and **Port** editable.
