"""Supertrend — ATR-band trend follower; flip position when the trend flips."""
from __future__ import annotations

from core.indicators import Supertrend as STIndicator
from core.strategy import Strategy, StrategyContext, register
from core.models import Bar


@register
class SupertrendStrategy(Strategy):
    key = "supertrend"
    display_name = "Supertrend"
    description = "Follow the Supertrend: go long when it turns up, short when it turns down."
    params = {"period": 10, "mult": 3.0}

    def setup(self) -> None:
        self.st = STIndicator(self.params["period"], self.params["mult"])
        self._prev_dir = 0

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> None:
        self.st.update(bar.high, bar.low, bar.close)
        if not self.st.ready:
            return
        d = self.st.direction
        if d != self._prev_dir:
            if d == 1:
                ctx.buy(f"Supertrend flipped up @ {self.st.value:.2f}")
            elif d == -1:
                ctx.sell(f"Supertrend flipped down @ {self.st.value:.2f}")
        self._prev_dir = d
