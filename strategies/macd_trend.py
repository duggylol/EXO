"""MACD trend — trade signal-line crossovers of the MACD."""
from __future__ import annotations

from core.indicators import MACD
from core.strategy import Strategy, StrategyContext, register
from core.models import Bar


@register
class MACDTrend(Strategy):
    key = "macd_trend"
    display_name = "MACD Trend"
    description = "Long when MACD crosses above its signal line, short when it crosses below."
    params = {"fast": 12, "slow": 26, "signal": 9}

    def setup(self) -> None:
        self.macd = MACD(self.params["fast"], self.params["slow"], self.params["signal"])
        self._prev_hist = None

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> None:
        self.macd.update(bar.close)
        if not self.macd.ready:
            return
        hist = self.macd.hist
        if self._prev_hist is not None:
            if self._prev_hist <= 0 < hist:
                ctx.buy(f"MACD crossed above signal (hist {hist:.3f})")
            elif self._prev_hist >= 0 > hist:
                ctx.sell(f"MACD crossed below signal (hist {hist:.3f})")
        self._prev_hist = hist
