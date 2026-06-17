"""EMA trend with pullback entry — trade in the trend's direction off the fast EMA."""
from __future__ import annotations

from core.indicators import EMA
from core.strategy import Strategy, StrategyContext, register
from core.models import Bar


@register
class EMATrendPullback(Strategy):
    key = "ema_trend"
    display_name = "EMA Trend Pullback"
    description = "Trade with the EMA trend; enter when price reclaims the fast EMA, exit when trend flips."
    params = {"fast": 21, "slow": 55}

    def setup(self) -> None:
        self.fast = EMA(self.params["fast"])
        self.slow = EMA(self.params["slow"])
        self._prev_close = None

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> None:
        f = self.fast.update(bar.close)
        s = self.slow.update(bar.close)
        prev = self._prev_close
        self._prev_close = bar.close
        if f is None or s is None or prev is None:
            return

        uptrend = f > s
        downtrend = f < s
        reclaim_up = prev < f <= bar.close
        reclaim_dn = prev > f >= bar.close

        if uptrend and reclaim_up and not ctx.is_long:
            ctx.buy(f"uptrend, price reclaimed EMA{self.params['fast']} @ {bar.close:.2f}")
        elif downtrend and reclaim_dn and not ctx.is_short:
            ctx.sell(f"downtrend, price lost EMA{self.params['fast']} @ {bar.close:.2f}")
        elif ctx.is_long and downtrend:
            ctx.close("trend flipped down")
        elif ctx.is_short and uptrend:
            ctx.close("trend flipped up")
