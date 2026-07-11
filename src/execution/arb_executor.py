"""Coordinated arbitrage execution — runs the full CEX-DEX arb lifecycle."""

from __future__ import annotations

import asyncio
import logging
import time
from decimal import Decimal
from typing import Optional

from ..core.config import Config
from ..core.types import (
    ArbitrageOpportunity,
    TradeExecution,
    OrderStatus,
    TradeDirection,
    BotMode,
)
from .cex_executor import CEXExecutor
from .dex_executor import DEXExecutor
from .flashbots import FlashbotsProtector
from ..risk.manager import RiskManager

logger = logging.getLogger(__name__)


class ArbExecutor:
    """Orchestrates the CEX↔DEX arbitrage trade lifecycle."""

    def __init__(
        self,
        config: Config,
        cex: CEXExecutor,
        dex: DEXExecutor,
        flashbots: FlashbotsProtector,
        risk: RiskManager,
    ):
        self.config = config
        self.cex = cex
        self.dex = dex
        self.flashbots = flashbots
        self.risk = risk
        self._active_trades: dict[str, TradeExecution] = {}
        self._completed_trades: list[TradeExecution] = []
        self._is_running = False

        # Set paper/live mode
        is_live = config.bot.mode == BotMode.LIVE.value
        self.cex._is_paper = not is_live
        self.dex._is_paper = not is_live

    async def execute(self, opportunity: ArbitrageOpportunity) -> Optional[TradeExecution]:
        """Execute a full CEX-DEX arbitrage trade.

        Flow:
        1. Check risk limits
        2. Execute CEX leg
        3. Execute DEX leg
        4. Record result
        """
        # Risk check
        if not await self.risk.check_trade(opportunity):
            logger.info("Trade rejected by risk manager: %s", opportunity.symbol)
            return None

        trade = TradeExecution(
            opportunity_id=opportunity.id or "",
            symbol=opportunity.symbol,
            direction=opportunity.direction,
            size_usd=opportunity.max_size_usd,
            started_at=time.time(),
        )

        self._active_trades[trade.opportunity_id] = trade
        logger.info("Executing arb: %s %s (profit=%s)",
                     opportunity.direction.value, opportunity.symbol,
                     opportunity.net_profit_usd)

        try:
            if opportunity.direction == TradeDirection.DEX_BUY_CEX_SELL:
                # Leg 1: Buy on DEX
                dex_trade = await self.dex.swap_exact_input(
                    token_in=opportunity.symbol.split("/")[0] if "/" in opportunity.symbol else "",
                    token_out="USDT",  # Simplified; real impl needs proper token mapping
                    amount_in=int(opportunity.max_size_usd * Decimal("1e18")),  # Simplified
                )
                trade.dex_tx_hash = dex_trade.dex_tx_hash

                # Leg 2: Sell on CEX
                cex_trade = await self.cex.market_sell(
                    symbol=opportunity.symbol.replace("/", ""),
                    base_amount=Decimal("0.01"),  # Simplified; real impl needs proper size
                )
                trade.cex_order_id = cex_trade.cex_order_id
                trade.cex_price = cex_trade.cex_price

            else:  # CEX_BUY_DEX_SELL
                # Leg 1: Buy on CEX
                cex_trade = await self.cex.market_buy(
                    symbol=opportunity.symbol.replace("/", ""),
                    quote_amount=opportunity.max_size_usd,
                )
                trade.cex_order_id = cex_trade.cex_order_id
                trade.cex_price = cex_trade.cex_price

                # Leg 2: Sell on DEX
                dex_trade = await self.dex.swap_exact_input(
                    token_in="USDT",
                    token_out=opportunity.symbol.split("/")[0] if "/" in opportunity.symbol else "",
                    amount_in=int(opportunity.max_size_usd * Decimal("1e6")),  # USDC = 6 decimals
                )
                trade.dex_tx_hash = dex_trade.dex_tx_hash

            # Check results
            if (cex_trade.status == OrderStatus.FILLED and
                    dex_trade.status == OrderStatus.FILLED):
                trade.status = OrderStatus.FILLED
                trade.profit_usd = opportunity.net_profit_usd
                logger.info("ARB SUCCESS: %s profit=%s", opportunity.symbol,
                            opportunity.net_profit_usd)
            else:
                failed_legs = []
                if cex_trade.status != OrderStatus.FILLED:
                    failed_legs.append(f"CEX: {cex_trade.error_message}")
                if dex_trade.status != OrderStatus.FILLED:
                    failed_legs.append(f"DEX: {dex_trade.error_message}")
                trade.status = OrderStatus.FAILED
                trade.error_message = "; ".join(failed_legs)
                logger.warning("ARB FAILED: %s — %s", opportunity.symbol, trade.error_message)
                # TODO: If one leg failed and the other succeeded, add hedge logic

        except Exception as e:
            trade.status = OrderStatus.FAILED
            trade.error_message = str(e)
            logger.error("ARB EXCEPTION: %s — %s", opportunity.symbol, e)

        trade.completed_at = time.time()
        self._active_trades.pop(trade.opportunity_id, None)
        self._completed_trades.append(trade)
        self.risk.record_trade(trade)

        return trade

    def get_active_trades(self) -> list[TradeExecution]:
        return list(self._active_trades.values())

    def get_recent_trades(self, limit: int = 50) -> list[TradeExecution]:
        return self._completed_trades[-limit:]

    async def get_pnl_summary(self) -> dict:
        """Get summary statistics for reporting."""
        total_trades = len(self._completed_trades)
        successful = [t for t in self._completed_trades if t.status == OrderStatus.FILLED]
        total_profit = sum(t.profit_usd or Decimal(0) for t in successful)
        return {
            "total_trades": total_trades,
            "successful_trades": len(successful),
            "failed_trades": total_trades - len(successful),
            "total_profit_usd": total_profit,
            "avg_profit_usd": total_profit / len(successful) if successful else Decimal(0),
        }
