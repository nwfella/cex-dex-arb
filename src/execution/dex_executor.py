"""DEX swap execution — builds and sends Uniswap V3 swap transactions."""

from __future__ import annotations

import asyncio
import logging
import time
from decimal import Decimal
from typing import Optional

from web3 import Web3
from web3.types import TxParams, Wei

from ..core.config import DEXChainConfig
from ..core.constants import (
    UNISWAP_V3_SWAP_ROUTER,
    ERC20_ABI,
)
from ..core.types import OrderStatus, TradeExecution

logger = logging.getLogger(__name__)

# Uniswap V3 SwapRouter minimal ABI for exactInputSingle
SWAP_ROUTER_ABI = [
    {
        "inputs": [
            {
                "components": [
                    {"name": "tokenIn", "type": "address"},
                    {"name": "tokenOut", "type": "address"},
                    {"name": "fee", "type": "uint24"},
                    {"name": "recipient", "type": "address"},
                    {"name": "deadline", "type": "uint256"},
                    {"name": "amountIn", "type": "uint256"},
                    {"name": "amountOutMinimum", "type": "uint256"},
                    {"name": "sqrtPriceLimitX96", "type": "uint160"},
                ],
                "name": "params",
                "type": "tuple",
            }
        ],
        "name": "exactInputSingle",
        "outputs": [{"name": "amountOut", "type": "uint256"}],
        "stateMutability": "payable",
        "type": "function",
    },
    {
        "inputs": [
            {
                "components": [
                    {"name": "tokenIn", "type": "address"},
                    {"name": "tokenOut", "type": "address"},
                    {"name": "fee", "type": "uint24"},
                    {"name": "recipient", "type": "address"},
                    {"name": "deadline", "type": "uint256"},
                    {"name": "amountOut", "type": "uint256"},
                    {"name": "amountInMaximum", "type": "uint256"},
                    {"name": "sqrtPriceLimitX96", "type": "uint160"},
                ],
                "name": "params",
                "type": "tuple",
            }
        ],
        "name": "exactOutputSingle",
        "outputs": [{"name": "amountIn", "type": "uint256"}],
        "stateMutability": "payable",
        "type": "function",
    },
]


class DEXExecutor:
    """Executes token swaps on Uniswap V3."""

    def __init__(self, chain_name: str, config: DEXChainConfig, private_key: str, wallet_address: str):
        self.chain_name = chain_name
        self.config = config
        self.private_key = private_key
        self.wallet_address = Web3.to_checksum_address(wallet_address)
        self.w3 = Web3(Web3.HTTPProvider(config.rpc_url))
        self._is_paper = True  # Set externally
        self._nonce: Optional[int] = None

    async def start(self):
        """Initialize nonce tracking."""
        if self.w3.is_connected() and self.wallet_address:
            loop = asyncio.get_event_loop()
            self._nonce = await loop.run_in_executor(
                None, self.w3.eth.get_transaction_count, self.wallet_address
            )
            logger.info("DEXExecutor (%s) initialized. Nonce: %s", self.chain_name, self._nonce)

    async def stop(self):
        pass

    async def swap_exact_input(
        self,
        token_in: str,
        token_out: str,
        amount_in: int,
        min_amount_out: int = 0,
        fee: int = 3000,
        deadline_seconds: int = 300,
    ) -> TradeExecution:
        """Swap an exact amount of token_in for token_out.

        Args:
            token_in: Address of input token
            token_out: Address of output token
            amount_in: Amount in wei/smallest unit
            min_amount_out: Minimum amount to receive (slippage protection)
            fee: Pool fee tier (3000 = 0.3%)
            deadline_seconds: Txn expiry from now
        """
        trade = TradeExecution(
            opportunity_id="",
            symbol=f"{token_in[:8]}→{token_out[:8]}",
            direction=None,
            size_usd=Decimal(0),
        )

        if self._is_paper:
            logger.info("[PAPER] SWAP %s → %s amount=%s", token_in[:10], token_out[:10], amount_in)
            trade.status = OrderStatus.FILLED
            trade.dex_tx_hash = f"0xpaper_{int(time.time())}"
            return trade

        try:
            router_addr = UNISWAP_V3_SWAP_ROUTER.get(self.config.chain_id)
            if not router_addr:
                raise ValueError(f"No router for chain {self.config.chain_id}")

            router = self.w3.eth.contract(
                address=Web3.to_checksum_address(router_addr),
                abi=SWAP_ROUTER_ABI,
            )

            # Build swap params
            deadline = int(time.time()) + deadline_seconds
            tx_params = {
                "from": self.wallet_address,
                "nonce": self._nonce,
                "chainId": self.config.chain_id,
            }
            if self._nonce is not None:
                self._nonce += 1

            # Check if token_in is ETH (native) vs ERC20
            is_native = token_in.lower() == "0x0000000000000000000000000000000000000000"

            if not is_native:
                # Need to approve the router first
                await self._ensure_allowance(token_in, router_addr, amount_in)

            # Estimate gas
            params = (
                Web3.to_checksum_address(token_in),
                Web3.to_checksum_address(token_out),
                fee,
                self.wallet_address,
                deadline,
                amount_in,
                min_amount_out,
                0,  # sqrtPriceLimitX96
            )

            gas_estimate = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: router.functions.exactInputSingle(params).estimate_gas(tx_params),
            )

            # Get gas prices
            base_fee = await asyncio.get_event_loop().run_in_executor(
                None, self.w3.eth.gas_price
            )
            priority_fee = self.w3.to_wei(self.config.max_priority_fee_gwei, "gwei")

            tx_params.update({
                "gas": int(gas_estimate * 1.2),  # 20% buffer
                "maxFeePerGas": int(base_fee + priority_fee),
                "maxPriorityFeePerGas": priority_fee,
                "value": amount_in if is_native else 0,
            })

            # Sign and send
            signed = self.w3.eth.account.sign_transaction(
                router.functions.exactInputSingle(params).build_transaction(tx_params),
                self.private_key,
            )
            tx_hash = await asyncio.get_event_loop().run_in_executor(
                None, self.w3.eth.send_raw_transaction, signed.raw_transaction
            )

            trade.dex_tx_hash = tx_hash.hex()
            trade.status = OrderStatus.PENDING

            # Wait for receipt
            receipt = await asyncio.get_event_loop().run_in_executor(
                None, lambda: self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            )

            if receipt["status"] == 1:
                trade.status = OrderStatus.FILLED
                logger.info("SWAP %s → %s tx=%s", token_in[:10], token_out[:10], tx_hash.hex())
            else:
                trade.status = OrderStatus.FAILED
                trade.error_message = f"Transaction reverted: {tx_hash.hex()}"
                logger.error("SWAP reverted: %s", tx_hash.hex())

        except Exception as e:
            trade.status = OrderStatus.FAILED
            trade.error_message = str(e)
            logger.error("DEX swap failed: %s", e)

        trade.completed_at = time.time()
        return trade

    async def _ensure_allowance(self, token_address: str, spender: str, amount: int):
        """Ensure the router has approval to spend the token."""
        token = self.w3.eth.contract(
            address=Web3.to_checksum_address(token_address),
            abi=ERC20_ABI,
        )

        loop = asyncio.get_event_loop()
        current_allowance = await loop.run_in_executor(
            None,
            lambda: token.functions.allowance(
                self.wallet_address,
                Web3.to_checksum_address(spender),
            ).call()
        )

        if current_allowance < amount:
            logger.info("Approving %s for router...", token_address[:10])
            approve_tx = token.functions.approve(
                Web3.to_checksum_address(spender),
                2**256 - 1,  # Max approval
            ).build_transaction({
                "from": self.wallet_address,
                "nonce": self._nonce,
                "chainId": self.config.chain_id,
                "gas": 100000,
                "maxFeePerGas": self.w3.to_wei(50, "gwei"),
                "maxPriorityFeePerGas": self.w3.to_wei(2, "gwei"),
            })

            if self._nonce is not None:
                self._nonce += 1

            signed = self.w3.eth.account.sign_transaction(approve_tx, self.private_key)
            tx_hash = await loop.run_in_executor(
                None, self.w3.eth.send_raw_transaction, signed.raw_transaction
            )
            await loop.run_in_executor(
                None, lambda: self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            )
            logger.info("Approval confirmed: %s", tx_hash.hex())

    @property
    def is_connected(self) -> bool:
        return self.w3.is_connected()
