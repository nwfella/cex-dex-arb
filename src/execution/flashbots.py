"""Flashbots MEV protection — submits bundles to Flashbots relay."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from web3 import Web3

from ..core.config import DEXChainConfig

logger = logging.getLogger(__name__)

# Flashbots relay URLs
FLASHBOTS_RELAYS = {
    1: "https://relay.flashbots.net",
    5: "https://relay-goerli.flashbots.net",  # Goerli testnet
}


class FlashbotsProtector:
    """Protects DEX transactions from MEV via Flashbots private relay."""

    def __init__(self, config: DEXChainConfig, private_key: str, w3: Web3):
        self.config = config
        self.private_key = private_key
        self.w3 = w3
        self._enabled = config.flashbots
        self._relay_url = FLASHBOTS_RELAYS.get(config.chain_id, "")
        self._flashbots = None

    async def start(self):
        if not self._enabled or not self._relay_url:
            logger.info("Flashbots disabled for chain %d", self.config.chain_id)
            return

        try:
            from flashbots import flashbots
            self._flashbots = flashbots(
                self.w3,
                self.private_key,
                self._relay_url,
            )
            logger.info("Flashbots protector initialized")
        except ImportError:
            logger.warning("flashbots package not installed. MEV protection disabled.")
            self._enabled = False
        except Exception as e:
            logger.warning("Flashbots init failed: %s", e)
            self._enabled = False

    async def send_private_tx(self, signed_tx: bytes) -> Optional[str]:
        """Send a transaction via Flashbots private relay.

        Args:
            signed_tx: Raw signed transaction bytes

        Returns:
            Transaction hash if submitted successfully, None otherwise
        """
        if not self._enabled or not self._flashbots:
            return None

        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self._flashbots.send_private_transaction(
                    signed_tx,
                    max_block_number=self.w3.eth.block_number + 25,  # ~5 min
                )
            )
            tx_hash = result.get("result", {}).get("transactionHash", "")
            if tx_hash:
                logger.info("Flashbots tx submitted: %s", tx_hash)
                return tx_hash
            else:
                logger.warning("Flashbots submission returned no hash: %s", result)
                return None

        except Exception as e:
            logger.error("Flashbots send failed: %s", e)
            return None

    async def simulate_bundle(self, signed_txs: list[bytes]) -> bool:
        """Simulate a bundle of transactions to check viability.

        Args:
            signed_txs: List of signed transactions

        Returns:
            True if simulation succeeds
        """
        if not self._enabled or not self._flashbots:
            return True  # Can't simulate, assume OK

        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self._flashbots.simulate(
                    signed_txs,
                    self.w3.eth.block_number,
                )
            )
            success = result.get("firstRevert") is None
            if not success:
                logger.warning("Bundle simulation reverted")
            return success

        except Exception as e:
            logger.warning("Bundle simulation error: %s", e)
            return False

    @property
    def is_enabled(self) -> bool:
        return self._enabled
