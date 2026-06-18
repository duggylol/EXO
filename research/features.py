"""
Feature engineering for the meta-model.

`compute_features(df)` returns one feature row per bar, using ONLY information
available up to and including that bar's close (no lookahead). The exact same
function is used for offline training and for live gating in MLMetaFilter, which
guarantees the model sees identical features in both — a common source of silent
live/backtest divergence when the two are computed differently.

Features are deliberately simple and few (avoid the "throw 200 features at it"
trap, which inflates overfitting). All are scale-free where possible so a model
trained on one instrument transfers reasonably to another.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Minimum bars of history needed before features are valid (the longest lookback).
WARMUP = 60


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    close, high, low, vol = df["close"], df["high"], df["low"], df["volume"]
    ret1 = close.pct_change()
    f = pd.DataFrame(index=df.index)

    # Momentum / returns over several horizons (scale-free).
    for n in (1, 5, 15, 30):
        f[f"ret_{n}"] = close.pct_change(n)

    # Volatility regime.
    f["vol_15"] = ret1.rolling(15).std()
    f["vol_60"] = ret1.rolling(60).std()
    f["vol_ratio"] = f["vol_15"] / f["vol_60"].replace(0, np.nan)

    # Trend / distance from moving averages (normalized by price).
    for n in (10, 30, 60):
        ma = close.rolling(n).mean()
        f[f"ma_dist_{n}"] = (close - ma) / close
    f["ma_cross"] = (close.rolling(10).mean() - close.rolling(30).mean()) / close

    # Oscillators / position in recent range.
    f["rsi_14"] = _rsi(close, 14)
    hh, ll = high.rolling(20).max(), low.rolling(20).min()
    f["range_pos_20"] = (close - ll) / (hh - ll).replace(0, np.nan)

    # Candle shape (this bar).
    rng = (high - low).replace(0, np.nan)
    f["body_frac"] = (close - df["open"]).abs() / rng
    f["upper_wick"] = (high - close.combine(df["open"], max)) / rng

    # Volume surprise.
    f["vol_z"] = (vol - vol.rolling(30).mean()) / vol.rolling(30).std().replace(0, np.nan)

    # Time-of-day (cyclical) — session effects matter intraday.
    minutes = f.index.hour * 60 + f.index.minute
    f["tod_sin"] = np.sin(2 * np.pi * minutes / 1440)
    f["tod_cos"] = np.cos(2 * np.pi * minutes / 1440)
    f["dow"] = f.index.dayofweek.astype(float)

    return f.replace([np.inf, -np.inf], np.nan)


def feature_columns(df_features: pd.DataFrame) -> list[str]:
    return list(df_features.columns)
