"""Market data feeds. Engine consumes Bar events via the DataFeed ABC."""
from __future__ import annotations

from .base import DataFeed
from .simulated import SimulatedFeed


def build_feed(name: str, settings: dict) -> DataFeed:
    name = (name or "simulated").lower()
    if name == "simulated":
        return SimulatedFeed(settings)
    if name == "csv":
        from .csv_feed import CSVFeed
        return CSVFeed(settings)
    if name == "rithmic":
        from .rithmic_feed import RithmicFeed
        return RithmicFeed(settings)
    if name == "projectx":
        from .projectx_feed import ProjectXFeed
        return ProjectXFeed(settings)
    raise ValueError(f"unknown feed '{name}' (use: simulated | csv | rithmic | projectx)")
