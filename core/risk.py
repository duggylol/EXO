"""
Risk manager / prop-firm evaluation guard.

This is the most important safety layer. It sits between strategy intents and
the broker, and enforces account-level limits modeled on prop-firm eval rules:

  * daily loss limit           -> halt trading for the day, flatten everything
  * trailing max drawdown      -> halt for good (account would be blown)
  * max open contracts (acct)  -> reject entries that exceed it
  * max contracts per strategy -> cap per-strategy size
  * flatten-by time            -> force-flat before the session close

When a limit trips, the manager returns a RiskDecision telling the engine to
block (and optionally flatten + halt). Read your firm's exact rules and set
these numbers to match; the defaults are deliberately conservative.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .portfolio import Portfolio


@dataclass
class RiskConfig:
    daily_loss_limit: float = 1000.0        # halt the day if day P/L <= -this
    trailing_drawdown: float = 2500.0       # halt for good if equity <= peak - this
    max_contracts_account: int = 10         # total open contracts across strategies
    max_contracts_per_strategy: int = 3     # per-strategy cap
    default_contracts: int = 1              # size used when a strategy gives no hint
    flatten_after_hhmm: Optional[str] = None  # e.g. "15:55" local; None disables
    halt_on_drawdown: bool = True


@dataclass
class RiskDecision:
    approved_qty: int
    block: bool = False
    flatten_all: bool = False
    halt_day: bool = False
    halt_permanent: bool = False
    reason: str = ""


class RiskManager:
    def __init__(self, config: RiskConfig, portfolio: Portfolio):
        self.cfg = config
        self.pf = portfolio
        self.day_halted = False
        self.permanently_halted = False

    # --- continuous checks (called each bar before strategies trade) -----
    def check_account(self) -> RiskDecision:
        """Account-wide guard, evaluated every bar against live equity."""
        if self.pf.roll_day_if_needed():
            self.day_halted = False  # new day resets the daily-loss halt

        # Trailing max drawdown -> terminal.
        if (
            self.cfg.halt_on_drawdown
            and not self.permanently_halted
            and self.pf.drawdown_from_peak <= -self.cfg.trailing_drawdown
        ):
            self.permanently_halted = True
            return RiskDecision(
                0, block=True, flatten_all=True, halt_permanent=True,
                reason=(
                    f"TRAILING DRAWDOWN breached: equity {self.pf.equity:,.0f} "
                    f"<= peak {self.pf.peak_equity:,.0f} - {self.cfg.trailing_drawdown:,.0f}"
                ),
            )

        # Daily loss limit -> halt for the rest of the day.
        if not self.day_halted and self.pf.day_pnl <= -self.cfg.daily_loss_limit:
            self.day_halted = True
            return RiskDecision(
                0, block=True, flatten_all=True, halt_day=True,
                reason=f"DAILY LOSS LIMIT hit: day P/L {self.pf.day_pnl:,.0f}",
            )

        return RiskDecision(0)

    @property
    def trading_blocked(self) -> bool:
        return self.day_halted or self.permanently_halted

    # --- per-entry sizing / approval -------------------------------------
    def approve_entry(self, instance_id: str, current_open_contracts: int,
                      strategy_open: int, hint_qty: Optional[int]) -> RiskDecision:
        """Decide the size for a new/added entry, or block it."""
        if self.trading_blocked:
            return RiskDecision(0, block=True,
                                reason="trading halted (risk limit active)")

        want = hint_qty or self.cfg.default_contracts
        want = max(1, want)

        # Per-strategy cap.
        room_strat = self.cfg.max_contracts_per_strategy - abs(strategy_open)
        if room_strat <= 0:
            return RiskDecision(0, block=True,
                                reason=f"{instance_id} at per-strategy cap")
        # Account-wide cap.
        room_acct = self.cfg.max_contracts_account - current_open_contracts
        if room_acct <= 0:
            return RiskDecision(0, block=True, reason="account contract cap reached")

        qty = min(want, room_strat, room_acct)
        return RiskDecision(qty)
