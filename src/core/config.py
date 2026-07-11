"""Configuration loader — merges YAML config + .env overrides."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field


class BinanceConfig(BaseModel):
    api_key: str = ""
    api_secret: str = ""
    testnet: bool = False
    timeout_seconds: int = 30
    rate_limit_per_second: int = 10


class DEXChainConfig(BaseModel):
    enabled: bool = True
    rpc_url: str = ""
    chain_id: int = 1
    flashbots: bool = True
    max_gas_price_gwei: float = 100.0
    slippage_tolerance: float = 0.01
    max_priority_fee_gwei: float = 2.0


class DEXConfig(BaseModel):
    ethereum: DEXChainConfig = DEXChainConfig()
    arbitrum: DEXChainConfig = DEXChainConfig(enabled=False)
    base: DEXChainConfig = DEXChainConfig(enabled=False)


class PoolScanConfig(BaseModel):
    scan_interval_seconds: int = 30
    min_liquidity_usd: float = 50_000
    max_pools: int = 200


class RiskConfig(BaseModel):
    max_drawdown_pct: float = 15.0
    min_cex_balance_usd: float = 50.0
    max_slippage_pct: float = 3.0
    concurrent_same_asset: bool = False


class TelegramConfig(BaseModel):
    enabled: bool = False
    bot_token: str = ""
    chat_id: str = ""


class NotificationsConfig(BaseModel):
    telegram: TelegramConfig = TelegramConfig()
    on_trade: bool = True
    on_error: bool = True
    on_opportunity: bool = False


class BotConfig(BaseModel):
    mode: str = "paper"
    scan_interval_ms: int = 1000
    max_concurrent_trades: int = 2
    min_profit_threshold_usd: float = 5.0
    max_position_size_usd: float = 1000.0
    daily_loss_limit_usd: float = 100.0
    cooldown_seconds: int = 60
    log_level: str = "INFO"


class Config(BaseModel):
    bot: BotConfig = BotConfig()
    cex: dict = {"binance": BinanceConfig().model_dump()}
    dex: DEXConfig = DEXConfig()
    pools: PoolScanConfig = PoolScanConfig()
    risk: RiskConfig = RiskConfig()
    notifications: NotificationsConfig = NotificationsConfig()


def _resolve_env_refs(obj: Any) -> Any:
    """Recursively resolve ${VAR_NAME} references in config values."""
    if isinstance(obj, str) and obj.startswith("${") and obj.endswith("}"):
        env_var = obj[2:-1]
        return os.getenv(env_var, "")
    if isinstance(obj, dict):
        return {k: _resolve_env_refs(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_env_refs(item) for item in obj]
    return obj


def load_config(config_dir: Optional[Path] = None) -> Config:
    """Load config from YAML files with .env variable substitution.

    Loads default.yaml first, then local.yaml as overrides (if exists).
    """
    load_dotenv()

    if config_dir is None:
        config_dir = Path(__file__).parent.parent.parent / "config"

    # Load default config
    default_path = config_dir / "default.yaml"
    if not default_path.exists():
        raise FileNotFoundError(f"Config not found: {default_path}")

    with open(default_path) as f:
        raw = yaml.safe_load(f) or {}

    # Override with local.yaml if it exists
    local_path = config_dir / "local.yaml"
    if local_path.exists():
        with open(local_path) as f:
            local_overrides = yaml.safe_load(f) or {}
        _deep_merge(raw, local_overrides)

    # Resolve environment variable references
    raw = _resolve_env_refs(raw)

    # Fill in .env values for key fields
    binance_section = raw.setdefault("cex", {}).setdefault("binance", {})
    binance_section.setdefault("api_key", os.getenv("BINANCE_API_KEY", ""))
    binance_section.setdefault("api_secret", os.getenv("BINANCE_API_SECRET", ""))

    dex_section = raw.setdefault("dex", {})
    for chain_key in ("ethereum", "arbitrum", "base"):
        chain_cfg = dex_section.setdefault(chain_key, {})
        rpc_env = f"{chain_key.upper()}_RPC_URL"
        chain_cfg.setdefault("rpc_url", os.getenv(rpc_env, ""))

    return Config(**raw)


def _deep_merge(base: dict, override: dict) -> None:
    """Merge override into base, recursing for nested dicts."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
