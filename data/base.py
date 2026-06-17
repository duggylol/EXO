"""Market data feed abstract base class."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Awaitable, Callable, Optional

from core.models import Bar

BarCallback = Callable[[Bar], Awaitable[None]]


class DataFeed(ABC):
    name: str = "base"

    def __init__(self, settings: dict):
        self.settings = settings or {}
        self.symbols: list[str] = list(self.settings.get("symbols", []))
        self._bar_cb: Optional[BarCallback] = None
        self._running = False

    def on_bar(self, cb: BarCallback) -> None:
        self._bar_cb = cb

    async def _emit_bar(self, bar: Bar) -> None:
        if self._bar_cb:
            await self._bar_cb(bar)

    @abstractmethod
    async def run(self) -> None:
        """Long-running coroutine that produces bars until stop() is called."""

    async def stop(self) -> None:
        self._running = False
