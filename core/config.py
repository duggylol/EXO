"""
Configuration loader: YAML file + environment-variable overlay for secrets.

Secrets (API keys, webhook URLs, passwords) should live in .env, never in
config.yaml. This merges them so config.yaml can be committed safely.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml

from . import paths

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


def load_config(path: Optional[str] = None) -> dict:
    if load_dotenv:
        # Prefer a .env in the writable user-data dir (desktop app); fall back
        # to a repo-local .env for the terminal workflow.
        env_file = paths.env_path()
        load_dotenv(env_file if env_file.exists() else None)

    cfg = {}
    p = Path(path) if path else paths.config_path()
    if p.exists():
        cfg = yaml.safe_load(p.read_text()) or {}

    cfg.setdefault("account", {})
    cfg.setdefault("risk", {})
    cfg.setdefault("strategies", [])
    cfg.setdefault("broker", {"type": "paper"})
    cfg.setdefault("feed", {"type": "simulated"})
    cfg.setdefault("discord", {})
    cfg.setdefault("server", {"host": "127.0.0.1", "port": 8000})
    cfg.setdefault("database", {"path": "tradingbot.db"})
    cfg.setdefault("update", {})

    # Overlay secrets from environment.
    env = os.environ
    bset = cfg["broker"].setdefault("settings", {})
    if env.get("PROJECTX_USERNAME"): bset["username"] = env["PROJECTX_USERNAME"]
    if env.get("PROJECTX_API_KEY"): bset["api_key"] = env["PROJECTX_API_KEY"]
    if env.get("PROJECTX_ACCOUNT"): bset["account_name"] = env["PROJECTX_ACCOUNT"]
    if env.get("PROJECTX_BASE_URL"): bset["base_url"] = env["PROJECTX_BASE_URL"]
    if env.get("TRADERSPOST_WEBHOOK_URL"): bset["webhook_url"] = env["TRADERSPOST_WEBHOOK_URL"]
    if env.get("TRADERSPOST_SECRET"): bset["shared_secret"] = env["TRADERSPOST_SECRET"]

    fset = cfg["feed"].setdefault("settings", {})
    if env.get("RITHMIC_USER"): fset["user"] = env["RITHMIC_USER"]
    if env.get("RITHMIC_PASSWORD"): fset["password"] = env["RITHMIC_PASSWORD"]
    if env.get("RITHMIC_SYSTEM"): fset["system_name"] = env["RITHMIC_SYSTEM"]
    if env.get("RITHMIC_GATEWAY"): fset["gateway"] = env["RITHMIC_GATEWAY"]

    if env.get("DISCORD_WEBHOOK_URL"):
        cfg["discord"]["webhook_url"] = env["DISCORD_WEBHOOK_URL"]

    # Resolve the database to a writable location (user-data dir when frozen).
    cfg["database"]["path"] = paths.db_path(cfg["database"].get("path", "tradingbot.db"))

    return cfg
