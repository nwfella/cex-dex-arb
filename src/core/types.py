from __future__ import annotations

from enum import Enum
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional
from datetime import datetime


class TradeDirection(Enum):
    """Direction of the arbitrage trade."""
    CEX_BUY_DEX_SELL = "cex_buy_dex_sell"
    DEX_BUY_CEX_SELL = "dex_buy_cex_sell"


class OrderStatus(Enum):
    PENDING = "pending"
    PARTIAL = "partial"
    FILLED = "filled"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BotMode(Enum):
    PAPER = "paper"
    LIVE = "live"


@dataclass
class PriceSnapshot:
    """A snapshot of prices for a trading pair across both venues."""
    symbol: str
    cex_bid: Decimal     # Highest bid on CEX
    cex_ask: Decimal     # Lowest ask on CEX
    cex_last: Decimal    # Last trade price on CEX
    dex_price: Decimal   # Current DEX pool price (in same quote asset)
    dex_liquidity_usd: Decimal
    timestamp: float     # Unix timestamp
    cex_volume_24h: Optional[Decimal] = None
    dex_tvl_usd: Optional[Decimal] = None


@dataclass
class ArbitrageOpportunity:
    """A detected arbitrage opportunity."""
    symbol: str
    direction: TradeDirection
    cex_price: Decimal
    dex_price: Decimal
    spread_pct: float           # Raw spread %
    net_profit_usd: Decimal     # After fees, gas, slippage
    gross_profit_usd: Decimal   # Before costs
    estimated_gas_usd: Decimal
    estimated_slippage_usd: Decimal
    estimated_fees_usd: Decimal
    max_size_usd: Decimal       # Max trade size constrained by liquidity
    confidence: float           # 0.0 - 1.0
    timestamp: float = field(default_factory=lambda: datetime.utcnow().timestamp())
    id: Optional[str] = None
    executed: bool = False


@dataclass
class TradeExecution:
    """Record of an executed or attempted arbitrage trade."""
    opportunity_id: str
    symbol: str
    direction: TradeDirection
    size_usd: Decimal
    cex_order_id: Optional[str] = None
    dex_tx_hash: Optional[str] = None
    cex_price: Optional[Decimal] = None
    dex_price: Optional[Decimal] = None
    status: OrderStatus = OrderStatus.PENDING
    profit_usd: Optional[Decimal] = None
    error_message: Optional[str] = None
    started_at: float = field(default_factory=lambda: datetime.utcnow().timestamp())
    completed_at: Optional[float] = None


@dataclass
class CEXBalance:
    asset: str
    free: Decimal
    locked: Decimal
    total: Decimal


@dataclass
class DEXBalance:
    token_symbol: str
    token_address: str
    balance: Decimal
    usd_value: Decimal
