"""SQLAlchemy models for persistent storage."""

from __future__ import annotations

import time
from decimal import Decimal
from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Boolean,
    BigInteger, Text, DateTime, JSON
)
from sqlalchemy.sql import func
from sqlalchemy.orm import declarative_base, Session

Base = declarative_base()


class TradeRecord(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    opportunity_id = Column(String(64), unique=True, index=True)
    symbol = Column(String(20), nullable=False)
    direction = Column(String(20), nullable=False)  # cex_buy_dex_sell | dex_buy_cex_sell
    size_usd = Column(Float, nullable=False)
    cex_order_id = Column(String(64), nullable=True)
    dex_tx_hash = Column(String(128), nullable=True)
    cex_price = Column(Float, nullable=True)
    dex_price = Column(Float, nullable=True)
    status = Column(String(20), default="pending")
    profit_usd = Column(Float, nullable=True)
    spread_pct = Column(Float, nullable=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(Float, default=time.time)
    completed_at = Column(Float, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class OpportunityRecord(Base):
    __tablename__ = "opportunities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    opportunity_id = Column(String(64), unique=True, index=True)
    symbol = Column(String(20), nullable=False)
    direction = Column(String(20), nullable=False)
    spread_pct = Column(Float, nullable=False)
    net_profit_usd = Column(Float, nullable=False)
    gross_profit_usd = Column(Float, nullable=False)
    estimated_gas_usd = Column(Float, nullable=True)
    max_size_usd = Column(Float, nullable=False)
    confidence = Column(Float, default=0.0)
    executed = Column(Boolean, default=False)
    timestamp = Column(Float, default=time.time)
    created_at = Column(DateTime, server_default=func.now())


def init_db(db_path: str = "data/arb_bot.db"):
    """Initialize the database and return a session factory."""
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    from sqlalchemy.orm import sessionmaker
    return sessionmaker(bind=engine)
