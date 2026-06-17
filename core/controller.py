"""
AppController — owns the connection lifecycle.

The app starts with NO connection (welcome screen). When the user picks a
provider and enters the credentials their prop firm gave them, the controller
validates them, saves them locally for next time, and builds + starts the
engine bound to that real connection. Disconnecting tears the engine down.

Credentials are persisted to the per-user data dir (connection.json, chmod 600)
so the app reconnects automatically on next launch. They are stored locally
only — never transmitted anywhere except to the provider you chose.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Optional

from brokers import build_broker
from data import build_feed
from notify import DiscordNotifier
from storage import Database

from . import paths
from . import providers as providers_mod
from .config import load_config
from .engine import Engine
from .enums import EventType
from .event_bus import EventBus
from .updater import Updater
from strategies import load_all

CONNECTION_FILE = "connection.json"


class AppController:
    def __init__(self) -> None:
        load_all()
        self.cfg = load_config(os.environ.get("BOT_CONFIG"))
        self.db = Database(self.cfg["database"]["path"])
        self.notifier = DiscordNotifier(
            self.cfg.get("discord", {}).get("webhook_url", ""),
            enabled=self.cfg.get("discord", {}).get("enabled", True))
        self.bus = EventBus()                 # persistent across connections
        self.engine: Optional[Engine] = None
        self.provider_id = ""
        self.connecting = False
        self.last_error = ""
        self._lock = asyncio.Lock()
        self.updater = Updater(self.cfg.get("update", {}))
        self._update_task: Optional[asyncio.Task] = None

    # --- local persistence ------------------------------------------------
    def _conn_path(self):
        return paths.user_data_dir() / CONNECTION_FILE

    def _save_connection(self, provider_id: str, fields: dict) -> None:
        p = self._conn_path()
        p.write_text(json.dumps({"provider": provider_id, "fields": fields}, indent=2))
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass

    def _load_connection(self) -> Optional[dict]:
        p = self._conn_path()
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text())
        except Exception:
            return None

    def clear_connection(self) -> None:
        p = self._conn_path()
        if p.exists():
            p.unlink()

    def has_saved(self) -> bool:
        return self._conn_path().exists()

    # --- queries ----------------------------------------------------------
    def providers(self) -> list[dict]:
        return providers_mod.public_list()

    def status(self) -> dict:
        eng = self.engine
        return {
            "connected": bool(eng and eng.broker.connected),
            "connecting": self.connecting,
            "provider": self.provider_id,
            "provider_name": (providers_mod.get_provider(self.provider_id).name
                              if self.provider_id else ""),
            "mode": ("trading" if (eng and eng.feed) else "monitor") if eng else None,
            "account_sync": bool(eng and eng.broker.supports_account_data),
            "has_saved": self.has_saved(),
            "error": self.last_error,
        }

    def snapshot(self) -> dict:
        if self.engine:
            return self.engine.snapshot()
        return {
            "connected": False, "provider": "", "broker": None, "feed": None,
            "mode": None, "account_sync": False, "status": "not connected",
            "account": {"synced": False}, "risk": {}, "live_positions": [],
            "strategies": [], "equity_curve": [], "recent_trades": [],
        }

    # --- connection lifecycle --------------------------------------------
    async def auto_connect(self) -> None:
        saved = self._load_connection()
        if saved and saved.get("provider"):
            try:
                await self.connect(saved["provider"], saved.get("fields", {}), save=False)
            except Exception as e:
                self.last_error = str(e)
                print(f"[controller] auto-connect failed: {e!r}", file=sys.stderr)

    async def connect(self, provider_id: str, fields: dict, save: bool = True) -> dict:
        async with self._lock:
            self.connecting = True
            self.last_error = ""
            try:
                spec = providers_mod.get_provider(provider_id)
                broker = build_broker(spec.broker_type, fields)
                ok, msg = await broker.test_connection()
                if not ok:
                    self.last_error = msg
                    try:
                        await broker.disconnect()   # release any open HTTP session
                    except Exception:
                        pass
                    return {"ok": False, "error": msg}

                feed = None
                if spec.feed_type:
                    symbols = sorted({s["symbol"].upper()
                                      for s in self.cfg.get("strategies", [])})
                    feed_settings = dict(fields)
                    feed_settings["symbols"] = symbols
                    try:
                        feed = build_feed(spec.feed_type, feed_settings)
                    except Exception as e:
                        # Account monitoring still works without market data.
                        print(f"[controller] market feed unavailable: {e!r}", file=sys.stderr)
                        feed = None

                if self.engine is not None:
                    await self.engine.stop()
                    self.engine = None

                self.engine = Engine(self.cfg, broker=broker, notifier=self.notifier,
                                     db=self.db, feed=feed, provider=provider_id, bus=self.bus)
                await self.engine.start()
                self.provider_id = provider_id
                if save:
                    self._save_connection(provider_id, fields)
                return {"ok": True, "message": msg}
            except Exception as e:
                self.last_error = str(e)
                return {"ok": False, "error": str(e)}
            finally:
                self.connecting = False

    async def disconnect(self, forget: bool = False) -> None:
        async with self._lock:
            if self.engine is not None:
                await self.engine.stop()
                self.engine = None
            self.provider_id = ""
            if forget:
                self.clear_connection()

    async def shutdown(self) -> None:
        if self._update_task is not None:
            self._update_task.cancel()
        if self.engine is not None:
            await self.engine.stop()
        await self.notifier.close()
        self.db.close()

    # --- auto-update ------------------------------------------------------
    def start_background(self) -> None:
        if self.updater.enabled and self.updater.configured and self._update_task is None:
            self._update_task = asyncio.create_task(self._update_loop())

    async def _update_loop(self) -> None:
        interval = float(self.cfg.get("update", {}).get("check_interval_hours", 6)) * 3600
        await asyncio.sleep(8)
        while True:
            try:
                info = await self.updater.check()
                if info and self.updater.available:
                    await self.bus.publish(EventType.UPDATE, self.updater.status())
            except Exception as e:
                print(f"[controller] update check error: {e!r}", file=sys.stderr)
            await asyncio.sleep(max(900.0, interval))

    def update_status(self) -> dict:
        return self.updater.status()

    async def check_updates(self) -> dict:
        info = await self.updater.check()
        if info and self.updater.available:
            await self.bus.publish(EventType.UPDATE, self.updater.status())
        return self.updater.status()

    async def apply_update(self) -> dict:
        if not self.updater.available:
            return {"ok": False, "error": "no update available"}
        try:
            extracted = await self.updater.download(self.updater.latest)
            new_app = self.updater._find_new_app(extracted)
            if not new_app:
                return {"ok": False, "error": "could not locate new app in the download"}
            self.updater.spawn_swap(new_app)
        except Exception as e:
            return {"ok": False, "error": str(e)}
        # Let the HTTP response flush, then hard-exit so the (already-waiting)
        # swap script can replace the bundle and relaunch. Saved data is in the
        # user-data dir and is untouched.
        import threading
        threading.Timer(1.2, lambda: os._exit(0)).start()
        return {"ok": True}

    # control passthrough
    def toggle_strategy(self, instance_id: str) -> bool:
        if not self.engine:
            raise KeyError(instance_id)
        return self.engine.toggle_strategy(instance_id)

    async def flatten_all(self) -> None:
        if self.engine:
            await self.engine.flatten_all_now()
