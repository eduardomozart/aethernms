"""Authentication, RBAC permissions, API keys, strong session secrets, and IP/CIDR allowlist helpers."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import os
from pathlib import Path
import re
import secrets
import string
from typing import Dict, List, Optional, Tuple


_PBKDF2_ITERATIONS = 200_000
_SECRET_ALPHABET = string.ascii_uppercase + string.ascii_lowercase + string.digits + "!@#%^&*()-_=+"

DEFAULT_API_ALLOWED_IPS = "127.0.0.1, ::1"

ALL_PERMISSIONS: Tuple[Dict[str, str], ...] = (
    {"key": "jobs:read", "group": "Jobs", "label": "View Jobs & Logs"},
    {"key": "jobs:run", "group": "Jobs", "label": "Create, Run & Stop Jobs"},
    {"key": "jobs:delete", "group": "Jobs", "label": "Delete Jobs"},
    {"key": "snippets:read", "group": "Snippets", "label": "View & Export Snippets"},
    {"key": "snippets:write", "group": "Snippets", "label": "Create, Edit, Import & Delete Snippets"},
    {"key": "devices:read", "group": "Devices", "label": "View & Ping Devices"},
    {"key": "devices:write", "group": "Devices", "label": "Create, Edit & Delete Devices"},
    {"key": "airwave:import", "group": "Devices", "label": "Fetch & Import AirWave Devices"},
    {"key": "system:settings", "group": "Administration", "label": "Manage System Settings & External API"},
    {"key": "users:manage", "group": "Administration", "label": "Manage Users"},
    {"key": "roles:manage", "group": "Administration", "label": "Manage Roles"},
    {"key": "api_keys:manage", "group": "Administration", "label": "Manage API Keys"},
)

ALL_PERMISSION_KEYS: Tuple[str, ...] = tuple(item["key"] for item in ALL_PERMISSIONS)

DEFAULT_ROLES: Tuple[Dict[str, object], ...] = (
    {
        "name": "Admin",
        "description": "Full administrative access to automation, system settings, users, roles, and API keys.",
        "is_system": True,
        "permissions": list(ALL_PERMISSION_KEYS),
    },
    {
        "name": "Operator",
        "description": "Can run jobs, manage snippets and devices, import from AirWave, and manage own API keys.",
        "is_system": True,
        "permissions": [
            "jobs:read",
            "jobs:run",
            "jobs:delete",
            "snippets:read",
            "snippets:write",
            "devices:read",
            "devices:write",
            "airwave:import",
            "api_keys:manage",
        ],
    },
    {
        "name": "Viewer",
        "description": "Read-only access to jobs, execution logs, snippets, and device inventory.",
        "is_system": True,
        "permissions": [
            "jobs:read",
            "snippets:read",
            "devices:read",
        ],
    },
)


def canonical_role_name(raw_role: Optional[str]) -> str:
    """Normalize legacy lowercase system role names (e.g. 'admin' -> 'Admin')."""
    text = (raw_role or "").strip()
    if not text:
        return "Viewer"
    lowered = text.lower()
    for role in DEFAULT_ROLES:
        rname = str(role["name"])
        if rname.lower() == lowered:
            return rname
    return text


def hash_password(password: str) -> str:
    """Hash a plaintext password using PBKDF2-HMAC-SHA256 with a random 16-byte salt."""
    if not password:
        raise ValueError("Password cannot be empty.")
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a plaintext password against a PBKDF2-HMAC-SHA256 hash in constant time."""
    if not password or not stored_hash:
        return False
    parts = stored_hash.split("$")
    if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
        return False
    try:
        iterations = int(parts[1])
        salt = bytes.fromhex(parts[2])
        expected = bytes.fromhex(parts[3])
    except ValueError:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def hash_api_key(raw_token: str) -> str:
    """Compute SHA-256 digest of a plaintext REST API key for storage/lookup."""
    return hashlib.sha256((raw_token or "").encode("utf-8")).hexdigest()


def generate_api_key() -> Tuple[str, str, str]:
    """Generate a new REST API key and return (plaintext_token, display_prefix, sha256_hash)."""
    raw = f"aethernms_{secrets.token_urlsafe(32)}"
    prefix = raw[:14]
    return raw, prefix, hash_api_key(raw)


def generate_strong_secret(length: int = 64) -> str:
    """Generate a high-entropy secret guaranteed to satisfy Py4Web IS_STRONG(entropy=50)."""
    chars = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice("!@#%^&*()-_=+"),
    ]
    chars.extend(secrets.choice(_SECRET_ALPHABET) for _ in range(max(48, length) - len(chars)))
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def ensure_session_secret(storage_dir: Path) -> str:
    """Load or generate a persistent high-entropy Py4Web session secret in storage_dir."""
    env_secret = os.environ.get("AETHERNMS_SESSION_SECRET", "").strip()
    if len(env_secret) >= 32:
        return env_secret

    storage_dir.mkdir(parents=True, exist_ok=True)
    secret_file = storage_dir / ".session_secret"
    if secret_file.is_file():
        existing = secret_file.read_text(encoding="utf-8").strip()
        if len(existing) >= 32:
            return existing

    secret = generate_strong_secret(64)
    secret_file.write_text(secret + "\n", encoding="utf-8")
    try:
        os.chmod(secret_file, 0o600)
    except OSError:
        pass
    return secret


def _normalize_ip_address(raw_ip: str):
    """Parse an IP string and unwrap IPv4-mapped IPv6 addresses (e.g. ::ffff:127.0.0.1 -> 127.0.0.1)."""
    text = (raw_ip or "").strip()
    if not text:
        return None
    # Strip IPv6 zone index (e.g. fe80::1%eth0) or bracketed host
    if text.startswith("[") and "]" in text:
        text = text[1:text.index("]")]
    if "%" in text:
        text = text.split("%", 1)[0]
    try:
        addr = ipaddress.ip_address(text)
    except ValueError:
        return None
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        return addr.ipv4_mapped
    return addr


def parse_ip_allowlist(raw: str) -> Tuple[List[str], Optional[str]]:
    """
    Validate and normalize a comma/semicolon/newline-separated IP or CIDR allowlist.
    Returns (normalized_entries, error_message_or_None).
    """
    tokens = [tok.strip() for tok in re.split(r"[,;\r\n]+", raw or "") if tok.strip()]
    if not tokens:
        return [], "At least one allowed IP address or CIDR range is required."

    normalized: List[str] = []
    seen = set()
    for tok in tokens:
        if tok == "*":
            if "*" not in seen:
                normalized.append("*")
                seen.add("*")
            continue
        if "/" in tok:
            try:
                net = ipaddress.ip_network(tok, strict=False)
            except ValueError:
                return [], f"Invalid CIDR range: '{tok}'."
            norm = str(net)
        else:
            addr = _normalize_ip_address(tok)
            if addr is None:
                return [], f"Invalid IP address: '{tok}'."
            norm = str(addr)
        if norm not in seen:
            normalized.append(norm)
            seen.add(norm)
    return normalized, None


def is_ip_allowed(client_ip: str, raw_allowlist: str) -> bool:
    """Return True when client_ip matches any IP, CIDR range, or '*' entry in raw_allowlist."""
    entries, err = parse_ip_allowlist(raw_allowlist or DEFAULT_API_ALLOWED_IPS)
    if err or not entries:
        return False
    if "*" in entries:
        return True
    addr = _normalize_ip_address(client_ip)
    if addr is None:
        return False

    for item in entries:
        if "/" in item:
            try:
                net = ipaddress.ip_network(item, strict=False)
            except ValueError:
                continue
            if addr.version == net.version and addr in net:
                return True
        else:
            allowed_addr = _normalize_ip_address(item)
            if allowed_addr is not None and addr == allowed_addr:
                return True
    return False
