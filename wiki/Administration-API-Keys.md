# Administration: API Keys (`/administration/api-keys`)

The **API Keys** page lets authorized users generate and revoke token credentials (`aethernms_...`) for programmatic REST API automation and interactive **Swagger UI** testing.

## 1. Prerequisites

* By default, **External REST API & Swagger UI** is disabled (`api_enabled = False`).
* When disabled, a warning banner provides a quick **Go to System Settings** link so Administrators can enable external API access and configure **Allowed IP Addresses / CIDRs**.

## 2. Generating & Using Tokens

1. Enter a descriptive **API Key Name** (for example, `Ansible NetOps` or `CI Pipeline`).
2. Users with `users:manage` may optionally assign a different **Owner** or constrain the token's **Role Scope**.
3. Click **Generate Key** (`api_keys:manage` permission required).
4. **Copy the secret token immediately** from the confirmation banner — only the SHA-256 hash and token prefix are saved on the server, so the full token cannot be revealed again later.
5. Pass the token in `X-API-Key: aethernms_...` or `Authorization: Bearer aethernms_...` headers, or revoke compromised keys at any time from the DataTable.
