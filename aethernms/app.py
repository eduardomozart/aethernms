"""Standalone Py4Web server launcher for aethernms."""

from __future__ import annotations

import argparse
from pathlib import Path
import threading
import time
from typing import Optional, Sequence
import webbrowser

from rocket3 import Rocket3

from aethernms import __app_name__, __version__
from aethernms.web_app import create_app


def run_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    db_path: Optional[Path | str] = None,
    open_browser: bool = False,
) -> None:
    """Initialize SQLite + Py4Web routes and run the embedded Rocket3 WSGI server."""
    wsgi_app, ctx = create_app(db_path=db_path)
    url = f"http://{host}:{port}"
    print(f"{__app_name__} {__version__} (Py4Web + SQLite) running at {url}")
    print(f"Database: {ctx.db.db_path}")
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
        description="aethernms — Netmiko Config & Audit Automation (Py4Web + SQLite + IBM Carbon)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="TCP port (default: 8000)")
    parser.add_argument("--db-path", default=None, help="Custom path to SQLite database file")
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
        open_browser=args.open_browser,
    )
