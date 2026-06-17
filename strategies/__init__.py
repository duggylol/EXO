"""
Strategy plugin package.

Every module here that defines a `@register`-decorated Strategy subclass is
auto-discovered at startup. To add a strategy, drop a new .py file in this
folder — no wiring needed.
"""
from __future__ import annotations

import importlib
import pkgutil


def load_all() -> None:
    """Import every strategy module so its @register runs.

    Iterates over the package's own __path__ (rather than a filesystem dir) so
    discovery also works when frozen by PyInstaller, provided the build collects
    this package's submodules (see FuturesBot.spec -> collect_submodules).
    """
    for mod in pkgutil.iter_modules(__path__, prefix=f"{__name__}."):
        short = mod.name.rsplit(".", 1)[-1]
        if not short.startswith("_"):
            importlib.import_module(mod.name)
