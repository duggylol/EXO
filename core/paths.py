"""
Path resolution that works both in development and inside a packaged desktop
app (PyInstaller .app / .exe).

Two kinds of location:
  * RESOURCES (read-only) — bundled assets: dashboard static files, the default
    config. In dev these are the repo files; when frozen they live in the
    PyInstaller temp dir (sys._MEIPASS).
  * USER DATA (writable) — config the user edits, the SQLite database, .env,
    and logs. Must NOT be inside the app bundle (which can be read-only or get
    replaced on update). In dev we keep using the repo folder so the terminal
    workflow is unchanged; when frozen we use the OS per-user app-data folder.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "EXO"

_REPO_ROOT = Path(__file__).resolve().parent.parent


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> Path:
    """Root for read-only bundled resources."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", _REPO_ROOT))
    return _REPO_ROOT


def resource_path(rel: str) -> Path:
    return resource_dir() / rel


def user_data_dir() -> Path:
    """Writable per-user folder for config, db, logs. Created if missing."""
    if not is_frozen():
        # Dev mode: keep everything in the repo so `python run.py` is unchanged.
        return _REPO_ROOT
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_NAME
    elif sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def config_path() -> Path:
    """The config file to load/edit. When frozen, seed it from the bundled default."""
    if not is_frozen():
        return _REPO_ROOT / "config" / "config.yaml"
    user_cfg = user_data_dir() / "config.yaml"
    if not user_cfg.exists():
        default = resource_path("config/config.yaml")
        if default.exists():
            shutil.copyfile(default, user_cfg)
    return user_cfg


def env_path() -> Path:
    return user_data_dir() / ".env"


def db_path(configured: str) -> str:
    """Resolve a configured DB path against the writable user-data dir."""
    p = Path(configured)
    if p.is_absolute():
        return str(p)
    return str(user_data_dir() / configured)


def log_path() -> Path:
    return user_data_dir() / "exo.log"
