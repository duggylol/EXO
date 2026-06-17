"""Broker (execution adapter) abstract base class."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Awaitable, Callable, Optional

from core.models import AccountInfo, BrokerPosition, Fill, Order

FillCallback = Callable[[Fill], Awaitable[None]]


class Broker(ABC):
    name: str = "base"

    # Capability flags — drive what the dashboard shows. Real connections that
    # can report account state set supports_account_data = True.
    supports_account_data: bool = False

    def __init__(self) -> None:
        self._fill_cb: Optional[FillCallback] = None
        self.connected = False

    def on_fill(self, cb: FillCallback) -> None:
        """Engine registers its fill handler here."""
        self._fill_cb = cb

    async def _emit_fill(self, fill: Fill) -> None:
        if self._fill_cb:
            await self._fill_cb(fill)

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def test_connection(self) -> tuple[bool, str]:
        """Validate credentials for the onboarding flow. Returns (ok, message).
        `message` is an account label on success or an error string on failure."""
        try:
            await self.connect()
            return True, "connected"
        except Exception as e:
            return False, str(e)

    def update_price(self, symbol: str, price: float) -> None:
        """Engine pushes latest prices so paper/sim brokers can fill realistically."""

    @abstractmethod
    async def submit(self, order: Order) -> None:
        """Submit an order. A resulting Fill must be delivered via _emit_fill()."""

    async def flatten(self, symbol: str) -> None:
        """Optional: flatten a symbol at the venue. Default: no-op."""

    # --- real account data (override in providers that support it) --------
    async def fetch_account(self) -> Optional[AccountInfo]:
        """Return REAL account info from the provider, or None if unsupported."""
        return None

    async def fetch_positions(self) -> list[BrokerPosition]:
        """Return REAL open positions from the provider, or [] if unsupported."""
        return []
