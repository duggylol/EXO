"""
SQLite persistence for trades, fills, and equity samples.

Lightweight and synchronous (sqlite3 is fast for this volume). The engine calls
these from the event loop; writes are tiny so we don't bother threading them.
Trade history survives restarts so the dashboard shows cumulative stats.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from core.models import Fill, Trade


class Database:
    def __init__(self, path: str = "tradingbot.db"):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True) if "/" in path else None
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id TEXT PRIMARY KEY, strategy_id TEXT, symbol TEXT, direction TEXT,
                qty INTEGER, entry_price REAL, exit_price REAL,
                entry_ts REAL, exit_ts REAL, pnl REAL, commission REAL
            );
            CREATE TABLE IF NOT EXISTS fills (
                order_id TEXT, strategy_id TEXT, symbol TEXT, side TEXT,
                qty INTEGER, price REAL, commission REAL, ts REAL
            );
            CREATE TABLE IF NOT EXISTS equity (
                ts REAL, equity REAL
            );
            CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades(strategy_id);
            CREATE INDEX IF NOT EXISTS idx_equity_ts ON equity(ts);
            """
        )
        self.conn.commit()

    def save_trade(self, t: Trade) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (t.id, t.strategy_id, t.symbol, t.direction, t.qty, t.entry_price,
             t.exit_price, t.entry_ts, t.exit_ts, t.pnl, t.commission),
        )
        self.conn.commit()

    def save_fill(self, f: Fill) -> None:
        self.conn.execute(
            "INSERT INTO fills VALUES (?,?,?,?,?,?,?,?)",
            (f.order_id, f.strategy_id, f.symbol, f.side.value, f.qty, f.price,
             f.commission, f.ts),
        )
        self.conn.commit()

    def save_equity(self, equity: float) -> None:
        self.conn.execute("INSERT INTO equity VALUES (?,?)", (time.time(), equity))
        self.conn.commit()

    def recent_trades(self, limit: int = 200) -> list[dict]:
        cur = self.conn.execute(
            "SELECT * FROM trades ORDER BY exit_ts DESC LIMIT ?", (limit,)
        )
        return [dict(r) for r in cur.fetchall()]

    def close(self) -> None:
        self.conn.close()
