"""
Paper / simulation broker.

Fills market orders immediately at the latest known price plus a configurable
slippage, and charges commission per contract. This lets the entire platform
run end-to-end with zero credentials and zero cost — use it for development,
backtesting-style forward testing, and demoing the dashboard.
"""
from __future__ import annotations

from core.enums import OrderType
from core.instruments import get_instrument
from core.models import Fill, Order
from .base import Broker


class PaperBroker(Broker):
    name = "paper"

    def __init__(self, commission_per_contract: float = 0.0, slippage_ticks: float = 1.0):
        super().__init__()
        self.commission_per_contract = commission_per_contract
        self.slippage_ticks = slippage_ticks
        self._last: dict[str, float] = {}

    def update_price(self, symbol: str, price: float) -> None:
        self._last[symbol] = price

    async def submit(self, order: Order) -> None:
        ref = self._last.get(order.symbol, order.price or 0.0)
        instr = get_instrument(order.symbol)
        slip = self.slippage_ticks * instr.tick_size

        if order.type is OrderType.MARKET:
            # Buy pays up, sell receives down — adverse slippage.
            fill_price = ref + slip if order.side.value == "BUY" else ref - slip
        else:
            fill_price = order.price if order.price is not None else ref

        fill = Fill(
            order_id=order.id,
            strategy_id=order.strategy_id,
            symbol=order.symbol,
            side=order.side,
            qty=order.qty,
            price=fill_price,
            commission=self.commission_per_contract * order.qty,
        )
        await self._emit_fill(fill)
