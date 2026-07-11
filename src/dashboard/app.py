"""FastAPI dashboard for monitoring the arbitrage bot."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import jinja2

from ..core.types import ArbitrageOpportunity, TradeExecution
from ..risk.manager import RiskManager
from ..db.storage import Storage

logger = logging.getLogger(__name__)

# Templates
TEMPLATES_DIR = Path(__file__).parent / "templates"
template_loader = jinja2.FileSystemLoader(searchpath=str(TEMPLATES_DIR))
template_env = jinja2.Environment(loader=template_loader)


class DashboardApp:
    """Real-time FastAPI dashboard with WebSocket push."""

    def __init__(self, storage: Storage, risk: RiskManager):
        self.app = FastAPI(title="CEX-DEX Arbitrage Bot Dashboard")
        self.storage = storage
        self.risk = risk
        self._connected_clients: set[WebSocket] = set()
        self._latest_trades: list[TradeExecution] = []
        self._latest_opportunities: list[ArbitrageOpportunity] = []
        self._setup_routes()

    def _setup_routes(self):
        app = self.app

        @app.get("/", response_class=HTMLResponse)
        async def index():
            try:
                template = template_env.get_template("dashboard.html")
                stats = self.storage.get_stats()
                risk_status = self.risk.get_status()
                trades = self.storage.get_recent_trades(limit=20)
                opportunities = self.storage.get_recent_opportunities(limit=20)
                return template.render(
                    stats=stats,
                    risk=risk_status,
                    trades=trades,
                    opportunities=opportunities,
                )
            except jinja2.TemplateNotFound:
                return HTMLResponse("<h1>Dashboard template not found</h1><p>Run <code>mkdir -p src/dashboard/templates && ...</code></p>")

        @app.get("/api/stats")
        async def api_stats():
            return {
                **self.storage.get_stats(),
                "risk": self.risk.get_status(),
            }

        @app.get("/api/trades")
        async def api_trades(limit: int = 20):
            trades = self.storage.get_recent_trades(limit=limit)
            return [
                {
                    "id": t.id,
                    "symbol": t.symbol,
                    "direction": t.direction,
                    "status": t.status,
                    "profit_usd": t.profit_usd,
                    "size_usd": t.size_usd,
                    "cex_order_id": t.cex_order_id,
                    "dex_tx_hash": t.dex_tx_hash,
                    "error": t.error_message,
                    "started_at": t.started_at,
                    "completed_at": t.completed_at,
                }
                for t in trades
            ]

        @app.get("/api/opportunities")
        async def api_opportunities(limit: int = 20):
            opps = self.storage.get_recent_opportunities(limit=limit)
            return [
                {
                    "id": o.id,
                    "symbol": o.symbol,
                    "direction": o.direction,
                    "spread_pct": o.spread_pct,
                    "net_profit_usd": o.net_profit_usd,
                    "max_size_usd": o.max_size_usd,
                    "confidence": o.confidence,
                    "executed": o.executed,
                    "timestamp": o.timestamp,
                }
                for o in opps
            ]

        @app.websocket("/ws")
        async def websocket_endpoint(ws: WebSocket):
            await ws.accept()
            self._connected_clients.add(ws)
            try:
                while True:
                    await ws.receive_text()  # Keep alive
            except WebSocketDisconnect:
                self._connected_clients.discard(ws)

    async def push_opportunity(self, opp: ArbitrageOpportunity):
        """Push a new opportunity to all connected clients."""
        data = {
            "type": "opportunity",
            "symbol": opp.symbol,
            "direction": opp.direction.value,
            "spread_pct": opp.spread_pct,
            "net_profit_usd": float(opp.net_profit_usd),
            "max_size_usd": float(opp.max_size_usd),
            "confidence": opp.confidence,
        }
        await self._broadcast(data)

    async def push_trade(self, trade: TradeExecution):
        """Push a trade update to all connected clients."""
        data = {
            "type": "trade",
            "symbol": trade.symbol,
            "direction": trade.direction.value if trade.direction else "",
            "status": trade.status.value,
            "profit_usd": float(trade.profit_usd) if trade.profit_usd else 0,
            "size_usd": float(trade.size_usd),
            "error": trade.error_message or "",
        }
        await self._broadcast(data)

    async def _broadcast(self, data: dict):
        """Send data to all connected WebSocket clients."""
        dead = set()
        for ws in self._connected_clients:
            try:
                await ws.send_json(data)
            except Exception:
                dead.add(ws)
        self._connected_clients -= dead
