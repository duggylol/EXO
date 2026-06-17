"""
Discord notifications via webhook.

Sends a message on every entry and exit. Exit messages include a per-trade P/L
recap (dollars + ticks + win/loss), and embed color is green for a win, red for
a loss, yellow for risk events. Set DISCORD_WEBHOOK_URL in .env; if unset, the
notifier silently no-ops so the bot still runs.

Create a webhook in Discord: Server Settings -> Integrations -> Webhooks.
"""
from __future__ import annotations

import sys

from core.models import Fill, Trade

try:
    import aiohttp
except ImportError:  # pragma: no cover
    aiohttp = None

_GREEN = 0x3BA55D
_RED = 0xED4245
_YELLOW = 0xFAA61A
_GREY = 0x4F545C


class DiscordNotifier:
    def __init__(self, webhook_url: str = "", username: str = "EXO",
                 enabled: bool = True):
        self.webhook_url = webhook_url or ""
        self.username = username
        self.enabled = enabled and bool(self.webhook_url)
        self._session = None

    async def start(self) -> None:
        if self.enabled and aiohttp is not None:
            self._session = aiohttp.ClientSession()

    async def close(self) -> None:
        if self._session:
            await self._session.close()

    async def _send(self, title: str, lines: list[str], color: int) -> None:
        if not self.enabled or self._session is None:
            return
        embed = {
            "title": title,
            "description": "\n".join(lines),
            "color": color,
        }
        try:
            async with self._session.post(
                self.webhook_url,
                json={"username": self.username, "embeds": [embed]},
            ) as r:
                if r.status >= 300:
                    print(f"[discord] HTTP {r.status}: {await r.text()}", file=sys.stderr)
        except Exception as e:
            print(f"[discord] send error: {e!r}", file=sys.stderr)

    async def startup(self, strategies: list[str], broker: str, feed: str) -> None:
        await self._send(
            "🟢 Bot started",
            [f"**Broker:** {broker}", f"**Feed:** {feed}",
             f"**Strategies ({len(strategies)}):** {', '.join(strategies)}"],
            _GREY,
        )

    async def entry(self, strategy: str, symbol: str, side: str, qty: int, price: float) -> None:
        arrow = "🔼 LONG" if side == "BUY" else "🔽 SHORT"
        await self._send(
            f"{arrow}  {symbol}",
            [f"**Strategy:** {strategy}", f"**Side:** {side}  ×{qty}",
             f"**Entry:** {price:,.2f}"],
            _GREY,
        )

    async def exit(self, trade: Trade) -> None:
        win = trade.pnl >= 0
        sign = "🟩 WIN" if win else "🟥 LOSS"
        await self._send(
            f"{sign}  {trade.symbol}  {trade.direction}",
            [
                f"**Strategy:** {trade.strategy_id}",
                f"**Entry → Exit:** {trade.entry_price:,.2f} → {trade.exit_price:,.2f}",
                f"**Qty:** {trade.qty}",
                f"**P/L:** {'+' if win else ''}${trade.pnl:,.2f}  ({trade.pnl_ticks:+.0f} ticks)",
                f"**Held:** {trade.duration_s:,.0f}s",
            ],
            _GREEN if win else _RED,
        )

    async def risk(self, message: str) -> None:
        await self._send("⚠️ Risk event", [message], _YELLOW)
