# EXO

A fully-automated, **cross-platform** (macOS / Windows / Linux) futures trading
platform with a plug-in strategy engine, a prop-firm risk guard, swappable
broker/data adapters, Discord notifications, and a clean dark dashboard.

The **strategy brain is 100% firm-agnostic**; the broker and data feed are
swappable adapters — so the same bot runs on a paper account today and a
prop-firm account tomorrow with a one-line config change.

```
┌──────────────────────────────────────────────────────────────┐
│  Data Feed ──▶ Engine ──▶ Strategies ──▶ Risk Guard ──▶ Broker │
│  (sim/CSV/      (event     (12 plug-in    (prop-eval    (paper/ │
│   rithmic/       loop)      strategies)    limits)       projectx/
│   projectx)         │                                    traderspost)
│                     └──▶ Portfolio ──▶ Discord + SQLite + Dashboard
└──────────────────────────────────────────────────────────────┘
```

---

## Quick start (runs in 60 seconds, no credentials, $0)

```bash
cd futures-trading-bot
python3 -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

Open **http://127.0.0.1:8000**. The default config runs the **paper broker** on
a **simulated feed**, so 12 strategies start trading synthetic data immediately
and the dashboard comes alive. Nothing is connected to a real account until you
change the config and add credentials.

---

## What's included

- **12 strategies** out of the box (trend, breakout, mean-reversion):
  `ma_cross`, `ema_trend`, `rsi_reversion`, `macd_trend`, `bb_breakout`,
  `bb_reversion`, `orb` (opening-range breakout), `vwap_reversion`,
  `donchian` (turtle), `momentum`, `supertrend`, `keltner`.
- **Plug-in strategy system** — add a file to `strategies/`, it's auto-loaded.
- **Prop-firm risk guard** — daily loss limit, trailing drawdown, per-strategy
  and account contract caps. Flattens and halts when a limit trips.
- **Broker adapters** — `paper`, `projectx` (TopstepX/ProjectX REST),
  `traderspost` (the route for Lucid Trading).
- **Data feeds** — `simulated`, `csv`, `rithmic` (via `async_rithmic`),
  `projectx` (SignalR market hub).
- **Discord notifications** — entry/exit messages with per-trade P/L recap.
- **Backtester** — same accounting as live; compare every strategy at once.
- **Dashboard** — equity curve, per-strategy P/L, risk gauges, trade log,
  live strategy on/off toggles, emergency flatten.
- **SQLite persistence** — trades survive restarts.

---

## Configuration

Everything is in [`config/config.yaml`](config/config.yaml); secrets go in
`.env` (copy `.env.example`). Key sections:

- `account.starting_balance` — set to your prop account size.
- `risk.*` — **tune to your firm's exact rules** (see compliance below).
- `feed.type` / `broker.type` — pick your data + execution adapters.
- `strategies:` — one entry per running instance. Run the same strategy on
  multiple symbols or with different params by adding more entries.

### Add a strategy

Create `strategies/my_strategy.py`:

```python
from core.indicators import EMA
from core.strategy import Strategy, StrategyContext, register
from core.models import Bar

@register
class MyStrategy(Strategy):
    key = "my_strat"
    display_name = "My Strategy"
    description = "Buy when price > EMA, exit when it crosses back under."
    params = {"period": 50}

    def setup(self):
        self.ema = EMA(self.params["period"])

    def on_bar(self, bar: Bar, ctx: StrategyContext):
        e = self.ema.update(bar.close)
        if e is None:
            return
        if bar.close > e and ctx.is_flat:
            ctx.buy(f"close above EMA {e:.2f}")
        elif ctx.is_long and bar.close < e:
            ctx.close("lost the EMA")
```

Add it to `config.yaml` and restart. That's it.

---

## Backtesting

```bash
python -m backtest.backtester --list                       # show all strategies
python -m backtest.backtester --all --symbol MES --bars 5000   # compare them all
python -m backtest.backtester --strategy rsi_reversion --symbol MNQ --csv data/MNQ.csv
```

Reports trades, win %, profit factor, P/L, max drawdown per strategy.
> Simulated data is for plumbing/relative comparison only. Validate on real
> historical CSVs before trusting any edge.

---

## Going live

### Option A — ProjectX / TopstepX (cheapest API path, ~$14.50–29/mo)
1. Get an API key in your TopstepX/ProjectX dashboard.
2. Put credentials in `.env` (`PROJECTX_*`).
3. In `config.yaml`: `broker.type: projectx`, and `feed.type: projectx` (or keep
   Rithmic/CSV for data).
4. ⚠️ **TopstepX bans VPS/VPN/remote servers** — run on your own always-on
   machine (a spare laptop/Mac mini), not a cloud VPS.

### Option B — Lucid Trading (via TradersPost webhook)
1. Create a strategy in TradersPost, connect Lucid (routed through Tradovate).
2. Put the webhook URL in `.env` (`TRADERSPOST_WEBHOOK_URL`).
3. In `config.yaml`: `broker.type: traderspost`.
4. Local P/L is an **estimate** — reconcile against your platform. Lucid bans
   HFT and sub-5-second microscalping; keep strategies above that.

### Option C — Direct Rithmic (most capable, ~$125/mo + data, VPS-OK)
1. `pip install async-rithmic`; get Rithmic gateway credentials.
2. Put them in `.env` (`RITHMIC_*`); set `feed.type: rithmic`.

---

## Desktop apps (double-clickable Mac & Windows)

The bot also ships as a native desktop app — a double-clickable `.app` (macOS)
or `.exe` (Windows) that opens the dashboard in its own window (no terminal, no
browser needed; it falls back to your browser if the native window is
unavailable). Config, database, and `.env` live in a writable per-user folder:
`~/Library/Application Support/EXO` (macOS) or
`%APPDATA%\EXO` (Windows). A log is written there too.

> You cannot cross-build: a Mac app must be built on a Mac, a Windows app on
> Windows. The GitHub Actions workflow builds both for you.

### Build the Mac app (on a Mac)
```bash
./build/build_mac.sh
```
Produces an installer **`dist/EXO-<version>.dmg`** plus the raw
`.app` and an update `.zip`. Install like any Mac app: open the `.dmg` and drag
**EXO** into **Applications**.

First launch of an unsigned app: right-click the app → **Open** → **Open**
(Gatekeeper only prompts once).

### Auto-update (no reinstalling)
The app checks for new versions in the background and shows an **"Update
available"** banner with an **Update & Restart** button. Clicking it downloads
the new build, swaps the installed app in place, and relaunches — **all your
saved data is kept** (login, settings, database, and logs live in the user-data
dir, outside the app bundle, so updates never touch them).

To enable it, set your repo in `config.yaml` once:
```yaml
update:
  repo: "yourusername/futures-trading-bot"   # reads GitHub Releases
```
Then to ship an update: bump `VERSION` in [core/version.py](core/version.py),
commit, and push a matching tag:
```bash
git tag v1.0.1 && git push origin v1.0.1
```
The CI workflow builds both apps and publishes a GitHub Release; every installed
copy then sees the update banner within a few hours (or immediately via the
in-app check). No manifest to maintain — GitHub Releases *is* the update feed.
(Alternatively point `update.feed_url` at your own `latest.json`.)

### Build the Windows app (on Windows)
```bat
build\build_windows.bat        REM -> dist\EXO\EXO.exe
```
First launch: Windows SmartScreen → **More info** → **Run anyway**.
Requires the Microsoft **Edge WebView2 runtime** (preinstalled on Windows 10/11).

### Build BOTH automatically (no Windows PC needed)
Push this repo to GitHub, open the **Actions** tab → **Build desktop apps** →
**Run workflow**. It builds the `.app` and `.exe` on real Mac/Windows runners
and uploads both as downloadable artifacts. (Or push a `v1.0.0` tag.)

Building locally needs the extra deps: `pip install -r requirements-desktop.txt`.

> These are **unsigned** builds (fine for personal use). Distributing to others
> without warnings needs an Apple Developer ID ($99/yr) + notarization, and a
> Windows code-signing certificate — out of scope for a low-cost setup.

---

## ⚠️ Prop-firm compliance — READ THIS

Researched and verified (mid-2026); **rules change — confirm with your firm**:

- **Apex Trader Funding** bans *"hands-off, set-and-forget… systems that run
  continuously 24 hours a day."* Penalty: **account closure + forfeiture of all
  funds.** Supervised/semi-automated tools with a human able to intervene are
  allowed. **Do not leave this bot running unattended on Apex.**
- **TopstepX/ProjectX** allows automated strategies via its API but **prohibits
  VPS/VPN/remote-server execution** — run on your personal device.
- **Lucid Trading** is the most automation-friendly (bots/algos/copiers OK; no
  HFT, no sub-5s scalping) but has **no native custom API** — automate via
  TradersPost → Tradovate.
- ProjectX went **Topstep-exclusive (Feb 28, 2026)**; non-Topstep firms reach
  automation through Tradovate/TradersPost, not ProjectX.

**The risk guard is your safety net, but YOU are responsible for compliance.**
Set `risk.*` to your firm's published limits and trade within their automation
rules. Forward-test on a simulated/eval account first.

---

## Realistic monthly cost

| Item | Cost |
|---|---|
| This software (engine, strategies, dashboard) | **$0** (open source) |
| Discord notifications | **$0** |
| ProjectX/TopstepX API | ~$14.50–29/mo |
| Direct Rithmic (alt.) | ~$125/mo + CME data + $0.10/contract |
| Prop-firm eval/reset fees | varies by firm/account (your largest line) |

The bot is free; **prop access (eval + data + API) is where the money goes.**

---

## Project layout

```
core/        engine, models, indicators, strategy base, risk, portfolio, config
strategies/  plug-in strategies (auto-discovered)
brokers/     execution adapters: paper, projectx, traderspost
data/        data feeds: simulated, csv, rithmic, projectx
backtest/    synchronous backtester (CLI)
notify/      Discord webhook notifier
storage/     SQLite persistence
server/      FastAPI app + dashboard (static/)
run.py       entrypoint — terminal/dev (engine + dashboard in your browser)
desktop.py   entrypoint — packaged desktop app (native window)
FuturesBot.spec   PyInstaller build recipe
build/       icon generator + per-OS build scripts
.github/workflows/build-apps.yml   CI that builds the Mac + Windows apps
```

## Disclaimer
Trading futures involves substantial risk of loss. This software is provided for
educational purposes with no warranty. Test thoroughly on simulated/evaluation
accounts before risking real capital, and ensure your usage complies with your
prop firm's and broker's rules.
