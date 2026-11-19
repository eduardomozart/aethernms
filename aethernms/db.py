"""SQLite persistence via PyDAL for users, API keys, settings, snippets, devices, jobs, and logs."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import threading
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple
import xml.etree.ElementTree as ET

from pydal import DAL, Field

from aethernms.auth import (
    ALL_PERMISSION_KEYS,
    DEFAULT_API_ALLOWED_IPS,
    DEFAULT_ROLES,
    canonical_role_name,
    generate_api_key,
    hash_api_key,
    hash_password,
    verify_password,
)
from aethernms.logger import format_host_log
from aethernms.models import (
    AirWaveFilter,
    AppSettings,
    CommandStepResult,
    ConnectionProtocol,
    HostEntry,
    HostExecutionResult,
    JobRecord,
    ScheduleSequence,
    Snippet,
    SnippetSeverity,
    SnippetType,
    is_airwave_host,
)
from aethernms.netmiko_catalog import (
    canonical_platform,
    default_protocol_for_platform,
    normalize_legacy_platform,
)
from aethernms.paths import bundled_snippets_dir, get_db_path
from aethernms.snippet_store import SnippetStore, normalize_folder_path, snippet_from_xml_file
from aethernms.variables import extract_variables


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _enum_by_value(enum_cls, raw: Optional[str], default):
    val = (raw or "").strip().lower()
    for member in enum_cls:
        if member.value.lower() == val:
            return member
    return default


def _parse_bool(raw: Optional[str], default: bool = False) -> bool:
    if raw is None:
        return default
    return str(raw).strip().lower() in ("true", "1", "yes", "on")


def _parse_int(raw: Any, default: int) -> int:
    try:
        return int(float(str(raw).strip())) if raw is not None else default
    except (ValueError, TypeError):
        return default


def _json_loads_safe(raw: Optional[str], default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return default


def _normalized_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _parse_host_platform_and_protocol(
    raw_os: Optional[str],
    raw_protocol: Optional[str],
) -> Tuple[str, ConnectionProtocol]:
    platform, inferred_proto = normalize_legacy_platform(raw_os)
    proto = _enum_by_value(
        ConnectionProtocol,
        raw_protocol,
        inferred_proto or ConnectionProtocol.SSH,
    )
    if platform:
        proto = default_protocol_for_platform(platform, proto)
    return platform, proto


def _define_tables(db: DAL) -> None:
    """Define all aethernms SQLite tables on the given PyDAL instance."""
    db.define_table(
        "auth_role",
        Field("name", "string", length=128, unique=True, notnull=True),
        Field("description", "text", default=""),
        Field("is_system", "boolean", default=False),
        Field("permissions_json", "text", default="[]"),
        Field("created_at", "string", length=32, default=_now_iso),
    )

    db.define_table(
        "auth_user",
        Field("username", "string", length=128, unique=True, notnull=True),
        Field("display_name", "string", length=256, default=""),
        Field("password_hash", "string", length=256, notnull=True),
        Field("role", "string", length=128, default="Admin"),
        Field("is_active", "boolean", default=True),
        Field("created_at", "string", length=32, default=_now_iso),
    )

    db.define_table(
        "api_key",
        Field("user_id", "reference auth_user", ondelete="CASCADE", notnull=True),
        Field("name", "string", length=128, notnull=True),
        Field("role_name", "string", length=128, default=""),
        Field("key_prefix", "string", length=32, notnull=True),
        Field("key_hash", "string", length=128, unique=True, notnull=True),
        Field("created_at", "string", length=32, default=_now_iso),
        Field("last_used_at", "string", length=32, default=""),
    )

    db.define_table(
        "app_settings",
        Field("singleton_key", "string", length=32, unique=True, default="global"),
        Field("language", "string", length=32, default="auto"),
        Field("theme_mode", "string", length=16, default="auto"),
        Field("ssh_username", "string", length=128, default=""),
        Field("default_protocol", "string", length=16, default="SSH"),
        Field("ssh_port", "integer", default=22),
        Field("telnet_port", "integer", default=23),
        Field("schedule_sequence", "string", length=32, default="Concurrent"),
        Field("max_parallel", "integer", default=10),
        Field("command_timeout", "integer", default=15),
        Field("connect_timeout", "integer", default=10),
        Field("airwave_url", "string", length=256, default=""),
        Field("airwave_username", "string", length=128, default=""),
        Field("airwave_verify_ssl", "boolean", default=False),
        Field("airwave_filters_json", "text", default="{}"),
        Field("airwave_os_mappings_json", "text", default="{}"),
        Field("api_enabled", "boolean", default=False),
        Field("api_allowed_ips", "text", default=DEFAULT_API_ALLOWED_IPS),
    )

    db.define_table(
        "snippet",
        Field("name", "string", length=256, notnull=True),
        Field("folder", "string", length=256, default="aruba/aruba_procurve"),
        Field("snippet_type", "string", length=64, default=SnippetType.CONFIG.value),
        Field("device_type", "string", length=128, default="aruba_procurve"),
        Field("severity", "string", length=32, default=SnippetSeverity.INFO.value),
        Field("description", "text", default=""),
        Field("commands", "text", default=""),
        Field("audit_regex", "text", default=""),
        Field("created_at", "string", length=32, default=_now_iso),
        Field("bundled_rel_path", "string", length=256, default=""),
        Field("seeded_sha256", "string", length=64, default=""),
        Field("is_deleted", "boolean", default=False),
    )

    db.define_table(
        "device",
        Field("name", "string", length=256, default=""),
        Field("ip", "string", length=128, notnull=True),
        Field("port", "integer", default=22),
        Field("os_type", "string", length=128, default=""),
        Field("protocol", "string", length=16, default="SSH"),
        Field("model", "string", length=256, default=""),
        Field("firmware", "string", length=128, default=""),
        Field("folder_id", "string", length=128, default=""),
        Field("folder_path", "string", length=512, default=""),
        Field("device_category", "string", length=128, default=""),
        Field("serial_number", "string", length=128, default=""),
        Field("airwave_status", "string", length=64, default="Manual"),
        Field("device_role", "string", length=128, default=""),
        Field("airwave_os", "string", length=128, default=""),
        Field("enabled", "boolean", default=True),
        Field("ping_status", "string", length=32, default="Unknown"),
    )

    db.define_table(
        "saved_parameter",
        Field("name", "string", length=256, unique=True, notnull=True),
        Field("value", "text", default=""),
    )

    db.define_table(
        "job",
        Field("job_uid", "string", length=64, unique=True, notnull=True),
        Field("name", "string", length=256, notnull=True),
        Field("job_type", "string", length=64, default=SnippetType.CONFIG.value),
        Field("device_type", "string", length=128, default="aruba_procurve"),
        Field("status", "string", length=32, default="Running"),
        Field("creation_time", "string", length=32, default=""),
        Field("start_time", "string", length=32, default=""),
        Field("end_time", "string", length=32, default=""),
        Field("description", "text", default=""),
        Field("snippet_name", "string", length=256, default=""),
        Field("commands_raw", "text", default=""),
        Field("commands_rendered", "text", default=""),
        Field("audit_regex", "text", default=""),
        Field("max_parallel", "integer", default=10),
        Field("schedule_sequence", "string", length=32, default="Concurrent"),
        Field("include_write", "boolean", default=False),
        Field("parameters_masked_json", "text", default="{}"),
    )

    db.define_table(
        "job_result",
        Field("job_id", "reference job", ondelete="CASCADE", notnull=True),
        Field("host_key", "string", length=160, notnull=True),
        Field("host_name", "string", length=256, default=""),
        Field("host_ip", "string", length=128, default=""),
        Field("host_port", "integer", default=22),
        Field("host_os", "string", length=128, default=""),
        Field("host_protocol", "string", length=16, default="SSH"),
        Field("host_model", "string", length=256, default=""),
        Field("host_firmware", "string", length=128, default=""),
        Field("status", "string", length=32, default="Pending"),
        Field("started_at", "string", length=32, default=""),
        Field("finished_at", "string", length=32, default=""),
        Field("operation_result", "text", default=""),
        Field("connection_method", "string", length=256, default=""),
        Field("exception_message", "text", default=""),
        Field("raw_output", "text", default=""),
        Field("formatted_log", "text", default=""),
        Field("error_lines_json", "text", default="[]"),
        Field("step_results_json", "text", default="[]"),
        Field("commands_run_json", "text", default="[]"),
    )


class DatabaseStore:
    """Thread-safe SQLite repository backed by PyDAL for all aethernms state and logs."""

    def __init__(self, db_path: Optional[Path | str] = None) -> None:
        self.db_path = Path(db_path) if db_path else get_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._uri = f"sqlite://{self.db_path.name}"

        # Initialize schema once cleanly.
        self._bootstrap_schema()

    def _open_dal(self, migrate: bool = False) -> DAL:
        db = DAL(
            self._uri,
            folder=str(self.db_path.parent),
            migrate=migrate,
            fake_migrate=False,
            pool_size=0,
            check_reserved=[],
            adapter_args={"timeout": 15.0},
        )
        db.executesql("PRAGMA journal_mode=WAL;")
        db.executesql("PRAGMA busy_timeout=15000;")
        db.executesql("PRAGMA foreign_keys=ON;")
        _define_tables(db)
        return db

    def _bootstrap_schema(self) -> None:
        with self._lock:
            db = self._open_dal(migrate=True)
            try:
                self._seed_default_roles_in_tx(db)
                db.commit()
            finally:
                db.close()

    @staticmethod
    def _seed_default_roles_in_tx(db: DAL) -> None:
        for spec in DEFAULT_ROLES:
            rname = str(spec["name"])
            existing = db(db.auth_role.name == rname).select().first()
            perms_json = json.dumps(list(spec["permissions"]), sort_keys=True)
            if existing is None:
                db.auth_role.insert(
                    name=rname,
                    description=str(spec["description"]),
                    is_system=True,
                    permissions_json=perms_json,
                    created_at=_now_iso(),
                )
            elif rname == "Admin":
                # Keep built-in Admin full-access so administrators can never lock themselves out.
                existing.update_record(is_system=True, permissions_json=perms_json)
        # Normalize legacy lowercase 'admin' user rows to 'Admin'
        for urow in db(db.auth_user.id > 0).select():
            canon = canonical_role_name(urow.role)
            if canon != urow.role:
                urow.update_record(role=canon)

    def _with_db(self, fn):
        """Execute `fn(db)` inside a locked short-lived PyDAL connection so threads never leak handles."""
        with self._lock:
            db = self._open_dal(migrate=False)
            try:
                result = fn(db)
                db.commit()
                return result
            except Exception:
                try:
                    db.rollback()
                except Exception:
                    pass
                raise
            finally:
                db.close()

    def close(self) -> None:
        """No-op hook kept for symmetrical cleanup (connections close per operation)."""
        return None

    # ------------------------------------------------------------------
    # Roles, Users & API Keys (RBAC)
    # ------------------------------------------------------------------
    @staticmethod
    def _clean_permissions(raw_perms: Iterable[str]) -> List[str]:
        valid = set(ALL_PERMISSION_KEYS)
        cleaned = sorted({str(p).strip() for p in (raw_perms or []) if str(p).strip() in valid})
        return cleaned

    @classmethod
    def _resolve_permissions_in_tx(cls, db: DAL, role_name: str) -> List[str]:
        canon = canonical_role_name(role_name)
        rrow = db(db.auth_role.name == canon).select().first()
        if rrow is not None:
            loaded = _json_loads_safe(rrow.permissions_json, [])
            if isinstance(loaded, list):
                return cls._clean_permissions(loaded)
        if canon == "Admin":
            return list(ALL_PERMISSION_KEYS)
        for spec in DEFAULT_ROLES:
            if str(spec["name"]).lower() == canon.lower():
                return list(spec["permissions"])
        return []

    @classmethod
    def _row_to_user_dict(cls, db: DAL, row: Any) -> Dict[str, Any]:
        role_name = canonical_role_name(row.role)
        return {
            "id": int(row.id),
            "username": row.username,
            "display_name": row.display_name or "",
            "role": role_name,
            "is_active": True if row.is_active is None else bool(row.is_active),
            "permissions": cls._resolve_permissions_in_tx(db, role_name),
            "created_at": row.created_at or "",
        }

    def list_roles(self) -> List[Dict[str, Any]]:
        def _op(db: DAL) -> List[Dict[str, Any]]:
            roles = db(db.auth_role.id > 0).select(orderby=db.auth_role.id)
            users = db(db.auth_user.id > 0).select()
            counts: Dict[str, int] = {}
            for u in users:
                rn = canonical_role_name(u.role)
                counts[rn] = counts.get(rn, 0) + 1
            out: List[Dict[str, Any]] = []
            for r in roles:
                perms = self._clean_permissions(_json_loads_safe(r.permissions_json, []))
                out.append(
                    {
                        "id": int(r.id),
                        "name": r.name,
                        "description": r.description or "",
                        "is_system": bool(r.is_system),
                        "permissions": perms,
                        "user_count": counts.get(r.name, 0),
                        "created_at": r.created_at or "",
                    }
                )
            return out

        return self._with_db(_op)

    def get_role(self, role_id: int) -> Optional[Dict[str, Any]]:
        def _op(db: DAL) -> Optional[Dict[str, Any]]:
            r = db.auth_role[int(role_id)]
            if r is None:
                return None
            user_cnt = db(db.auth_user.role == r.name).count()
            return {
                "id": int(r.id),
                "name": r.name,
                "description": r.description or "",
                "is_system": bool(r.is_system),
                "permissions": self._clean_permissions(_json_loads_safe(r.permissions_json, [])),
                "user_count": int(user_cnt),
                "created_at": r.created_at or "",
            }

        return self._with_db(_op)

    def create_role(
        self,
        name: str,
        permissions: Iterable[str],
        description: str = "",
    ) -> Dict[str, Any]:
        clean_name = (name or "").strip()
        if not clean_name:
            raise ValueError("Role name is required.")
        perms = self._clean_permissions(permissions)

        def _op(db: DAL) -> Dict[str, Any]:
            existing = db(db.auth_role.name.lower() == clean_name.lower()).select().first()
            if existing is not None:
                raise ValueError(f"Role '{clean_name}' already exists.")
            rid = db.auth_role.insert(
                name=clean_name,
                description=(description or "").strip(),
                is_system=False,
                permissions_json=json.dumps(perms, sort_keys=True),
                created_at=_now_iso(),
            )
            r = db.auth_role[rid]
            return {
                "id": int(r.id),
                "name": r.name,
                "description": r.description or "",
                "is_system": False,
                "permissions": perms,
                "user_count": 0,
                "created_at": r.created_at or "",
            }

        return self._with_db(_op)

    def update_role(
        self,
        role_id: int,
        name: Optional[str] = None,
        permissions: Optional[Iterable[str]] = None,
        description: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        def _op(db: DAL) -> Optional[Dict[str, Any]]:
            r = db.auth_role[int(role_id)]
            if r is None:
                return None
            if r.name == "Admin":
                raise ValueError("The built-in Admin role cannot be modified.")

            new_name = (name if name is not None else r.name).strip()
            if not new_name:
                raise ValueError("Role name is required.")
            if r.is_system and new_name != r.name:
                raise ValueError("System roles cannot be renamed.")
            if new_name.lower() != r.name.lower():
                dup = db(db.auth_role.name.lower() == new_name.lower()).select().first()
                if dup is not None and int(dup.id) != int(role_id):
                    raise ValueError(f"Role '{new_name}' already exists.")

            old_name = r.name
            new_perms = (
                self._clean_permissions(permissions)
                if permissions is not None
                else self._clean_permissions(_json_loads_safe(r.permissions_json, []))
            )
            new_desc = (description if description is not None else (r.description or "")).strip()
            r.update_record(
                name=new_name,
                description=new_desc,
                permissions_json=json.dumps(new_perms, sort_keys=True),
            )
            if new_name != old_name:
                db(db.auth_user.role == old_name).update(role=new_name)
                db(db.api_key.role_name == old_name).update(role_name=new_name)
            user_cnt = db(db.auth_user.role == new_name).count()
            return {
                "id": int(r.id),
                "name": new_name,
                "description": new_desc,
                "is_system": bool(r.is_system),
                "permissions": new_perms,
                "user_count": int(user_cnt),
                "created_at": r.created_at or "",
            }

        return self._with_db(_op)

    def delete_role(self, role_id: int) -> bool:
        def _op(db: DAL) -> bool:
            r = db.auth_role[int(role_id)]
            if r is None:
                return False
            if r.is_system:
                raise ValueError(f"System role '{r.name}' cannot be deleted.")
            assigned = db(db.auth_user.role == r.name).count()
            if assigned > 0:
                raise ValueError(
                    f"Cannot delete role '{r.name}' while {assigned} user(s) are assigned to it."
                )
            db(db.api_key.role_name == r.name).update(role_name="")
            return bool(db(db.auth_role.id == int(role_id)).delete())

        return self._with_db(_op)

    def user_count(self) -> int:
        return int(self._with_db(lambda db: db(db.auth_user.id > 0).count()))

    def list_users(self) -> List[Dict[str, Any]]:
        def _op(db: DAL) -> List[Dict[str, Any]]:
            rows = db(db.auth_user.id > 0).select(orderby=db.auth_user.id)
            return [self._row_to_user_dict(db, r) for r in rows]

        return self._with_db(_op)

    def create_user(
        self,
        username: str,
        password: str,
        role: str = "Admin",
        display_name: str = "",
        is_active: bool = True,
    ) -> Dict[str, Any]:
        clean_user = (username or "").strip()
        if not clean_user:
            raise ValueError("Username is required.")
        if len(password or "") < 6:
            raise ValueError("Password must be at least 6 characters long.")
        pw_hash = hash_password(password)
        role_canon = canonical_role_name(role or "Admin")

        def _op(db: DAL) -> Dict[str, Any]:
            existing = db(db.auth_user.username == clean_user).select().first()
            if existing is not None:
                raise ValueError(f"User '{clean_user}' already exists.")
            rrow = db(db.auth_role.name == role_canon).select().first()
            if rrow is None:
                raise ValueError(f"Unknown role '{role_canon}'.")
            uid = db.auth_user.insert(
                username=clean_user,
                display_name=(display_name or "").strip(),
                password_hash=pw_hash,
                role=rrow.name,
                is_active=bool(is_active),
                created_at=_now_iso(),
            )
            return self._row_to_user_dict(db, db.auth_user[uid])

        return self._with_db(_op)

    def update_user(
        self,
        user_id: int,
        role: Optional[str] = None,
        display_name: Optional[str] = None,
        is_active: Optional[bool] = None,
        password: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        if password is not None and password != "" and len(password) < 6:
            raise ValueError("Password must be at least 6 characters long.")

        def _op(db: DAL) -> Optional[Dict[str, Any]]:
            row = db.auth_user[int(user_id)]
            if row is None:
                return None
            cur_role = canonical_role_name(row.role)
            cur_active = True if row.is_active is None else bool(row.is_active)
            new_role = canonical_role_name(role) if role is not None else cur_role
            new_active = bool(is_active) if is_active is not None else cur_active

            rrow = db(db.auth_role.name == new_role).select().first()
            if rrow is None:
                raise ValueError(f"Unknown role '{new_role}'.")

            if cur_role == "Admin" and cur_active and (new_role != "Admin" or not new_active):
                other_admins = db(
                    (db.auth_user.id != int(user_id))
                    & (db.auth_user.role == "Admin")
                    & (db.auth_user.is_active == True)  # noqa: E712
                ).count()
                if other_admins == 0:
                    raise ValueError("At least one active Admin user is required.")

            updates: Dict[str, Any] = {
                "role": rrow.name,
                "is_active": new_active,
            }
            if display_name is not None:
                updates["display_name"] = display_name.strip()
            if password:
                updates["password_hash"] = hash_password(password)
            row.update_record(**updates)
            return self._row_to_user_dict(db, db.auth_user[int(user_id)])

        return self._with_db(_op)

    def delete_user(self, user_id: int) -> bool:
        def _op(db: DAL) -> bool:
            row = db.auth_user[int(user_id)]
            if row is None:
                return False
            cur_role = canonical_role_name(row.role)
            cur_active = True if row.is_active is None else bool(row.is_active)
            if cur_role == "Admin" and cur_active:
                other_admins = db(
                    (db.auth_user.id != int(user_id))
                    & (db.auth_user.role == "Admin")
                    & (db.auth_user.is_active == True)  # noqa: E712
                ).count()
                if other_admins == 0:
                    raise ValueError("Cannot delete the last active Admin user.")
            db(db.api_key.user_id == int(user_id)).delete()
            return bool(db(db.auth_user.id == int(user_id)).delete())

        return self._with_db(_op)

    def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        def _op(db: DAL) -> Optional[Dict[str, Any]]:
            row = db.auth_user[int(user_id)]
            if row is None:
                return None
            return self._row_to_user_dict(db, row)

        return self._with_db(_op)

    def authenticate_user(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        clean_user = (username or "").strip()
        if not clean_user or not password:
            return None

        def _op(db: DAL) -> Optional[Dict[str, Any]]:
            row = db(db.auth_user.username == clean_user).select().first()
            if row is None or not verify_password(password, row.password_hash):
                return None
            if row.is_active is False:
                return None
            return self._row_to_user_dict(db, row)

        return self._with_db(_op)

    def update_user_password(self, user_id: int, new_password: str) -> bool:
        if len(new_password or "") < 6:
            raise ValueError("Password must be at least 6 characters long.")
        pw_hash = hash_password(new_password)

        def _op(db: DAL) -> bool:
            updated = db(db.auth_user.id == int(user_id)).update(password_hash=pw_hash)
            return bool(updated)

        return self._with_db(_op)

    def bootstrap_admin_from_env(self) -> Optional[Dict[str, Any]]:
        """Create initial admin from AETHERNMS_ADMIN_USER/AETHERNMS_ADMIN_PASSWORD if DB has no users."""
        env_user = os.environ.get("AETHERNMS_ADMIN_USER", "").strip()
        env_pass = os.environ.get("AETHERNMS_ADMIN_PASSWORD", "")
        if env_user and env_pass and self.user_count() == 0:
            return self.create_user(env_user, env_pass, role="Admin")
        return None

    def list_api_keys(self, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
        def _op(db: DAL) -> List[Dict[str, Any]]:
            query = db.api_key.id > 0 if user_id is None else (db.api_key.user_id == int(user_id))
            rows = db(query).select(orderby=~db.api_key.id)
            users_map = {int(u.id): u for u in db(db.auth_user.id > 0).select()}
            out: List[Dict[str, Any]] = []
            for r in rows:
                u = users_map.get(int(r.user_id))
                owner_role = canonical_role_name(u.role) if u is not None else "Viewer"
                eff_role = canonical_role_name(r.role_name) if (r.role_name or "").strip() else owner_role
                out.append(
                    {
                        "id": int(r.id),
                        "user_id": int(r.user_id),
                        "username": u.username if u is not None else "",
                        "name": r.name,
                        "role_name": eff_role,
                        "key_prefix": r.key_prefix,
                        "created_at": r.created_at,
                        "last_used_at": r.last_used_at or "",
                    }
                )
            return out

        return self._with_db(_op)

    def create_api_key(
        self,
        user_id: int,
        name: str,
        role_name: str = "",
    ) -> Dict[str, Any]:
        clean_name = (name or "").strip() or "API Key"
        clean_role = (role_name or "").strip()
        plaintext, prefix, key_digest = generate_api_key()

        def _op(db: DAL) -> Dict[str, Any]:
            u = db.auth_user[int(user_id)]
            if u is None:
                raise ValueError("Target user not found.")
            eff_role = canonical_role_name(u.role)
            stored_role = ""
            if clean_role:
                rc = canonical_role_name(clean_role)
                rrow = db(db.auth_role.name == rc).select().first()
                if rrow is None:
                    raise ValueError(f"Unknown role '{clean_role}'.")
                stored_role = rrow.name
                eff_role = rrow.name
            kid = db.api_key.insert(
                user_id=int(user_id),
                name=clean_name,
                role_name=stored_role,
                key_prefix=prefix,
                key_hash=key_digest,
                created_at=_now_iso(),
                last_used_at="",
            )
            row = db.api_key[kid]
            return {
                "id": int(row.id),
                "user_id": int(u.id),
                "username": u.username,
                "name": row.name,
                "role_name": eff_role,
                "key_prefix": row.key_prefix,
                "token": plaintext,
                "created_at": row.created_at,
                "last_used_at": "",
            }

        return self._with_db(_op)

    def revoke_api_key(self, user_id: int, key_id: int, allow_any: bool = False) -> bool:
        def _op(db: DAL) -> bool:
            if allow_any:
                deleted = db(db.api_key.id == int(key_id)).delete()
            else:
                deleted = db(
                    (db.api_key.id == int(key_id)) & (db.api_key.user_id == int(user_id))
                ).delete()
            return bool(deleted)

        return self._with_db(_op)

    def authenticate_api_key(self, raw_token: str) -> Optional[Dict[str, Any]]:
        token = (raw_token or "").strip()
        if not token:
            return None
        digest = hash_api_key(token)

        def _op(db: DAL) -> Optional[Dict[str, Any]]:
            row = db(db.api_key.key_hash == digest).select().first()
            if row is None:
                return None
            user_row = db.auth_user[int(row.user_id)]
            if user_row is None or user_row.is_active is False:
                return None
            row.update_record(last_used_at=_now_iso())
            eff_role = (
                canonical_role_name(row.role_name)
                if (row.role_name or "").strip()
                else canonical_role_name(user_row.role)
            )
            return {
                "id": int(user_row.id),
                "username": user_row.username,
                "display_name": user_row.display_name or "",
                "role": eff_role,
                "is_active": True,
                "permissions": self._resolve_permissions_in_tx(db, eff_role),
                "api_key_id": int(row.id),
            }

        return self._with_db(_op)

    # ------------------------------------------------------------------
    # AppSettings
    # ------------------------------------------------------------------
    @staticmethod
    def _row_to_settings(row: Any) -> AppSettings:
        if row is None:
            return AppSettings()
        flt_dict = _json_loads_safe(row.airwave_filters_json, {})
        if not isinstance(flt_dict, dict):
            flt_dict = {}
        os_maps_raw = _json_loads_safe(row.airwave_os_mappings_json, {})
        os_mappings: Dict[str, str] = {}
        if isinstance(os_maps_raw, dict):
            for k, v in os_maps_raw.items():
                key = str(k or "").strip()
                plat, _proto = normalize_legacy_platform(str(v or ""))
                if key and plat:
                    os_mappings[key] = plat

        return AppSettings(
            language=(row.language or "auto").strip() or "auto",
            theme_mode=(row.theme_mode or "auto").strip() or "auto",
            ssh_username=(row.ssh_username or "").strip(),
            default_protocol=_enum_by_value(
                ConnectionProtocol, row.default_protocol, ConnectionProtocol.SSH
            ),
            ssh_port=max(1, min(65535, _parse_int(row.ssh_port, 22))),
            telnet_port=max(1, min(65535, _parse_int(row.telnet_port, 23))),
            schedule_sequence=_enum_by_value(
                ScheduleSequence, row.schedule_sequence, ScheduleSequence.CONCURRENT
            ),
            max_parallel=max(1, _parse_int(row.max_parallel, 10)),
            command_timeout=max(1, _parse_int(row.command_timeout, 15)),
            connect_timeout=max(1, _parse_int(row.connect_timeout, 10)),
            airwave_url=(row.airwave_url or "").strip(),
            airwave_username=(row.airwave_username or "").strip(),
            airwave_verify_ssl=bool(row.airwave_verify_ssl),
            airwave_filters=AirWaveFilter(
                folder=str(flt_dict.get("folder", "")),
                category=str(flt_dict.get("category", "switch") or "switch"),
                name_filter=str(flt_dict.get("name_filter", "")),
                ip_filter=str(flt_dict.get("ip_filter", "")),
                model=str(flt_dict.get("model", "")),
                os_filter=str(flt_dict.get("os_filter", "All") or "All"),
                status_filter=str(flt_dict.get("status_filter", "All") or "All"),
                search_query=str(flt_dict.get("search_query", "")),
                include_stacked=False,
            ),
            airwave_os_mappings=os_mappings,
            api_enabled=bool(getattr(row, "api_enabled", False)),
            api_allowed_ips=(
                (getattr(row, "api_allowed_ips", None) or "").strip() or DEFAULT_API_ALLOWED_IPS
            ),
        )

    def get_settings(self) -> AppSettings:
        def _op(db: DAL) -> AppSettings:
            row = db(db.app_settings.singleton_key == "global").select().first()
            return self._row_to_settings(row)

        return self._with_db(_op)

    def save_settings(self, settings: AppSettings) -> AppSettings:
        cleaned_maps: Dict[str, str] = {}
        for k, v in (settings.airwave_os_mappings or {}).items():
            ck = (k or "").strip()
            cp = canonical_platform(v) or normalize_legacy_platform(v)[0]
            if ck and cp:
                cleaned_maps[ck] = cp

        flt = settings.airwave_filters or AirWaveFilter()
        flt_json = json.dumps(
            {
                "folder": flt.folder or "",
                "category": flt.category or "switch",
                "name_filter": flt.name_filter or "",
                "ip_filter": flt.ip_filter or "",
                "model": flt.model or "",
                "os_filter": flt.os_filter or "All",
                "status_filter": flt.status_filter or "All",
                "search_query": flt.search_query or "",
            },
            sort_keys=True,
        )

        payload = dict(
            language=(settings.language or "auto").strip() or "auto",
            theme_mode=(settings.theme_mode or "auto").strip() or "auto",
            ssh_username=(settings.ssh_username or "").strip(),
            default_protocol=settings.default_protocol.value,
            ssh_port=max(1, min(65535, int(settings.ssh_port or 22))),
            telnet_port=max(1, min(65535, int(settings.telnet_port or 23))),
            schedule_sequence=settings.schedule_sequence.value,
            max_parallel=max(1, int(settings.max_parallel or 10)),
            command_timeout=max(1, int(settings.command_timeout or 15)),
            connect_timeout=max(1, int(settings.connect_timeout or 10)),
            airwave_url=(settings.airwave_url or "").strip(),
            airwave_username=(settings.airwave_username or "").strip(),
            airwave_verify_ssl=bool(settings.airwave_verify_ssl),
            airwave_filters_json=flt_json,
            airwave_os_mappings_json=json.dumps(cleaned_maps, sort_keys=True),
            api_enabled=bool(settings.api_enabled),
            api_allowed_ips=(settings.api_allowed_ips or "").strip() or DEFAULT_API_ALLOWED_IPS,
        )

        def _op(db: DAL) -> AppSettings:
            row = db(db.app_settings.singleton_key == "global").select().first()
            if row is None:
                db.app_settings.insert(singleton_key="global", **payload)
            else:
                row.update_record(**payload)
            saved = db(db.app_settings.singleton_key == "global").select().first()
            return self._row_to_settings(saved)

        return self._with_db(_op)

    # ------------------------------------------------------------------
    # Snippets (SQLite + SHA-256 seeding from bundled XMLs)
    # ------------------------------------------------------------------
    @staticmethod
    def _row_to_snippet(row: Any) -> Snippet:
        plat, _proto = normalize_legacy_platform(row.device_type)
        dev_type = plat or (row.device_type or "").strip() or "aruba_procurve"
        folder = normalize_folder_path(row.folder) or SnippetStore.default_folder_for_os(dev_type)
        return Snippet(
            id=int(row.id),
            name=row.name or "",
            folder=folder,
            snippet_type=_enum_by_value(SnippetType, row.snippet_type, SnippetType.CONFIG),
            device_type=dev_type,
            severity=_enum_by_value(SnippetSeverity, row.severity, SnippetSeverity.INFO),
            description=row.description or "",
            commands=row.commands or "",
            audit_regex=row.audit_regex or "",
            created_at=row.created_at or "",
            file_path=None,
        )

    def seed_bundled_snippets(self, source_dir: Optional[Path] = None) -> int:
        """
        Seed built-in XML snippets into SQLite with SHA-256 upgrade tracking:
          - New bundled XMLs are inserted with bundled_rel_path + seeded_sha256.
          - Unmodified built-in snippets receive upstream changes automatically.
          - Deleted built-in snippets (is_deleted=True) stay deleted across restarts/upgrades.
          - User-edited built-in snippets (seeded_sha256 cleared on edit) stay untouched.
        Returns count of inserted/updated records.
        """
        src = Path(source_dir) if source_dir else bundled_snippets_dir()
        if not src.is_dir():
            return 0

        xml_files = sorted(src.rglob("*.xml"))
        if not xml_files:
            return 0

        def _op(db: DAL) -> int:
            changed = 0
            for xml_path in xml_files:
                rel = xml_path.relative_to(src).as_posix()
                try:
                    snip = snippet_from_xml_file(xml_path, base_dir=src)
                    src_hash = _normalized_sha256(xml_path)
                except Exception:
                    continue

                existing = db(db.snippet.bundled_rel_path == rel).select().first()
                if existing is None:
                    db.snippet.insert(
                        name=snip.name,
                        folder=snip.folder or SnippetStore.default_folder_for_os(snip.device_type),
                        snippet_type=snip.snippet_type.value,
                        device_type=snip.device_type,
                        severity=snip.severity.value,
                        description=snip.description,
                        commands=snip.commands,
                        audit_regex=snip.audit_regex,
                        created_at=snip.created_at or _now_iso(),
                        bundled_rel_path=rel,
                        seeded_sha256=src_hash,
                        is_deleted=False,
                    )
                    changed += 1
                    continue

                if existing.is_deleted:
                    continue

                # Empty seeded_sha256 marks a user-edited snippet; do not overwrite it.
                if existing.seeded_sha256 and existing.seeded_sha256 != src_hash:
                    existing.update_record(
                        name=snip.name,
                        folder=snip.folder or SnippetStore.default_folder_for_os(snip.device_type),
                        snippet_type=snip.snippet_type.value,
                        device_type=snip.device_type,
                        severity=snip.severity.value,
                        description=snip.description,
                        commands=snip.commands,
                        audit_regex=snip.audit_regex,
                        seeded_sha256=src_hash,
                    )
                    changed += 1
            return changed

        return int(self._with_db(_op))

    def list_snippets(self) -> List[Snippet]:
        def _op(db: DAL) -> List[Snippet]:
            rows = db(db.snippet.is_deleted == False).select()  # noqa: E712
            items = [self._row_to_snippet(r) for r in rows]
            items.sort(key=lambda s: (s.folder.lower(), s.name.lower()))
            return items

        return self._with_db(_op)

    def get_snippet(self, snippet_id: int) -> Optional[Snippet]:
        def _op(db: DAL) -> Optional[Snippet]:
            row = db(
                (db.snippet.id == int(snippet_id)) & (db.snippet.is_deleted == False)  # noqa: E712
            ).select().first()
            return self._row_to_snippet(row) if row is not None else None

        return self._with_db(_op)

    def create_snippet(self, snippet: Snippet) -> Snippet:
        plat = canonical_platform(snippet.device_type) or normalize_legacy_platform(
            snippet.device_type
        )[0]
        dev_type = plat or (snippet.device_type or "").strip() or "aruba_procurve"
        folder = normalize_folder_path(snippet.folder) or SnippetStore.default_folder_for_os(
            dev_type
        )
        created_at = snippet.created_at or _now_iso()

        def _op(db: DAL) -> Snippet:
            sid = db.snippet.insert(
                name=snippet.name.strip(),
                folder=folder,
                snippet_type=snippet.snippet_type.value,
                device_type=dev_type,
                severity=snippet.severity.value,
                description=snippet.description or "",
                commands=snippet.commands or "",
                audit_regex=snippet.audit_regex or "",
                created_at=created_at,
                bundled_rel_path="",
                seeded_sha256="",
                is_deleted=False,
            )
            return self._row_to_snippet(db.snippet[sid])

        return self._with_db(_op)

    def update_snippet(self, snippet_id: int, snippet: Snippet) -> Optional[Snippet]:
        plat = canonical_platform(snippet.device_type) or normalize_legacy_platform(
            snippet.device_type
        )[0]
        dev_type = plat or (snippet.device_type or "").strip() or "aruba_procurve"
        folder = normalize_folder_path(snippet.folder) or SnippetStore.default_folder_for_os(
            dev_type
        )

        def _op(db: DAL) -> Optional[Snippet]:
            row = db(
                (db.snippet.id == int(snippet_id)) & (db.snippet.is_deleted == False)  # noqa: E712
            ).select().first()
            if row is None:
                return None
            row.update_record(
                name=snippet.name.strip(),
                folder=folder,
                snippet_type=snippet.snippet_type.value,
                device_type=dev_type,
                severity=snippet.severity.value,
                description=snippet.description or "",
                commands=snippet.commands or "",
                audit_regex=snippet.audit_regex or "",
                # Clearing seeded_sha256 protects user edits from future upstream seeding.
                seeded_sha256="",
            )
            return self._row_to_snippet(db.snippet[int(snippet_id)])

        return self._with_db(_op)

    def delete_snippet(self, snippet_id: int) -> bool:
        def _op(db: DAL) -> bool:
            row = db(
                (db.snippet.id == int(snippet_id)) & (db.snippet.is_deleted == False)  # noqa: E712
            ).select().first()
            if row is None:
                return False
            if row.bundled_rel_path:
                row.update_record(is_deleted=True)
            else:
                db(db.snippet.id == int(snippet_id)).delete()
            return True

        return self._with_db(_op)

    # ------------------------------------------------------------------
    # Devices
    # ------------------------------------------------------------------
    @staticmethod
    def _row_to_host(row: Any) -> HostEntry:
        plat, proto = _parse_host_platform_and_protocol(row.os_type, row.protocol)
        default_port = 23 if proto == ConnectionProtocol.TELNET else 22
        return HostEntry(
            id=int(row.id),
            name=row.name or "",
            ip=row.ip or "",
            os_type=plat,
            protocol=proto,
            model=row.model or "",
            firmware=row.firmware or "",
            folder_id=row.folder_id if row.folder_id else None,
            folder_path=row.folder_path or "",
            device_category=row.device_category or "",
            serial_number=row.serial_number or "",
            airwave_status=row.airwave_status or "Manual",
            device_role=row.device_role or "",
            airwave_os=row.airwave_os or "",
            enabled=bool(row.enabled),
            port=_parse_int(row.port, default_port),
            ping_status=row.ping_status or "Unknown",
        )

    @staticmethod
    def _host_to_fields(host: HostEntry) -> Dict[str, Any]:
        plat, proto = _parse_host_platform_and_protocol(host.os_type, host.protocol.value)
        default_port = 23 if proto == ConnectionProtocol.TELNET else 22
        return dict(
            name=(host.name or "").strip(),
            ip=(host.ip or "").strip(),
            port=max(1, min(65535, _parse_int(host.port, default_port))),
            os_type=plat,
            protocol=proto.value,
            model=(host.model or "").strip(),
            firmware=(host.firmware or "").strip(),
            folder_id=str(host.folder_id) if host.folder_id is not None else "",
            folder_path=(host.folder_path or "").strip(),
            device_category=(host.device_category or "").strip(),
            serial_number=(host.serial_number or "").strip(),
            airwave_status=(host.airwave_status or "Manual").strip() or "Manual",
            device_role=(host.device_role or "").strip(),
            airwave_os=(host.airwave_os or "").strip(),
            enabled=bool(host.enabled),
            ping_status=(host.ping_status or "Unknown").strip() or "Unknown",
        )

    def list_devices(self) -> List[HostEntry]:
        def _op(db: DAL) -> List[HostEntry]:
            rows = db(db.device.id > 0).select()
            hosts = [self._row_to_host(r) for r in rows]
            hosts.sort(key=lambda h: (h.display_label.lower(), h.ip, h.port))
            return hosts

        return self._with_db(_op)

    def search_devices(self, query: str, limit: int = 12) -> List[HostEntry]:
        """Search devices across name, IP, model, group/folder, Netmiko platform, and serial."""
        q = (query or "").strip().lower()
        hosts = self.list_devices()
        if not q:
            return hosts[: max(1, limit)]
        matched: List[HostEntry] = []
        for h in hosts:
            haystack = " ".join(
                (
                    h.name or "",
                    h.ip or "",
                    h.model or "",
                    h.folder_path or "",
                    h.os_type or "",
                    h.serial_number or "",
                    h.protocol.value,
                )
            ).lower()
            if q in haystack:
                matched.append(h)
        # Prioritize exact prefix match on name or IP first
        matched.sort(
            key=lambda h: (
                0 if (h.name.lower().startswith(q) or h.ip.lower().startswith(q)) else 1,
                h.display_label.lower(),
                h.ip,
            )
        )
        return matched[: max(1, limit)]

    def get_device(self, device_id: int) -> Optional[HostEntry]:
        def _op(db: DAL) -> Optional[HostEntry]:
            row = db.device[int(device_id)]
            return self._row_to_host(row) if row is not None else None

        return self._with_db(_op)

    def create_or_replace_device(self, host: HostEntry) -> HostEntry:
        fields = self._host_to_fields(host)

        def _op(db: DAL) -> HostEntry:
            existing = (
                db((db.device.ip == fields["ip"]) & (db.device.port == fields["port"]))
                .select()
                .first()
            )
            if existing is not None:
                existing.update_record(**fields)
                return self._row_to_host(db.device[int(existing.id)])
            did = db.device.insert(**fields)
            return self._row_to_host(db.device[did])

        return self._with_db(_op)

    def update_device(self, device_id: int, host: HostEntry) -> Optional[HostEntry]:
        fields = self._host_to_fields(host)

        def _op(db: DAL) -> Optional[HostEntry]:
            row = db.device[int(device_id)]
            if row is None:
                return None
            existing_host = self._row_to_host(row)
            if is_airwave_host(existing_host):
                # Enforce AirWave read-only identity/inventory fields; keep Platform/Protocol/Port editable
                fields["name"] = existing_host.name
                fields["ip"] = existing_host.ip
                fields["model"] = existing_host.model
                fields["folder_path"] = existing_host.folder_path
                fields["folder_id"] = (
                    str(existing_host.folder_id) if existing_host.folder_id is not None else ""
                )
                fields["firmware"] = existing_host.firmware
                fields["device_category"] = existing_host.device_category
                fields["serial_number"] = existing_host.serial_number
                fields["airwave_status"] = existing_host.airwave_status
                fields["device_role"] = existing_host.device_role
                fields["airwave_os"] = existing_host.airwave_os
            row.update_record(**fields)
            return self._row_to_host(db.device[int(device_id)])

        return self._with_db(_op)

    def delete_device(self, device_id: int) -> bool:
        def _op(db: DAL) -> bool:
            return bool(db(db.device.id == int(device_id)).delete())

        return self._with_db(_op)

    def merge_airwave_devices(self, imported: Sequence[HostEntry]) -> List[HostEntry]:
        """Upsert imported AirWave devices by ip:port (or AirWave IP) while preserving manual devices."""

        def _op(db: DAL) -> List[HostEntry]:
            saved_list: List[HostEntry] = []
            for host in imported:
                fields = self._host_to_fields(host)
                existing = (
                    db((db.device.ip == fields["ip"]) & (db.device.port == fields["port"]))
                    .select()
                    .first()
                )
                if existing is None:
                    # Match an existing AirWave entry for the same IP even if port was customized
                    candidates = db(db.device.ip == fields["ip"]).select()
                    for cand in candidates:
                        if is_airwave_host(self._row_to_host(cand)):
                            existing = cand
                            break
                if existing is not None:
                    prev = self._row_to_host(existing)
                    fields["ping_status"] = prev.ping_status
                    existing.update_record(**fields)
                    saved_list.append(self._row_to_host(db.device[int(existing.id)]))
                else:
                    did = db.device.insert(**fields)
                    saved_list.append(self._row_to_host(db.device[did]))
            return saved_list

        return self._with_db(_op)

    def update_ping_statuses(self, status_by_key: Dict[str, str]) -> None:
        if not status_by_key:
            return

        def _op(db: DAL) -> None:
            rows = db(db.device.id > 0).select()
            for r in rows:
                key = f"{(r.ip or '').strip()}:{_parse_int(r.port, 22)}"
                if key in status_by_key:
                    r.update_record(ping_status=status_by_key[key])

        self._with_db(_op)

    # ------------------------------------------------------------------
    # Saved non-secret Parameters
    # ------------------------------------------------------------------
    def get_saved_parameters(self) -> Dict[str, str]:
        def _op(db: DAL) -> Dict[str, str]:
            rows = db(db.saved_parameter.id > 0).select()
            return {r.name: r.value or "" for r in rows if r.name}

        return self._with_db(_op)

    def save_parameters(
        self,
        values: Dict[str, str],
        secret_names: Optional[Iterable[str]] = None,
    ) -> None:
        secrets_set: Set[str] = set(secret_names or ())

        def _op(db: DAL) -> None:
            for k, v in (values or {}).items():
                name = str(k or "").strip()
                if not name:
                    continue
                if name in secrets_set:
                    db(db.saved_parameter.name == name).delete()
                    continue
                existing = db(db.saved_parameter.name == name).select().first()
                if existing is None:
                    db.saved_parameter.insert(name=name, value="" if v is None else str(v))
                else:
                    existing.update_record(value="" if v is None else str(v))

        self._with_db(_op)

    # ------------------------------------------------------------------
    # Jobs & SQLite Per-Device Execution Logs
    # ------------------------------------------------------------------
    @staticmethod
    def _row_to_job_result(row: Any) -> HostExecutionResult:
        plat, proto = _parse_host_platform_and_protocol(row.host_os, row.host_protocol)
        default_port = 23 if proto == ConnectionProtocol.TELNET else 22
        host = HostEntry(
            name=row.host_name or "",
            ip=row.host_ip or "",
            os_type=plat,
            protocol=proto,
            model=row.host_model or "",
            firmware=row.host_firmware or "",
            port=_parse_int(row.host_port, default_port),
        )
        steps_raw = _json_loads_safe(row.step_results_json, [])
        steps: List[CommandStepResult] = []
        if isinstance(steps_raw, list):
            for s in steps_raw:
                if isinstance(s, dict):
                    steps.append(
                        CommandStepResult(
                            index=_parse_int(s.get("index"), 0),
                            command=str(s.get("command", "")),
                            result=str(s.get("result", "")),
                            suggestion=str(s.get("suggestion", "")),
                            begin_time=str(s.get("begin_time", "")),
                            finish_time=str(s.get("finish_time", "")),
                            output_snippet=str(s.get("output_snippet", "")),
                        )
                    )
        errs = _json_loads_safe(row.error_lines_json, [])
        cmds = _json_loads_safe(row.commands_run_json, [])
        return HostExecutionResult(
            id=int(row.id),
            host=host,
            status=row.status or "Pending",
            commands_run=cmds if isinstance(cmds, list) else [],
            step_results=steps,
            raw_output=row.raw_output or "",
            error_lines=errs if isinstance(errs, list) else [],
            operation_result=row.operation_result or "",
            log_path="",
            started_at=row.started_at or "",
            finished_at=row.finished_at or "",
            exception_message=row.exception_message or "",
            connection_method=row.connection_method or "",
            formatted_log=row.formatted_log or "",
        )

    @classmethod
    def _row_to_job(cls, row: Any, result_rows: Sequence[Any]) -> JobRecord:
        plat, _proto = normalize_legacy_platform(row.device_type)
        dev_type = plat or (row.device_type or "").strip() or "aruba_procurve"
        cmd_raw = row.commands_raw or ""
        audit_rx = row.audit_regex or ""
        secret_names = {
            s.name for s in extract_variables(f"{cmd_raw}\n{audit_rx}") if s.is_secret
        }
        pm_raw = _json_loads_safe(row.parameters_masked_json, {})
        pm: Dict[str, str] = {}
        if isinstance(pm_raw, dict):
            for pk, pv in pm_raw.items():
                pm[str(pk)] = "••••••••" if pk in secret_names else str(pv or "")

        return JobRecord(
            job_id=row.job_uid,
            name=row.name or "Config Job",
            job_type=_enum_by_value(SnippetType, row.job_type, SnippetType.CONFIG),
            device_type=dev_type,
            status=row.status or "Success",
            creation_time=row.creation_time or "",
            start_time=row.start_time or "",
            end_time=row.end_time or "",
            description=row.description or "",
            snippet_name=row.snippet_name or "",
            commands_raw=cmd_raw,
            commands_rendered=row.commands_rendered or cmd_raw,
            audit_regex=audit_rx,
            max_parallel=max(1, _parse_int(row.max_parallel, 10)),
            schedule_sequence=_enum_by_value(
                ScheduleSequence, row.schedule_sequence, ScheduleSequence.CONCURRENT
            ),
            include_write=bool(row.include_write),
            log_dir="",
            parameters_masked=pm,
            results=[cls._row_to_job_result(rr) for rr in result_rows],
        )

    @staticmethod
    def _result_to_fields(job_pk: int, res: HostExecutionResult) -> Dict[str, Any]:
        formatted = res.formatted_log or format_host_log(res)
        step_dicts = [
            {
                "index": s.index,
                "command": s.command,
                "result": s.result,
                "suggestion": s.suggestion,
                "begin_time": s.begin_time,
                "finish_time": s.finish_time,
                "output_snippet": s.output_snippet,
            }
            for s in (res.step_results or [])
        ]
        return dict(
            job_id=int(job_pk),
            host_key=res.host.unique_key,
            host_name=res.host.name or "",
            host_ip=res.host.ip or "",
            host_port=int(res.host.port or 22),
            host_os=res.host.os_type or "",
            host_protocol=res.host.protocol.value,
            host_model=res.host.model or "",
            host_firmware=res.host.firmware or "",
            status=res.status or "Pending",
            started_at=res.started_at or "",
            finished_at=res.finished_at or "",
            operation_result=res.operation_result or "",
            connection_method=res.connection_method or "",
            exception_message=res.exception_message or "",
            raw_output=res.raw_output or "",
            formatted_log=formatted,
            error_lines_json=json.dumps(res.error_lines or []),
            step_results_json=json.dumps(step_dicts),
            commands_run_json=json.dumps(res.commands_run or []),
        )

    def create_job(
        self,
        job: JobRecord,
        secret_names: Optional[Iterable[str]] = None,
    ) -> JobRecord:
        secrets_set = set(secret_names or ())
        for spec in extract_variables(f"{job.commands_raw}\n{job.audit_regex}"):
            if spec.is_secret:
                secrets_set.add(spec.name)
        safe_masked = {
            str(k): ("••••••••" if k in secrets_set else str(v or ""))
            for k, v in (job.parameters_masked or {}).items()
        }

        def _op(db: DAL) -> JobRecord:
            jpk = db.job.insert(
                job_uid=job.job_id,
                name=job.name,
                job_type=job.job_type.value,
                device_type=job.device_type or "aruba_procurve",
                status=job.status or "Running",
                creation_time=job.creation_time or "",
                start_time=job.start_time or "",
                end_time=job.end_time or "",
                description=job.description or "",
                snippet_name=job.snippet_name or "",
                commands_raw=job.commands_raw or "",
                commands_rendered=job.commands_rendered or "",
                audit_regex=job.audit_regex or "",
                max_parallel=max(1, int(job.max_parallel or 10)),
                schedule_sequence=job.schedule_sequence.value,
                include_write=bool(job.include_write),
                parameters_masked_json=json.dumps(safe_masked, sort_keys=True),
            )
            for res in job.results:
                db.job_result.insert(**self._result_to_fields(jpk, res))
            row = db.job[jpk]
            res_rows = db(db.job_result.job_id == jpk).select(orderby=db.job_result.id)
            return self._row_to_job(row, res_rows)

        return self._with_db(_op)

    def list_jobs(self) -> List[JobRecord]:
        def _op(db: DAL) -> List[JobRecord]:
            job_rows = db(db.job.id > 0).select(orderby=~db.job.id)
            if not job_rows:
                return []
            all_results = db(db.job_result.id > 0).select(orderby=db.job_result.id)
            by_job: Dict[int, List[Any]] = {}
            for rr in all_results:
                by_job.setdefault(int(rr.job_id), []).append(rr)
            return [self._row_to_job(jr, by_job.get(int(jr.id), [])) for jr in job_rows]

        return self._with_db(_op)

    def get_job(self, job_uid: str) -> Optional[JobRecord]:
        def _op(db: DAL) -> Optional[JobRecord]:
            row = db(db.job.job_uid == job_uid).select().first()
            if row is None:
                return None
            res_rows = db(db.job_result.job_id == int(row.id)).select(orderby=db.job_result.id)
            return self._row_to_job(row, res_rows)

        return self._with_db(_op)

    def get_job_result(self, job_uid: str, result_id: int) -> Optional[HostExecutionResult]:
        def _op(db: DAL) -> Optional[HostExecutionResult]:
            jrow = db(db.job.job_uid == job_uid).select().first()
            if jrow is None:
                return None
            rrow = (
                db(
                    (db.job_result.id == int(result_id))
                    & (db.job_result.job_id == int(jrow.id))
                )
                .select()
                .first()
            )
            return self._row_to_job_result(rrow) if rrow is not None else None

        return self._with_db(_op)

    def update_job_result_running(self, job_uid: str, host_key: str) -> None:
        def _op(db: DAL) -> None:
            jrow = db(db.job.job_uid == job_uid).select().first()
            if jrow is None:
                return
            db(
                (db.job_result.job_id == int(jrow.id))
                & (db.job_result.host_key == host_key)
            ).update(status="Running", operation_result="Executing...")

        self._with_db(_op)

    def update_job_result(self, job_uid: str, result: HostExecutionResult) -> None:
        def _op(db: DAL) -> None:
            jrow = db(db.job.job_uid == job_uid).select().first()
            if jrow is None:
                return
            fields = self._result_to_fields(int(jrow.id), result)
            existing = (
                db(
                    (db.job_result.job_id == int(jrow.id))
                    & (db.job_result.host_key == result.host.unique_key)
                )
                .select()
                .first()
            )
            if existing is not None:
                existing.update_record(**fields)
            else:
                db.job_result.insert(**fields)

        self._with_db(_op)

    def finalize_job(
        self,
        job_uid: str,
        results: Sequence[HostExecutionResult],
        end_time: str,
    ) -> None:
        has_fail = any(r.status != "Success" for r in results)
        final_status = "Failed" if has_fail else "Success"

        def _op(db: DAL) -> None:
            jrow = db(db.job.job_uid == job_uid).select().first()
            if jrow is None:
                return
            for res in results:
                fields = self._result_to_fields(int(jrow.id), res)
                existing = (
                    db(
                        (db.job_result.job_id == int(jrow.id))
                        & (db.job_result.host_key == res.host.unique_key)
                    )
                    .select()
                    .first()
                )
                if existing is not None:
                    existing.update_record(**fields)
                else:
                    db.job_result.insert(**fields)
            jrow.update_record(status=final_status, end_time=end_time)

        self._with_db(_op)

    def delete_job(self, job_uid: str) -> bool:
        def _op(db: DAL) -> bool:
            jrow = db(db.job.job_uid == job_uid).select().first()
            if jrow is None:
                return False
            db(db.job_result.job_id == int(jrow.id)).delete()
            db(db.job.id == int(jrow.id)).delete()
            return True

        return self._with_db(_op)

    # ------------------------------------------------------------------
    # One-time Legacy XML Migration (settings.xml, devices.xml, jobs.xml, session.xml)
    # ------------------------------------------------------------------
    def migrate_legacy_xml_files(self, config_dir: Optional[Path] = None) -> Dict[str, int]:
        """
        Import legacy XML state into SQLite when the corresponding tables are still empty.
        Returns summary counts {'settings': 0|1, 'devices': N, 'jobs': M}.
        """
        base = Path(config_dir) if config_dir else self.db_path.parent
        counts = {"settings": 0, "devices": 0, "jobs": 0}

        settings_file = base / "settings.xml"
        devices_file = base / "devices.xml"
        jobs_file = base / "jobs.xml"
        session_file = base / "session.xml"

        def _ct(parent: Optional[ET.Element], tag: str, default: str = "") -> str:
            if parent is None:
                return default
            el = parent.find(tag)
            return el.text if (el is not None and el.text is not None) else default

        # 1. Settings
        has_settings = self._with_db(
            lambda db: db(db.app_settings.singleton_key == "global").count() > 0
        )
        if not has_settings:
            migrated_settings: Optional[AppSettings] = None
            if settings_file.is_file():
                try:
                    root = ET.parse(settings_file).getroot()
                    if root.tag in ("AetherNMSSettings", "PsshSettings"):
                        app_el = root.find("Appearance")
                        exec_el = root.find("ExecutionDefaults")
                        aw_el = root.find("AirWave")
                        flt_el = aw_el.find("Filters") if aw_el is not None else None
                        maps_el = aw_el.find("OsMappings") if aw_el is not None else None
                        os_mappings: Dict[str, str] = {}
                        if maps_el is not None:
                            for m in maps_el.findall("Mapping"):
                                mk = (m.attrib.get("key") or "").strip()
                                mp, _ = normalize_legacy_platform(m.attrib.get("platform") or "")
                                if mk and mp:
                                    os_mappings[mk] = mp
                        migrated_settings = AppSettings(
                            language=_ct(app_el, "Language", "auto") or "auto",
                            theme_mode=_ct(app_el, "ThemeMode", "auto") or "auto",
                            ssh_username=_ct(exec_el, "SshUsername", ""),
                            default_protocol=_enum_by_value(
                                ConnectionProtocol,
                                _ct(exec_el, "DefaultProtocol", "SSH"),
                                ConnectionProtocol.SSH,
                            ),
                            ssh_port=max(1, min(65535, _parse_int(_ct(exec_el, "SshPort", "22"), 22))),
                            telnet_port=max(
                                1, min(65535, _parse_int(_ct(exec_el, "TelnetPort", "23"), 23))
                            ),
                            schedule_sequence=_enum_by_value(
                                ScheduleSequence,
                                _ct(exec_el, "ScheduleSequence", "Concurrent"),
                                ScheduleSequence.CONCURRENT,
                            ),
                            max_parallel=max(1, _parse_int(_ct(exec_el, "MaxParallel", "10"), 10)),
                            command_timeout=max(
                                1, _parse_int(_ct(exec_el, "CommandTimeout", "15"), 15)
                            ),
                            connect_timeout=max(
                                1, _parse_int(_ct(exec_el, "ConnectTimeout", "10"), 10)
                            ),
                            airwave_url=_ct(aw_el, "Url", ""),
                            airwave_username=_ct(aw_el, "Username", ""),
                            airwave_verify_ssl=_parse_bool(_ct(aw_el, "VerifySSL", "false"), False),
                            airwave_filters=AirWaveFilter(
                                folder=_ct(flt_el, "Folder", ""),
                                category=_ct(flt_el, "Category", "switch"),
                                name_filter=_ct(flt_el, "NameFilter", ""),
                                ip_filter=_ct(flt_el, "IPFilter", ""),
                                model=_ct(flt_el, "Model", ""),
                                os_filter=_ct(flt_el, "OSFilter", "All") or "All",
                                status_filter=_ct(flt_el, "StatusFilter", "All") or "All",
                                search_query=_ct(flt_el, "SearchQuery", ""),
                                include_stacked=False,
                            ),
                            airwave_os_mappings=os_mappings,
                        )
                except Exception:
                    migrated_settings = None
            elif session_file.is_file():
                try:
                    root = ET.parse(session_file).getroot()
                    exec_el = root.find("ExecutionSettings")
                    aw_el = root.find("AirWave")
                    if exec_el is not None or aw_el is not None:
                        flt_el = aw_el.find("Filters") if aw_el is not None else None
                        migrated_settings = AppSettings(
                            ssh_username=_ct(exec_el, "SshUsername", ""),
                            ssh_port=max(1, min(65535, _parse_int(_ct(exec_el, "SshPort", "22"), 22))),
                            max_parallel=max(1, _parse_int(_ct(exec_el, "MaxParallel", "10"), 10)),
                            command_timeout=max(
                                1, _parse_int(_ct(exec_el, "CommandTimeout", "15"), 15)
                            ),
                            connect_timeout=max(
                                1, _parse_int(_ct(exec_el, "ConnectTimeout", "10"), 10)
                            ),
                            airwave_url=_ct(aw_el, "Url", ""),
                            airwave_username=_ct(aw_el, "Username", ""),
                            airwave_verify_ssl=_parse_bool(_ct(aw_el, "VerifySSL", "false"), False),
                            airwave_filters=AirWaveFilter(
                                folder=_ct(flt_el, "Folder", ""),
                                category=_ct(flt_el, "Category", "switch"),
                            ),
                        )
                except Exception:
                    migrated_settings = None

            if migrated_settings is not None:
                self.save_settings(migrated_settings)
                counts["settings"] = 1

        # 2. Devices
        has_devices = self._with_db(lambda db: db(db.device.id > 0).count() > 0)
        if not has_devices:
            dev_src = devices_file if devices_file.is_file() else (
                session_file if session_file.is_file() else None
            )
            if dev_src is not None:
                try:
                    root = ET.parse(dev_src).getroot()
                    container = root.find("Devices")
                    tag = "Device"
                    if container is None:
                        container = root.find("Hosts")
                        tag = "Host"
                    if container is not None:
                        for el in container.findall(tag):
                            a = el.attrib
                            ip = (a.get("ip") or "").strip()
                            name = (a.get("name") or "").strip()
                            if not ip and not name:
                                continue
                            plat, proto = _parse_host_platform_and_protocol(
                                a.get("os"), a.get("protocol")
                            )
                            def_port = 23 if proto == ConnectionProtocol.TELNET else 22
                            self.create_or_replace_device(
                                HostEntry(
                                    name=name,
                                    ip=ip,
                                    os_type=plat,
                                    protocol=proto,
                                    model=a.get("model", ""),
                                    firmware=a.get("firmware", ""),
                                    folder_id=(a.get("folder_id") or "").strip() or None,
                                    folder_path=a.get("folder_path", ""),
                                    device_category=a.get("device_category", ""),
                                    serial_number=a.get("serial_number", ""),
                                    airwave_status=a.get("airwave_status", "Manual"),
                                    device_role=a.get("device_role", ""),
                                    airwave_os=a.get("airwave_os", ""),
                                    enabled=_parse_bool(a.get("enabled"), True),
                                    port=_parse_int(a.get("port"), def_port),
                                )
                            )
                            counts["devices"] += 1
                except Exception:
                    pass

        # 3. Jobs & saved parameters
        has_jobs = self._with_db(lambda db: db(db.job.id > 0).count() > 0)
        if not has_jobs:
            job_src = jobs_file if jobs_file.is_file() else (
                session_file if session_file.is_file() else None
            )
            if job_src is not None:
                try:
                    root = ET.parse(job_src).getroot()
                    var_values: Dict[str, str] = {}
                    params_el = root.find("Parameters")
                    if params_el is not None:
                        for p in params_el.findall("Param"):
                            pname = (p.attrib.get("name") or "").strip()
                            if pname:
                                var_values[pname] = p.text or ""

                    all_secrets: Set[str] = set()
                    jobs_el = root.find("Jobs")
                    if jobs_el is not None:
                        # Insert oldest first so newest ends up with highest id (desc order)
                        job_nodes = list(jobs_el.findall("Job"))
                        for j in reversed(job_nodes):
                            a = j.attrib
                            cmd_raw = _ct(j, "CommandsRaw", "")
                            audit_rx = _ct(j, "AuditRegex", "")
                            j_secrets = {
                                s.name
                                for s in extract_variables(f"{cmd_raw}\n{audit_rx}")
                                if s.is_secret
                            }
                            all_secrets.update(j_secrets)

                            pm: Dict[str, str] = {}
                            pm_el = j.find("ParametersMasked")
                            if pm_el is not None:
                                for p in pm_el.findall("Param"):
                                    pn = (p.attrib.get("name") or "").strip()
                                    if pn:
                                        pm[pn] = "••••••••" if pn in j_secrets else (p.text or "")

                            res_list: List[HostExecutionResult] = []
                            res_el = j.find("Results")
                            if res_el is not None:
                                for hr in res_el.findall("DeviceResult") or res_el.findall(
                                    "HostResult"
                                ):
                                    ha = hr.attrib
                                    rp, rproto = _parse_host_platform_and_protocol(
                                        ha.get("os"), ha.get("protocol")
                                    )
                                    def_p = 23 if rproto == ConnectionProtocol.TELNET else 22
                                    h_obj = HostEntry(
                                        name=ha.get("name", ""),
                                        ip=ha.get("ip", ""),
                                        os_type=rp,
                                        protocol=rproto,
                                        port=_parse_int(ha.get("port"), def_p),
                                    )
                                    log_path = ha.get("log_path", "")
                                    raw_log_txt = ""
                                    if log_path and Path(log_path).is_file():
                                        try:
                                            raw_log_txt = Path(log_path).read_text(
                                                encoding="utf-8", errors="replace"
                                            )
                                        except OSError:
                                            raw_log_txt = ""
                                    res_list.append(
                                        HostExecutionResult(
                                            host=h_obj,
                                            status=ha.get("status", "Pending"),
                                            started_at=ha.get("started_at", ""),
                                            finished_at=ha.get("finished_at", ""),
                                            operation_result=ha.get("operation_result", ""),
                                            connection_method=ha.get("connection_method", ""),
                                            raw_output=raw_log_txt,
                                            formatted_log=raw_log_txt,
                                        )
                                    )

                            jp, _ = normalize_legacy_platform(a.get("device_type"))
                            jp = jp or (a.get("device_type") or "").strip() or "aruba_procurve"
                            self.create_job(
                                JobRecord(
                                    job_id=a.get("id", "") or f"mig_{counts['jobs'] + 1}",
                                    name=a.get("name", "Config Job"),
                                    job_type=_enum_by_value(
                                        SnippetType, a.get("job_type"), SnippetType.CONFIG
                                    ),
                                    device_type=jp,
                                    status=a.get("status", "Success"),
                                    creation_time=a.get("creation_time", ""),
                                    start_time=a.get("start_time", ""),
                                    end_time=a.get("end_time", ""),
                                    description=_ct(j, "Description", ""),
                                    snippet_name=a.get("snippet_name", ""),
                                    commands_raw=cmd_raw,
                                    commands_rendered=_ct(j, "CommandsRendered", "") or cmd_raw,
                                    audit_regex=audit_rx,
                                    max_parallel=max(1, _parse_int(a.get("max_parallel"), 10)),
                                    schedule_sequence=_enum_by_value(
                                        ScheduleSequence,
                                        a.get("schedule_sequence"),
                                        ScheduleSequence.CONCURRENT,
                                    ),
                                    include_write=_parse_bool(a.get("include_write"), False),
                                    parameters_masked=pm,
                                    results=res_list,
                                ),
                                secret_names=j_secrets,
                            )
                            counts["jobs"] += 1

                    if var_values:
                        self.save_parameters(var_values, secret_names=all_secrets)
                except Exception:
                    pass

        return counts
