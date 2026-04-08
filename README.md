# Trading Bot

AI-powered stock trading bot that copies US politician trades via Alpaca Paper Trading, with an integrated **Wheel Strategy** for consistent options income.

## Features

- 📊 **Copy Trading** — Follow US politician stock trades (Capitol Trades data)
- 🛑 **Stop Losses** — Automatic 10% stop loss on all positions
- 📈 **Trailing Stops** — Floor rises as price climbs, never falls
- 🎯 **Wheel Strategy** — Automated options selling for consistent income
- ⏰ **Scheduled** — Runs every 5 minutes during market hours
- 📝 **Logging** — Full trade history with Discord notifications

## Setup

### Prerequisites

- Python 3.12+
- [Alpaca account](https://app.alpaca.markets) (free paper trading)
- `uv` package manager

### Installation

```bash
# Clone the repo
git clone https://github.com/suleclaw/trading-bot.git
cd trading-bot

# Install dependencies
uv sync

# Create .env file
cp .env.example .env
```

### Configuration

Edit `.env` with your Alpaca credentials:

```env
ALPACA_API_KEY=your_api_key_here
ALPACA_API_SECRET=your_api_secret_here
ALPACA_ENDPOINT=https://paper-api.alpaca.markets
```

### Running

```bash
# Run once
uv run python trading_bot.py

# Run continuously (every 5 minutes during market hours)
uv run python scheduler.py

# Run with custom interval
uv run python trading_bot.py --interval 300
```

## Wheel Strategy

The wheel strategy generates income by repeatedly selling options:

```
Stage 1: Sell Cash-Secured Put (CSP)
  ↓ (if assigned / put exercised)
Stage 2: Sell Covered Call
  ↓ (if called away)
Back to Stage 1
```

### How It Works

**Stage 1 — Sell Cash-Secured Put:**
- Sell a put option at a strike ~10% below current price
- Collect premium upfront (e.g., $5/share = $500 per contract)
- If stock stays above strike → option expires worthless, keep premium
- If stock drops below strike → you buy shares at the strike price
  - Your real cost = strike - premium collected
  - e.g., $230 strike - $5 premium = $225 effective cost

**Stage 2 — Sell Covered Call:**
- You now own 100 shares (assigned from Stage 1)
- Sell a call option at a strike ~10% above your cost basis
- Collect more premium
- If stock stays below strike → keep premium, keep shares
- If stock rises above strike → shares called away at strike
  - Your profit = (sale price - cost basis) + (put premium + call premium)
  - Go back to Stage 1

### Rules

- Never sell a put without enough cash to buy if assigned
- Never sell a call below your cost basis
- Close contracts at 50% profit before expiration
- Track all premiums across cycles

### Example (Tesla at $250)

```
Stage 1: Sell $230 put, collect $5 premium ($500)
  → Tesla stays above $230: Keep $500, repeat
  → Tesla drops to $220: Buy 100 shares at $230, net cost $225

Stage 2: Sell $260 call, collect $5 premium ($500)
  → Tesla stays below $260: Keep $500, repeat
  → Tesla hits $270: Shares called away at $260
     Total profit = ($260-$225) + $5 + $5 = $45/share = $4,500 per 100 shares
```

## Project Structure

```
trading-bot/
├── trading_bot.py      # Main bot (copy trading + wheel strategy)
├── wheel_strategy.py   # Options wheel engine
├── alpaca_client.py    # Alpaca API wrapper
├── capitol_trades.py   # Politician trade fetcher
├── scheduler.py        # Continuous scheduler
├── .env.example        # Environment template
├── pyproject.toml      # uv project config
├── README.md
└── LICENSE
```

## Strategies

### Copy Trading
- Tracks a chosen politician's trades
- Places limit orders matching their position size
- Applies trailing stop protection
- Backtest: 34.8% annual return (McCaul strategy)

### Wheel Strategy
- Stage 1: Sell cash-secured puts, collect premium
- Stage 2: Sell covered calls, collect more premium
- Automatically rolls and manages positions
- Works best on stocks you'd be happy to own

### Trailing Stop
- Entry: Set floor at -10% from entry
- Trigger: When price +10% above entry, raise floor to -5% from current price
- Effect: You never lose the gains you've locked in

## Disclaimer

⚠️ **Paper trading only.** This bot uses Alpaca's paper trading API with simulated money. No real funds are used. Options strategies involve substantial risk. Not financial advice.