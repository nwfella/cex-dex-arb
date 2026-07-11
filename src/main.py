"""Main entry point — CLI and orchestrator for the CEX-DEX arbitrage bot."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Optional

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel

from .core.config import load_config, Config
from .core.types import (
    ArbitrageOpportunity,
    BotMode,
    PriceSnapshot,
    TradeDirection,
    OrderStatus,
)
from .scanner.cex_scanner import BinanceScanner
from .scanner.dex_scanner import UniswapPriceScanner
from .scanner.opportunity import OpportunityDetector
from .execution.cex_executor import CEXExecutor
from .execution.dex_executor import DEXExecutor
from .execution.flashbots import FlashbotsProtector
from .execution.arb_executor import ArbExecutor
from .risk.manager import RiskManager
from .db.storage import Storage
from .dashboard.app import DashboardApp

console = Console()
logger = logging.getLogger(__name__)

# Rich logging
LOG_LEVELS = {"DEBUG": logging.DEBUG, "INFO": logging.INFO, "WARNING": logging.WARNING}


class ArbitrageBot:
    """Main orchestrator — wires up all components and runs the arb loop."""

    def __init__(self, config: Config):
        self.config = config
        self._running = False
        self._components: dict[str, object] = {}

        # Storage
        self.storage = Storage()

        # Risk
        self.risk = RiskManager(config.risk, config.bot)

        # Scanner: CEX
        binance_cfg = BinanceConfig(**config.cex.get("binance", {}))
        self.cex_scanner = BinanceScanner(binance_cfg)

        # Scanner: DEX (Ethereum main by default)
        self.dex_scanners: dict[str, UniswapPriceScanner] = {}
        if config.dex.ethereum.enabled and config.dex.ethereum.rpc_url:
            scanner = UniswapPriceScanner("ethereum", config.dex.ethereum)
            self.dex_scanners["ethereum"] = scanner

        if config.dex.arbitrum.enabled and config.dex.arbitrum.rpc_url:
            scanner = UniswapPriceScanner("arbitrum", config.dex.arbitrum)
            self.dex_scanners["arbitrum"] = scanner

        if config.dex.base.enabled and config.dex.base.rpc_url:
            scanner = UniswapPriceScanner("base", config.dex.base)
            self.dex_scanners["base"] = scanner

        # Opportunity detector
        self.detector = OpportunityDetector(config.bot)

        # Execution
        self.cex_executor = CEXExecutor(binance_cfg)

        # DEX executor (primary chain)
        primary_dex = "ethereum"
        dex_cfg = config.dex.ethereum
        private_key = os.getenv("ETH_PRIVATE_KEY", "")
        wallet_addr = os.getenv("ETH_WALLET_ADDRESS", "0x0000000000000000000000000000000000000000")
        self.dex_executor = DEXExecutor(primary_dex, dex_cfg, private_key, wallet_addr)

        # Flashbots
        self.flashbots = FlashbotsProtector(dex_cfg, private_key, self.dex_executor.w3)

        # Arb executor
        self.arb_executor = ArbExecutor(
            config, self.cex_executor, self.dex_executor, self.flashbots, self.risk
        )

        # Dashboard
        self.dashboard = DashboardApp(self.storage, self.risk)

        # Wire up callbacks
        self.detector.on_opportunity(self._on_opportunity)

    async def start(self, load_pairs: bool = True):
        """Start all components."""
        self._running = True
        logger.info("Starting CEX-DEX Arbitrage Bot (mode=%s)", self.config.bot.mode)

        # Load trading pairs
        if load_pairs:
            self._load_pairs()

        # Start scanners
        await self.cex_scanner.start()
        for chain, scanner in self.dex_scanners.items():
            await scanner.start()

        # Start execution
        await self.cex_executor.start()
        await self.dex_executor.start()
        await self.flashbots.start()

        # Start main loop
        asyncio.create_task(self._main_loop())

        logger.info("Bot started — scanning %d CEX pairs and %d DEX chains",
                     len(self.cex_scanner._symbols), len(self.dex_scanners))

    async def stop(self):
        """Graceful shutdown."""
        self._running = False
        await self.cex_scanner.stop()
        for scanner in self.dex_scanners.values():
            await scanner.stop()
        await self.cex_executor.stop()
        await self.dex_executor.stop()
        logger.info("Bot stopped")

    def _load_pairs(self):
        """Load trading pairs from config/pairs.yaml and register DEX pools."""
        import yaml
        pairs_path = Path(__file__).parent.parent / "config" / "pairs.yaml"
        if not pairs_path.exists():
            logger.warning("No pairs.yaml found at %s", pairs_path)
            return

        with open(pairs_path) as f:
            data = yaml.safe_load(f) or {}

        pair_count = 0
        for pair in data.get("pairs", []):
            symbol = pair.get("symbol", "").replace("/", "").replace("-", "")
            dex_chain = pair.get("dex_chain", "ethereum")
            dex_pool = pair.get("dex_pool", "")
            min_spread = pair.get("min_spread_pct", 0.3)

            if not symbol:
                continue

            # Register with CEX scanner
            self.cex_scanner.set_symbols(list(self.cex_scanner._symbols) + [symbol])

            # Register with DEX scanner
            scanner = self.dex_scanners.get(dex_chain)
            if scanner and dex_pool:
                scanner.register_pool(symbol, dex_pool)
                pair_count += 1

        logger.info("Loaded %d trading pairs", pair_count)

    async def _main_loop(self):
        """Main arbitrage scanning loop."""
        while self._running:
            try:
                # Get latest CEX prices
                prices = self.cex_scanner.get_all_prices()
                if not prices:
                    await asyncio.sleep(0.1)
                    continue

                # For each price snapshot, find arb opportunities
                for symbol, snapshot in prices.items():
                    if snapshot.dex_price <= 0:
                        continue  # No DEX price yet

                    opp = self.detector.evaluate(snapshot, {}, {})
                    if opp:
                        self.storage.save_opportunity(opp)

                        # Try to execute if profitable enough and not paper
                        if opp.net_profit_usd > Decimal(
                            str(self.config.bot.min_profit_threshold_usd * 3)
                        ):
                            trade = await self.arb_executor.execute(opp)
                            if trade:
                                self.detector.mark_executed(symbol)
                                self.storage.save_trade(trade)
                                self.storage.mark_opportunity_executed(opp.id or "")
                                await self.dashboard.push_trade(trade)
                                await self.dashboard.push_opportunity(opp)

                await asyncio.sleep(self.config.bot.scan_interval_ms / 1000)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Main loop error: %s", e, exc_info=True)
                await asyncio.sleep(1)

    def _on_opportunity(self, opp: ArbitrageOpportunity):
        """Callback when a new opportunity is detected."""
        self.storage.save_opportunity(opp)
        logger.info("OPPORTUNITY: %s | %s | spread=%.3f%% | profit=$%.2f | confidence=%.0f%%",
                     opp.symbol, opp.direction.value,
                     opp.spread_pct, float(opp.net_profit_usd), opp.confidence * 100)


@click.group()
@click.option("--config", "-c", default="config/default.yaml", help="Config file path")
@click.option("--log-level", "-l", default=None,
              type=click.Choice(["DEBUG", "INFO", "WARNING"]), help="Log level")
@click.pass_context
def cli(ctx, config, log_level):
    """CEX-DEX Arbitrage Bot — High-frequency arbitrage between centralized and decentralized exchanges."""
    load_dotenv()

    # Setup logging
    cfg = load_config(Path(config).parent)
    level = log_level or cfg.bot.log_level
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
        handlers=[RichHandler(rich_tracebacks=True)],
    )

    ctx.ensure_object(dict)
    ctx.obj["config"] = cfg


@cli.command()
@click.pass_context
def scan(ctx):
    """Run in scan-only mode — detect opportunities without executing."""
    config = ctx.obj["config"]
    config.bot.mode = BotMode.PAPER.value

    async def _run():
        bot = ArbitrageBot(config)
        await bot.start()
        console.print("[bold green]✓[/] Scanner running. Press Ctrl+C to stop.")
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            await bot.stop()

    asyncio.run(_run())


@cli.command()
@click.option("--live", is_flag=True, help="Run in LIVE trading mode (default: paper)")
@click.option("--port", default=8080, help="Dashboard port")
@click.pass_context
def run(ctx, live, port):
    """Run the full arbitrage bot with execution."""
    config = ctx.obj["config"]
    if live:
        config.bot.mode = BotMode.LIVE.value
        console.print("[bold red]⚠ LIVE MODE — real funds will be used![/]")
    else:
        console.print("[bold yellow]📝 PAPER MODE — no real trades[/]")

    async def _run():
        bot = ArbitrageBot(config)
        await bot.start()

        # Start dashboard
        import uvicorn
        dash_config = uvicorn.Config(
            bot.dashboard.app,
            host="0.0.0.0",
            port=port,
            log_level="info",
        )
        server = uvicorn.Server(dash_config)
        asyncio.create_task(server.serve())

        console.print(f"[bold green]✓[/] Dashboard: [link]http://localhost:{port}[/]")
        console.print("[dim]Press Ctrl+C to stop[/]")

        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            await bot.stop()

    asyncio.run(_run())


@cli.command()
@click.pass_context
def balances(ctx):
    """Check current CEX and DEX balances."""
    config = ctx.obj["config"]

    async def _check():
        cex = CEXExecutor(BinanceConfig(**config.cex.get("binance", {})))
        await cex.start()
        cex._is_paper = config.bot.mode == BotMode.PAPER.value

        balances = await cex.get_balances()

        table = Table(title="Wallet Balances")
        table.add_column("Asset", style="cyan")
        table.add_column("Free", justify="right")
        table.add_column("Locked", justify="right")
        table.add_column("Total", justify="right")

        for asset, free in sorted(balances.items(), key=lambda x: -float(x[1])):
            table.add_row(asset, f"{float(free):.6f}", "0.0", f"{float(free):.6f}")

        console.print(table)

    asyncio.run(_check())


def main():
    cli(obj={})


if __name__ == "__main__":
    main()
