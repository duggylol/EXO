"""
Rithmic execution + account adapter via the open-source `async_rithmic` library.

Cross-platform (uses Rithmic's Protocol Buffer interface, not the Windows-only
.NET R|API). Needs Rithmic API-enabled credentials and `pip install async-rithmic`.

This is a best-effort adapter built to async_rithmic's documented API surface
(list_accounts / submit_order / get_fill_history, PnL updates). The exact field
names for balance/PnL vary by library version and account type, so VALIDATE
against your live Rithmic credentials before trusting the account figures —
anything the library doesn't return is left as None (shown as '—'), never faked.
"""
from __future__ import annotations

import sys
from typing import Optional

from core.enums import OrderSide
from core.models import AccountInfo, BrokerPosition, Fill, Order
from .base import Broker

try:
    from async_rithmic import RithmicClient  # type: ignore
except ImportError:  # pragma: no cover
    RithmicClient = None


class RithmicBroker(Broker):
    name = "rithmic"
    supports_account_data = True

    def __init__(self, settings: dict):
        super().__init__()
        self.user = settings.get("user", "")
        self.password = settings.get("password", "")
        self.system_name = settings.get("system_name", "Rithmic Paper Trading")
        self.gateway = settings.get("gateway", "Rithmic Paper Trading")
        self.app_name = settings.get("app_name", "futures-trading-bot")
        self.app_version = settings.get("app_version", "1.0")
        self.exchange = settings.get("exchange", "CME")
        self._client = None
        self._account_id = ""
        self._last: dict[str, float] = {}

    def update_price(self, symbol: str, price: float) -> None:
        self._last[symbol] = price

    async def connect(self) -> None:
        if RithmicClient is None:
            raise RuntimeError("async_rithmic not installed. pip install async-rithmic")
        if not (self.user and self.password):
            raise RuntimeError("Rithmic needs user + password.")
        self._client = RithmicClient(
            user=self.user, password=self.password, system_name=self.system_name,
            app_name=self.app_name, app_version=self.app_version, gateway=self.gateway,
        )
        await self._client.connect()
        accounts = await self._client.list_accounts()
        if accounts:
            first = accounts[0]
            self._account_id = getattr(first, "account_id", None) or (
                first.get("account_id") if isinstance(first, dict) else "")
        self.connected = True

    async def disconnect(self) -> None:
        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception:
                pass
        self.connected = False

    async def test_connection(self) -> tuple[bool, str]:
        try:
            await self.connect()
            return True, f"Connected ({self._account_id})" if self._account_id else "Connected"
        except Exception as e:
            return False, str(e)

    async def fetch_account(self) -> Optional[AccountInfo]:
        if not self.connected or self._client is None:
            return None
        try:
            accounts = await self._client.list_accounts()
            if not accounts:
                return None
            a = accounts[0]
            get = (lambda k: getattr(a, k, None)) if not isinstance(a, dict) else a.get
            return AccountInfo(
                provider="rithmic",
                account_id=str(self._account_id),
                name=str(get("account_name") or get("account_id") or self._account_id),
                balance=get("account_balance") or get("balance"),
                open_pnl=get("open_position_pnl") or get("open_pnl"),
                day_pnl=get("day_pnl"),
            )
        except Exception as e:
            print(f"[rithmic] fetch_account error: {e!r}", file=sys.stderr)
            return None

    async def fetch_positions(self) -> list[BrokerPosition]:
        if not self.connected or self._client is None:
            return []
        try:
            positions = await self._client.list_positions()  # type: ignore[attr-defined]
        except Exception:
            return []
        out: list[BrokerPosition] = []
        for p in positions or []:
            get = (lambda k: getattr(p, k, None)) if not isinstance(p, dict) else p.get
            qty = int(get("net_quantity") or get("quantity") or 0)
            out.append(BrokerPosition(
                symbol=str(get("symbol") or ""),
                qty=qty,
                avg_price=get("avg_price") or get("average_price"),
                open_pnl=get("open_pnl"),
            ))
        return out

    async def submit(self, order: Order) -> None:
        if self._client is None:
            return
        try:
            await self._client.submit_order(  # type: ignore[attr-defined]
                symbol=order.symbol, exchange=self.exchange,
                qty=order.qty,
                order_type="MARKET",
                side="BUY" if order.side is OrderSide.BUY else "SELL",
            )
        except Exception as e:
            print(f"[rithmic] submit error: {e!r}", file=sys.stderr)
            return
        ref = self._last.get(order.symbol, order.price or 0.0)
        await self._emit_fill(Fill(order_id=order.id, strategy_id=order.strategy_id,
                                   symbol=order.symbol, side=order.side, qty=order.qty, price=ref))
