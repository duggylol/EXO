"""Moving-average crossover — the classic trend follower."""
from __future__ import annotations

from core.indicators import SMA
from core.strategy import Strategy, StrategyContext, register
from core.models import Bar


@register
class MACrossover(Strategy):
    key = "ma_cross"
    display_name = "MA Crossover"
    description = "Long when the fast SMA crosses above the slow SMA; short on the reverse."
    params = {"fast": 10, "slow": 30}

    def setup(self) -> None:
        self.fast = SMA(self.params["fast"])
        self.slow = SMA(self.params["slow"])
        self._prev_diff = None

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> None:
        f = self.fast.update(bar.close)
        s = self.slow.update(bar.close)
        if f is None or s is None:
            return
        diff = f - s
        if self._prev_diff is not None:
            if self._prev_diff <= 0 < diff:
                ctx.buy(f"fast {f:.2f} crossed above slow {s:.2f}")
            elif self._prev_diff >= 0 > diff:
                ctx.sell(f"fast {f:.2f} crossed below slow {s:.2f}")
        self._prev_diff = diff
