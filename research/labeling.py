"""
Triple-barrier labeling + meta-labels (López de Prado, AFML Ch. 3).

For each trade signal we set three barriers from the entry:
  * a profit-take barrier  (entry +/- pt * volatility)
  * a stop-loss barrier    (entry -/+ sl * volatility)
  * a vertical/time barrier (max_holding bars later)
Whichever is touched FIRST determines the outcome. The price barriers scale with
recent volatility, so the labels respect risk instead of treating every bar
equally (the flaw in fixed-horizon "up after N bars" labels).

The META-LABEL is then simply: did the primary strategy's bet make money?
1 = take it (the side was right), 0 = skip it. The secondary model learns to
predict this, i.e. when the primary strategy tends to be wrong.

We also return `t1` (the time each label resolves) — essential for purging the
cross-validation so train/test don't leak through overlapping label windows.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def rolling_volatility(close: pd.Series, span: int = 50) -> pd.Series:
    """EWMA volatility of simple returns — used to scale the barriers."""
    return close.pct_change().ewm(span=span).std()


def triple_barrier_labels(
    close: pd.Series,
    entries: pd.DataFrame,        # columns: side (+1 long / -1 short)
    vol: pd.Series,
    pt: float = 2.0,
    sl: float = 1.0,
    max_holding: int = 30,
) -> pd.DataFrame:
    """Label each entry by first-barrier-touch.

    Returns a frame indexed by entry time with: side, ret (signed return in the
    side's direction), bin (meta-label 1/0), t1 (resolution time), outcome.
    """
    idx = close.index
    pos = {ts: i for i, ts in enumerate(idx)}
    rows = []
    for ts, row in entries.iterrows():
        if ts not in pos:
            continue
        i0 = pos[ts]
        side = int(row["side"])
        p0 = float(close.iloc[i0])
        v = float(vol.get(ts, np.nan))
        if not np.isfinite(v) or v <= 0:
            continue
        up = p0 * (1 + pt * v)       # upper price barrier
        dn = p0 * (1 - sl * v)       # lower price barrier
        if side < 0:                  # for shorts, profit is down, stop is up
            up = p0 * (1 + sl * v)
            dn = p0 * (1 - pt * v)
        i_end = min(i0 + max_holding, len(idx) - 1)

        outcome, exit_i = "time", i_end
        for j in range(i0 + 1, i_end + 1):
            pj = float(close.iloc[j])
            if pj >= up:
                outcome, exit_i = ("pt" if side > 0 else "sl"), j
                break
            if pj <= dn:
                outcome, exit_i = ("sl" if side > 0 else "pt"), j
                break
        exit_p = float(close.iloc[exit_i])
        ret = (exit_p / p0 - 1.0) * side
        rows.append({
            "side": side, "ret": ret, "bin": 1 if ret > 0 else 0,
            "t1": idx[exit_i], "outcome": outcome,
        })
    return pd.DataFrame(rows, index=[r for r in entries.index if r in pos][: len(rows)])
