"""
Account-level portfolio accounting.

Tracks realized/unrealized P/L, account equity, the equity curve, a peak for
trailing-drawdown logic, and the closed-trade ledger. Per-strategy positions
live on each StrategyRunner; this object aggregates them for the account.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from .models import Trade


@dataclass
class Portfolio:
    starting_balance: float
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    commission_paid: float = 0.0
    peak_equity: float = 0.0
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[tuple[float, float]] = field(default_factory=list)  # (ts, equity)
    _day_start_balance: float = 0.0
    _day_key: str = ""

    def __post_init__(self) -> None:
        self.peak_equity = self.starting_balance
        self._day_start_balance = self.starting_balance
        self._day_key = self._today_key()
        self.equity_curve.append((time.time(), self.starting_balance))

    @staticmethod
    def _today_key() -> str:
        return time.strftime("%Y-%m-%d", time.localtime())

    @property
    def equity(self) -> float:
        return self.starting_balance + self.realized_pnl + self.unrealized_pnl - self.commission_paid

    @property
    def balance(self) -> float:
        """Closed balance (no open P/L)."""
        return self.starting_balance + self.realized_pnl - self.commission_paid

    @property
    def day_pnl(self) -> float:
        """P/L since the start of the current trading day (incl. open)."""
        return self.equity - self._day_start_balance

    @property
    def total_pnl(self) -> float:
        return self.equity - self.starting_balance

    @property
    def drawdown_from_peak(self) -> float:
        """Negative number when below the peak."""
        return self.equity - self.peak_equity

    def roll_day_if_needed(self) -> bool:
        key = self._today_key()
        if key != self._day_key:
            self._day_key = key
            self._day_start_balance = self.balance  # lock in closed balance
            return True
        return False

    def set_unrealized(self, value: float) -> None:
        self.unrealized_pnl = value
        eq = self.equity
        if eq > self.peak_equity:
            self.peak_equity = eq

    def record_trade(self, trade: Trade) -> None:
        self.realized_pnl += trade.pnl
        self.commission_paid += trade.commission
        self.trades.append(trade)
        eq = self.equity
        if eq > self.peak_equity:
            self.peak_equity = eq

    def sample_equity(self, max_points: int = 1500) -> None:
        self.equity_curve.append((time.time(), self.equity))
        if len(self.equity_curve) > max_points:
            # Down-sample oldest half to keep the curve light for the dashboard.
            self.equity_curve = self.equity_curve[-max_points:]
