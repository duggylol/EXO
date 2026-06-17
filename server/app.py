"""
FastAPI app: serves the welcome/onboarding flow and the dashboard, and streams
live engine state over WebSocket.

REST:
    GET  /api/providers              -> connectable providers + their fields
    GET  /api/status                 -> connection status
    GET  /api/state                  -> full snapshot (real data only)
    POST /api/connect  {provider, fields}  -> validate creds, save, connect
    POST /api/disconnect {forget?}    -> tear down the connection
    POST /api/strategy/{id}/toggle    -> enable/disable a strategy
    POST /api/flatten                 -> flatten everything now
WebSocket:
    /ws  -> {type:"state"|"trade"|"risk"} messages
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from core import paths
from core.enums import EventType

STATIC_DIR = paths.resource_path("server/static")


class ConnectionManager:
    def __init__(self) -> None:
        self.active: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.active.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self.active.discard(ws)

    async def broadcast(self, message: dict) -> None:
        dead = []
        for ws in list(self.active):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


def create_app(controller) -> FastAPI:
    manager = ConnectionManager()

    async def on_state(_et, payload):
        await manager.broadcast({"type": "state", "data": payload})

    async def on_trade(_et, t):
        await manager.broadcast({"type": "trade", "data": {
            "strategy": t.strategy_id, "symbol": t.symbol, "direction": t.direction,
            "pnl": t.pnl, "ticks": t.pnl_ticks}})

    async def on_risk(_et, msg):
        await manager.broadcast({"type": "risk", "data": {"message": msg}})

    async def on_update(_et, status):
        await manager.broadcast({"type": "update", "data": status})

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # Subscribe once to the controller's persistent bus (survives reconnects).
        controller.bus.subscribe(EventType.STATE, on_state)
        controller.bus.subscribe(EventType.TRADE_CLOSED, on_trade)
        controller.bus.subscribe(EventType.RISK_BLOCK, on_risk)
        controller.bus.subscribe(EventType.UPDATE, on_update)
        await controller.auto_connect()       # reconnect saved provider if any
        controller.start_background()          # periodic update checks
        try:
            yield
        finally:
            await controller.shutdown()

    app = FastAPI(title="EXO", lifespan=lifespan)

    @app.get("/api/providers")
    async def providers():
        return controller.providers()

    @app.get("/api/status")
    async def status():
        return controller.status()

    @app.get("/api/state")
    async def state():
        return JSONResponse(controller.snapshot())

    @app.post("/api/connect")
    async def connect(req: Request):
        body = await req.json()
        provider = body.get("provider")
        fields = body.get("fields", {})
        if not provider:
            return JSONResponse({"ok": False, "error": "no provider"}, status_code=400)
        result = await controller.connect(provider, fields)
        await manager.broadcast({"type": "state", "data": controller.snapshot()})
        return JSONResponse(result, status_code=200 if result.get("ok") else 400)

    @app.post("/api/disconnect")
    async def disconnect(req: Request):
        body = {}
        try:
            body = await req.json()
        except Exception:
            pass
        await controller.disconnect(forget=bool(body.get("forget")))
        return {"ok": True}

    @app.post("/api/strategy/{instance_id}/toggle")
    async def toggle(instance_id: str):
        try:
            return {"id": instance_id, "enabled": controller.toggle_strategy(instance_id)}
        except KeyError:
            return JSONResponse({"error": "unknown strategy or not connected"}, status_code=404)

    @app.post("/api/flatten")
    async def flatten():
        await controller.flatten_all()
        return {"ok": True}

    @app.get("/api/update/status")
    async def update_status():
        return controller.update_status()

    @app.post("/api/update/check")
    async def update_check():
        return await controller.check_updates()

    @app.post("/api/update/apply")
    async def update_apply():
        result = await controller.apply_update()
        return JSONResponse(result, status_code=200 if result.get("ok") else 400)

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await manager.connect(ws)
        try:
            await ws.send_json({"type": "state", "data": controller.snapshot()})
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            manager.disconnect(ws)
        except Exception:
            manager.disconnect(ws)

    @app.get("/")
    async def index():
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
    return app


# Backwards-compatible alias (older callers passed an engine; now a controller).
create_app_from_controller = create_app
