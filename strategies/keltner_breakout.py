"""Keltner channel breakout — EMA-centered, ATR-width channel breakout."""
from __future__ import annotations

from core.indicators import Keltner
from core.strategy import Strategy, StrategyContext, register
from core.models import Bar


@register
class KeltnerBreakout(Strategy):
    key = "keltner"
    display_name = "Keltner Breakout"
    description = "Break above the upper Keltner channel goes long, below the lower goes short; exit at mid."
    params = {"period": 20, "atr_period": 10, "mult": 2.0}

    def setup(self) -> None:
        self.kc = Keltner(self.params["period"], self.params["atr_period"], self.params["mult"])

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> None:
        self.kc.update(bar.high, bar.low, bar.close)
        if not self.kc.ready:
            return
        if bar.close > self.kc.upper and not ctx.is_long:
            ctx.buy(f"close {bar.close:.2f} > upper Keltner {self.kc.upper:.2f}")
        elif bar.close < self.kc.lower and not ctx.is_short:
            ctx.sell(f"close {bar.close:.2f} < lower Keltner {self.kc.lower:.2f}")
        elif ctx.is_long and bar.close < self.kc.mid:
            ctx.close("back below Keltner mid")
        elif ctx.is_short and bar.close > self.kc.mid:
            ctx.close("back above Keltner mid")
