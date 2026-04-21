# Trading Bot

AI-powered stock trading bot using **trailing stops** for risk management and **options wheel strategy** for consistent income — running on Alpaca Paper Trading.

> **Status (2026-04-08):** Copy trading parked — Capitol Trades API requires auth. Bot focuses on trailing stops + wheel strategy only.

## Features

- 🛑 **Stop Losses** — Automatic 10% stop loss on all positions
- 📈 **Trailing Stops** — Floor rises as price climbs, never falls
- 🎯 **Options Wheel Strategy** — Automated options selling for consistent income (1-3% per cycle)
- ⏰ **Scheduled** — Runs every 5 minutes during market hours
- 📝 **Logging** — Full trade history with Discord + Telegram notifications

## Strategy

### Trailing Stops (Risk Management)

Every position has a 10% stop loss and a trailing stop that rises with the stock:

```
Example — NVDA @ $183.46:
- Stop loss floor: $165.11 (−10%)
- If NVDA climbs to $200, trailing stop floor rises to $180 (−10% from $200)
- Bot sells automatically if price closes below floor
```

This prevents catastrophic losses while letting winners run.

### Options Wheel Strategy (Income)

Sell cash-secured puts (CSP) → collect premium → if assigned, sell covered calls → if called away, repeat.

```
Example cycle on NVDA @ $183:
1. Sell CSP at $175 strike, 30 days out → collect ~$150 premium
2. If NVDA drops below $175 and you're assigned: you buy 100 shares at $175
3. Sell covered call at $200 strike → collect ~$150 premium
4. If called away at $200: you sold at $200, keep premium from both legs
5. Sell new CSP → wheel continues spinning
```

Best in sideways/neutral markets. Generates income regardless of direction.

## Setup

### Prerequisites

- Python 3.12+
- [Alpaca account](https://app.alpaca.markets) (free paper trading)
- `uv` package manager

### Installation

```bash
git clone https://github.com/suleclaw/trading-bot.git
cd trading-bot
uv sync
cp .env.example .env
```

### Configuration

Edit `.env`:

```env
ALPACA_API_KEY=your_api_key_here
ALPACA_API_SECRET=your_api_secret_here
ALPACA_ENDPOINT=https://paper-api.alpaca.markets
```

## Running

```bash
# Run once (check positions, update stops, manage options)
uv run python trading_bot.py

# Run continuously (every 5 minutes during market hours)
uv run python scheduler.py

# Custom interval
uv run python trading_bot.py --interval 300
```

## Current Positions (Paper Trading)

| Symbol | Shares | Entry | Stop Loss | Status |
|--------|--------|-------|-----------|--------|
| NVDA | 27 | $183.46 | $165.11 | Active |
| MSFT | 13 | $384.55 | $346.10 | Active |
| TSLA | 8 | $364.03 | $327.63 | Active |
| AAPL | 15 | $259.33 | $233.40 | Active |
| GOOGL | 14 | $316.78 | $285.10 | Active |

## Project Structure

```
trading_bot.py      — main entry (check positions, update stops, manage wheel)
wheel_strategy.py   — options wheel engine (CSP + covered calls)
alpaca_client.py    — Alpaca API wrapper
capitol_trades.py   — politician trade fetcher (currently simulated)
scheduler.py        — continuous scheduler (every 5 mins)
.env.example        — template for API keys
```

## Roadmap

- [x] Alpaca paper trading setup
- [x] Stop losses + trailing stops
- [x] Options wheel strategy
- [ ] Real Capitol Trades API (parked — needs paid data provider)
- [ ] Telegram notifications
- [ ] Weekly position summary

## License

MIT
