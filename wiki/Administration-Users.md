# Administration: Users (`/administration/users`)

The **Users** page manages user accounts, RBAC role assignments, active status, and **per-user appearance preferences** (Language & Theme).

## 1. Editing Your Own Profile (`?edit=me`)

* Click your **username** in the top-right header at any time to navigate directly to **`/administration/users?edit=me`** with your profile editor opened automatically.
* Any authenticated user — including `Operator` and `Viewer` accounts without `users:manage` — can open `?edit=me` to update:
  * **Display Name**
  * **Language** (`Auto (OS Default)` or any installed language catalog such as `English` / `Português (Brasil)`)
  * **Theme** (`Auto (OS Default)`, `Light`, or `Dark`)
  * **Password** *(requires entering **Current Password** when modifying your own password)*
* Users without `users:manage` only see their own account in `?edit=me` and cannot change their assigned **Role** or **Active** status.

## 2. Managing All Users (`users:manage` permission)

* Administrators with `users:manage` can browse, search, filter by **Role** or **Status** via the Carbon DataTable Toolbar, create accounts with **Add User**, edit existing users, deactivate accounts, or delete unused accounts.
* Usernames are matched case-insensitively across login and creation (`admin` and `Admin` refer to the same identity).
