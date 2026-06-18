"""
The trading engine: ties a real broker connection, (optional) market-data feed,
strategies, risk, and notifications together.

Data integrity rule: the account panel only ever shows REAL data fetched from
the connected provider (balance, positions, P/L). Nothing is synthesized. If the
provider doesn't return a field, it stays null and the UI shows '—'.

The engine can run in two modes off one connection:
  * monitor mode  — no market-data feed: just polls and displays real account
    data and positions, and guards the real account against your risk limits.
  * trading mode  — a market-data feed is connected: strategies run on real bars
    and place real orders through the broker.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional

from brokers.base import Broker
from data.base import DataFeed
from notify.discord import DiscordNotifier
from storage.db import Database

from .enums import EventType, IntentType, OrderSide
from .event_bus import EventBus
from .models import AccountInfo, Bar, BrokerPosition, Fill, Order, Position, Trade
from .portfolio import Portfolio
from .risk import RiskConfig, RiskManager
from .strategy import Strategy, StrategyContext, create_strategy


@dataclass
class StrategyRunner:
    """Runtime wrapper around a strategy instance: its position, stats, state."""
    instance_id: str
    strategy: Strategy
    symbol: str
    enabled: bool = True
    manual: bool = False          # semi-auto: entries need approval, exits auto
    _has_pending: bool = False
    position: Position = field(default=None)  # type: ignore
    trade_count: int = 0
    wins: int = 0
    total_pnl: float = 0.0
    day_pnl: float = 0.0
    _entry_price: float = 0.0
    _entry_ts: float = 0.0
    _entry_dir: str = ""
    _realized_at_entry: float = 0.0

    def __post_init__(self) -> None:
        if self.position is None:
            self.position = Position(symbol=self.symbol)

    @property
    def win_rate(self) -> float:
        return (self.wins / self.trade_count * 100.0) if self.trade_count else 0.0

    def apply_fill(self, fill: Fill) -> Optional[Trade]:
        old_qty = self.position.qty
        self.position.apply_fill(fill.side, fill.qty, fill.price)
        new_qty = self.position.qty
        closed: Optional[Trade] = None

        opened_from_flat = old_qty == 0 and new_qty != 0
        flipped = old_qty != 0 and new_qty != 0 and (old_qty > 0) != (new_qty > 0)
        closed_to_flat = old_qty != 0 and new_qty == 0

        if closed_to_flat or flipped:
            pnl = self.position.realized_pnl - self._realized_at_entry
            closed = Trade(
                strategy_id=self.instance_id, symbol=self.symbol,
                direction=self._entry_dir, qty=abs(old_qty),
                entry_price=self._entry_price, exit_price=fill.price,
                entry_ts=self._entry_ts, exit_ts=fill.ts, pnl=pnl,
                commission=fill.commission,
            )
            self.trade_count += 1
            self.wins += 1 if pnl > 0 else 0
            self.total_pnl += pnl
            self.day_pnl += pnl

        if opened_from_flat or flipped:
            self._entry_price = self.position.avg_price
            self._entry_ts = fill.ts
            self._entry_dir = "LONG" if new_qty > 0 else "SHORT"
            self._realized_at_entry = self.position.realized_pnl
        return closed

    def reset_day(self) -> None:
        self.day_pnl = 0.0


class Engine:
    def __init__(self, config: dict, broker: Broker, notifier: DiscordNotifier,
                 db: Database, feed: Optional[DataFeed] = None, provider: str = "",
                 bus: Optional[EventBus] = None):
        self.config = config
        self.broker = broker
        self.feed = feed
        self.notifier = notifier
        self.db = db
        self.provider = provider
        # A shared bus (owned by the controller) lets the dashboard's live stream
        # survive connect/disconnect cycles.
        self.bus = bus or EventBus()

        acct = config.get("account", {})
        self.portfolio = Portfolio(starting_balance=float(acct.get("starting_balance", 0) or 0))
        self.risk = RiskManager(RiskConfig(**config.get("risk", {})), self.portfolio)

        self.runners: list[StrategyRunner] = []
        self._build_runners(config.get("strategies", []))

        # REAL account state (from the provider) — never synthesized.
        self.live_account: Optional[AccountInfo] = None
        self.live_positions: list[BrokerPosition] = []
        self.pending: list[dict] = []     # semi-auto setups awaiting your approval
        self._sig_id = 0
        self.signal_ttl_s = float(config.get("signal_ttl_s", 120))
        self.equity_curve: list[tuple[float, float]] = []     # (ts, real equity)
        self._real_session_start: Optional[float] = None
        self._real_peak: Optional[float] = None
        self._real_day_key = time.strftime("%Y-%m-%d", time.localtime())

        self.account_poll_s = float(config.get("account_poll_s", 4.0))
        self._tasks: list[asyncio.Task] = []
        self._day_key = self._real_day_key
        self._bars_received = 0       # only "trading" once real bars actually flow
        self.started_at = time.time()
        self.last_status_msg = "monitoring" if feed is None else "connecting market data"

    def _build_runners(self, specs: list[dict]) -> None:
        for i, spec in enumerate(specs):
            key = spec["strategy"]
            symbol = spec["symbol"].upper()
            instance_id = spec.get("id") or f"{key}-{symbol}-{i+1}"
            strat = create_strategy(key, instance_id, symbol, spec.get("params", {}))
            self.runners.append(StrategyRunner(
                instance_id=instance_id, strategy=strat, symbol=symbol,
                enabled=spec.get("enabled", True), manual=spec.get("manual", False)))

    # --- lifecycle --------------------------------------------------------
    async def start(self) -> None:
        if not self.broker.connected:
            await self.broker.connect()
        await self.notifier.start()
        self.broker.on_fill(self._on_fill)

        await self.notifier.startup(
            [r.instance_id for r in self.runners if r.enabled],
            self.broker.name, self.feed.name if self.feed else "account-only")

        # Market data + strategy trading only if a feed is connected.
        if self.feed is not None:
            self.feed.on_bar(self._on_bar)
            self._tasks.append(asyncio.create_task(self._run_feed(), name="feed"))

        if self.broker.supports_account_data:
            self._tasks.append(asyncio.create_task(self._poll_account(), name="account"))

        self._tasks.append(asyncio.create_task(self._housekeeping(), name="housekeeping"))

    async def _run_feed(self) -> None:
        try:
            await self.feed.run()
        except Exception as e:
            import sys
            self.last_status_msg = f"market data feed error: {e}"
            print(f"[engine] feed error: {e!r}", file=sys.stderr)

    async def stop(self) -> None:
        if self.feed is not None:
            await self.feed.stop()
        for t in self._tasks:
            t.cancel()
        await self.broker.disconnect()
        await self.notifier.close()

    async def _housekeeping(self) -> None:
        while True:
            await asyncio.sleep(2.0)
            self._expire_signals()
            await self.bus.publish(EventType.STATE, self.snapshot())

    # --- REAL account polling --------------------------------------------
    async def _poll_account(self) -> None:
        while True:
            try:
                acct = await self.broker.fetch_account()
                positions = await self.broker.fetch_positions()
                if acct is not None:
                    self.live_account = acct
                    self.live_positions = positions
                    await self._on_real_account(acct)
                    await self.bus.publish(EventType.STATE, self.snapshot())
            except Exception as e:
                import sys
                print(f"[engine] account poll error: {e!r}", file=sys.stderr)
            await asyncio.sleep(self.account_poll_s)

    async def _on_real_account(self, acct: AccountInfo) -> None:
        """Track real equity, sample the curve, and guard the real account."""
        eq = acct.equity if acct.equity is not None else acct.balance
        if eq is None:
            return
        daykey = time.strftime("%Y-%m-%d", time.localtime())
        if daykey != self._real_day_key:
            self._real_day_key = daykey
            self._real_session_start = eq
            self.risk.day_halted = False
        if self._real_session_start is None:
            self._real_session_start = eq
        self._real_peak = eq if self._real_peak is None else max(self._real_peak, eq)

        self.equity_curve.append((time.time(), eq))
        if len(self.equity_curve) > 1500:
            self.equity_curve = self.equity_curve[-1500:]
        self.db.save_equity(eq)

        day_pnl = acct.day_pnl if acct.day_pnl is not None else eq - self._real_session_start
        drawdown = eq - self._real_peak
        cfg = self.risk.cfg

        if not self.risk.permanently_halted and cfg.halt_on_drawdown and drawdown <= -cfg.trailing_drawdown:
            self.risk.permanently_halted = True
            msg = f"REAL trailing drawdown breached ({drawdown:,.0f}) — flattening"
            self.last_status_msg = msg
            await self.notifier.risk(msg)
            await self.bus.publish(EventType.RISK_BLOCK, msg)
            await self._flatten_all("drawdown")
        elif not self.risk.day_halted and day_pnl <= -cfg.daily_loss_limit:
            self.risk.day_halted = True
            msg = f"REAL daily loss limit hit ({day_pnl:,.0f}) — flattening"
            self.last_status_msg = msg
            await self.notifier.risk(msg)
            await self.bus.publish(EventType.RISK_BLOCK, msg)
            await self._flatten_all("daily loss")

    # --- strategy trading (only with a market feed) ----------------------
    async def _on_bar(self, bar: Bar) -> None:
        self._bars_received += 1
        if self._bars_received == 1:
            self.last_status_msg = "trading on live market data"
        self.broker.update_price(bar.symbol, bar.close)
        for r in self.runners:
            if r.symbol == bar.symbol:
                r.position.mark(bar.close)
        if self.risk.trading_blocked:
            return
        for r in self.runners:
            if not r.enabled or r.symbol != bar.symbol:
                continue
            ctx = StrategyContext(r.position)
            try:
                r.strategy._feed_bar(bar, ctx)
            except Exception as e:
                import sys
                print(f"[engine] strategy {r.instance_id} error: {e!r}", file=sys.stderr)
                continue
            for intent in ctx.intents:
                await self._execute_intent(r, intent)

    async def _execute_intent(self, r: StrategyRunner, intent) -> None:
        pos = r.position
        if intent.type is IntentType.EXIT:
            if not pos.is_flat:
                side = OrderSide.SELL if pos.is_long else OrderSide.BUY
                await self._submit(r, side, abs(pos.qty), intent.reason)
            return
        want_long = intent.type is IntentType.ENTER_LONG
        if (want_long and pos.is_long) or (not want_long and pos.is_short):
            return
        open_contracts = sum(abs(x.position.qty) for x in self.runners)
        close_qty = abs(pos.qty)
        approval = self.risk.approve_entry(r.instance_id, open_contracts - close_qty, 0, intent.qty)
        if approval.block or approval.approved_qty <= 0:
            if close_qty:
                flat_side = OrderSide.SELL if pos.is_long else OrderSide.BUY
                await self._submit(r, flat_side, close_qty, "risk capped reversal -> flatten")
            return
        side = OrderSide.BUY if want_long else OrderSide.SELL
        qty = approval.approved_qty + close_qty

        # Semi-auto (cockpit): propose the entry for your approval instead of
        # firing it. Exits stay automatic (you never hand-approve a stop-loss).
        if r.manual:
            if not r._has_pending:
                self._propose_signal(r, side, qty, intent.reason)
            return

        await self._submit(r, side, qty, intent.reason)

    def _propose_signal(self, r: StrategyRunner, side: OrderSide, qty: int, reason: str) -> None:
        self._sig_id += 1
        strat = r.strategy
        self.pending.append({
            "id": f"sig-{self._sig_id}", "strategy_id": r.instance_id, "symbol": r.symbol,
            "side": side.value, "qty": qty, "reason": reason,
            "target": getattr(strat, "_entry_target", None),
            "stop": getattr(strat, "_entry_stop", None),
            "price": getattr(getattr(strat, "_prev", None), "close", None),
            "ts": time.time(),
        })
        r._has_pending = True

    async def approve_signal(self, sig_id: str) -> bool:
        sig = next((s for s in self.pending if s["id"] == sig_id), None)
        if not sig:
            return False
        r = next((x for x in self.runners if x.instance_id == sig["strategy_id"]), None)
        self.pending = [s for s in self.pending if s["id"] != sig_id]
        if r is None:
            return False
        r._has_pending = False
        await self._submit(r, OrderSide(sig["side"]), sig["qty"], f"approved: {sig['reason']}")
        return True

    def dismiss_signal(self, sig_id: str) -> bool:
        sig = next((s for s in self.pending if s["id"] == sig_id), None)
        if not sig:
            return False
        self.pending = [s for s in self.pending if s["id"] != sig_id]
        for r in self.runners:
            if r.instance_id == sig["strategy_id"]:
                r._has_pending = False
        return True

    def _expire_signals(self) -> None:
        now = time.time()
        live = []
        for s in self.pending:
            if now - s["ts"] <= self.signal_ttl_s:
                live.append(s)
            else:
                for r in self.runners:
                    if r.instance_id == s["strategy_id"]:
                        r._has_pending = False
        self.pending = live

    async def _submit(self, r: StrategyRunner, side: OrderSide, qty: int, reason: str) -> None:
        order = Order(strategy_id=r.instance_id, symbol=r.symbol, side=side, qty=qty, reason=reason)
        await self.bus.publish(EventType.ORDER, order)
        await self.broker.submit(order)

    async def _on_fill(self, fill: Fill) -> None:
        r = next((x for x in self.runners if x.instance_id == fill.strategy_id), None)
        if r is None:
            return
        self.db.save_fill(fill)
        was_flat = r.position.is_flat
        closed = r.apply_fill(fill)
        await self.bus.publish(EventType.FILL, fill)
        if closed is not None:
            self.portfolio.record_trade(closed)
            self.db.save_trade(closed)
            await self.notifier.exit(closed)
            await self.bus.publish(EventType.TRADE_CLOSED, closed)
        if was_flat and not r.position.is_flat:
            await self.notifier.entry(r.instance_id, fill.symbol, fill.side.value,
                                      fill.qty, fill.price)

    async def _flatten_all(self, reason: str) -> None:
        for r in self.runners:
            if not r.position.is_flat:
                side = OrderSide.SELL if r.position.is_long else OrderSide.BUY
                await self._submit(r, side, abs(r.position.qty), f"flatten ({reason})")
        for sym in {r.symbol for r in self.runners} | {p.symbol for p in self.live_positions}:
            try:
                await self.broker.flatten(sym)
            except Exception:
                pass

    # --- control surface --------------------------------------------------
    def toggle_strategy(self, instance_id: str, enabled: Optional[bool] = None) -> bool:
        for r in self.runners:
            if r.instance_id == instance_id:
                r.enabled = (not r.enabled) if enabled is None else enabled
                return r.enabled
        raise KeyError(instance_id)

    async def flatten_all_now(self) -> None:
        await self._flatten_all("manual")

    # --- dashboard snapshot (REAL data only) ------------------------------
    def snapshot(self) -> dict:
        a = self.live_account
        cfg = self.risk.cfg
        eq = (a.equity if a and a.equity is not None else (a.balance if a else None))
        day_pnl = a.day_pnl if (a and a.day_pnl is not None) else (
            (eq - self._real_session_start) if (eq is not None and self._real_session_start is not None) else None)
        drawdown = (eq - self._real_peak) if (eq is not None and self._real_peak is not None) else None

        def pct(used, limit):
            if not limit or used is None:
                return 0.0
            return min(100.0, max(0.0, -used / limit * 100.0))

        return {
            "ts": time.time(),
            "connected": self.broker.connected,
            "provider": self.provider,
            "broker": self.broker.name,
            "feed": self.feed.name if self.feed else None,
            "mode": "trading" if (self.feed and self._bars_received > 0) else "monitor",
            "account_sync": self.broker.supports_account_data,
            "status": self.last_status_msg,
            "uptime_s": time.time() - self.started_at,
            "account": {
                "synced": a is not None,
                "name": a.name if a else "",
                "account_id": a.account_id if a else "",
                "balance": a.balance if a else None,
                "equity": eq,
                "open_pnl": a.open_pnl if a else None,
                "day_pnl": day_pnl,
                "drawdown": drawdown,
                "peak_equity": self._real_peak,
                "can_trade": a.can_trade if a else None,
                "currency": a.currency if a else "USD",
                "open_contracts": sum(abs(p.qty) for p in self.live_positions),
            },
            "risk": {
                "daily_loss_limit": cfg.daily_loss_limit,
                "trailing_drawdown": cfg.trailing_drawdown,
                "max_contracts_account": cfg.max_contracts_account,
                "day_halted": self.risk.day_halted,
                "permanently_halted": self.risk.permanently_halted,
                "daily_loss_used_pct": pct(day_pnl if (day_pnl or 0) < 0 else 0, cfg.daily_loss_limit),
                "drawdown_used_pct": pct(drawdown, cfg.trailing_drawdown),
            },
            "live_positions": [
                {"symbol": p.symbol, "side": p.side, "qty": p.qty,
                 "avg_price": p.avg_price, "open_pnl": p.open_pnl}
                for p in self.live_positions
            ],
            "strategies": [
                {
                    "id": r.instance_id, "name": r.strategy.label, "key": r.strategy.key,
                    "symbol": r.symbol, "description": r.strategy.description,
                    "enabled": r.enabled, "manual": r.manual,
                    "position": r.position.side.value, "qty": r.position.qty,
                    "avg_price": r.position.avg_price, "unrealized": r.position.unrealized_pnl,
                    "day_pnl": r.day_pnl, "total_pnl": r.total_pnl, "trades": r.trade_count,
                    "win_rate": r.win_rate,
                    "viz": getattr(r.strategy, "viz_state", None),
                }
                for r in self.runners
            ],
            "pending_signals": self.pending,
            "equity_curve": self.equity_curve[-400:],
            "recent_trades": [
                {"id": t.id, "strategy": t.strategy_id, "symbol": t.symbol,
                 "direction": t.direction, "qty": t.qty, "entry": t.entry_price,
                 "exit": t.exit_price, "pnl": t.pnl, "ticks": t.pnl_ticks, "exit_ts": t.exit_ts}
                for t in reversed(self.portfolio.trades[-60:])
            ],
        }
