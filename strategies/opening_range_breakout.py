"""
Opening Range Breakout (ORB) — a staple intraday futures strategy.

Defines the high/low of the first N bars of the session ("opening range"), then
trades a breakout beyond it. Takes at most one long and one short attempt per
session. The engine calls on_session_start() at each new trading day.
"""
from __future__ import annotations

from core.strategy import Strategy, StrategyContext, register
from core.models import Bar


@register
class OpeningRangeBreakout(Strategy):
    key = "orb"
    display_name = "Opening Range Breakout"
    description = "Mark the first N bars' range, then trade a breakout above/below it once per session."
    params = {"range_bars": 15}

    def setup(self) -> None:
        self.on_session_start()

    def on_session_start(self) -> None:
        self._bars = 0
        self._hi = None
        self._lo = None
        self._took_long = False
        self._took_short = False

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> None:
        self._bars += 1
        n = self.params["range_bars"]
        if self._bars <= n:
            self._hi = bar.high if self._hi is None else max(self._hi, bar.high)
            self._lo = bar.low if self._lo is None else min(self._lo, bar.low)
            return
        if self._hi is None:
            return
        if bar.close > self._hi and not self._took_long and ctx.is_flat:
            self._took_long = True
            ctx.buy(f"broke opening-range high {self._hi:.2f}")
        elif bar.close < self._lo and not self._took_short and ctx.is_flat:
            self._took_short = True
            ctx.sell(f"broke opening-range low {self._lo:.2f}")
        # Protective reversion: exit if price falls back inside the range.
        elif ctx.is_long and bar.close < self._lo:
            ctx.close("fell back below range low")
        elif ctx.is_short and bar.close > self._hi:
            ctx.close("popped back above range high")
