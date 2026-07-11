# CEX-DEX Arbitrage Bot ⚡

High-frequency arbitrage bot that detects and executes price discrepancies between **Centralized Exchanges** (Binance) and **Decentralized Exchanges** (Uniswap V2/V3 on Ethereum, Arbitrum, and Base).

Designed for speed, safety, and extensibility — with MEV protection, dynamic risk controls, and a real-time dashboard.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    ArbitrageBot                       │
│  ┌──────────┐  ┌──────────┐  ┌───────────────────┐  │
│  │  CEX     │  │  DEX     │  │  Opportunity       │  │
│  │ Scanner  │  │ Scanner  │  │  Detector          │  │
│  │ (WSS)    │  │ (RPC)    │  │  (spread calc)     │  │
│  └────┬─────┘  └────┬─────┘  └─────────┬─────────┘  │
│       │              │                  │             │
│       ▼              ▼                  ▼             │
│  ┌─────────────────────────────────────────────┐     │
│  │              Risk Manager                    │     │
│  │  (daily loss, drawdown, concurrency limits)  │     │
│  └───────────────────┬─────────────────────────┘     │
│                      │                                │
│                      ▼                                │
│  ┌─────────────────────────────────────────────┐     │
│  │           Arb Executor                       │     │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  │     │
│  │  │ CEX      │  │ DEX      │  │ Flashbots│  │     │
│  │  │ Executor │  │ Executor │  │ Protector│  │     │
│  │  └──────────┘  └──────────┘  └──────────┘  │     │
│  └─────────────────────────────────────────────┘     │
│                                                       │
│  ┌──────────┐  ┌──────────────────┐                   │
│  │ SQLite   │  │  FastAPI + WS     │                   │
│  │ Storage  │  │  Dashboard        │                   │
│  └──────────┘  └──────────────────┘                   │
└─────────────────────────────────────────────────────┘
```

## Features

### 🔍 Scanning
- **CEX**: Real-time Binance order book depth via WebSocket streams (100ms updates)
- **DEX**: On-chain pool prices from Uniswap V2/V3 (Ethereum, Arbitrum, Base)
- **Auto-discovery**: Cross-references CEX volume spikes with DEX liquidity pools
- **Multi-pool**: Monitor up to 200 pools across multiple chains simultaneously

### 💹 Opportunity Detection
- **Direct arbitrage**: Same pair across CEX and DEX (e.g., ETH/USDT on Binance ↔ Uniswap)
- **Triangular detection**: Synthetic arb routes via intermediate tokens
- **Fee-aware**: Accounts for Binance fees, gas costs, and estimated slippage
- **Confidence scoring**: Price stability over time → higher confidence

### ⚡ Execution
- **Coordinated legs**: Simultaneous CEX order + DEX swap, with partial fill recovery
- **MEV protection**: Flashbots private relay for DEX transactions
- **Gas management**: Dynamic EIP-1559 fee estimation with priority fee control
- **ERC20 allowance**: Automatic token approval for Uniswap router

### 🛡️ Risk Management
- Daily loss limit (auto-shutdown at configurable threshold)
- Max drawdown protection (% from peak PnL)
- Per-trade position limits (USD)
- Per-asset concurrency guard
- Cooldown timer per symbol (prevents rapid re-entry)
- Min CEX balance reserve

### 📊 Dashboard
- Real-time trade feed via WebSocket push
- Live P&L tracking with drawdown visualization
- Opportunity log with spread %, profit estimates, and confidence
- Risk status with loss limit progress bars
- REST API for external monitoring

## Quick Start

### 1. Prerequisites

```bash
# Python 3.10+
python --version

# Clone
git clone https://github.com/nwfella/cex-dex-arb.git
cd cex-dex-arb
```

### 2. Install

```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure

```bash
cp .env.example .env
# Edit .env with your API keys:
#   BINANCE_API_KEY / BINANCE_API_SECRET
#   ETH_RPC_URL (e.g. Alchemy or Infura endpoint)
#   ETH_PRIVATE_KEY / ETH_WALLET_ADDRESS
```

### 4. Run Scanner Mode

```bash
python -m src.main scan
```

This starts the scanner without executing trades — reads prices, detects opportunities, logs them. Safe to run first.

### 5. Run Paper Trading

```bash
python -m src.main run
# Dashboard at http://localhost:8080
```

Paper mode logs what trades *would* have executed. Use this to validate your config before going live.

### 6. Live Trading

```bash
python -m src.main run --live
```

⚠️ **Real funds. Verify everything in paper mode first.**

## Configuration

### `config/default.yaml`

| Setting | Default | Description |
|---------|---------|-------------|
| `bot.mode` | `paper` | `paper` or `live` |
| `bot.scan_interval_ms` | 1000 | How often to scan (ms) |
| `bot.min_profit_threshold_usd` | 5.0 | Min profit to log an opportunity |
| `bot.max_position_size_usd` | 1000 | Max USD per trade |
| `bot.daily_loss_limit_usd` | 100 | Auto-stop if daily loss exceeds this |
| `bot.cooldown_seconds` | 60 | Wait between trades on same pair |
| `dex.ethereum.slippage_tolerance` | 0.01 | 1% max slippage |
| `dex.ethereum.flashbots` | true | Use Flashbots relay |
| `risk.max_drawdown_pct` | 15 | Auto-shutdown at 15% drawdown |

### `config/pairs.yaml`

Define which trading pairs and DEX pools to monitor:

```yaml
pairs:
  - symbol: "ETH/USDT"
    cex: binance
    dex_chain: ethereum
    dex_pool: "0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640"  # Uniswap V3
    min_spread_pct: 0.3
```

## CLI Reference

```bash
python -m src.main --help
python -m src.main scan           # Scan only (no trading)
python -m src.main run            # Paper trading + dashboard
python -m src.main run --live     # Live trading
python -m src.main balances       # Check wallet balances
```

## Project Structure

```
cex-dex-arb/
├── src/
│   ├── core/
│   │   ├── config.py       # Configuration loader (YAML + .env)
│   │   ├── types.py        # Dataclasses and enums
│   │   └── constants.py    # Addresses, ABIs, chain config
│   ├── scanner/
│   │   ├── cex_scanner.py  # Binance WebSocket + REST
│   │   ├── dex_scanner.py  # Uniswap on-chain polling
│   │   └── opportunity.py  # Spread calculator + scoring
│   ├── execution/
│   │   ├── cex_executor.py # Binance market orders
│   │   ├── dex_executor.py # Uniswap swap txn builder
│   │   ├── flashbots.py    # MEV protection
│   │   └── arb_executor.py # Coordinated arb lifecycle
│   ├── risk/
│   │   └── manager.py      # Risk gates + PnL tracking
│   ├── db/
│   │   ├── models.py       # SQLAlchemy ORM models
│   │   └── storage.py      # CRUD operations
│   ├── dashboard/
│   │   ├── app.py          # FastAPI server + WebSocket
│   │   └── templates/
│   │       └── dashboard.html  # Dark-themed UI
│   └── main.py             # CLI + orchestrator
├── config/
│   ├── default.yaml        # Default configuration
│   └── pairs.yaml          # Trading pairs / pools
├── scripts/                # Quick-start scripts
├── .env.example            # Environment template
├── requirements.txt
├── pyproject.toml
└── README.md
```

## Supported Chains

| Chain | Chain ID | V3 Pools | V2 Pools | Flashbots |
|-------|----------|----------|----------|-----------|
| Ethereum | 1 | ✅ | ✅ | ✅ |
| Arbitrum | 42161 | ✅ | ❌ | ❌ |
| Base | 8453 | ✅ | ✅ | ❌ |
| Polygon | 137 | ✅ | ❌ | ❌ |
| Optimism | 10 | ✅ | ❌ | ❌ |

## License

MIT — see [LICENSE](LICENSE)
