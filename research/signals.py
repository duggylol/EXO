"""
Replay a rule-based EXO strategy over historical bars to collect its ENTRY
signals (the "primary" / side decisions). These become the events the meta-model
labels and learns to filter.

The base strategy runs on its OWN simulated position (as if it took every
signal) so its internal logic stays self-consistent — exactly mirroring how
MLMetaFilter feeds the base strategy live.
"""
from __future__ import annotations

import pandas as pd

from core.enums import IntentType, OrderSide
from core.models import Position
from core.strategy import create_strategy


def replay_entries(strategy_key: str, params: dict, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Return a frame indexed by entry time with a `side` column (+1 long, -1 short)."""
    from research.data import df_to_bars
    bars = df_to_bars(df, symbol)
    strat = create_strategy(strategy_key, f"primary-{strategy_key}", symbol, params)
    pos = Position(symbol=symbol)
    from core.strategy import StrategyContext

    times, sides = [], []
    for bar, ts in zip(bars, df.index):
        pos.mark(bar.close)
        ctx = StrategyContext(pos)
        strat._feed_bar(bar, ctx)
        for intent in ctx.intents:
            if intent.type is IntentType.EXIT:
                if not pos.is_flat:
                    pos.apply_fill(OrderSide.SELL if pos.is_long else OrderSide.BUY,
                                   abs(pos.qty), bar.close)
            else:
                want_long = intent.type is IntentType.ENTER_LONG
                if (want_long and pos.is_long) or (not want_long and pos.is_short):
                    continue
                # record a new directional entry
                times.append(ts)
                sides.append(1 if want_long else -1)
                # simulate the base taking it (flip through zero if needed)
                close_qty = abs(pos.qty)
                pos.apply_fill(OrderSide.BUY if want_long else OrderSide.SELL,
                               close_qty + 1, bar.close)
    return pd.DataFrame({"side": sides}, index=pd.DatetimeIndex(times))
