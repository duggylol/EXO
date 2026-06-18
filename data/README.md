# Historical data

Drop your historical intraday OHLCV CSVs here, then point the trainer at them:

```bash
python -m research.train_meta --strategy ma_cross --symbol MES --csv data/MES_1min.csv
```

The loader (`research/data.py`) auto-detects these layouts:

- **Generic** — header row `timestamp,open,high,low,close,volume`
- **FirstRate Data** — `2008-01-02 09:31:00,open,high,low,close,volume` (header optional)
- **Databento** — `ts_event,open,high,low,close,volume,...` (`ts_event` = epoch nanoseconds, UTC)

## Where to get real data (cheap / free — verified June 2026)

- **Databento** (recommended to start) — pay-as-you-go CME data; each team gets
  **$125 free credits**. A full week of E-mini S&P 500 tick data cost ~**$2.17**.
  For ML, request the `ohlcv-1m` schema (1-minute bars) for your symbol, export CSV.
  https://databento.com
- **FirstRate Data** — ~18 years of 1-minute futures (e.g. NQ from 2008) as a
  low one-time purchase (~$99.95/yr for updates). https://firstratedata.com
- **Your broker** — Rithmic / ProjectX can export historical bars once connected.

## How much data?
For a meta-labeling model on 1-minute bars, aim for **1–3+ years** so the model
sees multiple regimes. Fewer than a few hundred trade signals isn't enough to
judge anything honestly (the trainer will warn you).

> Data files are git-ignored on purpose — they're large and often licensed.
> Never commit purchased datasets.
