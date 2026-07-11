"""Binance price scanner — WebSocket depth + REST ticker."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from decimal import Decimal
from typing import Callable, Dict, Optional, Set

import aiohttp

from ..core.config import BinanceConfig
from ..core.types import PriceSnapshot

logger = logging.getLogger(__name__)


class BinanceScanner:
    """Real-time price scanner for Binance using WebSocket streams + REST fallback."""

    WSS_BASE = "wss://stream.binance.com:9443/ws"
    REST_BASE = "https://api.binance.com/api/v3"

    def __init__(self, config: BinanceConfig):
        self.config = config
        self._symbols: Set[str] = set()
        self._prices: Dict[str, PriceSnapshot] = {}
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._running = False
        self._on_price: Optional[Callable[[PriceSnapshot], None]] = None

    def on_price_update(self, callback: Callable[[PriceSnapshot], None]):
        """Register callback for every price update."""
        self._on_price = callback

    def set_symbols(self, symbols: list[str]):
        """Set the list of trading pairs to monitor (e.g. ['ETHUSDT', 'BTCUSDT'])."""
        self._symbols = set(s.upper().replace("/", "").replace("-", "") for s in symbols)

    async def start(self):
        """Start the WebSocket price feed."""
        self._running = True
        self._session = aiohttp.ClientSession()
        await self._fetch_initial_prices()

        # Start WebSocket stream
        asyncio.create_task(self._ws_loop())
        # Start periodic REST refresh as fallback
        asyncio.create_task(self._rest_refresh_loop())

        logger.info("BinanceScanner started: %d symbols", len(self._symbols))

    async def stop(self):
        """Shut down the scanner."""
        self._running = False
        if self._ws:
            await self._ws.close()
        if self._session:
            await self._session.close()

    def get_price(self, symbol: str) -> Optional[PriceSnapshot]:
        """Get the latest price snapshot for a symbol."""
        key = symbol.upper().replace("/", "").replace("-", "")
        return self._prices.get(key)

    def get_all_prices(self) -> Dict[str, PriceSnapshot]:
        return dict(self._prices)

    async def _ws_loop(self):
        """Maintain WebSocket connection with auto-reconnect."""
        while self._running:
            try:
                streams = [f"{s.lower()}@depth20@100ms" for s in self._symbols]
                url = f"{self.WSS_BASE}/{'/'.join(streams)}"
                logger.debug("Connecting WebSocket for %d streams", len(self._symbols))

                async with self._session.ws_connect(url, heartbeat=30) as ws:
                    self._ws = ws
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            await self._handle_ws_message(msg.data)
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            logger.error("WebSocket error: %s", ws.exception())
                            break
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("WebSocket disconnected: %s — reconnecting in 5s", e)
                await asyncio.sleep(5)

    async def _handle_ws_message(self, raw: str):
        """Process a WebSocket depth message."""
        try:
            data = json.loads(raw)
            symbol = data.get("s", "")
            if not symbol:
                return

            # Parse top bids and asks
            bids = data.get("b", [])
            asks = data.get("a", [])

            if not bids or not asks:
                return

            best_bid = Decimal(bids[0][0]) if bids else Decimal(0)
            best_ask = Decimal(asks[0][0]) if asks else Decimal(0)
            mid = (best_bid + best_ask) / 2

            snapshot = PriceSnapshot(
                symbol=symbol,
                cex_bid=best_bid,
                cex_ask=best_ask,
                cex_last=mid,
                dex_price=Decimal(0),  # Filled by opportunity detector
                dex_liquidity_usd=Decimal(0),
                timestamp=time.time(),
            )

            # Preserve any existing DEX price data
            existing = self._prices.get(symbol)
            if existing and existing.dex_price > 0:
                snapshot.dex_price = existing.dex_price
                snapshot.dex_liquidity_usd = existing.dex_liquidity_usd

            self._prices[symbol] = snapshot

            if self._on_price:
                self._on_price(snapshot)

        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.debug("Failed to parse WS message: %s", e)

    async def _fetch_initial_prices(self):
        """Fetch current prices via REST on startup."""
        if not self._symbols:
            return

        try:
            symbols_param = '["' + '","'.join(self._symbols) + '"]'
            url = f"{self.REST_BASE}/ticker/bookTicker"
            async with self._session.get(url) as resp:
                if resp.ok:
                    data = await resp.json()
                    for item in data:
                        sym = item.get("symbol", "")
                        if sym in self._symbols:
                            self._prices[sym] = PriceSnapshot(
                                symbol=sym,
                                cex_bid=Decimal(item.get("bidPrice", "0")),
                                cex_ask=Decimal(item.get("askPrice", "0")),
                                cex_last=(Decimal(item.get("bidPrice", "0")) +
                                          Decimal(item.get("askPrice", "0"))) / 2,
                                dex_price=Decimal(0),
                                dex_liquidity_usd=Decimal(0),
                                timestamp=time.time(),
                            )
        except Exception as e:
            logger.warning("Failed to fetch initial prices: %s", e)

    async def _rest_refresh_loop(self):
        """Periodic REST fallback for missed updates."""
        while self._running:
            await asyncio.sleep(30)
            try:
                for symbol in self._symbols:
                    url = f"{self.REST_BASE}/ticker/bookTicker?symbol={symbol}"
                    async with self._session.get(url) as resp:
                        if resp.ok:
                            data = await resp.json()
                            snapshot = PriceSnapshot(
                                symbol=symbol,
                                cex_bid=Decimal(data.get("bidPrice", "0")),
                                cex_ask=Decimal(data.get("askPrice", "0")),
                                cex_last=(Decimal(data.get("bidPrice", "0")) +
                                          Decimal(data.get("askPrice", "0"))) / 2,
                                dex_price=Decimal(0),
                                dex_liquidity_usd=Decimal(0),
                                timestamp=time.time(),
                            )
                            existing = self._prices.get(symbol)
                            if existing and existing.dex_price > 0:
                                snapshot.dex_price = existing.dex_price
                                snapshot.dex_liquidity_usd = existing.dex_liquidity_usd
                            self._prices[symbol] = snapshot
            except Exception as e:
                logger.debug("REST refresh error: %s", e)
