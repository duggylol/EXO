#!/usr/bin/env python3
"""
Entrypoint: serves the dashboard in your browser (terminal/dev workflow).

    python run.py     ->  open http://127.0.0.1:8000

On first run you'll see the welcome screen: pick your prop-firm provider and log
in with the credentials they gave you. The app only ever shows real data from
that connection — there is no demo/simulated mode. For the double-clickable
desktop app, use desktop.py / the packaged build instead.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.controller import AppController   # noqa: E402
from server import create_app               # noqa: E402


def main() -> None:
    import uvicorn

    controller = AppController()
    app = create_app(controller)

    srv = controller.cfg.get("server", {})
    host, port = srv.get("host", "127.0.0.1"), int(srv.get("port", 8000))
    print("─" * 60)
    print("  EXO")
    print(f"  dashboard ->  http://{host}:{port}")
    print("  (first run: pick a provider and log in on the welcome screen)")
    print("─" * 60)
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
