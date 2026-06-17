"""
VWAP reversion — fade stretches away from session VWAP back toward it.

VWAP anchors to the session, so the engine resets it at on_session_start().
Entries trigger when price is more than `atr_mult` ATRs from VWAP.
"""
from __future__ import annotations

from core.indicators import ATR, VWAP
from core.strategy import Strategy, StrategyContext, register
from core.models import Bar


@register
class VWAPReversion(Strategy):
    key = "vwap_reversion"
    display_name = "VWAP Reversion"
    description = "Buy when price is stretched below session VWAP, sell when stretched above; exit at VWAP."
    params = {"atr_period": 14, "atr_mult": 1.5}

    def setup(self) -> None:
        self.vwap = VWAP()
        self.atr = ATR(self.params["atr_period"])

    def on_session_start(self) -> None:
        self.vwap.reset()

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> None:
        v = self.vwap.update(bar.high, bar.low, bar.close, bar.volume)
        a = self.atr.update(bar.high, bar.low, bar.close)
        if v is None or a is None:
            return
        stretch = self.params["atr_mult"] * a
        if bar.close < v - stretch and ctx.is_flat:
            ctx.buy(f"price {bar.close:.2f} stretched below VWAP {v:.2f}")
        elif bar.close > v + stretch and ctx.is_flat:
            ctx.sell(f"price {bar.close:.2f} stretched above VWAP {v:.2f}")
        elif ctx.is_long and bar.close >= v:
            ctx.close("reverted to VWAP")
        elif ctx.is_short and bar.close <= v:
            ctx.close("reverted to VWAP")
