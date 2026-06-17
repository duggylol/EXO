#!/usr/bin/env python3
"""
Desktop entrypoint for the packaged Mac/Windows app.

Starts the trading engine + dashboard server on a background thread, then opens
the dashboard in a NATIVE window (via pywebview). If pywebview isn't available
or fails, it falls back to opening your default browser — so it never just
breaks. Closing the window shuts the engine down cleanly.

Run in dev with:  python desktop.py
Packaged builds use this as the PyInstaller entry script (see FuturesBot.spec).
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time

# Make the repo importable when run as a plain script (dev mode).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import paths  # noqa: E402


def _setup_logging() -> None:
    """A packaged windowed app has no console, so always route output to a log
    file in the user-data dir. This both prevents print() from crashing on a
    None stdout and gives the user a log to inspect. Dev runs keep the console."""
    if not paths.is_frozen():
        return
    try:
        f = open(paths.log_path(), "a", buffering=1, encoding="utf-8")
        sys.stdout = f
        sys.stderr = f
        print(f"\n--- launch {time.strftime('%Y-%m-%d %H:%M:%S')} ---", file=f)
    except Exception:
        pass


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_until_up(port: int, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.2)
    return False


def main() -> None:
    _setup_logging()

    import uvicorn
    from core.controller import AppController
    from server import create_app

    # The native window opens automatically, so always grab a free port (avoids
    # colliding with anything on 8000). Override with BOT_PORT for testing.
    port = int(os.environ.get("BOT_PORT") or _free_port())
    host = "127.0.0.1"
    url = f"http://{host}:{port}"

    controller = AppController()
    app = create_app(controller)

    # Force pure-Python loop/http/ws stacks so the frozen bundle is portable
    # (uvloop/httptools aren't needed and complicate packaging, esp. on Windows).
    config = uvicorn.Config(app, host=host, port=port, log_level="warning",
                            loop="asyncio", http="h11", ws="websockets", lifespan="on")
    server = uvicorn.Server(config)
    server_thread = threading.Thread(target=server.run, daemon=True, name="uvicorn")
    server_thread.start()

    if not _wait_until_up(port):
        print("[desktop] server failed to start within timeout", file=sys.stderr)

    print(f"[desktop] dashboard at {url}", file=sys.stderr)

    # Native window first; browser as a robust fallback.
    try:
        import webview  # pywebview
        webview.create_window("EXO", url,
                              width=1280, height=860, min_size=(960, 600))
        webview.start()  # blocks until the window is closed
    except Exception as e:
        print(f"[desktop] native window unavailable ({e!r}); opening browser", file=sys.stderr)
        import webbrowser
        webbrowser.open(url)
        try:
            while server_thread.is_alive():
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass

    # Window closed (or interrupted) -> shut the server/engine down cleanly.
    server.should_exit = True
    server_thread.join(timeout=10)


if __name__ == "__main__":
    main()
