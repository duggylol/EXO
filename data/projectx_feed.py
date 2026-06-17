"""
ProjectX real-time market data feed (SignalR market hub).

ProjectX trading ops are REST (see brokers/projectx.py), but live quotes/bars
come over a SignalR WebSocket "market hub". This is a structural skeleton:
install a SignalR client (`pip install signalrcore`) and fill in the hub URL +
subscription messages from your firm's ProjectX docs
(https://gateway.docs.projectx.com — Realtime / market hub section).

If you only need bars (not tick-by-tick), the simplest robust approach is to
poll/aggregate quotes into bars here, or reuse the same auth token from the
ProjectX broker. For most strategies in this repo, 1-minute bars are enough.
"""
from __future__ import annotations

import asyncio
import sys
import time

from core.models import Bar
from .base import DataFeed

try:
    from signalrcore.hub_connection_builder import HubConnectionBuilder  # type: ignore
except ImportError:  # pragma: no cover
    HubConnectionBuilder = None


class ProjectXFeed(DataFeed):
    name = "projectx"

    def __init__(self, settings: dict):
        super().__init__(settings)
        self.hub_url = settings.get("market_hub_url", "")  # wss://.../hubs/market
        self.token = settings.get("token", "")             # bearer from ProjectX auth
        self._conn = None
        # Simple quote->bar aggregation buffer per symbol.
        self._agg: dict[str, dict] = {}
        self.bar_seconds = int(settings.get("bar_seconds", 60))

    def _ingest_quote(self, symbol: str, price: float, size: float) -> None:
        now = time.time()
        bucket = int(now // self.bar_seconds)
        a = self._agg.get(symbol)
        if a is None or a["bucket"] != bucket:
            if a is not None:
                # Previous bucket closed -> emit its bar.
                asyncio.create_task(self._emit_bar(Bar(
                    symbol=symbol, ts=now, open=a["o"], high=a["h"],
                    low=a["l"], close=a["c"], volume=a["v"],
                )))
            self._agg[symbol] = {"bucket": bucket, "o": price, "h": price,
                                 "l": price, "c": price, "v": size}
        else:
            a["h"] = max(a["h"], price)
            a["l"] = min(a["l"], price)
            a["c"] = price
            a["v"] += size

    async def run(self) -> None:
        if HubConnectionBuilder is None:
            raise RuntimeError("signalrcore not installed. pip install signalrcore")
        if not self.hub_url or not self.token:
            raise RuntimeError("ProjectX feed needs market_hub_url + token (see docs).")

        self._running = True
        self._conn = (
            HubConnectionBuilder()
            .with_url(f"{self.hub_url}?access_token={self.token}")
            .with_automatic_reconnect({"type": "raw", "keep_alive_interval": 10})
            .build()
        )

        def on_quote(args) -> None:
            # Shape depends on the firm's hub; typically [symbol, {lastPrice,...}].
            try:
                sym, q = args[0], args[1]
                self._ingest_quote(sym, float(q.get("lastPrice")), float(q.get("volume", 0)))
            except Exception as e:
                print(f"[projectx-feed] quote parse error: {e!r}", file=sys.stderr)

        self._conn.on("GatewayQuote", on_quote)
        self._conn.start()
        for sym in self.symbols:
            self._conn.send("SubscribeContractQuotes", [sym])
        print(f"[projectx-feed] subscribed to {self.symbols}", file=sys.stderr)

        while self._running:
            await asyncio.sleep(1.0)

    async def stop(self) -> None:
        self._running = False
        if self._conn is not None:
            try:
                self._conn.stop()
            except Exception:
                pass
