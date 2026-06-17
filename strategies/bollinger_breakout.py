"""Bollinger Band breakout — ride expansion beyond the upper/lower band."""
from __future__ import annotations

from core.indicators import Bollinger
from core.strategy import Strategy, StrategyContext, register
from core.models import Bar


@register
class BollingerBreakout(Strategy):
    key = "bb_breakout"
    display_name = "Bollinger Breakout"
    description = "Go long on a close above the upper band, short below the lower band; exit at the mid."
    params = {"period": 20, "mult": 2.0}

    def setup(self) -> None:
        self.bb = Bollinger(self.params["period"], self.params["mult"])

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> None:
        self.bb.update(bar.close)
        if not self.bb.ready:
            return
        if bar.close > self.bb.upper and not ctx.is_long:
            ctx.buy(f"close {bar.close:.2f} > upper band {self.bb.upper:.2f}")
        elif bar.close < self.bb.lower and not ctx.is_short:
            ctx.sell(f"close {bar.close:.2f} < lower band {self.bb.lower:.2f}")
        elif ctx.is_long and bar.close < self.bb.mid:
            ctx.close("back below mid band")
        elif ctx.is_short and bar.close > self.bb.mid:
            ctx.close("back above mid band")
