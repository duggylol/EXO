"""RSI mean reversion — fade oversold/overbought extremes back to the midline."""
from __future__ import annotations

from core.indicators import RSI
from core.strategy import Strategy, StrategyContext, register
from core.models import Bar


@register
class RSIReversion(Strategy):
    key = "rsi_reversion"
    display_name = "RSI Mean Reversion"
    description = "Buy when RSI is oversold, sell when overbought; exit back at the midline."
    params = {"period": 14, "oversold": 30, "overbought": 70, "exit_mid": 50}

    def setup(self) -> None:
        self.rsi = RSI(self.params["period"])

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> None:
        r = self.rsi.update(bar.close)
        if r is None:
            return
        if r <= self.params["oversold"] and not ctx.is_long:
            ctx.buy(f"RSI oversold {r:.1f}")
        elif r >= self.params["overbought"] and not ctx.is_short:
            ctx.sell(f"RSI overbought {r:.1f}")
        elif ctx.is_long and r >= self.params["exit_mid"]:
            ctx.close(f"RSI back to mid {r:.1f}")
        elif ctx.is_short and r <= self.params["exit_mid"]:
            ctx.close(f"RSI back to mid {r:.1f}")
