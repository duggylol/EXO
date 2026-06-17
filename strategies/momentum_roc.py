"""Momentum (Rate of Change) — ride positive momentum, flip on negative."""
from __future__ import annotations

from core.indicators import ROC
from core.strategy import Strategy, StrategyContext, register
from core.models import Bar


@register
class MomentumROC(Strategy):
    key = "momentum"
    display_name = "Momentum (ROC)"
    description = "Long when rate-of-change exceeds +threshold, short below -threshold; exit near zero."
    params = {"period": 12, "threshold": 0.15}

    def setup(self) -> None:
        self.roc = ROC(self.params["period"])

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> None:
        r = self.roc.update(bar.close)
        if r is None:
            return
        t = self.params["threshold"]
        if r > t and not ctx.is_long:
            ctx.buy(f"momentum +{r:.2f}%")
        elif r < -t and not ctx.is_short:
            ctx.sell(f"momentum {r:.2f}%")
        elif ctx.is_long and r < 0:
            ctx.close("momentum faded")
        elif ctx.is_short and r > 0:
            ctx.close("momentum faded")
