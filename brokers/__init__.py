"""Execution adapters. The engine talks to the Broker ABC only, so firms are swappable."""
from __future__ import annotations

from .base import Broker
from .paper import PaperBroker


def build_broker(name: str, settings: dict) -> Broker:
    name = (name or "paper").lower()
    if name == "paper":
        # Dev/backtest only — never exposed as a provider in the app.
        return PaperBroker(
            commission_per_contract=settings.get("commission_per_contract", 0.0),
            slippage_ticks=settings.get("slippage_ticks", 1.0),
        )
    if name == "projectx":
        from .projectx import ProjectXBroker
        return ProjectXBroker(settings)
    if name == "rithmic":
        from .rithmic import RithmicBroker
        return RithmicBroker(settings)
    if name == "traderspost":
        from .traderspost import TradersPostBroker
        return TradersPostBroker(settings)
    raise ValueError(f"unknown broker '{name}' (use: projectx | rithmic | traderspost)")
