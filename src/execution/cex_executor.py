"""Binance order execution."""

from __future__ import annotations

import asyncio
import logging
import time
from decimal import Decimal
from typing import Optional

from binance.client import Client as BinanceClient
from binance.exceptions import BinanceAPIException
from binance.enums import (
    ORDER_TYPE_MARKET,
    ORDER_TYPE_LIMIT,
    SIDE_BUY,
    SIDE_SELL,
    TIME_IN_FORCE_GTC,
)

from ..core.config import BinanceConfig
from ..core.types import OrderStatus, TradeExecution

logger = logging.getLogger(__name__)


class CEXExecutor:
    """Executes market/limit orders on Binance."""

    def __init__(self, config: BinanceConfig):
        self.config = config
        self._client: Optional[BinanceClient] = None
        self._is_paper = True  # Set externally

    async def start(self):
        """Initialize the Binance client."""
        loop = asyncio.get_event_loop()
        self._client = await loop.run_in_executor(
            None,
            lambda: BinanceClient(self.config.api_key, self.config.api_secret)
        )
        logger.info("CEXExecutor initialized (paper=%s)", self._is_paper)

    async def stop(self):
        self._client = None

    async def market_buy(self, symbol: str, quote_amount: Decimal) -> TradeExecution:
        """Buy on CEX at market price.

        Args:
            symbol: e.g. 'ETHUSDT'
            quote_amount: Amount in quote currency (e.g. USDT) to spend
        """
        trade = TradeExecution(
            opportunity_id="",
            symbol=symbol,
            direction=None,  # Will be set by caller
            size_usd=quote_amount,
        )

        if self._is_paper:
            logger.info("[PAPER] MARKET BUY %s %s USDT", symbol, quote_amount)
            trade.status = OrderStatus.FILLED
            trade.cex_order_id = f"paper_buy_{int(time.time())}"
            return trade

        try:
            loop = asyncio.get_event_loop()
            order = await loop.run_in_executor(
                None,
                lambda: self._client.order_market_buy(
                    symbol=symbol,
                    quoteOrderQty=float(quote_amount),
                )
            )
            trade.cex_order_id = order.get("orderId", "")
            trade.status = OrderStatus.FILLED
            trade.cex_price = Decimal(str(order.get("fills", [{}])[0].get("price", "0")))
            logger.info("MARKET BUY %s %s USDT → order=%s", symbol, quote_amount,
                        trade.cex_order_id)

        except BinanceAPIException as e:
            trade.status = OrderStatus.FAILED
            trade.error_message = str(e)
            logger.error("Binance buy failed: %s", e)

        return trade

    async def market_sell(self, symbol: str, base_amount: Decimal) -> TradeExecution:
        """Sell on CEX at market price.

        Args:
            symbol: e.g. 'ETHUSDT'
            base_amount: Amount in base currency (e.g. ETH) to sell
        """
        trade = TradeExecution(
            opportunity_id="",
            symbol=symbol,
            direction=None,
            size_usd=Decimal(0),
        )

        if self._is_paper:
            logger.info("[PAPER] MARKET SELL %s %s", symbol, base_amount)
            trade.status = OrderStatus.FILLED
            trade.cex_order_id = f"paper_sell_{int(time.time())}"
            return trade

        try:
            loop = asyncio.get_event_loop()
            order = await loop.run_in_executor(
                None,
                lambda: self._client.order_market_sell(
                    symbol=symbol,
                    quantity=float(base_amount),
                )
            )
            trade.cex_order_id = order.get("orderId", "")
            trade.status = OrderStatus.FILLED
            trade.cex_price = Decimal(str(order.get("fills", [{}])[0].get("price", "0")))
            logger.info("MARKET SELL %s %s → order=%s", symbol, base_amount,
                        trade.cex_order_id)

        except BinanceAPIException as e:
            trade.status = OrderStatus.FAILED
            trade.error_message = str(e)
            logger.error("Binance sell failed: %s", e)

        return trade

    async def get_balances(self) -> dict[str, Decimal]:
        """Get all non-zero free balances from Binance."""
        if self._is_paper:
            return {"USDT": Decimal("10000")}  # Paper balance

        try:
            loop = asyncio.get_event_loop()
            account = await loop.run_in_executor(
                None, lambda: self._client.get_account()
            )
            balances = {}
            for bal in account.get("balances", []):
                free = Decimal(str(bal.get("free", "0")))
                if free > 0:
                    balances[bal["asset"]] = free
            return balances
        except Exception as e:
            logger.error("Failed to get balances: %s", e)
            return {}

    async def get_usdt_balance(self) -> Decimal:
        """Get USDT balance specifically."""
        balances = await self.get_balances()
        return balances.get("USDT", Decimal("0"))
