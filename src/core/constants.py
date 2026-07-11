"""Constants, known addresses, and minimal ABI fragments."""

from typing import Dict, Tuple

# === Chain Info ===
CHAIN_NAMES: Dict[int, str] = {
    1: "ethereum",
    42161: "arbitrum",
    8453: "base",
    137: "polygon",
    10: "optimism",
}

# === Uniswap V3 Constants ===
UNISWAP_V3_FACTORY: Dict[int, str] = {
    1: "0x1F98431c8aD98523631AE4a59f267346ea31F984",
    42161: "0x1F98431c8aD98523631AE4a59f267346ea31F984",
    8453: "0x33128a8fC17869897dcE68Ed026d694621f6FDfD",
    137: "0x1F98431c8aD98523631AE4a59f267346ea31F984",
    10: "0x1F98431c8aD98523631AE4a59f267346ea31F984",
}

UNISWAP_V3_QUOTER: Dict[int, str] = {
    1: "0x61fFE014bA17989E743c5F6cE21d969F0D5dD500",
    42161: "0x61fFE014bA17989E743c5F6cE21d969F0D5dD500",
    8453: "0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a",
    137: "0x61fFE014bA17989E743c5F6cE21d969F0D5dD500",
    10: "0x61fFE014bA17989E743c5F6cE21d969F0D5dD500",
}

UNISWAP_V3_SWAP_ROUTER: Dict[int, str] = {
    1: "0xE592427A0AEce92De3Edee1F18E0157C05861564",
    42161: "0xE592427A0AEce92De3Edee1F18E0157C05861564",
    8453: "0x2626664c2603336E57B271c5C0b26F421741e481",
    137: "0xE592427A0AEce92De3Edee1F18E0157C05861564",
    10: "0xE592427A0AEce92De3Edee1F18E0157C05861564",
}

# === Uniswap V2 Constants ===
UNISWAP_V2_FACTORY: Dict[int, str] = {
    1: "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f",
    42161: "0xf1D7CC64Fb4452F05c498126312eBE29f30Fbcf9",
    8453: "0x8909Dc15e40173Ff4699343b6eB8132c65e18eC6",
}

UNISWAP_V2_ROUTER: Dict[int, str] = {
    1: "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D",
    42161: "0x0000000000000000000000000000000000000000",  # V2 not official on Arb
    8453: "0x0000000000000000000000000000000000000000",
}

# === Common Token Addresses (Ethereum) ===
TOKENS: Dict[str, Dict[int, Tuple[str, int]]] = {
    "WETH": {1: ("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2", 18)},
    "USDC": {1: ("0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", 6)},
    "USDT": {1: ("0xdAC17F958D2ee523a2206206994597C13D831ec7", 6)},
    "WBTC": {1: ("0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599", 8)},
    "DAI":  {1: ("0x6B175474E89094C44Da98b954EedeAC495271d0F", 18)},
    "LINK": {1: ("0x514910771AF9Ca656af840dff83E8264EcF986CA", 18)},
    "UNI":  {1: ("0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984", 18)},
    "AAVE": {1: ("0x7Fc66500c84A76Ad7e9c93437bFc5Ac33E2DDaE9", 18)},
}

# === Minimal ABIs ===

ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function",
    },
]

UNISWAP_V3_POOL_ABI = [
    {
        "inputs": [],
        "name": "slot0",
        "outputs": [
            {"name": "sqrtPriceX96", "type": "uint160"},
            {"name": "tick", "type": "int24"},
            {"name": "observationIndex", "type": "uint16"},
            {"name": "observationCardinality", "type": "uint16"},
            {"name": "observationCardinalityNext", "type": "uint16"},
            {"name": "feeProtocol", "type": "uint8"},
            {"name": "unlocked", "type": "bool"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "liquidity",
        "outputs": [{"name": "", "type": "uint128"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "fee",
        "outputs": [{"name": "", "type": "uint24"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "token0",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "token1",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
]

UNISWAP_V2_PAIR_ABI = [
    {
        "constant": True,
        "inputs": [],
        "name": "getReserves",
        "outputs": [
            {"name": "_reserve0", "type": "uint112"},
            {"name": "_reserve1", "type": "uint112"},
            {"name": "_blockTimestampLast", "type": "uint32"},
        ],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "token0",
        "outputs": [{"name": "", "type": "address"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "token1",
        "outputs": [{"name": "", "type": "address"}],
        "type": "function",
    },
]

QUOTER_V3_ABI = [
    {
        "inputs": [
            {"name": "tokenIn", "type": "address"},
            {"name": "tokenOut", "type": "address"},
            {"name": "fee", "type": "uint24"},
            {"name": "amountIn", "type": "uint256"},
            {"name": "sqrtPriceLimitX96", "type": "uint160"},
        ],
        "name": "quoteExactInputSingle",
        "outputs": [{"name": "amountOut", "type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]
