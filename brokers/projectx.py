"""
ProjectX Gateway API execution adapter (TopstepX and other ProjectX-powered firms).

REST for trading operations; cross-platform (Mac/Windows/Linux). Activates only
when you provide credentials in config/.env. Endpoint shapes follow the public
ProjectX Gateway docs (https://gateway.docs.projectx.com) — VERIFY the exact
paths/enums for your firm before live trading, as they evolve.

IMPORTANT COMPLIANCE NOTE (verified in research, mid-2026):
  * TopstepX prohibits running automation on a VPS/VPN/remote server — all
    activity must originate from your personal device. Run this on your own
    always-on machine, not a cloud VPS, on the Topstep/ProjectX path.
  * After ProjectX went Topstep-exclusive (Feb 28, 2026), non-Topstep firms
    (incl. Lucid) lost ProjectX access — use the TradersPost adapter for Lucid.

Fill handling: a successful /Order/place is optimistically reported as a fill at
the latest known price (fine for market orders). For production, reconcile real
fills via the ProjectX SignalR *user hub* (GatewayUserTrade) — see TODO below.
"""
from __future__ import annotations

import sys
from typing import Optional

from core.enums import OrderType
from core.models import AccountInfo, BrokerPosition, Fill, Order
from .base import Broker

try:
    import aiohttp
except ImportError:  # pragma: no cover
    aiohttp = None

# ProjectX order enums (per gateway docs).
_PX_SIDE = {"BUY": 0, "SELL": 1}          # 0 = Bid/Buy, 1 = Ask/Sell
_PX_TYPE = {"LIMIT": 1, "MARKET": 2, "STOP": 4}


class ProjectXBroker(Broker):
    name = "projectx"
    supports_account_data = True

    def __init__(self, settings: dict):
        super().__init__()
        self.base_url = settings.get("base_url", "https://api.topstepx.com").rstrip("/")
        self.username = settings.get("username", "")
        self.api_key = settings.get("api_key", "")
        self.account_name = settings.get("account_name", "")
        self._token: Optional[str] = None
        self._account_id: Optional[int] = None
        self._contract_ids: dict[str, str] = {}
        self._last: dict[str, float] = {}
        self._session: Optional["aiohttp.ClientSession"] = None

    def update_price(self, symbol: str, price: float) -> None:
        self._last[symbol] = price

    # --- HTTP helpers -----------------------------------------------------
    def _headers(self) -> dict:
        h = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    async def _post(self, path: str, body: dict) -> dict:
        assert self._session is not None
        url = f"{self.base_url}{path}"
        async with self._session.post(url, json=body, headers=self._headers()) as r:
            r.raise_for_status()
            return await r.json()

    # --- lifecycle --------------------------------------------------------
    async def connect(self) -> None:
        if aiohttp is None:
            raise RuntimeError("aiohttp is required for ProjectX. pip install aiohttp")
        if not (self.username and self.api_key):
            raise RuntimeError(
                "ProjectX needs username + api_key. Set them in config/.env "
                "(PROJECTX_USERNAME / PROJECTX_API_KEY)."
            )
        self._session = aiohttp.ClientSession()

        # 1) Authenticate with API key -> bearer token.
        auth = await self._post("/api/Auth/loginKey",
                                {"userName": self.username, "apiKey": self.api_key})
        self._token = auth.get("token")
        if not self._token:
            raise RuntimeError(f"ProjectX auth failed: {auth}")

        # 2) Resolve the trading account id.
        accts = await self._post("/api/Account/search", {"onlyActiveAccounts": True})
        accounts = accts.get("accounts", [])
        match = next((a for a in accounts
                      if not self.account_name or a.get("name") == self.account_name), None)
        if not match and accounts:
            match = accounts[0]
        if not match:
            raise RuntimeError("ProjectX: no active accounts found for these credentials")
        self._account_id = match["id"]
        print(f"[projectx] connected, account={match.get('name')} id={self._account_id}",
              file=sys.stderr)
        self.connected = True

    async def disconnect(self) -> None:
        if self._session:
            await self._session.close()
        self.connected = False

    async def _resolve_contract(self, symbol: str) -> str:
        if symbol in self._contract_ids:
            return self._contract_ids[symbol]
        res = await self._post("/api/Contract/search", {"searchText": symbol, "live": True})
        contracts = res.get("contracts", [])
        if not contracts:
            raise RuntimeError(f"ProjectX: no contract found for '{symbol}'")
        cid = contracts[0]["id"]
        self._contract_ids[symbol] = cid
        return cid

    # --- orders -----------------------------------------------------------
    async def submit(self, order: Order) -> None:
        contract_id = await self._resolve_contract(order.symbol)
        body = {
            "accountId": self._account_id,
            "contractId": contract_id,
            "type": _PX_TYPE.get(order.type.value, 2),
            "side": _PX_SIDE[order.side.value],
            "size": order.qty,
            "limitPrice": order.price if order.type is OrderType.LIMIT else None,
            "stopPrice": order.stop_price if order.type is OrderType.STOP else None,
            "customTag": order.strategy_id,
        }
        res = await self._post("/api/Order/place", body)
        if not res.get("success", True) and "orderId" not in res:
            print(f"[projectx] order rejected: {res}", file=sys.stderr)
            return

        # Optimistic fill at last price. TODO(production): subscribe to the
        # ProjectX SignalR user hub and emit fills from GatewayUserTrade events
        # instead, for exact fill prices and partial fills.
        ref = self._last.get(order.symbol, order.price or 0.0)
        await self._emit_fill(Fill(
            order_id=order.id, strategy_id=order.strategy_id, symbol=order.symbol,
            side=order.side, qty=order.qty, price=ref,
        ))

    async def flatten(self, symbol: str) -> None:
        contract_id = await self._resolve_contract(symbol)
        await self._post("/api/Position/closeContract",
                         {"accountId": self._account_id, "contractId": contract_id})

    # --- onboarding + real account data -----------------------------------
    async def test_connection(self) -> tuple[bool, str]:
        try:
            await self.connect()
            acct = await self.fetch_account()
            label = (acct.name or str(acct.account_id)) if acct else ""
            return True, f"Connected to {label}" if label else "Connected"
        except Exception as e:
            return False, str(e)

    async def fetch_account(self) -> Optional[AccountInfo]:
        if not self.connected or self._account_id is None:
            return None
        res = await self._post("/api/Account/search", {"onlyActiveAccounts": True})
        accounts = res.get("accounts", [])
        match = next((a for a in accounts if a.get("id") == self._account_id),
                     accounts[0] if accounts else None)
        if not match:
            return None
        positions = await self.fetch_positions()
        open_pnl = None
        pnls = [p.open_pnl for p in positions if p.open_pnl is not None]
        if pnls:
            open_pnl = sum(pnls)
        balance = match.get("balance")
        equity = balance + open_pnl if (balance is not None and open_pnl is not None) else balance
        return AccountInfo(
            provider="projectx",
            account_id=str(match.get("id", "")),
            name=match.get("name", ""),
            balance=balance,
            equity=equity,
            open_pnl=open_pnl,
            can_trade=match.get("canTrade"),
        )

    async def fetch_positions(self) -> list[BrokerPosition]:
        if not self.connected or self._account_id is None:
            return []
        res = await self._post("/api/Position/searchOpen", {"accountId": self._account_id})
        out: list[BrokerPosition] = []
        for p in res.get("positions", []):
            # Field names per ProjectX docs — verify against your firm's gateway.
            size = p.get("size", p.get("netQuantity", 0)) or 0
            ptype = p.get("type")            # 1 = long, 2 = short (per docs)
            qty = -abs(size) if ptype == 2 else abs(size)
            out.append(BrokerPosition(
                symbol=str(p.get("symbolId") or p.get("contractId", "")),
                qty=int(qty),
                avg_price=p.get("averagePrice"),
                open_pnl=p.get("profitAndLoss", p.get("unrealizedPnl")),
            ))
        return out
