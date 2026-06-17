"""
Synthetic market data feed.

Generates realistic-looking OHLC bars via a random walk with per-instrument
volatility, so the entire platform — strategies, risk, brokers, dashboard —
runs end-to-end with no data subscription and no credentials. Use it to develop
and demo, then switch `feed` to `rithmic`/`projectx`/`csv` in config.

`interval_s` controls how fast bars arrive (default 1s = one "bar" per second,
which makes the dashboard lively). `seed` makes runs reproducible.
"""
from __future__ import annotations

import asyncio
import random
import time

from core.instruments import get_instrument
from core.models import Bar
from .base import DataFeed

# Reasonable starting prices so charts look familiar.
_BASE_PRICES = {
    "ES": 5600.0, "MES": 5600.0, "NQ": 20000.0, "MNQ": 20000.0,
    "RTY": 2250.0, "M2K": 2250.0, "YM": 42000.0, "MYM": 42000.0,
    "GC": 2650.0, "MGC": 2650.0, "SI": 31.0, "CL": 72.0, "MCL": 72.0,
    "NG": 2.8, "ZB": 118.0, "ZN": 110.0, "6E": 1.08, "6J": 0.0067,
}


class SimulatedFeed(DataFeed):
    name = "simulated"

    def __init__(self, settings: dict):
        super().__init__(settings)
        self.interval_s = float(settings.get("interval_s", 1.0))
        self.vol_bps = float(settings.get("vol_bps", 8.0))  # per-bar vol, basis points
        seed = settings.get("seed")
        self._rng = random.Random(seed)
        self._price: dict[str, float] = {
            s: float(_BASE_PRICES.get(s.upper(), 1000.0)) for s in self.symbols
        }

    def _next_bar(self, symbol: str) -> Bar:
        instr = get_instrument(symbol)
        prev = self._price[symbol]
        # Geometric-ish random walk with slight mean drift toward 0.
        drift = self._rng.gauss(0, 1) * (self.vol_bps / 10000.0) * prev
        close = max(instr.tick_size, prev + drift)
        # Snap to tick.
        close = round(close / instr.tick_size) * instr.tick_size
        o = prev
        hi = max(o, close) + abs(self._rng.gauss(0, 1)) * instr.tick_size * 2
        lo = min(o, close) - abs(self._rng.gauss(0, 1)) * instr.tick_size * 2
        hi = round(hi / instr.tick_size) * instr.tick_size
        lo = round(lo / instr.tick_size) * instr.tick_size
        vol = self._rng.randint(50, 1500)
        self._price[symbol] = close
        return Bar(symbol=symbol, ts=time.time(), open=o, high=hi, low=lo,
                   close=close, volume=vol)

    async def run(self) -> None:
        self._running = True
        if not self.symbols:
            return
        while self._running:
            for sym in self.symbols:
                await self._emit_bar(self._next_bar(sym))
            await asyncio.sleep(self.interval_s)
