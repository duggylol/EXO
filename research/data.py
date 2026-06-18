"""
Historical data loader for the research pipeline.

Reads intraday OHLCV CSVs into a clean, datetime-indexed pandas DataFrame and
auto-detects the common layouts so you can drop in files from different vendors:

  * Generic:     timestamp,open,high,low,close,volume
  * FirstRate:   2008-01-02 09:31:00,open,high,low,close,volume  (often headerless)
  * Databento:   ts_event,open,high,low,close,volume,...  (ts_event = epoch ns, UTC)

Drop your files in data/ and pass the path to the trainer. See data/README.md.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

OHLCV = ["open", "high", "low", "close", "volume"]
_DT_NAMES = ["timestamp", "datetime", "date_time", "ts_event", "ts", "date", "time"]
_ALIASES = {
    "open": ["open", "o"], "high": ["high", "h"], "low": ["low", "l"],
    "close": ["close", "c", "last"], "volume": ["volume", "vol", "v", "size"],
}


def _parse_datetime(series: pd.Series) -> pd.DatetimeIndex:
    # Numeric epoch (Databento ts_event is nanoseconds): pick unit by magnitude.
    if pd.api.types.is_numeric_dtype(series):
        v = float(series.iloc[0])
        unit = "ns" if v > 1e17 else "ms" if v > 1e12 else "s"
        return pd.to_datetime(series, unit=unit, utc=True).tz_convert(None)
    dt = pd.to_datetime(series, utc=True, errors="coerce")
    return dt.dt.tz_convert(None) if getattr(dt.dt, "tz", None) is not None else dt


def load_ohlcv(path: str | Path) -> pd.DataFrame:
    """Return a DataFrame indexed by tz-naive datetime with open/high/low/close/volume."""
    path = Path(path)
    raw = pd.read_csv(path)
    raw.columns = [str(c).lower().strip() for c in raw.columns]

    dt_col = next((c for c in _DT_NAMES if c in raw.columns), None)
    if dt_col is None and not any(a in raw.columns for a in _ALIASES["open"]):
        # Looks headerless — re-read assuming [datetime, o, h, l, c, v].
        raw = pd.read_csv(path, header=None)
        if raw.shape[1] < 6:
            raise ValueError(f"{path.name}: cannot identify columns (need datetime + OHLCV)")
        raw = raw.iloc[:, :6]
        raw.columns = ["datetime"] + OHLCV
        dt_col = "datetime"

    def pick(field: str) -> str:
        for a in _ALIASES[field]:
            if a in raw.columns:
                return a
        raise ValueError(f"{path.name}: missing '{field}' column")

    idx = _parse_datetime(raw[dt_col])
    out = pd.DataFrame({f: pd.to_numeric(raw[pick(f)], errors="coerce") for f in OHLCV})
    out.index = idx
    out = out[~out.index.isna()].sort_index()
    out = out[~out.index.duplicated(keep="first")].dropna(subset=["open", "high", "low", "close"])
    out["volume"] = out["volume"].fillna(0.0)
    if out.empty:
        raise ValueError(f"{path.name}: no valid rows after parsing")
    return out


def synthetic_ohlcv(symbol: str, n: int, seed: int = 7, freq_min: int = 1) -> pd.DataFrame:
    """Generate a random-walk OHLCV frame — ONLY for smoke-testing the pipeline.
    There is no real edge in random data; never trust results trained on this."""
    from data.simulated import SimulatedFeed
    feed = SimulatedFeed({"symbols": [symbol], "seed": seed})
    rows = [feed._next_bar(symbol) for _ in range(n)]
    start = pd.Timestamp("2022-01-03 09:30:00")
    idx = pd.date_range(start, periods=n, freq=f"{freq_min}min")
    df = pd.DataFrame(
        {"open": [b.open for b in rows], "high": [b.high for b in rows],
         "low": [b.low for b in rows], "close": [b.close for b in rows],
         "volume": [b.volume for b in rows]}, index=idx)
    return df


def df_to_bars(df: pd.DataFrame, symbol: str):
    """Convert an OHLCV frame to engine Bar objects (for the backtester)."""
    from core.models import Bar
    return [
        Bar(symbol=symbol, ts=ts.timestamp(), open=float(r.open), high=float(r.high),
            low=float(r.low), close=float(r.close), volume=float(r.volume))
        for ts, r in df.iterrows()
    ]
