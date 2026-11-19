"""OpenAPI 3.0.3 specification builder and /api/openapi.json route for aethernms (API Key auth only)."""

from __future__ import annotations

from typing import Any, Dict

from py4web.core import action

from aethernms import __app_name__, __version__
from aethernms.api.common import CtxGetter, check_external_api_access, json_error, json_response


def _json_content(schema: Dict[str, Any]) -> Dict[str, Any]:
    return {"application/json": {"schema": schema}}


def _ref(name: str) -> Dict[str, str]:
    return {"$ref": f"#/components/schemas/{name}"}


def _error_response(desc: str) -> Dict[str, Any]:
    return {"description": desc, "content": _json_content(_ref("ErrorResponse"))}


def build_openapi_spec(server_url: str = "/") -> Dict[str, Any]:
    """Return a complete OpenAPI 3.0.3 dictionary documenting all aethernms REST API endpoints."""
    sec_api_key = [{"ApiKeyHeader": []}, {"BearerAuth": []}]

    return {
        "openapi": "3.0.3",
        "info": {
            "title": f"{__app_name__} REST API",
            "version": __version__,
            "description": (
                "Authenticated REST API for parallel SSH/Telnet Netmiko configuration and audit "
                "automation backed by Py4Web and SQLite. External API and Swagger access is "
                "disabled by default (enable in Administration -> System Settings and configure "
                "the IP/CIDR allowlist). All external API requests must authenticate with an "
                "API Key via `X-API-Key: <token>` or `Authorization: Bearer <token>`."
            ),
        },
        "servers": [{"url": server_url}],
        "security": sec_api_key,
        "tags": [
            {"name": "Auth & API Keys", "description": "Verify API key identity and manage scoped REST API keys"},
            {"name": "Administration", "description": "RBAC user accounts, roles, and permissions management"},
            {"name": "Metadata & i18n", "description": "Application metadata, Netmiko catalog, and UI translations"},
            {"name": "Settings", "description": "Appearance, Execution Defaults, Connection Defaults, and External API controls"},
            {"name": "Devices", "description": "Managed network device inventory, global search, and live ICMP reachability"},
            {"name": "AirWave", "description": "Aruba AirWave inventory discovery, OS-to-Netmiko mapping, and import"},
            {"name": "Snippets", "description": "Reusable CLI Config and Audit snippets (CRUD + XML Import/Export)"},
            {"name": "Variables", "description": "Template variable extraction, regex validation, and preview rendering"},
            {"name": "Jobs", "description": "Job execution lifecycle, stop/delete, and SQLite per-device logs"},
        ],
        "components": {
            "securitySchemes": {
                "ApiKeyHeader": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "X-API-Key",
                    "description": "REST API key generated under Administration -> API Keys.",
                },
                "BearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": "Same REST API key supplied as `Authorization: Bearer <token>`.",
                },
            },
            "schemas": {
                "ErrorResponse": {
                    "type": "object",
                    "properties": {
                        "error": {"type": "string"},
                        "errors": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["error"],
                },
                "AuthStatus": {
                    "type": "object",
                    "properties": {
                        "authenticated": {"type": "boolean"},
                        "auth_method": {"type": "string", "enum": ["api_key", "session"]},
                        "username": {"type": "string"},
                        "display_name": {"type": "string"},
                        "role": {"type": "string"},
                        "permissions": {"type": "array", "items": {"type": "string"}},
                    },
                },
                "ApiKeyRecord": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "user_id": {"type": "integer"},
                        "username": {"type": "string"},
                        "name": {"type": "string"},
                        "role_name": {"type": "string"},
                        "key_prefix": {"type": "string"},
                        "token": {"type": "string", "description": "Returned only once upon creation."},
                        "created_at": {"type": "string"},
                        "last_used_at": {"type": "string"},
                    },
                },
                "UserRecord": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "username": {"type": "string"},
                        "display_name": {"type": "string"},
                        "role": {"type": "string"},
                        "is_active": {"type": "boolean"},
                        "language": {"type": "string", "example": "auto"},
                        "theme_mode": {"type": "string", "enum": ["auto", "light", "dark"]},
                        "permissions": {"type": "array", "items": {"type": "string"}},
                        "created_at": {"type": "string"},
                    },
                },
                "RoleRecord": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "is_system": {"type": "boolean"},
                        "permissions": {"type": "array", "items": {"type": "string"}},
                        "user_count": {"type": "integer"},
                        "created_at": {"type": "string"},
                    },
                },
                "AppSettings": {
                    "type": "object",
                    "properties": {
                        "language": {"type": "string", "example": "auto"},
                        "theme_mode": {"type": "string", "enum": ["auto", "light", "dark"]},
                        "ssh_username": {"type": "string"},
                        "default_protocol": {"type": "string", "enum": ["SSH", "Telnet"]},
                        "ssh_port": {"type": "integer", "minimum": 1, "maximum": 65535},
                        "telnet_port": {"type": "integer", "minimum": 1, "maximum": 65535},
                        "schedule_sequence": {"type": "string", "enum": ["Concurrent", "Sequential"]},
                        "max_parallel": {"type": "integer", "minimum": 1},
                        "command_timeout": {"type": "integer", "minimum": 1},
                        "connect_timeout": {"type": "integer", "minimum": 1},
                        "airwave_url": {"type": "string"},
                        "airwave_username": {"type": "string"},
                        "airwave_verify_ssl": {"type": "boolean"},
                        "airwave_os_mappings": {
                            "type": "object",
                            "additionalProperties": {"type": "string"},
                        },
                        "api_enabled": {"type": "boolean", "default": False},
                        "api_allowed_ips": {"type": "string", "default": "127.0.0.1, ::1"},
                        "db_engine": {"type": "string", "readOnly": True, "example": "sqlite"},
                        "db_uri_masked": {"type": "string", "readOnly": True, "example": "sqlite:///aethernms.db"},
                    },
                },
                "Device": {
                    "type": "object",
                    "required": ["ip", "os_type"],
                    "properties": {
                        "id": {"type": "integer"},
                        "name": {"type": "string", "example": "SW-CORE-01"},
                        "ip": {"type": "string", "example": "10.0.0.10"},
                        "os_type": {"type": "string", "example": "aruba_aoscx"},
                        "os_type_label": {"type": "string", "readOnly": True, "example": "ArubaOS-CX"},
                        "protocol": {"type": "string", "enum": ["SSH", "Telnet"], "default": "SSH"},
                        "port": {"type": "integer", "default": 22},
                        "model": {"type": "string"},
                        "firmware": {"type": "string"},
                        "folder_id": {"type": "string", "nullable": True},
                        "folder_path": {"type": "string", "description": "Device Group / AirWave folder path"},
                        "device_category": {"type": "string"},
                        "serial_number": {"type": "string"},
                        "airwave_status": {"type": "string"},
                        "device_role": {"type": "string"},
                        "airwave_os": {"type": "string"},
                        "enabled": {"type": "boolean", "default": True},
                        "ping_status": {"type": "string", "enum": ["Unknown", "Up", "Down"]},
                        "is_airwave": {"type": "boolean"},
                        "unique_key": {"type": "string"},
                    },
                },
                "Snippet": {
                    "type": "object",
                    "required": ["name", "device_type", "commands"],
                    "properties": {
                        "id": {"type": "integer"},
                        "name": {"type": "string"},
                        "folder": {"type": "string", "example": "aruba/aruba_procurve"},
                        "snippet_type": {"type": "string", "enum": ["Config", "Audit and Remediate"]},
                        "device_type": {"type": "string", "example": "aruba_procurve"},
                        "device_type_label": {"type": "string", "readOnly": True, "example": "ArubaOS-S"},
                        "severity": {"type": "string", "enum": ["Info", "Warning", "Minor", "Major", "Critical"]},
                        "description": {"type": "string"},
                        "commands": {"type": "string"},
                        "audit_regex": {"type": "string"},
                        "created_at": {"type": "string"},
                        "is_builtin": {"type": "boolean", "readOnly": True},
                    },
                },
                "JobCreateRequest": {
                    "type": "object",
                    "required": ["name", "device_type", "commands_raw", "username", "password", "device_ids"],
                    "properties": {
                        "name": {"type": "string", "example": "NTP Rollout"},
                        "description": {"type": "string"},
                        "job_type": {"type": "string", "enum": ["Config", "Audit and Remediate"], "default": "Config"},
                        "device_type": {"type": "string", "example": "aruba_procurve"},
                        "snippet_name": {"type": "string"},
                        "commands_raw": {"type": "string", "example": "ntp server ${NTP Server}\nntp enable"},
                        "audit_regex": {"type": "string"},
                        "values": {
                            "type": "object",
                            "additionalProperties": {"type": "string"},
                            "description": "Template variable values (password-typed variables are never stored).",
                        },
                        "device_ids": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": "List of SQLite device IDs to target.",
                        },
                        "username": {"type": "string"},
                        "password": {"type": "string", "format": "password"},
                        "enable_password": {"type": "string", "format": "password"},
                        "max_parallel": {"type": "integer", "default": 10},
                        "schedule_sequence": {"type": "string", "enum": ["Concurrent", "Sequential"], "default": "Concurrent"},
                        "include_write": {"type": "boolean", "default": False},
                    },
                },
                "JobResult": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "host_key": {"type": "string"},
                        "host_name": {"type": "string"},
                        "host_ip": {"type": "string"},
                        "host_port": {"type": "integer"},
                        "host_os": {"type": "string"},
                        "host_protocol": {"type": "string"},
                        "status": {"type": "string", "enum": ["Pending", "Running", "Success", "Failed"]},
                        "started_at": {"type": "string"},
                        "finished_at": {"type": "string"},
                        "operation_result": {"type": "string"},
                        "operation_result_localized": {"type": "string"},
                        "connection_method": {"type": "string"},
                        "has_log": {"type": "boolean"},
                    },
                },
                "JobRecord": {
                    "type": "object",
                    "properties": {
                        "job_id": {"type": "string"},
                        "name": {"type": "string"},
                        "job_type": {"type": "string"},
                        "device_type": {"type": "string"},
                        "status": {"type": "string", "enum": ["Running", "Success", "Failed"]},
                        "creation_time": {"type": "string"},
                        "start_time": {"type": "string"},
                        "end_time": {"type": "string"},
                        "description": {"type": "string"},
                        "snippet_name": {"type": "string"},
                        "commands_raw": {"type": "string"},
                        "commands_rendered": {"type": "string"},
                        "audit_regex": {"type": "string"},
                        "max_parallel": {"type": "integer"},
                        "schedule_sequence": {"type": "string"},
                        "include_write": {"type": "boolean"},
                        "parameters_masked": {"type": "object", "additionalProperties": {"type": "string"}},
                        "counts": {
                            "type": "object",
                            "properties": {
                                "total": {"type": "integer"},
                                "success": {"type": "integer"},
                                "failed": {"type": "integer"},
                            },
                        },
                        "results": {"type": "array", "items": _ref("JobResult")},
                    },
                },
                "AirWaveFetchRequest": {
                    "type": "object",
                    "required": ["url", "username", "password"],
                    "properties": {
                        "url": {"type": "string", "example": "https://airwave.example.org"},
                        "username": {"type": "string"},
                        "password": {"type": "string", "format": "password"},
                        "verify_ssl": {"type": "boolean", "default": False},
                    },
                },
                "AirWaveImportRequest": {
                    "type": "object",
                    "required": ["devices"],
                    "properties": {
                        "devices": {"type": "array", "items": _ref("Device")},
                        "os_mappings": {
                            "type": "object",
                            "additionalProperties": {"type": "string"},
                            "description": "Optional newly mapped AirWave OS/model -> Netmiko platform associations to persist.",
                        },
                        "airwave_url": {"type": "string"},
                        "airwave_username": {"type": "string"},
                        "airwave_verify_ssl": {"type": "boolean"},
                    },
                },
            },
        },
        "paths": {
            "/api/auth/status": {
                "get": {
                    "tags": ["Auth & API Keys"],
                    "summary": "Verify API Key identity, effective role, and granted permissions",
                    "responses": {
                        "200": {"description": "Authenticated identity", "content": _json_content(_ref("AuthStatus"))},
                        "401": _error_response("API key required or invalid"),
                        "403": _error_response("External API disabled or IP not allowed"),
                    },
                }
            },
            "/api/auth/api-keys": {
                "get": {
                    "tags": ["Auth & API Keys"],
                    "summary": "List API keys (all keys for Admins, own keys otherwise)",
                    "responses": {
                        "200": {
                            "description": "API keys list",
                            "content": _json_content(
                                {"type": "object", "properties": {"items": {"type": "array", "items": _ref("ApiKeyRecord")}}}
                            ),
                        },
                        "401": _error_response("Unauthorized"),
                        "403": _error_response("Forbidden"),
                    },
                },
                "post": {
                    "tags": ["Auth & API Keys"],
                    "summary": "Create a new REST API key (plaintext token returned once)",
                    "requestBody": {
                        "required": True,
                        "content": _json_content(
                            {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string", "example": "CI Pipeline"},
                                    "role_name": {"type": "string", "example": "Operator"},
                                    "user_id": {"type": "integer"},
                                },
                            }
                        ),
                    },
                    "responses": {
                        "201": {"description": "API key created", "content": _json_content(_ref("ApiKeyRecord"))},
                        "401": _error_response("Unauthorized"),
                        "403": _error_response("Forbidden"),
                    },
                },
            },
            "/api/auth/api-keys/{key_id}": {
                "delete": {
                    "tags": ["Auth & API Keys"],
                    "summary": "Revoke an API key by ID",
                    "parameters": [{"name": "key_id", "in": "path", "required": True, "schema": {"type": "integer"}}],
                    "responses": {
                        "200": {"description": "API key revoked"},
                        "404": _error_response("API key not found"),
                    },
                }
            },
            "/api/users": {
                "get": {
                    "tags": ["Administration"],
                    "summary": "List user accounts (requires users:manage)",
                    "responses": {
                        "200": {
                            "description": "Users list",
                            "content": _json_content(
                                {"type": "object", "properties": {"items": {"type": "array", "items": _ref("UserRecord")}}}
                            ),
                        },
                        "403": _error_response("Forbidden"),
                    },
                },
                "post": {
                    "tags": ["Administration"],
                    "summary": "Create a user account (requires users:manage)",
                    "requestBody": {
                        "required": True,
                        "content": _json_content(
                            {
                                "type": "object",
                                "required": ["username", "password", "role"],
                                "properties": {
                                    "username": {"type": "string"},
                                    "display_name": {"type": "string"},
                                    "password": {"type": "string", "format": "password"},
                                    "role": {"type": "string", "example": "Operator"},
                                    "is_active": {"type": "boolean", "default": True},
                                },
                            }
                        ),
                    },
                    "responses": {
                        "201": {"description": "Created user", "content": _json_content(_ref("UserRecord"))},
                        "400": _error_response("Validation error"),
                        "403": _error_response("Forbidden"),
                    },
                },
            },
            "/api/users/{user_id}": {
                "put": {
                    "tags": ["Administration"],
                    "summary": "Update a user's role, display name, status, or password (requires users:manage)",
                    "parameters": [{"name": "user_id", "in": "path", "required": True, "schema": {"type": "integer"}}],
                    "responses": {
                        "200": {"description": "Updated user", "content": _json_content(_ref("UserRecord"))},
                        "400": _error_response("Validation error"),
                        "404": _error_response("User not found"),
                    },
                },
                "delete": {
                    "tags": ["Administration"],
                    "summary": "Delete a user account (requires users:manage)",
                    "parameters": [{"name": "user_id", "in": "path", "required": True, "schema": {"type": "integer"}}],
                    "responses": {
                        "200": {"description": "Deleted"},
                        "400": _error_response("Cannot delete active self or last Admin"),
                        "404": _error_response("User not found"),
                    },
                },
            },
            "/api/roles": {
                "get": {
                    "tags": ["Administration"],
                    "summary": "List RBAC roles and permissions",
                    "responses": {
                        "200": {
                            "description": "Roles list",
                            "content": _json_content(
                                {"type": "object", "properties": {"items": {"type": "array", "items": _ref("RoleRecord")}}}
                            ),
                        },
                    },
                },
                "post": {
                    "tags": ["Administration"],
                    "summary": "Create a custom RBAC role (requires roles:manage)",
                    "requestBody": {
                        "required": True,
                        "content": _json_content(
                            {
                                "type": "object",
                                "required": ["name", "permissions"],
                                "properties": {
                                    "name": {"type": "string", "example": "Auditor"},
                                    "description": {"type": "string"},
                                    "permissions": {"type": "array", "items": {"type": "string"}},
                                },
                            }
                        ),
                    },
                    "responses": {
                        "201": {"description": "Created role", "content": _json_content(_ref("RoleRecord"))},
                        "400": _error_response("Validation error"),
                    },
                },
            },
            "/api/roles/{role_id}": {
                "put": {
                    "tags": ["Administration"],
                    "summary": "Update an RBAC role (requires roles:manage; Admin is immutable)",
                    "parameters": [{"name": "role_id", "in": "path", "required": True, "schema": {"type": "integer"}}],
                    "responses": {
                        "200": {"description": "Updated role", "content": _json_content(_ref("RoleRecord"))},
                        "400": _error_response("Validation error"),
                        "404": _error_response("Role not found"),
                    },
                },
                "delete": {
                    "tags": ["Administration"],
                    "summary": "Delete a custom RBAC role (requires roles:manage)",
                    "parameters": [{"name": "role_id", "in": "path", "required": True, "schema": {"type": "integer"}}],
                    "responses": {
                        "200": {"description": "Deleted"},
                        "400": _error_response("System role or role still assigned"),
                        "404": _error_response("Role not found"),
                    },
                },
            },
            "/api/meta": {
                "get": {
                    "tags": ["Metadata & i18n"],
                    "summary": "Get application metadata and native Netmiko platform/protocol catalog",
                    "responses": {"200": {"description": "Metadata and Netmiko platform registry"}},
                }
            },
            "/api/i18n": {
                "get": {
                    "tags": ["Metadata & i18n"],
                    "summary": "Get translated UI strings and available locales",
                    "parameters": [{"name": "lang", "in": "query", "required": False, "schema": {"type": "string"}}],
                    "responses": {"200": {"description": "Locale dictionary and language options"}},
                }
            },
            "/api/settings": {
                "get": {
                    "tags": ["Settings"],
                    "summary": "Retrieve global settings",
                    "responses": {"200": {"description": "Settings object", "content": _json_content(_ref("AppSettings"))}},
                },
                "put": {
                    "tags": ["Settings"],
                    "summary": "Update global settings (requires system:settings)",
                    "requestBody": {"required": True, "content": _json_content(_ref("AppSettings"))},
                    "responses": {
                        "200": {"description": "Updated settings", "content": _json_content(_ref("AppSettings"))},
                        "400": _error_response("Invalid settings payload"),
                        "403": _error_response("Forbidden"),
                    },
                },
            },
            "/api/devices": {
                "get": {
                    "tags": ["Devices"],
                    "summary": "List registered network devices (with optional filters)",
                    "parameters": [
                        {"name": "name", "in": "query", "schema": {"type": "string"}},
                        {"name": "ip", "in": "query", "schema": {"type": "string"}},
                        {"name": "os", "in": "query", "schema": {"type": "string"}},
                        {"name": "group", "in": "query", "schema": {"type": "string"}},
                        {"name": "status", "in": "query", "schema": {"type": "string"}},
                    ],
                    "responses": {
                        "200": {
                            "description": "Device inventory list",
                            "content": _json_content(
                                {"type": "object", "properties": {"items": {"type": "array", "items": _ref("Device")}}}
                            ),
                        }
                    },
                },
                "post": {
                    "tags": ["Devices"],
                    "summary": "Add (or replace by ip:port) a manual network device",
                    "requestBody": {"required": True, "content": _json_content(_ref("Device"))},
                    "responses": {
                        "201": {"description": "Device created", "content": _json_content(_ref("Device"))},
                        "400": _error_response("Unsupported Netmiko platform or protocol"),
                    },
                },
            },
            "/api/devices/search": {
                "get": {
                    "tags": ["Devices"],
                    "summary": "Global search across devices by name, IP, model, group, platform, or serial",
                    "parameters": [
                        {"name": "q", "in": "query", "required": False, "schema": {"type": "string"}},
                        {"name": "limit", "in": "query", "required": False, "schema": {"type": "integer", "default": 10}},
                    ],
                    "responses": {
                        "200": {
                            "description": "Matching devices",
                            "content": _json_content(
                                {"type": "object", "properties": {"items": {"type": "array", "items": _ref("Device")}}}
                            ),
                        }
                    },
                }
            },
            "/api/devices/{device_id}": {
                "put": {
                    "tags": ["Devices"],
                    "summary": "Update a device (AirWave devices keep Name/IP/Model/Group read-only)",
                    "parameters": [{"name": "device_id", "in": "path", "required": True, "schema": {"type": "integer"}}],
                    "requestBody": {"required": True, "content": _json_content(_ref("Device"))},
                    "responses": {
                        "200": {"description": "Device updated", "content": _json_content(_ref("Device"))},
                        "400": _error_response("Validation error"),
                        "404": _error_response("Device not found"),
                    },
                },
                "delete": {
                    "tags": ["Devices"],
                    "summary": "Delete a device from inventory",
                    "parameters": [{"name": "device_id", "in": "path", "required": True, "schema": {"type": "integer"}}],
                    "responses": {
                        "200": {"description": "Device deleted"},
                        "404": _error_response("Device not found"),
                    },
                },
            },
            "/api/devices/ping": {
                "post": {
                    "tags": ["Devices"],
                    "summary": "Run concurrent ICMP ping checks for specified device IDs (or all devices)",
                    "requestBody": {
                        "required": False,
                        "content": _json_content(
                            {
                                "type": "object",
                                "properties": {
                                    "device_ids": {"type": "array", "items": {"type": "integer"}},
                                },
                            }
                        ),
                    },
                    "responses": {"200": {"description": "Map of unique_key/device_id to Up|Down"}},
                }
            },
            "/api/airwave/fetch": {
                "post": {
                    "tags": ["AirWave"],
                    "summary": "Fetch live switch inventory from Aruba AirWave and auto-map OS Type to Netmiko",
                    "requestBody": {"required": True, "content": _json_content(_ref("AirWaveFetchRequest"))},
                    "responses": {
                        "200": {"description": "Fetched folders, preview devices, and unmapped groups"},
                        "400": _error_response("AirWave fetch or credential error"),
                    },
                }
            },
            "/api/airwave/import": {
                "post": {
                    "tags": ["AirWave"],
                    "summary": "Import selected AirWave devices and persist any manual OS-to-Netmiko mappings",
                    "requestBody": {"required": True, "content": _json_content(_ref("AirWaveImportRequest"))},
                    "responses": {
                        "200": {"description": "Devices imported"},
                        "400": _error_response("Validation error (unmapped devices)"),
                    },
                }
            },
            "/api/snippets": {
                "get": {
                    "tags": ["Snippets"],
                    "summary": "List command and audit snippets stored in SQLite",
                    "responses": {
                        "200": {
                            "description": "Snippets list",
                            "content": _json_content(
                                {"type": "object", "properties": {"items": {"type": "array", "items": _ref("Snippet")}}}
                            ),
                        }
                    },
                },
                "post": {
                    "tags": ["Snippets"],
                    "summary": "Create a new command or audit snippet",
                    "requestBody": {"required": True, "content": _json_content(_ref("Snippet"))},
                    "responses": {
                        "201": {"description": "Snippet created", "content": _json_content(_ref("Snippet"))},
                        "400": _error_response("Validation error"),
                    },
                },
            },
            "/api/snippets/{snippet_id}": {
                "put": {
                    "tags": ["Snippets"],
                    "summary": "Update a custom snippet (built-in snippets are read-only -> 403)",
                    "parameters": [{"name": "snippet_id", "in": "path", "required": True, "schema": {"type": "integer"}}],
                    "requestBody": {"required": True, "content": _json_content(_ref("Snippet"))},
                    "responses": {
                        "200": {"description": "Snippet updated", "content": _json_content(_ref("Snippet"))},
                        "403": _error_response("Built-in snippets are read-only"),
                        "404": _error_response("Snippet not found"),
                    },
                },
                "delete": {
                    "tags": ["Snippets"],
                    "summary": "Delete a custom snippet (built-in snippets are read-only -> 403)",
                    "parameters": [{"name": "snippet_id", "in": "path", "required": True, "schema": {"type": "integer"}}],
                    "responses": {
                        "200": {"description": "Snippet deleted"},
                        "403": _error_response("Built-in snippets are read-only"),
                        "404": _error_response("Snippet not found"),
                    },
                },
            },
            "/api/snippets/import": {
                "post": {
                    "tags": ["Snippets"],
                    "summary": "Import a snippet from XML (JSON {xml, filename} or raw XML body)",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["xml"],
                                    "properties": {
                                        "xml": {"type": "string"},
                                        "filename": {"type": "string"},
                                    },
                                }
                            },
                            "application/xml": {"schema": {"type": "string"}},
                        },
                    },
                    "responses": {
                        "201": {"description": "Snippet imported", "content": _json_content(_ref("Snippet"))},
                        "400": _error_response("Invalid Snippet XML"),
                    },
                }
            },
            "/api/snippets/{snippet_id}/export": {
                "get": {
                    "tags": ["Snippets"],
                    "summary": "Export a snippet as a formatted .xml attachment",
                    "parameters": [{"name": "snippet_id", "in": "path", "required": True, "schema": {"type": "integer"}}],
                    "responses": {
                        "200": {"description": "XML snippet file", "content": {"application/xml": {"schema": {"type": "string"}}}},
                        "404": _error_response("Snippet not found"),
                    },
                }
            },
            "/api/variables/parse": {
                "post": {
                    "tags": ["Variables"],
                    "summary": "Extract ${...} variables, validate values, and preview rendered CLI commands",
                    "requestBody": {
                        "required": True,
                        "content": _json_content(
                            {
                                "type": "object",
                                "properties": {
                                    "commands": {"type": "string"},
                                    "audit_regex": {"type": "string"},
                                    "values": {"type": "object", "additionalProperties": {"type": "string"}},
                                },
                            }
                        ),
                    },
                    "responses": {"200": {"description": "Variable specs, saved non-secret defaults, errors, and rendered preview"}},
                }
            },
            "/api/jobs": {
                "get": {
                    "tags": ["Jobs"],
                    "summary": "List jobs ordered newest first",
                    "responses": {
                        "200": {
                            "description": "Jobs list",
                            "content": _json_content(
                                {"type": "object", "properties": {"items": {"type": "array", "items": _ref("JobRecord")}}}
                            ),
                        }
                    },
                },
                "post": {
                    "tags": ["Jobs"],
                    "summary": "Create and launch a new Netmiko Config or Audit job",
                    "requestBody": {"required": True, "content": _json_content(_ref("JobCreateRequest"))},
                    "responses": {
                        "201": {"description": "Job launched", "content": _json_content(_ref("JobRecord"))},
                        "400": _error_response("Validation errors"),
                    },
                },
            },
            "/api/jobs/{job_uid}": {
                "get": {
                    "tags": ["Jobs"],
                    "summary": "Get full job status, rendered commands, and per-device results",
                    "parameters": [{"name": "job_uid", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {
                        "200": {"description": "Job details", "content": _json_content(_ref("JobRecord"))},
                        "404": _error_response("Job not found"),
                    },
                },
                "delete": {
                    "tags": ["Jobs"],
                    "summary": "Delete a finished job and its logs from SQLite",
                    "parameters": [{"name": "job_uid", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {
                        "200": {"description": "Job deleted"},
                        "400": _error_response("Job is currently running"),
                        "404": _error_response("Job not found"),
                    },
                },
            },
            "/api/jobs/{job_uid}/stop": {
                "post": {
                    "tags": ["Jobs"],
                    "summary": "Request cancellation of a running job",
                    "parameters": [{"name": "job_uid", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {
                        "200": {"description": "Stop signal sent"},
                        "404": _error_response("Job not found"),
                    },
                }
            },
            "/api/jobs/{job_uid}/results/{result_id}/log": {
                "get": {
                    "tags": ["Jobs"],
                    "summary": "Read or download per-device execution log from SQLite",
                    "parameters": [
                        {"name": "job_uid", "in": "path", "required": True, "schema": {"type": "string"}},
                        {"name": "result_id", "in": "path", "required": True, "schema": {"type": "integer"}},
                        {"name": "download", "in": "query", "required": False, "schema": {"type": "boolean"}},
                    ],
                    "responses": {
                        "200": {"description": "Structured JSON log details or plain-text .log download"},
                        "404": _error_response("Job result not found"),
                    },
                }
            },
        },
    }


def register_openapi_routes(get_ctx: CtxGetter) -> None:
    """Register GET /api/openapi.json route (gated by External API toggle + IP allowlist)."""

    @action("/api/openapi.json", method="GET")
    def api_openapi_spec():
        ctx = get_ctx()
        if ctx.db is None:
            return json_error(
                503,
                "Initial setup is required. Complete setup at /setup first.",
                extra={"setup_required": True},
            )
        ext_err = check_external_api_access(ctx)
        if ext_err:
            return json_error(403, ext_err)
        return json_response(build_openapi_spec(server_url="/"))
