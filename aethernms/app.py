"""Standalone Py4Web server launcher for aethernms."""

from __future__ import annotations

import argparse
from pathlib import Path
import socket
import sys
import threading
import time
from typing import Optional, Sequence
import webbrowser

from rocket3 import Rocket3

from aethernms import __app_name__, __version__
from aethernms.web_app import create_app


def _ensure_port_available(host: str, port: int) -> None:
    """Fail fast if another process is already bound to (host, port) (prevents Windows SO_REUSEADDR shadowing)."""
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            sock.bind((host, int(port)))
        except OSError as exc:
            raise RuntimeError(
                f"Address http://{host}:{port} is already in use ({exc}). "
                f"Stop the existing server or pass --port <port>."
            ) from exc


def run_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    db_path: Optional[Path | str] = None,
    db_uri: Optional[str] = None,
    open_browser: bool = False,
) -> None:
    """Initialize Py4Web routes (and configured database) and run the embedded Rocket3 WSGI server."""
    try:
        _ensure_port_available(host, int(port))
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    wsgi_app, ctx = create_app(db_path=db_path, db_uri=db_uri)
    url = f"http://{host}:{port}"
    print(f"Data directory: {ctx.config_dir}")
    if ctx.db is None:
        print(f"{__app_name__} {__version__} (Py4Web) running at {url}")
        print(f"Setup required: {url}/setup")
    else:
        print(f"{__app_name__} {__version__} (Py4Web + {ctx.db.engine}) running at {url}")
        print(f"Database: {ctx.db.db_uri_masked}")
        if ctx.db.user_count() == 0:
            print(f"Setup required: {url}/setup")
        else:
            print(f"Swagger UI: {url}/api/docs")

    if open_browser:
        def _open() -> None:
            time.sleep(0.8)
            try:
                webbrowser.open(url)
            except Exception:
                pass

        threading.Thread(target=_open, daemon=True).start()

    server = Rocket3((host, int(port)), "wsgi", {"wsgi_app": wsgi_app})
    try:
        server.start()
    except KeyboardInterrupt:
        try:
            server.stop()
        except Exception:
            pass


def main(argv: Optional[Sequence[str]] = None) -> None:
    """CLI entry point launching the Py4Web web server."""
    parser = argparse.ArgumentParser(
        prog=__app_name__,
        description="aethernms — Netmiko Config & Audit Automation (Py4Web + PyDAL + IBM Carbon)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="TCP port (default: 8000)")
    parser.add_argument("--db-path", default=None, help="Custom path to SQLite database file")
    parser.add_argument(
        "--db-uri",
        default=None,
        help="Custom PyDAL database URI (e.g. postgres://..., mysql://..., mssql4://..., oracle://...)",
    )
    parser.add_argument(
        "--open-browser",
        action="store_true",
        help="Automatically open the web UI in the default browser after startup",
    )
    args = parser.parse_args(argv)
    run_server(
        host=args.host,
        port=args.port,
        db_path=args.db_path,
        db_uri=args.db_uri,
        open_browser=args.open_browser,
    )
