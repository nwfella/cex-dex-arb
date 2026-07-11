"""Opportunity detector — finds profitable CEX-DEX arbitrage opportunities."""

from __future__ import annotations

import logging
import time
import uuid
from decimal import Decimal
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass

from ..core.config import BotConfig
from ..core.types import (
    ArbitrageOpportunity,
    PriceSnapshot,
    TradeDirection,
    CEXBalance,
    DEXBalance,
)

logger = logging.getLogger(__name__)


# Typical fee assumptions
BINANCE_MAKER_FEE = Decimal("0.001")   # 0.1%
BINANCE_TAKER_FEE = Decimal("0.001")   # 0.1%
ETH_GAS_ESTIMATE_USD = Decimal("15")    # Conservative ETH mainnet gas
ARB_GAS_ESTIMATE_USD = Decimal("0.50")
BASE_GAS_ESTIMATE_USD = Decimal("0.20")


class OpportunityDetector:
    """Detects and scores CEX↔DEX arbitrage opportunities."""

    def __init__(self, config: BotConfig):
        self.config = config
        self._on_opportunity: Optional[Callable[[ArbitrageOpportunity], None]] = None
        self._cooldowns: Dict[str, float] = {}  # symbol -> last trade timestamp
        self._consecutive_prices: Dict[str, list] = {}  # For confidence scoring

    def on_opportunity(self, callback: Callable[[ArbitrageOpportunity], None]):
        self._on_opportunity = callback

    def evaluate(self, snapshot: PriceSnapshot,
                 cex_balances: Dict[str, CEXBalance],
                 dex_balances: Dict[str, DEXBalance]) -> Optional[ArbitrageOpportunity]:
        """Evaluate a single price snapshot for arb opportunities."""
        if snapshot.cex_bid <= 0 or snapshot.cex_ask <= 0 or snapshot.dex_price <= 0:
            return None

        symbol = snapshot.symbol

        # Check cooldown
        last_trade = self._cooldowns.get(symbol, 0)
        if time.time() - last_trade < self.config.cooldown_seconds:
            return None

        # Track price history for confidence
        if symbol not in self._consecutive_prices:
            self._consecutive_prices[symbol] = []
        self._consecutive_prices[symbol].append({
            "cex_mid": float((snapshot.cex_bid + snapshot.cex_ask) / 2),
            "dex": float(snapshot.dex_price),
            "ts": snapshot.timestamp,
        })
        # Keep last 5
        if len(self._consecutive_prices[symbol]) > 5:
            self._consecutive_prices[symbol].pop(0)

        # === Direction 1: Buy on DEX, Sell on CEX ===
        opp1 = self._check_direction(
            symbol=symbol,
            direction=TradeDirection.DEX_BUY_CEX_SELL,
            buy_price=snapshot.dex_price,
            sell_price=snapshot.cex_bid,
            dex_liquidity=snapshot.dex_liquidity_usd,
        )

        # === Direction 2: Buy on CEX, Sell on DEX ===
        opp2 = self._check_direction(
            symbol=symbol,
            direction=TradeDirection.CEX_BUY_DEX_SELL,
            buy_price=snapshot.cex_ask,
            sell_price=snapshot.dex_price,
            dex_liquidity=snapshot.dex_liquidity_usd,
        )

        best = None
        for opp in [opp1, opp2]:
            if opp and opp.net_profit_usd >= Decimal(str(self.config.min_profit_threshold_usd)):
                opp.id = f"arb_{uuid.uuid4().hex[:12]}"
                # Cap size to configured max
                opp.max_size_usd = min(opp.max_size_usd,
                                       Decimal(str(self.config.max_position_size_usd)))
                # Set confidence based on price consistency
                opp.confidence = self._compute_confidence(symbol)
                if best is None or opp.net_profit_usd > best.net_profit_usd:
                    best = opp

        if best and self._on_opportunity:
            self._on_opportunity(best)

        return best

    def mark_executed(self, symbol: str):
        """Mark a symbol as recently traded (start cooldown)."""
        self._cooldowns[symbol] = time.time()

    def _check_direction(
        self,
        symbol: str,
        direction: TradeDirection,
        buy_price: Decimal,
        sell_price: Decimal,
        dex_liquidity: Decimal,
    ) -> Optional[ArbitrageOpportunity]:
        """Calculate net profitability for one direction."""
        if buy_price <= 0 or sell_price <= 0 or buy_price >= sell_price:
            return None

        # Raw spread
        spread = float((sell_price - buy_price) / buy_price) * 100

        # Estimate costs
        fees = (buy_price + sell_price) * BINANCE_TAKER_FEE / 2  # Approx total fees
        gas = ETH_GAS_ESTIMATE_USD
        slippage = buy_price * Decimal("0.005")  # 0.5% slippage estimate

        # Max size = min(dex_liquidity * 1%, config max)
        max_size = min(
            dex_liquidity * Decimal("0.01") if dex_liquidity > 0 else Decimal("1000"),
            Decimal(str(self.config.max_position_size_usd)),
        )

        gross_profit = sell_price - buy_price
        net_profit = gross_profit - fees - gas - slippage

        return ArbitrageOpportunity(
            symbol=symbol,
            direction=direction,
            cex_price=sell_price if direction == TradeDirection.DEX_BUY_CEX_SELL else buy_price,
            dex_price=buy_price if direction == TradeDirection.DEX_BUY_CEX_SELL else sell_price,
            spread_pct=spread,
            net_profit_usd=net_profit,
            gross_profit_usd=gross_profit,
            estimated_gas_usd=gas,
            estimated_slippage_usd=slippage,
            estimated_fees_usd=fees,
            max_size_usd=max_size,
            confidence=0.0,
        )

    def _compute_confidence(self, symbol: str) -> float:
        """Compute confidence score (0-1) based on price stability."""
        history = self._consecutive_prices.get(symbol, [])
        if len(history) < 3:
            return 0.3  # Low confidence with little data

        prices = history[-3:]
        cex_prices = [p["cex_mid"] for p in prices]
        dex_prices = [p["dex"] for p in prices]

        # Check direction consistency
        spreads = []
        for p in prices:
            spread = (p["cex_mid"] - p["dex"]) / p["dex"]
            spreads.append(spread)

        # Low variance in spread = higher confidence
        spread_mean = sum(spreads) / len(spreads)
        spread_var = sum((s - spread_mean) ** 2 for s in spreads) / len(spreads)

        # Higher confidence when spread is stable and positive
        if spread_mean <= 0:
            return 0.2

        # Variance penalty
        base_conf = min(1.0, spread_mean * 10)  # 10% spread = 1.0 confidence
        variance_penalty = min(0.5, spread_var * 50)

        return max(0.1, min(1.0, base_conf - variance_penalty))
