"""A tiny async pub/sub bus used to fan engine events out to subscribers.

The dashboard's WebSocket layer and the persistence layer both subscribe here,
so the engine never has to know who is listening.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, Awaitable, Callable

from .enums import EventType

Handler = Callable[[EventType, Any], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[EventType, list[Handler]] = defaultdict(list)
        self._all: list[Handler] = []

    def subscribe(self, event_type: EventType | None, handler: Handler) -> None:
        if event_type is None:
            self._all.append(handler)
        else:
            self._subs[event_type].append(handler)

    async def publish(self, event_type: EventType, payload: Any) -> None:
        handlers = self._subs.get(event_type, []) + self._all
        if not handlers:
            return
        # Fire handlers concurrently; never let one bad subscriber kill the bus.
        results = await asyncio.gather(
            *(h(event_type, payload) for h in handlers),
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, Exception):
                # Subscribers are best-effort; log to stderr and continue.
                import sys
                print(f"[event_bus] subscriber error: {r!r}", file=sys.stderr)
