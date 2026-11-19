"""Tests for multi-backend PyDAL configuration, URI building/masking, driver checks, and non-SQLite DatabaseStore."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import types

import pytest

import aethernms.db as db_mod
import aethernms.db_config as db_cfg
from aethernms.db import DatabaseStore
from aethernms.db_config import (
    build_dal_uri,
    check_engine_drivers,
    detect_engine_from_uri,
    get_supported_engines_info,
    load_db_config,
    mask_dal_uri,
    parse_sqlite_uri_path,
    save_db_config,
    test_dal_connection as run_dal_connection_test,
)


def test_engine_catalog_and_driver_checks(monkeypatch, tmp_path: Path):
    real_find_spec = importlib.util.find_spec

    def fake_find_spec(name: str, *args, **kwargs):
        if name in ("psycopg2", "pg8000", "pymysql", "MySQLdb", "pyodbc", "oracledb", "cx_Oracle"):
            return None
        return real_find_spec(name, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)
    engines = {e["id"]: e for e in get_supported_engines_info(tmp_path / "aethernms.db")}
    assert list(engines.keys()) == ["sqlite", "postgres", "mysql", "mssql", "oracle", "custom"]
    assert engines["sqlite"]["driver_available"] is True
    assert engines["postgres"]["driver_available"] is False
    assert "psycopg2-binary" in engines["postgres"]["pip_install"]
    assert engines["mysql"]["driver_available"] is False
    assert "pymysql" in engines["mysql"]["pip_install"]
    assert engines["mssql"]["driver_available"] is False
    assert "pyodbc" in engines["mssql"]["pip_install"]
    assert engines["oracle"]["driver_available"] is False
    assert "oracledb" in engines["oracle"]["pip_install"]
    assert engines["custom"]["driver_available"] is True

    # Simulate pg8000 present -> postgres becomes available
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, *a, **kw: object() if name == "pg8000" else fake_find_spec(name, *a, **kw),
    )
    pg = check_engine_drivers("postgres")
    assert pg["available"] is True
    assert pg["installed_drivers"] == ["pg8000"]


def test_build_dal_uri_for_all_engines_and_validation(tmp_path: Path):
    default_db = tmp_path / "aethernms.db"
    assert build_dal_uri("sqlite", {}, default_sqlite_path=default_db) == f"sqlite://{default_db.as_posix()}"
    assert (
        build_dal_uri("sqlite", {"sqlite_path": "nested/custom.db"}, default_sqlite_path=default_db)
        == f"sqlite://{(tmp_path / 'nested' / 'custom.db').as_posix()}"
    )
    assert build_dal_uri("sqlite", {"sqlite_path": "sqlite:memory"}) == "sqlite:memory"

    # Existing directory cannot be used as SQLite file
    subdir = tmp_path / "dir_not_file"
    subdir.mkdir()
    with pytest.raises(ValueError, match="directory"):
        build_dal_uri("sqlite", {"sqlite_path": str(subdir)})

    # PostgreSQL with URL-encoded special characters and IPv6 host
    pg_uri = build_dal_uri(
        "postgres",
        {
            "host": "2001:db8::10",
            "port": 5433,
            "database": "/aethernms_prod",
            "username": "netops@corp",
            "password": "p@ss:w/rd#1!",
            "extra_params": "sslmode=require",
        },
    )
    assert (
        pg_uri
        == "postgres://netops%40corp:p%40ss%3Aw%2Frd%231%21@[2001:db8::10]:5433/aethernms_prod?sslmode=require"
    )
    assert detect_engine_from_uri(pg_uri) == "postgres"

    # MySQL default port
    my_uri = build_dal_uri(
        "mysql",
        {"host": "db.local", "database": "anms", "username": "root", "password": "secret"},
    )
    assert my_uri == "mysql://root:secret@db.local:3306/anms"
    assert detect_engine_from_uri(my_uri) == "mysql"

    # MSSQL auto-wraps ODBC driver
    ms_uri = build_dal_uri(
        "mssql",
        {
            "host": "sql.local",
            "database": "aethernms",
            "username": "sa",
            "password": "Pass!123",
            "odbc_driver": "ODBC Driver 18 for SQL Server",
            "extra_params": "TrustServerCertificate=yes",
        },
    )
    assert (
        ms_uri
        == "mssql4://sa:Pass%21123@sql.local:1433/aethernms?DRIVER={ODBC Driver 18 for SQL Server}&TrustServerCertificate=yes"
    )
    assert detect_engine_from_uri(ms_uri) == "mssql"

    # Oracle
    ora_uri = build_dal_uri(
        "oracle",
        {"host": "ora.local", "database": "orclpdb1", "username": "system", "password": "ora"},
    )
    assert ora_uri == "oracle://system:ora@ora.local:1521/orclpdb1"
    assert detect_engine_from_uri(ora_uri) == "oracle"

    # Custom URI
    cust = build_dal_uri("custom", {"custom_uri": "firebird://sysdba:masterkey@127.0.0.1:3050/anms.fdb"})
    assert cust.startswith("firebird://")
    assert detect_engine_from_uri(cust) == "custom"

    # Validation failures
    with pytest.raises(ValueError, match="host"):
        build_dal_uri("postgres", {"host": "", "database": "db", "username": "u"})
    with pytest.raises(ValueError, match="port"):
        build_dal_uri("postgres", {"host": "h", "port": 70000, "database": "db", "username": "u"})
    with pytest.raises(ValueError, match="scheme"):
        build_dal_uri("custom", {"custom_uri": "not-a-uri"})


def test_mask_dal_uri_and_parse_windows_sqlite_path(tmp_path: Path):
    assert mask_dal_uri(f"sqlite://{(tmp_path / 'aethernms.db').as_posix()}").startswith("sqlite://")
    assert mask_dal_uri("sqlite:memory") == "sqlite:memory"
    assert (
        mask_dal_uri("postgres://user:p%40ss%3A123@db.local:5432/anms?sslmode=require")
        == "postgres://user:********@db.local:5432/anms?sslmode=require"
    )
    # Even raw unencoded '@' or ':' inside password in custom URI is masked completely
    assert (
        mask_dal_uri("postgres://user:raw@pass:with:colons@db.local:5432/anms")
        == "postgres://user:********@db.local:5432/anms"
    )
    # Redact query/DSN password attributes
    assert (
        mask_dal_uri("mssql4://sa:TopSecret@sql.local:1433/anms?DRIVER={ODBC}&PWD=TopSecret&password=abc")
        == "mssql4://sa:********@sql.local:1433/anms?DRIVER={ODBC}&PWD=********&password=********"
    )

    assert parse_sqlite_uri_path("sqlite:///C:/Users/demo/aethernms.db") == Path("C:/Users/demo/aethernms.db")
    assert parse_sqlite_uri_path("sqlite:memory") is None


def test_test_dal_connection_sqlite_never_leaves_orphan_db(tmp_path: Path):
    target = tmp_path / "never_created.db"
    res = run_dal_connection_test("sqlite", {"sqlite_path": str(target)})
    assert res["ok"] is True
    assert not target.exists()

    # Existing SQLite file also succeeds
    existing = tmp_path / "existing.db"
    existing.touch()
    res_ex = run_dal_connection_test("sqlite", {"sqlite_path": str(existing)})
    assert res_ex["ok"] is True

    # Regular file in parent path fails cleanly
    blocker = tmp_path / "file_not_dir"
    blocker.write_text("x", encoding="utf-8")
    res_bad = run_dal_connection_test("sqlite", {"sqlite_path": str(blocker / "sub.db")})
    assert res_bad["ok"] is False


def test_test_dal_connection_external_missing_driver_and_mocked_pydal(monkeypatch):
    real_find_spec = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, *a, **kw: None if name in ("psycopg2", "pg8000") else real_find_spec(name, *a, **kw),
    )
    missing = run_dal_connection_test(
        "postgres",
        {"host": "db.local", "database": "anms", "username": "u", "password": "secret"},
    )
    assert missing["ok"] is False
    assert missing["driver_available"] is False
    assert "pip install psycopg2-binary" in missing["pip_install"]
    assert "secret" not in missing["message"]

    # Mock driver installed + DAL probe
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, *a, **kw: object() if name == "psycopg2" else real_find_spec(name, *a, **kw),
    )

    calls = []

    class FakeDAL:
        def __init__(self, uri, **kwargs):
            calls.append(("init", uri, kwargs))

        def executesql(self, sql):
            calls.append(("sql", sql))
            return [(1,)]

        def close(self):
            calls.append(("close",))

    monkeypatch.setattr(db_cfg, "DAL", FakeDAL)
    ok_res = run_dal_connection_test(
        "postgres",
        {"host": "db.local", "database": "anms", "username": "u", "password": "MySecretPassword!"},
    )
    assert ok_res["ok"] is True
    assert "MySecretPassword" not in ok_res["uri_masked"]
    assert calls[0][2]["decode_credentials"] is True
    assert ("sql", "SELECT 1") in calls
    assert ("close",) in calls

    # Password scrubbed from exception message on failure
    class FailingDAL:
        def __init__(self, uri, **kwargs):
            raise RuntimeError("auth failed for password MySecretPassword!")

    monkeypatch.setattr(db_cfg, "DAL", FailingDAL)
    err_res = run_dal_connection_test(
        "postgres",
        {"host": "db.local", "database": "anms", "username": "u", "password": "MySecretPassword!"},
    )
    assert err_res["ok"] is False
    assert "MySecretPassword" not in err_res["message"]


def test_save_load_db_config_and_env_override(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("AETHERNMS_DB_URI", raising=False)
    assert load_db_config(config_dir=tmp_path) is None

    db_file = tmp_path / "aethernms.db"
    saved_path = save_db_config("sqlite", f"sqlite://{db_file.as_posix()}", config_dir=tmp_path)
    assert saved_path == tmp_path / "db_config.json"

    loaded = load_db_config(config_dir=tmp_path)
    assert loaded is not None
    assert loaded["engine"] == "sqlite"
    assert loaded["source"] == "config_file"

    monkeypatch.setenv("AETHERNMS_DB_URI", "postgres://u:p@db.internal:5432/aethernms")
    overridden = load_db_config(config_dir=tmp_path)
    assert overridden is not None
    assert overridden["engine"] == "postgres"
    assert overridden["source"] == "env"


def test_database_store_non_sqlite_skips_pragmas_and_adapter_args(monkeypatch, tmp_path: Path):
    captured = []

    class FakeDAL:
        def __init__(self, uri, **kwargs):
            self.uri = uri
            self.kwargs = kwargs
            captured.append(self)

        def executesql(self, sql):
            raise AssertionError(f"Unexpected executesql on non-SQLite bootstrap: {sql}")

        def commit(self):
            return None

        def close(self):
            return None

    monkeypatch.setattr(db_mod, "DAL", FakeDAL)
    monkeypatch.setattr(db_mod, "_define_tables", lambda db: None)
    monkeypatch.setattr(DatabaseStore, "_seed_default_roles_in_tx", staticmethod(lambda db: None))

    meta_dir = tmp_path / "dal_meta"
    store = DatabaseStore(
        db_uri="postgres://netops:SuperSecret!@pg.internal:5432/aethernms",
        folder=meta_dir,
        engine="postgres",
    )
    assert store.is_sqlite is False
    assert store.engine == "postgres"
    assert store.db_path is None
    assert store.db_uri_masked == "postgres://netops:********@pg.internal:5432/aethernms"
    assert len(captured) == 1
    assert captured[0].kwargs["folder"] == str(meta_dir)
    assert captured[0].kwargs["decode_credentials"] is True
    assert "adapter_args" not in captured[0].kwargs
