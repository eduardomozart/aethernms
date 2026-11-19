# Administration: Roles (`/administration/roles`)

The **Roles** page (`roles:manage` permission required) defines fine-grained Role-Based Access Control (RBAC) permission bundles assigned to users and scoped API keys.

## 1. Built-In System Roles (Read-Only)

`aethernms` seeds three immutable built-in roles on initial setup (marked with the **System** badge):

* **Admin** — Full administrative access to automation, system settings, users, roles, and API keys.
* **Operator** — Can run jobs, manage snippets and devices, import from AirWave, and manage own API keys.
* **Viewer** — Read-only access to jobs, execution logs, snippets, and device inventory.

Built-in system role descriptions automatically translate into your selected language, and system roles cannot be modified or deleted. Clicking **View** opens their permission list in read-only mode.

## 2. Creating & Managing Custom Roles

* Click **Add Role** to create custom roles tailored to regional NOC teams or external automation integrations.
* Filter between **All**, **System**, and **Custom** roles using the **Filter** popover in the DataTable toolbar.
* Custom roles actively assigned to users cannot be deleted until those users are reassigned to another role.
