"""Multi-backend Py4Web / PyDAL database configuration, URI building, masking, and connection tests."""

from __future__ import annotations

from datetime import datetime
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, unquote

from pydal import DAL

from aethernms.paths import get_db_path, runtime_root


DB_ENGINES: Tuple[Dict[str, Any], ...] = (
    {
        "id": "sqlite",
        "label": "SQLite (Local — Default)",
        "scheme": "sqlite",
        "default_port": None,
        "driver_modules": ("sqlite3",),
        "pip_install": "",
        "fields": ["sqlite_path"],
    },
    {
        "id": "postgres",
        "label": "PostgreSQL",
        "scheme": "postgres",
        "default_port": 5432,
        "driver_modules": ("psycopg2", "pg8000"),
        "pip_install": "pip install psycopg2-binary",
        "fields": ["host", "port", "database", "username", "password", "extra_params"],
    },
    {
        "id": "mysql",
        "label": "MySQL / MariaDB",
        "scheme": "mysql",
        "default_port": 3306,
        "driver_modules": ("pymysql", "MySQLdb"),
        "pip_install": "pip install pymysql",
        "fields": ["host", "port", "database", "username", "password", "extra_params"],
    },
    {
        "id": "mssql",
        "label": "Microsoft SQL Server (MSSQL)",
        "scheme": "mssql4",
        "default_port": 1433,
        "driver_modules": ("pyodbc",),
        "pip_install": "pip install pyodbc",
        "default_odbc_driver": "ODBC Driver 17 for SQL Server",
        "fields": ["host", "port", "database", "username", "password", "odbc_driver", "extra_params"],
    },
    {
        "id": "oracle",
        "label": "Oracle Database",
        "scheme": "oracle",
        "default_port": 1521,
        "driver_modules": ("oracledb", "cx_Oracle"),
        "pip_install": "pip install oracledb",
        "fields": ["host", "port", "database", "username", "password", "extra_params"],
    },
    {
        "id": "custom",
        "label": "Custom PyDAL URI",
        "scheme": "",
        "default_port": None,
        "driver_modules": (),
        "pip_install": "",
        "fields": ["custom_uri"],
    },
)

DB_ENGINE_MAP: Dict[str, Dict[str, Any]] = {spec["id"]: spec for spec in DB_ENGINES}


def get_db_config_path(config_dir: Optional[Path] = None) -> Path:
    """Return path to `<runtime_root>/db_config.json`."""
    base = Path(config_dir) if config_dir is not None else runtime_root()
    return base / "db_config.json"


def get_dal_meta_dir(config_dir: Optional[Path] = None) -> Path:
    """Return writable PyDAL `.table` metadata directory `<runtime_root>/dal_meta` for non-SQLite DBs."""
    base = Path(config_dir) if config_dir is not None else runtime_root()
    meta_dir = base / "dal_meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    return meta_dir


def check_engine_drivers(engine_id: str) -> Dict[str, Any]:
    """Check Python driver availability for the given engine using `importlib.util.find_spec`."""
    eid = (engine_id or "sqlite").strip().lower()
    spec = DB_ENGINE_MAP.get(eid)
    if spec is None:
        raise ValueError(f"Unsupported database engine: '{engine_id}'.")

    modules = tuple(spec.get("driver_modules") or ())
    if not modules:
        return {
            "available": True,
            "installed_drivers": [],
            "checked_drivers": [],
            "pip_install": spec.get("pip_install", ""),
        }

    installed: List[str] = []
    for mod in modules:
        try:
            if importlib.util.find_spec(mod) is not None:
                installed.append(mod)
        except (ValueError, ModuleNotFoundError):
            continue

    return {
        "available": bool(installed),
        "installed_drivers": installed,
        "checked_drivers": list(modules),
        "pip_install": spec.get("pip_install", ""),
    }


def get_supported_engines_info(default_sqlite_path: Optional[Path | str] = None) -> List[Dict[str, Any]]:
    """Return structured database engine definitions with live Python driver checks."""
    sqlite_default = Path(default_sqlite_path) if default_sqlite_path is not None else get_db_path()
    out: List[Dict[str, Any]] = []
    for spec in DB_ENGINES:
        drv = check_engine_drivers(spec["id"])
        out.append(
            {
                "id": spec["id"],
                "label": spec["label"],
                "scheme": spec["scheme"],
                "default_port": spec["default_port"],
                "driver_modules": list(spec["driver_modules"]),
                "pip_install": spec["pip_install"],
                "default_odbc_driver": spec.get("default_odbc_driver", ""),
                "fields": list(spec["fields"]),
                "driver_available": drv["available"],
                "installed_drivers": drv["installed_drivers"],
                "checked_drivers": drv["checked_drivers"],
                "default_sqlite_path": str(sqlite_default) if spec["id"] == "sqlite" else "",
            }
        )
    return out


def detect_engine_from_uri(uri: str) -> str:
    """Infer a supported engine ID (`sqlite`, `postgres`, `mysql`, `mssql`, `oracle`, `custom`) from a URI."""
    low = (uri or "").strip().lower()
    if low.startswith("sqlite"):
        return "sqlite"
    if low.startswith(("postgres://", "postgres:", "postgresql://", "postgresql:")):
        return "postgres"
    if low.startswith(("mysql://", "mysql:")):
        return "mysql"
    if low.startswith(
        (
            "mssql://",
            "mssql2://",
            "mssql3://",
            "mssql4://",
            "mssqln://",
            "mssqlpython://",
            "mssql:",
            "pytds://",
            "pymssql://",
        )
    ):
        return "mssql"
    if low.startswith(("oracle://", "oracle:")):
        return "oracle"
    return "custom"


def parse_sqlite_uri_path(uri: str, base_dir: Optional[Path] = None) -> Optional[Path]:
    """Extract a normalized local Path from a `sqlite://...` URI, or None for `sqlite:memory`."""
    raw_uri = (uri or "").strip()
    low = raw_uri.lower()
    if low.startswith("sqlite:memory"):
        return None
    if low.startswith("sqlite://"):
        raw = raw_uri.split("://", 1)[1]
    else:
        raw = raw_uri
    if "?" in raw and not raw.startswith("file:"):
        raw = raw.split("?", 1)[0]
    if re.match(r"^/[A-Za-z]:[/\\]", raw):
        raw = raw[1:]
    path = Path(raw).expanduser()
    if not path.is_absolute():
        root = Path(base_dir) if base_dir is not None else runtime_root()
        path = root / path
    return path


def _validate_no_newlines(value: str, field_name: str) -> None:
    if "\r" in value or "\n" in value:
        raise ValueError(f"{field_name} cannot contain newline characters.")


def _normalize_mssql_driver(raw_driver: str) -> str:
    text = (raw_driver or "").strip() or "ODBC Driver 17 for SQL Server"
    _validate_no_newlines(text, "ODBC Driver")
    if text.startswith("{") and text.endswith("}"):
        return text
    return f"{{{text}}}"


def build_dal_uri(
    engine: str,
    params: Dict[str, Any],
    default_sqlite_path: Optional[Path | str] = None,
) -> str:
    """Validate parameters and build a PyDAL connection URI with URL-encoded credentials."""
    eng = (engine or "sqlite").strip().lower()
    spec = DB_ENGINE_MAP.get(eng)
    if spec is None:
        raise ValueError(f"Unsupported database engine: '{engine}'.")

    if eng == "sqlite":
        raw_path = str(params.get("sqlite_path") or "").strip()
        _validate_no_newlines(raw_path, "SQLite path")
        base_default = Path(default_sqlite_path) if default_sqlite_path is not None else get_db_path()
        if not raw_path:
            target = base_default
        elif raw_path.lower().startswith("sqlite:memory"):
            return "sqlite:memory"
        elif raw_path.lower().startswith("sqlite://"):
            parsed = parse_sqlite_uri_path(raw_path, base_dir=base_default.parent)
            if parsed is None:
                return "sqlite:memory"
            target = parsed
        else:
            target = Path(raw_path).expanduser()
            if not target.is_absolute():
                target = base_default.parent / target
        if target.exists() and target.is_dir():
            raise ValueError("SQLite database path points to a directory, not a file.")
        return f"sqlite://{target.as_posix()}"

    if eng == "custom":
        custom_uri = str(params.get("custom_uri") or params.get("db_uri") or "").strip()
        _validate_no_newlines(custom_uri, "Custom PyDAL URI")
        if not custom_uri:
            raise ValueError("Custom PyDAL URI is required.")
        if "://" not in custom_uri and not custom_uri.lower().startswith("sqlite:memory"):
            raise ValueError("Custom PyDAL URI must include a scheme such as 'scheme://...'.")
        return custom_uri

    host = str(params.get("host") or "").strip()
    database = str(params.get("database") or "").strip().lstrip("/")
    username = str(params.get("username") or params.get("db_username") or "").strip()
    password = str(params.get("password") or params.get("db_password") or "")
    extra_params = str(params.get("extra_params") or "").strip().lstrip("?")
    raw_port = params.get("port")

    _validate_no_newlines(host, "Host")
    _validate_no_newlines(database, "Database")
    _validate_no_newlines(username, "Username")
    _validate_no_newlines(password, "Password")
    _validate_no_newlines(extra_params, "Extra parameters")

    if not host:
        raise ValueError("Database host is required.")
    if not database:
        raise ValueError("Database name is required.")
    if not username:
        raise ValueError("Database username is required.")

    default_port = int(spec["default_port"])
    if raw_port is None or str(raw_port).strip() == "":
        port = default_port
    else:
        try:
            port = int(str(raw_port).strip())
        except (TypeError, ValueError) as exc:
            raise ValueError("Database port must be between 1 and 65535.") from exc
        if port < 1 or port > 65535:
            raise ValueError("Database port must be between 1 and 65535.")

    if ":" in host and not (host.startswith("[") and host.endswith("]")):
        host_part = f"[{host}]"
    else:
        host_part = host

    user_enc = quote(username, safe="")
    if password != "":
        auth_part = f"{user_enc}:{quote(password, safe='')}"
    else:
        auth_part = user_enc

    query_parts: List[str] = []
    if eng == "mssql":
        has_driver_param = bool(re.search(r"(?:^|[&;])driver=", extra_params, flags=re.IGNORECASE))
        if not has_driver_param:
            odbc_drv = _normalize_mssql_driver(str(params.get("odbc_driver") or ""))
            query_parts.append(f"DRIVER={odbc_drv}")
    if extra_params:
        query_parts.append(extra_params)

    uri = f"{spec['scheme']}://{auth_part}@{host_part}:{port}/{database}"
    if query_parts:
        uri += "?" + "&".join(query_parts)
    return uri


def _redact_secret_params(text: str) -> str:
    return re.sub(r"(?i)(\b(?:pwd|password|passwd)=)([^&;]*)", r"\1********", text)


def mask_dal_uri(uri: str) -> str:
    """Mask any password or secret query/DSN parameters in a PyDAL URI before logging or UI display."""
    raw = (uri or "").strip()
    if not raw:
        return ""
    low = raw.lower()
    if low.startswith("sqlite://") or low.startswith("sqlite:memory"):
        return raw
    if "://" not in raw:
        return _redact_secret_params(raw)

    scheme, rest = raw.split("://", 1)
    sep_indices = [idx for idx in (rest.find("/"), rest.find("?")) if idx != -1]
    split_at = min(sep_indices) if sep_indices else len(rest)
    authority = rest[:split_at]
    tail = rest[split_at:]

    userinfo, at_sep, hostport = authority.rpartition("@")
    if at_sep:
        user, colon, _pwd = userinfo.partition(":")
        masked_auth = f"{user}:********@{hostport}" if colon else f"{user}@{hostport}"
        return f"{scheme}://{masked_auth}{_redact_secret_params(tail)}"

    return f"{scheme}://{_redact_secret_params(rest)}"


def _scrub_secret_from_text(text: str, secrets_to_hide: List[str]) -> str:
    cleaned = text
    for sec in secrets_to_hide:
        if sec and len(sec) >= 2:
            cleaned = cleaned.replace(sec, "********")
    return _redact_secret_params(cleaned)


def _extract_uri_password(uri: str) -> str:
    if "://" not in uri:
        return ""
    rest = uri.split("://", 1)[1]
    sep_indices = [idx for idx in (rest.find("/"), rest.find("?")) if idx != -1]
    authority = rest[: min(sep_indices)] if sep_indices else rest
    userinfo, at_sep, _hostport = authority.rpartition("@")
    if not at_sep or ":" not in userinfo:
        return ""
    return userinfo.split(":", 1)[1]


def _test_sqlite_target(target: Optional[Path]) -> Tuple[bool, str]:
    if target is None:
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute("SELECT 1;").fetchone()
        finally:
            conn.close()
        return True, "SQLite in-memory database check succeeded."

    if target.exists():
        if target.is_dir():
            return False, f"SQLite path '{target}' is a directory, not a database file."
        # Verify parent dir writability (WAL sidecar files require dir write permission) without touching target
        try:
            with tempfile.NamedTemporaryFile(
                dir=str(target.parent), prefix=".aethernms_probe_", delete=True
            ):
                pass
        except OSError as exc:
            return False, f"SQLite directory '{target.parent}' is not writable: {exc}"
        try:
            conn = sqlite3.connect(str(target), timeout=5.0)
            try:
                conn.execute("SELECT 1;").fetchone()
            finally:
                conn.close()
            return True, f"Connected to existing SQLite database: {target}"
        except sqlite3.Error as exc:
            return False, f"SQLite connection failed: {exc}"

    # Target does not exist yet — never create the .db file during connection tests.
    for parent in target.parents:
        if parent.exists():
            if not parent.is_dir():
                return False, f"Invalid SQLite path: '{parent}' is a file, not a directory."
            try:
                with tempfile.NamedTemporaryFile(
                    dir=str(parent), prefix=".aethernms_probe_", delete=True
                ):
                    pass
            except OSError as exc:
                return False, f"Target directory '{parent}' is not writable: {exc}"
            conn = sqlite3.connect(":memory:")
            try:
                conn.execute("SELECT 1;").fetchone()
            finally:
                conn.close()
            return True, f"SQLite path '{target}' is valid and writable (database file will be created upon setup)."

    return False, f"No valid parent directory found for SQLite path '{target}'."


def test_dal_connection(
    engine: str,
    params: Optional[Dict[str, Any]] = None,
    db_uri: Optional[str] = None,
    default_sqlite_path: Optional[Path | str] = None,
) -> Dict[str, Any]:
    """Validate and test connectivity for SQLite (without orphan files) or an external PyDAL URI."""
    eff_engine = (engine or "").strip().lower()
    raw_params = dict(params or {})
    if db_uri is not None:
        uri = (db_uri or "").strip()
        if not eff_engine:
            eff_engine = detect_engine_from_uri(uri)
        _validate_no_newlines(uri, "Database URI")
        if not uri:
            raise ValueError("Database URI is required.")
        if "://" not in uri and not uri.lower().startswith("sqlite:memory"):
            raise ValueError("Database URI must include a scheme such as 'scheme://...'.")
    else:
        if not eff_engine:
            eff_engine = "sqlite"
        uri = build_dal_uri(eff_engine, raw_params, default_sqlite_path=default_sqlite_path)

    effective_driver_engine = eff_engine if eff_engine != "custom" else detect_engine_from_uri(uri)
    drv_info = check_engine_drivers(
        effective_driver_engine if effective_driver_engine in DB_ENGINE_MAP else "custom"
    )
    masked = mask_dal_uri(uri)

    if effective_driver_engine == "sqlite":
        base_default = Path(default_sqlite_path) if default_sqlite_path is not None else get_db_path()
        target = parse_sqlite_uri_path(uri, base_dir=base_default.parent)
        ok, msg = _test_sqlite_target(target)
        return {
            "ok": ok,
            "engine": eff_engine,
            "uri_masked": masked,
            "message": msg,
            "driver_available": True,
            "pip_install": "",
        }

    if effective_driver_engine in DB_ENGINE_MAP and effective_driver_engine != "custom" and not drv_info["available"]:
        checked = ", ".join(drv_info["checked_drivers"])
        pip_hint = drv_info["pip_install"]
        return {
            "ok": False,
            "engine": eff_engine,
            "uri_masked": masked,
            "message": f"Missing Python database driver ({checked}). Install with: {pip_hint}",
            "driver_available": False,
            "pip_install": pip_hint,
        }

    raw_pwd = str(raw_params.get("password") or raw_params.get("db_password") or "")
    uri_pwd = _extract_uri_password(uri)
    secrets_to_hide = [s for s in (raw_pwd, uri_pwd, unquote(uri_pwd)) if s]

    with tempfile.TemporaryDirectory() as tmpdir:
        db = None
        try:
            db = DAL(
                uri,
                folder=tmpdir,
                migrate=False,
                migrate_enabled=False,
                pool_size=0,
                decode_credentials=True,
                attempts=1,
            )
            probe_sql = "SELECT 1 FROM DUAL" if effective_driver_engine == "oracle" else "SELECT 1"
            db.executesql(probe_sql)
            return {
                "ok": True,
                "engine": eff_engine,
                "uri_masked": masked,
                "message": f"Successfully connected to {masked}.",
                "driver_available": True,
                "pip_install": drv_info["pip_install"],
            }
        except Exception as exc:
            err_msg = _scrub_secret_from_text(str(exc), secrets_to_hide)
            return {
                "ok": False,
                "engine": eff_engine,
                "uri_masked": masked,
                "message": f"Connection failed: {err_msg}",
                "driver_available": drv_info["available"],
                "pip_install": drv_info["pip_install"],
            }
        finally:
            if db is not None:
                try:
                    db.close()
                except Exception:
                    pass


test_dal_connection.__test__ = False  # Prevent pytest from collecting helper as a test case


def load_db_config(config_dir: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """
    Load active database configuration, honoring `AETHERNMS_DB_URI` first,
    then `<config_dir>/db_config.json`. Returns None if unconfigured.
    """
    env_uri = os.environ.get("AETHERNMS_DB_URI", "").strip()
    if env_uri:
        return {
            "engine": detect_engine_from_uri(env_uri),
            "uri": env_uri,
            "source": "env",
        }

    cfg_path = get_db_config_path(config_dir)
    if not cfg_path.is_file():
        return None
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    uri = str(data.get("uri") or "").strip()
    if not uri:
        return None
    eng = str(data.get("engine") or "").strip().lower() or detect_engine_from_uri(uri)
    return {
        "engine": eng,
        "uri": uri,
        "sqlite_path": str(data.get("sqlite_path") or ""),
        "source": "config_file",
    }


def save_db_config(engine: str, uri: str, config_dir: Optional[Path] = None) -> Path:
    """Persist selected database configuration to `<config_dir>/db_config.json` (0o600 on POSIX)."""
    base = Path(config_dir) if config_dir is not None else runtime_root()
    base.mkdir(parents=True, exist_ok=True)
    cfg_path = get_db_config_path(base)
    eng = (engine or detect_engine_from_uri(uri)).strip().lower()
    payload: Dict[str, Any] = {
        "engine": eng,
        "uri": uri,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    if eng == "sqlite":
        parsed = parse_sqlite_uri_path(uri, base_dir=base)
        if parsed is not None:
            payload["sqlite_path"] = str(parsed)

    cfg_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(cfg_path, 0o600)
    except OSError:
        pass
    return cfg_path
