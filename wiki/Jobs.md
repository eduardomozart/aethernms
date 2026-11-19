# Jobs (`/jobs`)

The **Jobs** page lets you launch, monitor, inspect, stop, and delete parallel SSH/Telnet automation runs across your managed devices.

## 1. Filtering & Viewing Jobs

* Use the **Carbon DataTable Toolbar** above the jobs table to search by job name, platform, or creator.
* Click **Filter** to open the filter popover and narrow by **Type** (`Config` or `Audit`), **Netmiko Platform** (friendly labels such as `ArubaOS-S` and `ArubaOS-CX`), or **Status**. Active filters appear as removable filter tags.
* Click any job row to populate the **Job Details** split panel below with:
  * **Details** tab: total/succeeded/failed device counts, description, executed CLI commands, and Audit RegEx patterns.
  * **Devices** tab: per-device execution result and status; click **View Log** to inspect or download the formatted `.log` wire transcript stored in the database.

## 2. Launching a New Job (`Add Job`)

1. Click **Add Job** (`jobs:run` permission required).
2. **Command Setup**: Choose a Config or Audit task, load commands from an existing snippet (optional) or author custom CLI lines, select the target **Netmiko Platform**, and optionally enter **Audit Validation RegEx** patterns.
3. **Parameters** *(when `${...}` variables are present)*: Fill in each extracted variable; password variables (`${...|password}`) include a Show/Hide toggle and are scrubbed before persistence or logging.
4. **Target Devices & Confirm**: Select matching devices for the chosen platform, review execution concurrency/protocol settings (`Save configuration`, sequential/concurrent execution, max parallel threads), and launch the job.
5. Watch live status and progress updates directly in the Jobs table, or click **Stop** to cancel an in-flight job cleanly.
