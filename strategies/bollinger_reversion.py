"""Bollinger Band reversion — fade touches of the outer bands back to the mean."""
from __future__ import annotations

from core.indicators import Bollinger
from core.strategy import Strategy, StrategyContext, register
from core.models import Bar


@register
class BollingerReversion(Strategy):
    key = "bb_reversion"
    display_name = "Bollinger Reversion"
    description = "Fade the bands: buy a tag of the lower band, sell a tag of the upper; exit at the mid."
    params = {"period": 20, "mult": 2.0}

    def setup(self) -> None:
        self.bb = Bollinger(self.params["period"], self.params["mult"])

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> None:
        self.bb.update(bar.close)
        if not self.bb.ready:
            return
        if bar.low <= self.bb.lower and not ctx.is_long and ctx.is_flat:
            ctx.buy(f"tagged lower band {self.bb.lower:.2f}")
        elif bar.high >= self.bb.upper and not ctx.is_short and ctx.is_flat:
            ctx.sell(f"tagged upper band {self.bb.upper:.2f}")
        elif ctx.is_long and bar.close >= self.bb.mid:
            ctx.close("reverted to mid")
        elif ctx.is_short and bar.close <= self.bb.mid:
            ctx.close("reverted to mid")
