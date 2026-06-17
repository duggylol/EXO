"""
Strategy base class, execution context, and a plugin registry.

To add a strategy: subclass `Strategy`, set a unique `key`, declare default
`params`, and implement `on_bar`. Decorate with `@register`. Drop the file in
the `strategies/` package and it is auto-discovered at startup.
"""
from __future__ import annotations

from typing import Optional

from .enums import IntentType, PositionSide
from .models import Bar, Intent, Position

# --- registry --------------------------------------------------------------

_REGISTRY: dict[str, type["Strategy"]] = {}


def register(cls: type["Strategy"]) -> type["Strategy"]:
    key = getattr(cls, "key", None)
    if not key:
        raise ValueError(f"{cls.__name__} must define a class-level `key`")
    if key in _REGISTRY:
        raise ValueError(f"duplicate strategy key: {key}")
    _REGISTRY[key] = cls
    return cls


def registry() -> dict[str, type["Strategy"]]:
    return dict(_REGISTRY)


def create_strategy(key: str, instance_id: str, symbol: str, params: dict) -> "Strategy":
    if key not in _REGISTRY:
        raise KeyError(f"unknown strategy '{key}'. Available: {sorted(_REGISTRY)}")
    cls = _REGISTRY[key]
    merged = {**cls.params, **(params or {})}
    return cls(instance_id=instance_id, symbol=symbol, params=merged)


# --- context ---------------------------------------------------------------

class StrategyContext:
    """Passed to `on_bar`. Strategies inspect their position and queue intents.

    Intents are collected and executed by the engine after `on_bar` returns, so
    strategy code stays synchronous, side-effect-free, and easy to unit test.
    """

    def __init__(self, position: Position):
        self.position = position
        self.intents: list[Intent] = []

    # position helpers
    @property
    def side(self) -> PositionSide:
        return self.position.side

    @property
    def is_flat(self) -> bool:
        return self.position.is_flat

    @property
    def is_long(self) -> bool:
        return self.position.is_long

    @property
    def is_short(self) -> bool:
        return self.position.is_short

    @property
    def avg_price(self) -> float:
        return self.position.avg_price

    @property
    def unrealized_pnl(self) -> float:
        return self.position.unrealized_pnl

    # intent helpers (position-level semantics)
    def buy(self, reason: str = "", qty: Optional[int] = None) -> None:
        """Go/stay long. If short, the engine reverses to long."""
        self.intents.append(Intent(IntentType.ENTER_LONG, reason, qty))

    def sell(self, reason: str = "", qty: Optional[int] = None) -> None:
        """Go/stay short. If long, the engine reverses to short."""
        self.intents.append(Intent(IntentType.ENTER_SHORT, reason, qty))

    def close(self, reason: str = "") -> None:
        """Flatten this strategy's position."""
        self.intents.append(Intent(IntentType.EXIT, reason))


# --- base strategy ---------------------------------------------------------

class Strategy:
    key: str = ""                  # unique identifier, e.g. "ma_cross"
    display_name: str = ""         # human label for the dashboard
    description: str = ""          # one-liner shown in the UI
    params: dict = {}              # default parameters

    def __init__(self, instance_id: str, symbol: str, params: dict):
        self.instance_id = instance_id
        self.symbol = symbol
        self.params = params
        self.warmup_bars = 0       # set by subclass if it needs N bars first
        self._bars_seen = 0
        self.setup()

    # lifecycle hooks ------------------------------------------------------
    def setup(self) -> None:
        """Create indicators here. Called once at construction."""

    def on_session_start(self) -> None:
        """Optional: reset session-anchored state (e.g. VWAP, opening range)."""

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> None:
        """Implement the trading logic. Use ctx.buy/sell/close."""
        raise NotImplementedError

    # internal -------------------------------------------------------------
    def _feed_bar(self, bar: Bar, ctx: StrategyContext) -> None:
        self._bars_seen += 1
        self.on_bar(bar, ctx)

    @property
    def label(self) -> str:
        return self.display_name or self.key
