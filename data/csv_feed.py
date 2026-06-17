"""
CSV replay feed.

Replays historical bars from CSV files for forward-testing strategies against
real data. Expects one file per symbol with a header row:

    timestamp,open,high,low,close,volume

`timestamp` may be epoch seconds or ISO-8601. `speed` multiplies playback
(0 = as fast as possible). Point `files` at your CSVs in config.
"""
from __future__ import annotations

import asyncio
import csv
import time
from datetime import datetime

from core.models import Bar
from .base import DataFeed


def _parse_ts(raw: str) -> float:
    raw = raw.strip()
    try:
        return float(raw)
    except ValueError:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()


class CSVFeed(DataFeed):
    name = "csv"

    def __init__(self, settings: dict):
        super().__init__(settings)
        # files: {"ES": "data/ES_1min.csv", ...}
        self.files: dict[str, str] = settings.get("files", {})
        self.speed = float(settings.get("speed", 0.0))  # 0 = no delay

    def _load(self, symbol: str, path: str) -> list[Bar]:
        bars: list[Bar] = []
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                bars.append(Bar(
                    symbol=symbol,
                    ts=_parse_ts(row.get("timestamp") or row.get("time") or "0"),
                    open=float(row["open"]), high=float(row["high"]),
                    low=float(row["low"]), close=float(row["close"]),
                    volume=float(row.get("volume", 0) or 0),
                ))
        return bars

    async def run(self) -> None:
        self._running = True
        # Merge all symbols' bars and replay in timestamp order.
        merged: list[Bar] = []
        for sym, path in self.files.items():
            merged.extend(self._load(sym, path))
        merged.sort(key=lambda b: b.ts)

        prev_ts = None
        for bar in merged:
            if not self._running:
                break
            if self.speed > 0 and prev_ts is not None:
                await asyncio.sleep(max(0.0, (bar.ts - prev_ts) / self.speed))
            prev_ts = bar.ts
            await self._emit_bar(bar)
        self._running = False
