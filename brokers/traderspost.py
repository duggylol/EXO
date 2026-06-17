"""
TradersPost webhook execution adapter (the automation route for Lucid Trading).

Lucid is the most automation-friendly of the firms researched, but it has no
native custom API — automated orders reach a Lucid (Tradovate-routed) account by
POSTing JSON signals to a TradersPost webhook, which executes them. So this
adapter is fire-and-forget: it sends the signal and optimistically books an
estimated local fill for dashboard/attribution purposes.

  LOCAL P/L IS AN ESTIMATE. The real fills live on your firm's platform; treat
  this engine's numbers as indicative and reconcile against TradersPost / your
  broker statement. Lucid bans HFT and sub-5-second microscalping — keep your
  strategies above that threshold.

Set the webhook URL (and optional shared secret) in config/.env.
"""
from __future__ import annotations

import sys
from typing import Optional

from core.models import Fill, Order
from .base import Broker

try:
    import aiohttp
except ImportError:  # pragma: no cover
    aiohttp = None


class TradersPostBroker(Broker):
    name = "traderspost"

    def __init__(self, settings: dict):
        super().__init__()
        self.webhook_url = settings.get("webhook_url", "")
        self.shared_secret = settings.get("shared_secret", "")
        self._last: dict[str, float] = {}
        self._session: Optional["aiohttp.ClientSession"] = None

    def update_price(self, symbol: str, price: float) -> None:
        self._last[symbol] = price

    async def connect(self) -> None:
        if aiohttp is None:
            raise RuntimeError("aiohttp is required for TradersPost. pip install aiohttp")
        if not self.webhook_url:
            raise RuntimeError(
                "TradersPost needs a webhook_url (TRADERSPOST_WEBHOOK_URL). "
                "Create it in your TradersPost strategy and connect Lucid via Tradovate."
            )
        self._session = aiohttp.ClientSession()
        self.connected = True

    async def disconnect(self) -> None:
        if self._session:
            await self._session.close()
        self.connected = False

    async def submit(self, order: Order) -> None:
        action = "buy" if order.side.value == "BUY" else "sell"
        payload = {
            "ticker": order.symbol,
            "action": action,
            "quantity": order.qty,
            "price": self._last.get(order.symbol),
            "time_in_force": "gtc",
            "signal": order.strategy_id,
        }
        if self.shared_secret:
            payload["secret"] = self.shared_secret
        try:
            assert self._session is not None
            async with self._session.post(self.webhook_url, json=payload) as r:
                if r.status >= 300:
                    print(f"[traderspost] webhook HTTP {r.status}: {await r.text()}",
                          file=sys.stderr)
        except Exception as e:  # network hiccup shouldn't crash the engine
            print(f"[traderspost] webhook error: {e!r}", file=sys.stderr)

        # Estimated local fill at last price (see module docstring caveat).
        ref = self._last.get(order.symbol, order.price or 0.0)
        await self._emit_fill(Fill(
            order_id=order.id, strategy_id=order.strategy_id, symbol=order.symbol,
            side=order.side, qty=order.qty, price=ref,
        ))
