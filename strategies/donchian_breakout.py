"""
Donchian channel breakout — the classic 'Turtle' trend system.

Enter on a break of the N-bar high/low (entry channel); exit on a break of a
shorter M-bar channel in the opposite direction.
"""
from __future__ import annotations

from core.indicators import Donchian
from core.strategy import Strategy, StrategyContext, register
from core.models import Bar


@register
class DonchianBreakout(Strategy):
    key = "donchian"
    display_name = "Donchian Breakout (Turtle)"
    description = "Enter on a break of the N-bar channel; exit on the opposite M-bar channel."
    params = {"entry": 20, "exit": 10}

    def setup(self) -> None:
        self.entry = Donchian(self.params["entry"])
        self.exit = Donchian(self.params["exit"])

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> None:
        self.entry.update(bar.high, bar.low)
        self.exit.update(bar.high, bar.low)
        if not self.entry.ready or not self.exit.ready:
            return
        if bar.high >= self.entry.upper and not ctx.is_long:
            ctx.buy(f"broke {self.params['entry']}-bar high {self.entry.upper:.2f}")
        elif bar.low <= self.entry.lower and not ctx.is_short:
            ctx.sell(f"broke {self.params['entry']}-bar low {self.entry.lower:.2f}")
        elif ctx.is_long and bar.low <= self.exit.lower:
            ctx.close(f"hit {self.params['exit']}-bar exit low")
        elif ctx.is_short and bar.high >= self.exit.upper:
            ctx.close(f"hit {self.params['exit']}-bar exit high")
