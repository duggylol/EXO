"""Enumerations used across the engine."""
from __future__ import annotations

from enum import Enum


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

    @property
    def opposite(self) -> "OrderSide":
        return OrderSide.SELL if self is OrderSide.BUY else OrderSide.BUY


class PositionSide(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class IntentType(str, Enum):
    """What a strategy wants to do, expressed at the position level."""
    ENTER_LONG = "ENTER_LONG"
    ENTER_SHORT = "ENTER_SHORT"
    EXIT = "EXIT"  # flatten this strategy's position


class EventType(str, Enum):
    BAR = "BAR"
    TICK = "TICK"
    SIGNAL = "SIGNAL"
    ORDER = "ORDER"
    FILL = "FILL"
    TRADE_CLOSED = "TRADE_CLOSED"
    RISK_BLOCK = "RISK_BLOCK"
    STATE = "STATE"
    LOG = "LOG"
    UPDATE = "UPDATE"
