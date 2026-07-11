"""DEX price scanner — reads pool prices from on-chain data (Uniswap V2/V3)."""

from __future__ import annotations

import asyncio
import logging
import time
from decimal import Decimal
from typing import Dict, List, Optional, Callable

from web3 import Web3
from web3.types import Wei

from ..core.config import DEXChainConfig
from ..core.constants import (
    UNISWAP_V3_POOL_ABI,
    UNISWAP_V2_PAIR_ABI,
    ERC20_ABI,
    QUOTER_V3_ABI,
    UNISWAP_V3_QUOTER,
    UNISWAP_V3_SWAP_ROUTER,
)
from ..core.types import PriceSnapshot

logger = logging.getLogger(__name__)


class UniswapPriceScanner:
    """Scans Uniswap V2/V3 pool prices on a single chain."""

    def __init__(self, chain_name: str, config: DEXChainConfig):
        self.chain_name = chain_name
        self.config = config
        self.w3 = Web3(Web3.HTTPProvider(config.rpc_url))
        self._pools: Dict[str, dict] = {}  # symbol -> pool info
        self._running = False
        self._on_price: Optional[Callable[[str, Decimal, Decimal], None]] = None
        self._token_decimals: Dict[str, int] = {}

    def on_price_update(self, callback: Callable[[str, Decimal, Decimal], None]):
        """Register callback: receives (symbol, price, liquidity_usd)."""
        self._on_price = callback

    def register_pool(self, symbol: str, pool_address: str, pool_type: str = "v3",
                      fee: int = 3000, token0: str = "", token1: str = "",
                      decimals0: int = 18, decimals1: int = 18):
        """Register a DEX pool to monitor."""
        self._pools[symbol] = {
            "address": Web3.to_checksum_address(pool_address) if pool_address else "",
            "type": pool_type,
            "fee": fee,
            "token0": token0,
            "token1": token1,
            "decimals0": decimals0,
            "decimals1": decimals1,
        }

    async def start(self):
        """Start periodic polling of DEX pools."""
        self._running = True
        asyncio.create_task(self._poll_loop())
        logger.info("UniswapPriceScanner (%s): %d pools registered",
                    self.chain_name, len(self._pools))

    async def stop(self):
        self._running = False

    async def _poll_loop(self):
        """Poll pools for prices at configured interval."""
        while self._running:
            for symbol, pool_info in self._pools.items():
                try:
                    price, liquidity = await self._fetch_pool_price(pool_info)
                    if price > 0 and self._on_price:
                        self._on_price(symbol, price, liquidity)
                except Exception as e:
                    logger.debug("Pool poll error (%s): %s", symbol, e)
            await asyncio.sleep(self.config.slippage_tolerance * 100)  # ~1-2s

    async def _fetch_pool_price(self, pool: dict) -> tuple[Decimal, Decimal]:
        """Fetch current price and liquidity from a pool.

        Returns (price_in_quote_per_base, liquidity_usd).
        """
        address = pool["address"]
        if not address:
            return Decimal(0), Decimal(0)

        pool_contract = self.w3.eth.contract(
            address=address,
            abi=UNISWAP_V3_POOL_ABI if pool["type"] == "v3" else UNISWAP_V2_PAIR_ABI,
        )

        if pool["type"] == "v3":
            return await self._fetch_v3_price(pool_contract, pool)
        else:
            return await self._fetch_v2_price(pool_contract, pool)

    async def _fetch_v3_price(self, contract, pool: dict) -> tuple[Decimal, Decimal]:
        """Fetch V3 pool price from slot0."""
        slot0 = await asyncio.get_event_loop().run_in_executor(
            None, contract.functions.slot0().call
        )
        liquidity_raw = await asyncio.get_event_loop().run_in_executor(
            None, contract.functions.liquidity().call
        )

        sqrt_price_x96 = slot0[0]
        tick = slot0[1]

        # Calculate price: (sqrtPriceX96 / 2^96) ^ 2
        price_ratio = (sqrt_price_x96 / (1 << 96)) ** 2

        # Adjust for token decimals
        d0 = pool["decimals0"]
        d1 = pool["decimals1"]
        adjusted_price = Decimal(str(price_ratio)) * Decimal(10 ** (d0 - d1))

        # Estimate liquidity in USD (simplified: price * liquidity / 10^decimals)
        liquidity_val = Decimal(str(liquidity_raw))

        return adjusted_price, liquidity_val

    async def _fetch_v2_price(self, contract, pool: dict) -> tuple[Decimal, Decimal]:
        """Fetch V2 pool price from reserves."""
        reserves = await asyncio.get_event_loop().run_in_executor(
            None, contract.functions.getReserves().call
        )
        reserve0 = Decimal(str(reserves[0]))
        reserve1 = Decimal(str(reserves[1]))

        if reserve0 == 0:
            return Decimal(0), Decimal(0)

        d0 = pool["decimals0"]
        d1 = pool["decimals1"]

        # price = reserve1 / reserve0, adjusted for decimals
        price = (reserve1 / reserve0) * Decimal(10 ** (d0 - d1))
        # liquidity ≈ total value locked in USD (rough)
        liquidity = reserve0 * Decimal(10 ** -d0) + reserve1 * Decimal(10 ** -d1)

        return price, liquidity

    async def quote_swap(self, token_in: str, token_out: str, amount_in: int,
                         fee: int = 3000) -> Optional[int]:
        """Get a quote for a swap via the Quoter contract."""
        quoter_addr = UNISWAP_V3_QUOTER.get(self.config.chain_id)
        if not quoter_addr:
            return None

        quoter = self.w3.eth.contract(
            address=Web3.to_checksum_address(quoter_addr),
            abi=QUOTER_V3_ABI,
        )

        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: quoter.functions.quoteExactInputSingle(
                    Web3.to_checksum_address(token_in),
                    Web3.to_checksum_address(token_out),
                    fee,
                    amount_in,
                    0,  # sqrtPriceLimitX96 = 0 (no limit)
                ).call()
            )
            return result[0] if isinstance(result, (list, tuple)) else result
        except Exception as e:
            logger.debug("Quote failed: %s", e)
            return None

    @property
    def is_connected(self) -> bool:
        return self.w3.is_connected()
