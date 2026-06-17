"""
Synchronous backtester.

Replays a list of bars through one strategy (or many) using the SAME Position
accounting and StrategyContext as live trading, so backtest behavior matches
live behavior. Reports P/L, win rate, profit factor, max drawdown, and the
trade list.

Usage:
    python -m backtest.backtester --strategy ma_cross --symbol MES --bars 5000
    python -m backtest.backtester --strategy rsi_reversion --symbol MNQ --csv data/MNQ.csv
    python -m backtest.backtester --all --symbol MES --bars 5000   # compare every strategy
"""
from __future__ import annotations

import argparse
import time
from dataclasses import dataclass, field

from core.enums import OrderSide
from core.instruments import get_instrument
from core.models import Bar, Fill, Position, Trade
from core.strategy import StrategyContext, create_strategy, registry
from strategies import load_all


@dataclass
class BacktestResult:
    strategy: str
    symbol: str
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    commission_per_contract: float = 0.0

    @property
    def total_pnl(self) -> float:
        return sum(t.pnl for t in self.trades)

    @property
    def wins(self) -> list[Trade]:
        return [t for t in self.trades if t.pnl > 0]

    @property
    def losses(self) -> list[Trade]:
        return [t for t in self.trades if t.pnl <= 0]

    @property
    def win_rate(self) -> float:
        return len(self.wins) / len(self.trades) * 100 if self.trades else 0.0

    @property
    def profit_factor(self) -> float:
        gross_win = sum(t.pnl for t in self.wins)
        gross_loss = abs(sum(t.pnl for t in self.losses))
        return gross_win / gross_loss if gross_loss else float("inf")

    @property
    def avg_win(self) -> float:
        return sum(t.pnl for t in self.wins) / len(self.wins) if self.wins else 0.0

    @property
    def avg_loss(self) -> float:
        return sum(t.pnl for t in self.losses) / len(self.losses) if self.losses else 0.0

    @property
    def max_drawdown(self) -> float:
        peak = self.equity_curve[0] if self.equity_curve else 0.0
        dd = 0.0
        for e in self.equity_curve:
            peak = max(peak, e)
            dd = min(dd, e - peak)
        return dd

    def report(self) -> str:
        return (
            f"{self.strategy:<22} {self.symbol:<5} "
            f"trades={len(self.trades):<5} "
            f"win%={self.win_rate:5.1f} "
            f"PF={self.profit_factor:5.2f} "
            f"P/L=${self.total_pnl:>10,.2f} "
            f"maxDD=${self.max_drawdown:>10,.2f} "
            f"avgW=${self.avg_win:>8,.2f} avgL=${self.avg_loss:>8,.2f}"
        )


def run_backtest(strategy_key: str, symbol: str, bars: list[Bar],
                 params: dict | None = None, slippage_ticks: float = 1.0,
                 commission_per_contract: float = 0.0,
                 contracts: int = 1) -> BacktestResult:
    instr = get_instrument(symbol)
    strat = create_strategy(strategy_key, f"bt-{strategy_key}", symbol, params or {})
    pos = Position(symbol=symbol)
    result = BacktestResult(strategy_key, symbol, commission_per_contract=commission_per_contract)

    entry_price = entry_ts = 0.0
    entry_dir = ""
    realized_at_entry = 0.0
    equity = 0.0

    def fill(side: OrderSide, qty: int, price: float, ts: float):
        nonlocal entry_price, entry_ts, entry_dir, realized_at_entry, equity
        old = pos.qty
        slip = slippage_ticks * instr.tick_size
        fp = price + slip if side is OrderSide.BUY else price - slip
        pos.apply_fill(side, qty, fp)
        pos.realized_pnl -= commission_per_contract * qty
        new = pos.qty
        if (old != 0 and new == 0) or (old != 0 and new != 0 and (old > 0) != (new > 0)):
            pnl = pos.realized_pnl - realized_at_entry
            result.trades.append(Trade(
                strategy_id=strat.instance_id, symbol=symbol, direction=entry_dir,
                qty=abs(old), entry_price=entry_price, exit_price=fp,
                entry_ts=entry_ts, exit_ts=ts, pnl=pnl))
        if (old == 0 and new != 0) or (old != 0 and new != 0 and (old > 0) != (new > 0)):
            entry_price = pos.avg_price
            entry_ts = ts
            entry_dir = "LONG" if new > 0 else "SHORT"
            realized_at_entry = pos.realized_pnl

    for bar in bars:
        pos.mark(bar.close)
        ctx = StrategyContext(pos)
        strat._feed_bar(bar, ctx)
        for intent in ctx.intents:
            from core.enums import IntentType
            if intent.type is IntentType.EXIT:
                if not pos.is_flat:
                    fill(OrderSide.SELL if pos.is_long else OrderSide.BUY,
                         abs(pos.qty), bar.close, bar.ts)
            else:
                want_long = intent.type is IntentType.ENTER_LONG
                if (want_long and pos.is_long) or (not want_long and pos.is_short):
                    continue
                close_qty = abs(pos.qty)
                side = OrderSide.BUY if want_long else OrderSide.SELL
                fill(side, contracts + close_qty, bar.close, bar.ts)
        result.equity_curve.append(pos.realized_pnl + pos.unrealized_pnl)
    return result


def _make_sim_bars(symbol: str, n: int, seed: int = 42) -> list[Bar]:
    from data.simulated import SimulatedFeed
    feed = SimulatedFeed({"symbols": [symbol], "seed": seed})
    return [feed._next_bar(symbol) for _ in range(n)]


def _load_csv_bars(symbol: str, path: str) -> list[Bar]:
    from data.csv_feed import CSVFeed
    return CSVFeed({})._load(symbol, path)


def main() -> None:
    ap = argparse.ArgumentParser(description="Backtest futures strategies")
    ap.add_argument("--strategy", help="strategy key (see --list)")
    ap.add_argument("--all", action="store_true", help="run every registered strategy")
    ap.add_argument("--list", action="store_true", help="list available strategies")
    ap.add_argument("--symbol", default="MES")
    ap.add_argument("--bars", type=int, default=5000, help="simulated bar count")
    ap.add_argument("--csv", help="CSV file to backtest against instead of simulated data")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--contracts", type=int, default=1)
    ap.add_argument("--commission", type=float, default=0.0)
    args = ap.parse_args()

    load_all()
    if args.list:
        for key, cls in sorted(registry().items()):
            print(f"  {key:<18} {cls.display_name}")
        return

    bars = (_load_csv_bars(args.symbol, args.csv) if args.csv
            else _make_sim_bars(args.symbol, args.bars, args.seed))
    print(f"Backtesting on {len(bars)} {args.symbol} bars "
          f"({'CSV' if args.csv else 'simulated'})\n")

    keys = sorted(registry()) if args.all else [args.strategy]
    if not keys or keys == [None]:
        ap.error("provide --strategy KEY, or --all, or --list")
    results = [run_backtest(k, args.symbol, bars, contracts=args.contracts,
                            commission_per_contract=args.commission) for k in keys]
    results.sort(key=lambda r: r.total_pnl, reverse=True)
    for r in results:
        print(r.report())


if __name__ == "__main__":
    main()
