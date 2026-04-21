#!/usr/bin/env python3
"""
Trading Bot — Main Entry Point
AI-powered copy trading + wheel strategy via Alpaca Paper Trading

Usage:
  python trading_bot.py              # Run once
  python scheduler.py --continuous   # Run continuously
"""

import json
import logging
import argparse
from datetime import datetime
from pathlib import Path

from alpaca_client import (
    get_account,
    get_clock,
    is_market_open,
    get_latest_price,
    place_limit_order,
    get_positions,
)
from capitol_trades import get_recent_trades_formatted, get_top_politicians, get_simulated_trades

# ─── Logging ─────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(BASE_DIR / "trading.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

# ─── Config ──────────────────────────────────────────────────────────────────

MAX_POSITION_PCT = 0.10    # Max 10% of portfolio per position
STOP_LOSS_PCT = 10         # 10% stop loss
TRAILING_GAIN_PCT = 10     # Activate trailing floor when up 10%
TRAILING_OFFSET_PCT = 5     # Floor is 5% below current price

POSITIONS_FILE = BASE_DIR / "tracked_positions.json"

# ─── Copy Trading Engine ─────────────────────────────────────────────────────

class CopyTradingEngine:
    """
    Copy trading engine that follows US politician stock trades.
    
    For each trade signal:
    1. Calculate position size (max 10% of portfolio)
    2. Place limit order at current price
    3. Track with trailing stop:
       - Initial stop loss: -10% from entry
       - When price rises 10%+, set new floor at -5% from current price
       - Floor only moves UP, never down
    """

    def __init__(self):
        self.tracked = self._load_tracked()

    def _load_tracked(self) -> dict:
        if POSITIONS_FILE.exists():
            try:
                return json.loads(POSITIONS_FILE.read_text())
            except Exception:
                pass
        return {}

    def _save_tracked(self):
        with open(POSITIONS_FILE, "w") as f:
            json.dump(self.tracked, f, indent=2)

    def get_equity(self) -> float:
        return get_account()["equity"]

    def get_trade_price(self, symbol: str) -> float | None:
        """Get price for placing a trade order."""
        return get_latest_price(symbol)

    def buy(self, symbol: str, amount: float = None, qty: int = None) -> dict | None:
        """Place a buy order for a symbol."""
        price = self.get_trade_price(symbol)
        if not price:
            log.warning(f"Cannot determine price for {symbol}")
            return None

        equity = self.get_equity()

        if qty is None and amount:
            qty = int(amount / price)
        if qty is None:
            max_cost = equity * MAX_POSITION_PCT
            qty = max(1, int(max_cost / price))

        if qty < 1:
            return None

        order = place_limit_order(symbol, qty, "buy", price)
        if order:
            self.tracked[symbol] = {
                "entry_price": price,
                "qty": qty,
                "stop_loss": round(price * (1 - STOP_LOSS_PCT / 100), 2),
                "trailing_floor": round(price * (1 + TRAILING_GAIN_PCT / 100), 2),
                "trailing_activated": False,
                "bought_at": datetime.now().isoformat(),
            }
            self._save_tracked()
            log.info(f"BUY: {qty} {symbol} @ ${price} | Stop: ${self.tracked[symbol]['stop_loss']}")

        return order

    def sell(self, symbol: str, qty: int = None) -> dict | None:
        """Sell a symbol."""
        positions = get_positions()
        for pos in positions:
            if pos.symbol == symbol:
                sell_qty = qty or int(pos.qty)
                price = self.get_trade_price(symbol)
                if price:
                    order = place_limit_order(symbol, sell_qty, "sell", price)
                    if order and symbol in self.tracked:
                        del self.tracked[symbol]
                        self._save_tracked()
                        log.info(f"SELL: {sell_qty} {symbol} @ ${price}")
                    return order
        return None

    def check_trailing_stops(self):
        """Check all positions, update trailing floors and trigger stops."""
        positions = get_positions()

        for pos in positions:
            symbol = pos.symbol
            current = get_latest_price(symbol)
            if not current:
                continue

            entry = float(pos.avg_entry_price)
            qty = int(pos.qty)
            pl_pct = (current - entry) / entry * 100

            if symbol not in self.tracked:
                # Initialize tracking from actual position
                self.tracked[symbol] = {
                    "entry_price": entry,
                    "qty": qty,
                    "stop_loss": round(entry * 0.90, 2),
                    "trailing_floor": round(entry * 1.10, 2),
                    "trailing_activated": False,
                }

            t = self.tracked[symbol]

            # ── Stop loss ───────────────────────────────────────────────────
            if current <= t["stop_loss"]:
                log.warning(f"STOP LOSS: {symbol} @ ${current} (entry ${entry}, stop ${t['stop_loss']})")
                self.sell(symbol, qty)
                continue

            # ── Trailing floor update ───────────────────────────────────────
            gain_pct = (current - entry) / entry * 100
            if gain_pct >= TRAILING_GAIN_PCT and not t.get("trailing_activated"):
                # Activate trailing: floor follows price up
                t["trailing_activated"] = True
                log.info(f"TRAILING ACTIVATED: {symbol} @ ${current} (+{gain_pct:.1f}%)")

            if t.get("trailing_activated"):
                new_floor = round(current * (1 - TRAILING_OFFSET_PCT / 100), 2)
                if new_floor > t["trailing_floor"]:
                    log.info(f"TRAILING: {symbol} floor ${t['trailing_floor']} → ${new_floor} (price ${current})")
                    t["trailing_floor"] = new_floor

            # ── Trailing stop triggered ─────────────────────────────────────
            if t.get("trailing_activated") and current <= t["trailing_floor"]:
                log.info(f"TRAILING STOP: {symbol} @ ${current} (floor ${t['trailing_floor']}, +{gain_pct:.1f}% total)")
                self.sell(symbol, qty)
                continue

        self._save_tracked()

    def execute_copy_trade(self, trade: dict):
        """Execute a copy trade from a politician."""
        symbol = trade.get("symbol", "").upper()
        action = trade.get("action", "").lower()
        amount = trade.get("amount")

        if not symbol or action not in ("buy", "sell"):
            return

        positions = get_positions()
        held = [p.symbol for p in positions]

        if action == "buy":
            if symbol in held:
                log.info(f"SKIP: {symbol} already held")
            else:
                self.buy(symbol, amount=amount)

        elif action == "sell":
            if symbol in held:
                self.sell(symbol)
            else:
                log.info(f"SKIP: don't own {symbol}")

    def print_status(self):
        """Print current account and position status."""
        account = get_account()
        equity = account["equity"]

        log.info(f"Cash: ${account['cash']:,.2f} | Equity: ${equity:,.2f} | Power: ${account['buying_power']:,.2f}")

        positions = get_positions()
        if positions:
            log.info(f"Positions ({len(positions)}):")
            for pos in positions:
                current = get_latest_price(pos.symbol) or float(pos.current_price)
                entry = float(pos.avg_entry_price)
                pl = float(pos.unrealized_pl)
                pl_pct = float(pos.unrealized_plpc) * 100
                tracked = self.tracked.get(pos.symbol, {})
                stop = tracked.get("stop_loss", "N/A")
                floor = tracked.get("trailing_floor", "N/A")
                log.info(
                    f"  {pos.symbol}: {pos.qty}×${entry} → ${current} "
                    f"| P/L: ${pl:+.2f} ({pl_pct:+.1f}%) "
                    f"| Stop: ${stop} | Floor: ${floor}"
                )
        else:
            log.info("No open positions")

    def run(self, trades: list[dict] = None, market_open: bool = None):
        """Run one copy trading cycle."""
        log.info("=" * 50)
        log.info("COPY TRADING CYCLE")

        self.check_trailing_stops()

        if trades:
            if market_open:
                log.info(f"Executing {len(trades)} copy trades...")
                for trade in trades:
                    self.execute_copy_trade(trade)
            else:
                log.info("Market closed — placing limit orders for when market opens...")
                for trade in trades:
                    if trade.get("action") == "buy":
                        self.execute_copy_trade(trade)

        self.print_status()
        log.info("=" * 50)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Trading Bot")
    parser.add_argument("--dry-run", action="store_true", help="Don't place orders")
    parser.add_argument("--no-wheel", action="store_true", help="Skip wheel strategy")
    args = parser.parse_args()

    log.info("=" * 60)
    log.info(f"TRADING BOT — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 60)

    clock = get_clock()
    market_open = clock.is_open
    log.info(f"Market: {'OPEN' if market_open else 'CLOSED'}")
    log.info(f"Next open: {clock.next_open} | Close: {clock.next_close}")

    # ── Copy Trading ─────────────────────────────────────────────────────────
    log.info("\n[COPY TRADING]")
    log.info("NOTE: Capitol Trades API is defunct (api.capitoltrades.com = NXDOMAIN).")
    log.info("      Using simulated trade data. Real data requires a paid alternative source.")
    engine = CopyTradingEngine()

    # get_recent_trades_formatted() returns simulated data since the API is dead
    trades = get_recent_trades_formatted(limit=10)

    engine.run(trades=trades, market_open=market_open)

    # ── Wheel Strategy ────────────────────────────────────────────────────────
    if not args.no_wheel:
        log.info("\n[WHEEL STRATEGY]")
        try:
            from wheel_strategy import WheelStrategy
            wheel = WheelStrategy()
            positions = get_positions()
            symbols = [p.symbol for p in positions]
            if symbols:
                wheel.spin(symbols=symbols)
            else:
                log.info("No positions yet — wheel strategy starts when you own shares")
            wheel.print_status()
        except Exception as e:
            log.error(f"Wheel strategy error: {e}")

    log.info("\nDone.")


if __name__ == "__main__":
    main()
