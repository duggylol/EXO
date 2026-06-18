"""
Download historical CME trades from Databento and aggregate them into a compact
per-minute order-flow CSV (data/<SYMBOL>_orderflow_1min.csv).

Fetches in time chunks and aggregates each chunk immediately, so the raw tick
stream (tens of millions of rows) never has to fit in memory at once. Estimates
total cost first and refuses to exceed --max-cost without --force.

Usage:
  python -m research.fetch_orderflow --symbol MES --start 2026-01-01 --end 2026-04-01
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

from .orderflow import aggregate_trades


def main() -> None:
    if load_dotenv:
        load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    key = os.environ.get("DATABENTO_API_KEY", "").strip()
    if not key:
        sys.exit("DATABENTO_API_KEY not set — add it to .env")

    ap = argparse.ArgumentParser(description="Fetch + aggregate historical order flow")
    ap.add_argument("--symbol", default="MES")
    ap.add_argument("--start", default="2026-01-01")
    ap.add_argument("--end", default="2026-04-01")
    ap.add_argument("--dataset", default="GLBX.MDP3")
    ap.add_argument("--large", type=int, default=20, help="contracts that count as a 'large' trade")
    ap.add_argument("--chunk-days", type=int, default=14)
    ap.add_argument("--max-cost", type=float, default=45.0)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    import databento as db
    client = db.Historical(key)
    sym = f"{a.symbol}.c.0"
    common = dict(dataset=a.dataset, symbols=[sym], schema="trades", stype_in="continuous")

    try:
        cost = client.metadata.get_cost(mode="historical-streaming", start=a.start, end=a.end, **common)
        print(f"estimated cost: ${cost:.2f}  (trades {sym} {a.start}..{a.end})")
        if cost > a.max_cost and not a.force:
            sys.exit(f"cost ${cost:.2f} exceeds --max-cost ${a.max_cost:.2f}; "
                     f"shorten the window or re-run with --force")
    except Exception as e:
        print(f"(cost estimate unavailable: {e}; proceeding)", file=sys.stderr)

    bounds = list(pd.date_range(a.start, a.end, freq=f"{a.chunk_days}D"))
    if bounds[-1] < pd.Timestamp(a.end):
        bounds.append(pd.Timestamp(a.end))
    parts = []
    for c0, c1 in zip(bounds[:-1], bounds[1:]):
        s, e = c0.strftime("%Y-%m-%d"), c1.strftime("%Y-%m-%d")
        print(f"  fetching {s} .. {e} …")
        data = client.timeseries.get_range(start=s, end=e, **common)
        df = data.to_df()
        if len(df):
            parts.append(aggregate_trades(df.reset_index(), large_threshold=a.large))
        del df, data

    if not parts:
        sys.exit("no data returned")
    of = pd.concat(parts).groupby(level=0).sum().sort_index()
    out = Path("data") / f"{a.symbol}_orderflow_1min.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    of.to_csv(out)
    print(f"saved {len(of):,} minute-bars of order flow -> {out}")
    print(f"range: {of.index[0]} .. {of.index[-1]}")


if __name__ == "__main__":
    main()
