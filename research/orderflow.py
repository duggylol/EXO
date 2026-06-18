"""
Order-flow aggregation + features (Tier A: trade-based, deployable on a
top-of-book/time-and-sales feed — no full-depth Rithmic required).

`aggregate_trades` rolls Databento `trades` records into per-minute order-flow
stats (signed volume / delta, trade count, large-trade volume). The headline
signal is ORDER-FLOW IMBALANCE: net aggressor volume = buy-initiated minus
sell-initiated trades, which carries more short-term information than price
alone.

`compute_orderflow_features` turns those into leak-free, scale-free features
(prefixed `of_`) that join onto the OHLCV features by timestamp.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SIGN = {"B": 1, "A": -1, "N": 0}   # trade aggressor: Bid=buy(+), Ask=sell(-), None=0


def aggregate_trades(df: pd.DataFrame, large_threshold: int = 20) -> pd.DataFrame:
    """Per-minute order-flow stats from a Databento trades DataFrame
    (needs columns: ts_event, side, size)."""
    if "action" in df.columns:
        df = df[df["action"] == "T"]
    ts = pd.to_datetime(df["ts_event"], utc=True).dt.tz_convert(None)
    minute = ts.dt.floor("min")
    size = df["size"].astype(float).values
    sign = df["side"].map(SIGN).fillna(0).astype(float).values
    signed = size * sign

    base = pd.DataFrame({"m": minute.values, "size": size, "signed": signed,
                         "buy": np.where(sign > 0, size, 0.0),
                         "sell": np.where(sign < 0, size, 0.0),
                         "large": np.where(size >= large_threshold, size, 0.0)})
    g = base.groupby("m")
    of = pd.DataFrame({
        "of_volume": g["size"].sum(),
        "of_delta": g["signed"].sum(),
        "of_trades": g.size(),
        "of_buy_vol": g["buy"].sum(),
        "of_sell_vol": g["sell"].sum(),
        "of_large_vol": g["large"].sum(),
    })
    of.index.name = "timestamp"
    return of


def _zscore(s: pd.Series, win: int) -> pd.Series:
    mean = s.rolling(win).mean()
    std = s.rolling(win).std()
    return (s - mean) / std.replace(0, np.nan)


def compute_orderflow_features(of: pd.DataFrame) -> pd.DataFrame:
    """Leak-free, scale-free order-flow features (all usable up to the bar's close)."""
    vol = of["of_volume"].replace(0, np.nan)
    f = pd.DataFrame(index=of.index)
    f["of_delta_ratio"] = of["of_delta"] / vol            # net aggressor pressure this bar
    f["of_large_ratio"] = of["of_large_vol"] / vol        # share of volume from big trades
    f["of_avg_trade"] = vol / of["of_trades"].replace(0, np.nan)
    f["of_delta_z"] = _zscore(of["of_delta"], 60)         # is pressure unusual vs last hour?
    f["of_vol_z"] = _zscore(of["of_volume"], 60)
    f["of_intensity_z"] = _zscore(of["of_trades"].astype(float), 60)
    # multi-bar cumulative pressure (15-min net aggressor flow, normalized)
    f["of_cum_delta_15"] = of["of_delta"].rolling(15).sum() / vol.rolling(15).sum()
    f["of_cum_delta_5"] = of["of_delta"].rolling(5).sum() / vol.rolling(5).sum()
    return f.replace([np.inf, -np.inf], np.nan)
