"""Risk management — keeps the bot from blowing up."""

from __future__ import annotations

import logging
import time
from decimal import Decimal
from collections import defaultdict
from typing import Optional

from ..core.config import RiskConfig, BotConfig
from ..core.types import (
    ArbitrageOpportunity,
    TradeExecution,
    OrderStatus,
    TradeDirection,
)

logger = logging.getLogger(__name__)


class RiskManager:
    """Evaluates and tracks risk for the arbitrage bot.

    Checks performed before every trade:
    - Daily loss limit
    - Max position size per trade
    - Max drawdown from peak
    - Concurrent trade limits (per asset and overall)
    - Minimum CEX balance
    """

    def __init__(self, risk_cfg: RiskConfig, bot_cfg: BotConfig):
        self.risk_cfg = risk_cfg
        self.bot_cfg = bot_cfg
        self._daily_pnl: Decimal = Decimal(0)
        self._peak_pnl: Decimal = Decimal(0)
        self._drawdown_pct: float = 0.0
        self._active_assets: dict[str, int] = defaultdict(int)  # symbol -> count
        self._daily_reset_time: float = self._next_midnight()
        self._shutdown: bool = False
        self._total_trades: int = 0
        self._failed_trades: int = 0

    async def check_trade(self, opportunity: ArbitrageOpportunity) -> bool:
        """Check if a trade opportunity passes all risk gates.

        Returns True if the trade is allowed.
        """
        if self._shutdown:
            logger.warning("Bot is in shutdown state — no trades allowed")
            return False

        # Reset daily counters if new day
        self._check_daily_reset()

        # Check daily loss limit
        if abs(self._daily_pnl) >= Decimal(str(self.bot_cfg.daily_loss_limit_usd)):
            logger.warning("Daily loss limit hit: %s / %s",
                           self._daily_pnl, self.bot_cfg.daily_loss_limit_usd)
            return False

        # Check max position size
        if opportunity.max_size_usd > Decimal(str(self.bot_cfg.max_position_size_usd)):
            logger.warning("Trade size %s exceeds max %s",
                           opportunity.max_size_usd, self.bot_cfg.max_position_size_usd)
            return False

        # Check concurrent same asset
        if not self.risk_cfg.concurrent_same_asset:
            if self._active_assets.get(opportunity.symbol, 0) > 0:
                logger.debug("Skipping %s — already active", opportunity.symbol)
                return False

        # Check max concurrent trades
        total_active = sum(self._active_assets.values())
        if total_active >= self.bot_cfg.max_concurrent_trades:
            logger.debug("At max concurrent trades (%s)", total_active)
            return False

        # Check drawdown
        if self._drawdown_pct > self.risk_cfg.max_drawdown_pct:
            logger.warning("Max drawdown exceeded: %.1f%% (limit: %.1f%%)",
                           self._drawdown_pct, self.risk_cfg.max_drawdown_pct)
            self._shutdown = True
            return False

        # Check profit threshold
        if opportunity.net_profit_usd < Decimal(str(self.bot_cfg.min_profit_threshold_usd)):
            logger.debug("Profit %s below threshold %s",
                         opportunity.net_profit_usd, self.bot_cfg.min_profit_threshold_usd)
            return False

        # All checks passed
        self._active_assets[opportunity.symbol] += 1
        return True

    def record_trade(self, trade: TradeExecution):
        """Record the result of a trade to update risk metrics."""
        self._total_trades += 1

        # Decrement active count
        sym = self._active_assets.get(trade.symbol, 1)
        if sym > 0:
            self._active_assets[trade.symbol] = sym - 1

        if trade.status == OrderStatus.FAILED:
            self._failed_trades += 1
            return

        if trade.profit_usd:
            self._daily_pnl += trade.profit_usd

            # Update peak/track drawdown
            if self._daily_pnl > self._peak_pnl:
                self._peak_pnl = self._daily_pnl

            if self._peak_pnl > 0:
                self._drawdown_pct = float(
                    (self._peak_pnl - self._daily_pnl) / self._peak_pnl * 100
                )

    def release_asset(self, symbol: str):
        """Manually release a held asset (for cleanup)."""
        if self._active_assets.get(symbol, 0) > 0:
            self._active_assets[symbol] -= 1

    def get_status(self) -> dict:
        """Get current risk status for dashboard/display."""
        return {
            "daily_pnl_usd": float(self._daily_pnl),
            "peak_pnl_usd": float(self._peak_pnl),
            "drawdown_pct": round(self._drawdown_pct, 2),
            "shutdown": self._shutdown,
            "total_trades": self._total_trades,
            "failed_trades": self._failed_trades,
            "active_assets": dict(self._active_assets),
            "daily_loss_remaining": max(0,
                float(Decimal(str(self.bot_cfg.daily_loss_limit_usd)) - abs(self._daily_pnl))),
        }

    def reset_daily(self):
        """Force a daily reset (called by the bot on new day)."""
        self._daily_pnl = Decimal(0)
        self._peak_pnl = Decimal(0)
        self._drawdown_pct = 0.0
        self._daily_reset_time = self._next_midnight()
        logger.info("Daily risk counters reset")

    def _check_daily_reset(self):
        """Check if we've crossed into a new day."""
        if time.time() >= self._daily_reset_time:
            self.reset_daily()

    def _next_midnight(self) -> float:
        """Get timestamp for next midnight UTC."""
        now = time.time()
        # Simple: next midnight = seconds until end of today
        from datetime import datetime, timezone, timedelta
        tomorrow = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)
        return tomorrow.timestamp()
