#!/usr/bin/env python3
"""
Trading Bot Scheduler — Runs the trading bot on a schedule
Usage:
  python scheduler.py              # Run once
  python scheduler.py --continuous # Run continuously
  python scheduler.py --interval 300  # Custom interval (seconds)
"""

import argparse
import logging
import signal
import sys
import time
from datetime import datetime

# Import the trading bot modules
from wheel_strategy import WheelStrategy
from alpaca_client import is_market_open, get_clock

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

RUNNING = True

def signal_handler(signum, frame):
    global RUNNING
    log.info("Shutdown signal received, finishing current cycle...")
    RUNNING = False

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def is_within_market_hours() -> bool:
    """
    Check if current time is within trading hours.
    Market hours: Mon-Fri, 9:30 AM - 4:00 PM ET
    """
    clock = get_clock()
    
    if not clock.is_open:
        return False
    
    # Also double-check it's a weekday
    now = datetime.now(clock.next_open.tzinfo) if clock.next_open else None
    if now and now.weekday() >= 5:  # Saturday = 5, Sunday = 6
        return False
    
    return True


def get_next_run_interval() -> int:
    """
    Get the number of seconds until the next market open,
    or market close, whichever comes first.
    """
    clock = get_clock()
    
    if clock.is_open:
        # Market is open, check how long until close
        close = clock.next_close
        if close:
            delta = (close - datetime.now(close.tzinfo)).total_seconds()
            if delta > 0:
                return min(int(delta), 300)  # Max 5 min
    else:
        # Market closed, wait until open
        next_open = clock.next_open
        if next_open:
            delta = (next_open - datetime.now(next_open.tzinfo)).total_seconds()
            if delta > 0:
                return min(int(delta), 3600)  # Max 1 hour
    
    return 300  # Default 5 min


def run_trading_cycle():
    """Run one complete trading cycle."""
    log.info("=" * 60)
    log.info(f"TRADING CYCLE — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 60)
    
    clock = get_clock()
    log.info(f"Market: {'OPEN' if clock.is_open else 'CLOSED'}")
    
    # ── Wheel Strategy ───────────────────────────────────────────────────────
    log.info("\n[WHEEL STRATEGY]")
    try:
        wheel = WheelStrategy()
        wheel.print_status()
        # Run full wheel spin: check assignments, open CSPs, open covered calls
        positions = wheel.get_positions()
        symbols = [p.symbol for p in positions]
        if symbols:
            wheel.spin(symbols=symbols)
        else:
            log.info("No open positions — wheel idle. Add stocks to trade.")
    except Exception as e:
        log.error(f"Wheel strategy error: {e}")
    
    log.info("=" * 60)
    log.info("CYCLE COMPLETE\n")


def main():
    parser = argparse.ArgumentParser(description="Trading Bot Scheduler")
    parser.add_argument(
        "--continuous", "-c",
        action="store_true",
        help="Run continuously (default: run once)",
    )
    parser.add_argument(
        "--interval", "-i",
        type=int,
        default=300,
        help="Interval in seconds between runs (default: 300 = 5 min)",
    )
    parser.add_argument(
        "--wheel-only",
        action="store_true",
        help="Run wheel strategy only",
    )
    parser.add_argument(
        "--copy-only",
        action="store_true",
        help="Run copy trading only",
    )
    args = parser.parse_args()
    
    if args.continuous:
        log.info(f"Starting continuous scheduler (interval: {args.interval}s)")
        log.info("Press Ctrl+C to stop")
        
        while RUNNING:
            if is_within_market_hours() or True:  # Always run to check/execute
                run_trading_cycle()
            else:
                log.info("Outside market hours, waiting...")
            
            interval = get_next_run_interval() if is_within_market_hours() else args.interval
            log.info(f"Next run in {interval}s...")
            
            for _ in range(interval):
                if not RUNNING:
                    break
                time.sleep(1)
        
        log.info("Scheduler stopped.")
    else:
        log.info("Running single trading cycle...")
        run_trading_cycle()


if __name__ == "__main__":
    main()
