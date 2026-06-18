"""
Download real historical CME futures bars from Databento into data/.

Reads DATABENTO_API_KEY from .env. Estimates the cost first and refuses to spend
more than --max-cost without --force, so it can't quietly burn your credits.

Usage:
  python -m research.fetch_databento --symbol MES --start 2024-06-01 --end 2026-06-01
  python -m research.fetch_databento --symbol MNQ                       # uses defaults

Output: data/<SYMBOL>_1min.csv  (timestamp,open,high,low,close,volume) — ready
for research/train_meta.py.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


def main() -> None:
    if load_dotenv:
        load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    key = os.environ.get("DATABENTO_API_KEY", "").strip()
    if not key:
        sys.exit("DATABENTO_API_KEY not set — add it to .env")

    ap = argparse.ArgumentParser(description="Fetch historical CME futures from Databento")
    ap.add_argument("--symbol", default="MES", help="root symbol, e.g. MES, ES, MNQ, MGC")
    ap.add_argument("--start", default="2024-06-01")
    ap.add_argument("--end", default="2026-06-01")
    ap.add_argument("--schema", default="ohlcv-1m", help="ohlcv-1m | ohlcv-1h | trades …")
    ap.add_argument("--dataset", default="GLBX.MDP3", help="CME Globex MDP 3.0")
    ap.add_argument("--out", default="")
    ap.add_argument("--max-cost", type=float, default=25.0, help="abort if estimate exceeds this ($)")
    ap.add_argument("--force", action="store_true", help="download even if over --max-cost")
    a = ap.parse_args()

    import databento as db
    client = db.Historical(key)
    sym = f"{a.symbol}.c.0"          # front-month continuous (calendar roll)
    common = dict(dataset=a.dataset, symbols=[sym], schema=a.schema,
                  start=a.start, end=a.end, stype_in="continuous")

    # --- cost guard ---
    try:
        cost = client.metadata.get_cost(mode="historical-streaming", **common)
        print(f"estimated cost: ${cost:.4f}  ({sym} {a.schema} {a.start}..{a.end})")
        if cost > a.max_cost and not a.force:
            sys.exit(f"cost ${cost:.2f} exceeds --max-cost ${a.max_cost:.2f}; "
                     f"re-run with --force to proceed")
    except Exception as e:
        print(f"(cost estimate unavailable: {e}; proceeding)", file=sys.stderr)

    print(f"downloading {sym} … this can take a moment")
    data = client.timeseries.get_range(**common)
    df = data.to_df().reset_index()

    tcol = "ts_event" if "ts_event" in df.columns else df.columns[0]
    df = df.rename(columns={tcol: "timestamp"})
    keep = [c for c in ["timestamp", "open", "high", "low", "close", "volume"] if c in df.columns]
    df = df[keep]

    out = Path(a.out) if a.out else Path("data") / f"{a.symbol}_1min.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"saved {len(df):,} rows -> {out}")
    if len(df):
        print(f"range: {df['timestamp'].iloc[0]}  ..  {df['timestamp'].iloc[-1]}")


if __name__ == "__main__":
    main()
