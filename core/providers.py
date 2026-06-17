"""
Provider registry — the list of real connections shown on the welcome screen.

There is intentionally NO simulated/paper provider here: the app only ever
shows data from a real connection. Each provider declares the credential fields
the user must enter (the ones their prop firm gives them) and its real
capabilities (can it report account data? does it stream in real time?).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass
class Field:
    key: str
    label: str
    type: str = "text"        # "text" | "password"
    placeholder: str = ""
    required: bool = True
    default: str = ""
    help: str = ""


@dataclass
class Provider:
    id: str
    name: str
    description: str
    broker_type: str                 # -> brokers.build_broker
    feed_type: Optional[str]         # market-data feed, or None (account-only)
    account_sync: bool               # can display REAL account balance/positions
    realtime: bool                   # streaming updates available
    fields: list = field(default_factory=list)
    notes: str = ""

    def to_public(self) -> dict:
        d = asdict(self)
        return d


PROVIDERS: list[Provider] = [
    Provider(
        id="topstepx",
        name="TopstepX / ProjectX",
        description="Topstep and other ProjectX-powered firms. Real account data, "
                    "positions, and execution over the ProjectX REST API.",
        broker_type="projectx",
        feed_type="projectx",
        account_sync=True,
        realtime=True,
        fields=[
            Field("username", "Username", "text", "your TopstepX username"),
            Field("api_key", "API key", "password", "from your TopstepX/ProjectX dashboard"),
            Field("account_name", "Account name", "text", "leave blank to auto-detect",
                  required=False),
            Field("base_url", "API base URL", "text", default="https://api.topstepx.com",
                  help="Use your firm's ProjectX gateway URL if different."),
        ],
        notes="TopstepX prohibits running on a VPS/VPN/remote server — run on your own device.",
    ),
    Provider(
        id="rithmic",
        name="Rithmic",
        description="Direct Rithmic connection (market data + execution + account P/L) "
                    "via the cross-platform Protocol Buffer API.",
        broker_type="rithmic",
        feed_type="rithmic",
        account_sync=True,
        realtime=True,
        fields=[
            Field("user", "Rithmic user", "text"),
            Field("password", "Password", "password"),
            Field("system_name", "System name", "text", default="Rithmic Paper Trading",
                  help="e.g. 'Rithmic Paper Trading' or your firm's live system name."),
            Field("gateway", "Gateway", "text", default="Rithmic Paper Trading"),
        ],
        notes="Requires Rithmic API-enabled credentials. Install the optional 'async-rithmic' package.",
    ),
    Provider(
        id="traderspost",
        name="TradersPost (Lucid Trading)",
        description="Send automated orders to a Lucid (Tradovate-routed) account via a "
                    "TradersPost webhook. Execution only.",
        broker_type="traderspost",
        feed_type=None,
        account_sync=False,
        realtime=False,
        fields=[
            Field("webhook_url", "Webhook URL", "password", "from your TradersPost strategy"),
            Field("shared_secret", "Shared secret", "password", "optional", required=False),
        ],
        notes="This connection sends orders one-way; it cannot read account balances back, "
              "so account figures aren't available through it. Reconcile P/L on your platform.",
    ),
]

_BY_ID = {p.id: p for p in PROVIDERS}


def get_provider(provider_id: str) -> Provider:
    if provider_id not in _BY_ID:
        raise KeyError(f"unknown provider '{provider_id}'")
    return _BY_ID[provider_id]


def public_list() -> list[dict]:
    return [p.to_public() for p in PROVIDERS]
