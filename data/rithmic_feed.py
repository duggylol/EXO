"""
Rithmic live data feed via the open-source `async_rithmic` library (MIT).

This is the cross-platform path (Mac/Windows/Linux): async_rithmic speaks
Rithmic's Protocol Buffer interface, so you do NOT need the Windows-only .NET
R|API. Install with:  pip install async-rithmic

You must supply your own Rithmic gateway credentials (user, password,
system_name, gateway). On a personal broker account (e.g. AMP) these come with
the ~$125/mo R|API technology package + CME market-data fees. On a prop account,
the firm must provision API-enabled Rithmic access — many do not for evals.

The exact method/event names below follow async_rithmic's documented API; if the
library version differs, check https://github.com/rundef/async_rithmic.
"""
from __future__ import annotations

import sys

from core.models import Bar
from .base import DataFeed

try:
    from async_rithmic import RithmicClient  # type: ignore
    try:
        from async_rithmic import TimeBarType  # type: ignore
    except Exception:
        TimeBarType = None
except ImportError:  # pragma: no cover
    RithmicClient = None
    TimeBarType = None


class RithmicFeed(DataFeed):
    name = "rithmic"

    def __init__(self, settings: dict):
        super().__init__(settings)
        self.user = settings.get("user", "")
        self.password = settings.get("password", "")
        self.system_name = settings.get("system_name", "Rithmic Paper Trading")
        self.gateway = settings.get("gateway", "Rithmic Paper Trading")
        self.app_name = settings.get("app_name", "futures-trading-bot")
        self.app_version = settings.get("app_version", "1.0")
        self.exchange = settings.get("exchange", "CME")
        self.bar_period = int(settings.get("bar_period", 1))  # minutes
        self._client = None

    async def run(self) -> None:
        if RithmicClient is None:
            raise RuntimeError("async_rithmic not installed. pip install async-rithmic")
        if not (self.user and self.password):
            raise RuntimeError("Rithmic feed needs user + password (see config/.env).")

        self._running = True
        self._client = RithmicClient(
            user=self.user, password=self.password,
            system_name=self.system_name, app_name=self.app_name,
            app_version=self.app_version, gateway=self.gateway,
        )

        async def on_time_bar(data) -> None:
            # `data` fields follow async_rithmic's time-bar payload.
            try:
                bar = Bar(
                    symbol=data["symbol"],
                    ts=float(data.get("bar_end_datetime", 0) or 0) or __import__("time").time(),
                    open=float(data["open"]), high=float(data["high"]),
                    low=float(data["low"]), close=float(data["close"]),
                    volume=float(data.get("volume", 0) or 0),
                )
            except (KeyError, TypeError) as e:
                print(f"[rithmic] bad bar payload {data!r}: {e}", file=sys.stderr)
                return
            await self._emit_bar(bar)

        await self._client.connect()
        # async_rithmic exposes event emitters; subscribe our handler.
        self._client.on_time_bar += on_time_bar
        for sym in self.symbols:
            await self._client.subscribe_to_time_bar_data(
                sym, self.exchange,
                **({"bar_type": TimeBarType.MINUTE_BAR} if TimeBarType else {}),
                bar_type_period=self.bar_period,
            )
        print(f"[rithmic] subscribed to {self.symbols}", file=sys.stderr)

        # Keep the connection alive; async_rithmic drives callbacks internally.
        import asyncio
        while self._running:
            await asyncio.sleep(1.0)

    async def stop(self) -> None:
        self._running = False
        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception:
                pass
