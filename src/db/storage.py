"""Database storage operations."""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from .models import (
    TradeRecord,
    OpportunityRecord,
    init_db,
)
from ..core.types import (
    ArbitrageOpportunity,
    TradeExecution,
    OrderStatus,
    TradeDirection,
)


class Storage:
    """Persistent storage for trades, opportunities, and state."""

    def __init__(self, db_path: str = "data/arb_bot.db"):
        self._session_factory = init_db(db_path)

    def save_opportunity(self, opp: ArbitrageOpportunity):
        """Persist a detected opportunity."""
        with self._session_factory() as session:
            record = OpportunityRecord(
                opportunity_id=opp.id or "",
                symbol=opp.symbol,
                direction=opp.direction.value,
                spread_pct=opp.spread_pct,
                net_profit_usd=float(opp.net_profit_usd),
                gross_profit_usd=float(opp.gross_profit_usd),
                estimated_gas_usd=float(opp.estimated_gas_usd),
                max_size_usd=float(opp.max_size_usd),
                confidence=opp.confidence,
                executed=opp.executed,
                timestamp=opp.timestamp,
            )
            session.add(record)
            session.commit()

    def save_trade(self, trade: TradeExecution):
        """Persist a completed trade attempt."""
        with self._session_factory() as session:
            record = TradeRecord(
                opportunity_id=trade.opportunity_id,
                symbol=trade.symbol,
                direction=trade.direction.value if trade.direction else "",
                size_usd=float(trade.size_usd),
                cex_order_id=trade.cex_order_id,
                dex_tx_hash=trade.dex_tx_hash,
                cex_price=float(trade.cex_price) if trade.cex_price else None,
                status=trade.status.value,
                profit_usd=float(trade.profit_usd) if trade.profit_usd else None,
                error_message=trade.error_message,
                started_at=trade.started_at,
                completed_at=trade.completed_at,
            )
            session.add(record)
            session.commit()

    def mark_opportunity_executed(self, opp_id: str):
        """Mark an opportunity as executed."""
        with self._session_factory() as session:
            session.query(OpportunityRecord).filter(
                OpportunityRecord.opportunity_id == opp_id
            ).update({"executed": True})
            session.commit()

    def get_recent_trades(self, limit: int = 50) -> list[TradeRecord]:
        """Get most recent trades."""
        with self._session_factory() as session:
            return (
                session.query(TradeRecord)
                .order_by(TradeRecord.started_at.desc())
                .limit(limit)
                .all()
            )

    def get_recent_opportunities(self, limit: int = 50) -> list[OpportunityRecord]:
        """Get most recent opportunities."""
        with self._session_factory() as session:
            return (
                session.query(OpportunityRecord)
                .order_by(OpportunityRecord.timestamp.desc())
                .limit(limit)
                .all()
            )

    def get_stats(self) -> dict:
        """Get aggregate statistics."""
        with self._session_factory() as session:
            total_trades = session.query(TradeRecord).count()
            successful = session.query(TradeRecord).filter(
                TradeRecord.status == OrderStatus.FILLED.value
            ).count()
            failed = session.query(TradeRecord).filter(
                TradeRecord.status == OrderStatus.FAILED.value
            ).count()
            total_profit = (
                session.query(func.sum(TradeRecord.profit_usd))
                .filter(TradeRecord.profit_usd.isnot(None))
                .scalar() or 0
            )
            total_opportunities = session.query(OpportunityRecord).count()

            return {
                "total_trades": total_trades,
                "successful_trades": successful,
                "failed_trades": failed,
                "total_profit_usd": round(float(total_profit), 2),
                "total_opportunities": total_opportunities,
            }
