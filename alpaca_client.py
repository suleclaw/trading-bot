#!/usr/bin/env python3
"""
Alpaca API Client — Simple wrapper for Alpaca Paper Trading API
"""

import os
import logging
from pathlib import Path
from datetime import datetime

import alpaca_trade_api as alpaca

log = logging.getLogger(__name__)

# ─── Config ──────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent

def load_env():
    env = {}
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.strip().split("=", 1)
                env[k.strip()] = v.strip('"').strip("'")
    return env

env = load_env()

API_KEY = os.getenv("ALPACA_API_KEY") or env.get("ALPACA_API_KEY", "")
API_SECRET = os.getenv("ALPACA_API_SECRET") or env.get("ALPACA_API_SECRET", "")
BASE_URL = os.getenv("ALPACA_ENDPOINT") or env.get("ALPACA_ENDPOINT", "https://paper-api.alpaca.markets")

# ─── Client ──────────────────────────────────────────────────────────────────

def get_alpaca():
    return alpaca.REST(API_KEY, API_SECRET, BASE_URL, api_version="v2")

# ─── Account ─────────────────────────────────────────────────────────────────

def get_account():
    api = get_alpaca()
    account = api.get_account()
    return {
        "id": account.id,
        "cash": float(account.cash),
        "equity": float(account.equity),
        "buying_power": float(account.buying_power),
        "status": account.status,
    }

# ─── Clock ────────────────────────────────────────────────────────────────────

def get_clock():
    api = get_alpaca()
    return api.get_clock()

def is_market_open() -> bool:
    return get_clock().is_open

# ─── Price Data ─────────────────────────────────────────────────────────────

def get_latest_price(symbol: str) -> float | None:
    """Get latest traded price for a symbol using 1-min bars."""
    api = get_alpaca()
    try:
        bars = api.get_bars([symbol], timeframe="1Min", limit=1)
        for bar in bars:
            return round(bar.c, 2)
    except Exception as e:
        log.debug(f"Could not get bar for {symbol}: {e}")
    
    # Fallback: try quotes
    try:
        quotes = api.get_quotes([symbol])
        if quotes:
            q = quotes[0]
            if float(q.ap) > 0:
                return round((float(q.bp) + float(q.ap)) / 2, 2)
    except Exception:
        pass
    
    return None

def get_quote(symbol: str) -> dict | None:
    """Get bid/ask quote."""
    api = get_alpaca()
    try:
        quotes = api.get_quotes([symbol])
        if quotes:
            q = quotes[0]
            bp, ap = float(q.bp), float(q.ap)
            if ap > 0:
                return {"bid": bp, "ask": ap, "mid": round((bp + ap) / 2, 2)}
    except Exception:
        pass
    return None

def get_bars(symbol: str, timeframe="1Day", limit=30) -> list:
    """Get historical OHLCV bars."""
    api = get_alpaca()
    try:
        bars = api.get_bars([symbol], timeframe=timeframe, limit=limit)
        return [
            {
                "t": bar.t,
                "o": bar.o,
                "h": bar.h,
                "l": bar.l,
                "c": bar.c,
                "v": bar.v,
            }
            for bar in bars
        ]
    except Exception as e:
        log.error(f"Failed to get bars for {symbol}: {e}")
        return []

# ─── Orders ─────────────────────────────────────────────────────────────────

def place_limit_order(symbol: str, qty: int, side: str, price: float) -> dict | None:
    """Place a limit order."""
    api = get_alpaca()
    try:
        order = api.submit_order(
            symbol=symbol,
            qty=str(qty),
            side=side,
            type="limit",
            limit_price=round(price, 2),
            time_in_force="day",
        )
        log.info(f"Limit order: {side.upper()} {qty} {symbol} @ ${price} [ID: {order.id}]")
        return {"id": order.id, "status": order.status, "symbol": symbol, "side": side, "qty": qty, "price": price}
    except Exception as e:
        log.error(f"Limit order failed for {symbol}: {e}")
        return None

def place_market_order(symbol: str, qty: int, side: str) -> dict | None:
    """Place a market order."""
    api = get_alpaca()
    try:
        order = api.submit_order(
            symbol=symbol,
            qty=str(qty),
            side=side,
            type="market",
            time_in_force="day",
        )
        log.info(f"Market order: {side.upper()} {qty} {symbol} [ID: {order.id}]")
        return {"id": order.id, "status": order.status, "symbol": symbol, "side": side, "qty": qty}
    except Exception as e:
        log.error(f"Market order failed for {symbol}: {e}")
        return None

def get_orders(status="all", limit=100) -> list:
    api = get_alpaca()
    return api.list_orders(status=status, limit=limit)

def get_open_orders(symbol: str = None) -> list:
    api = get_alpaca()
    orders = api.list_orders(status="open", limit=100)
    if symbol:
        return [o for o in orders if o.symbol == symbol]
    return orders

def cancel_order(order_id: str):
    api = get_alpaca()
    try:
        api.cancel_order(order_id)
        log.info(f"Cancelled order {order_id}")
    except Exception as e:
        log.error(f"Could not cancel order {order_id}: {e}")

def cancel_all_orders():
    api = get_alpaca()
    for o in api.list_orders(status="open", limit=100):
        api.cancel_order(o.id)
        log.info(f"Cancelled order {o.id}: {o.symbol}")

# ─── Positions ───────────────────────────────────────────────────────────────

def get_positions():
    api = get_alpaca()
    return api.list_positions()

def get_position(symbol: str):
    positions = get_positions()
    for pos in positions:
        if pos.symbol == symbol:
            return pos
    return None

# ─── Asset Info ──────────────────────────────────────────────────────────────

def get_asset(symbol: str) -> dict | None:
    api = get_alpaca()
    try:
        asset = api.get_asset(symbol)
        return {
            "symbol": asset.symbol,
            "name": asset.name,
            "exchange": asset.exchange,
            "tradeable": asset.tradeable,
            "shortable": asset.shortable,
            "marginable": asset.marginable,
        }
    except Exception as e:
        log.warning(f"Could not get asset info for {symbol}: {e}")
        return None

def is_tradeable(symbol: str) -> bool:
    asset = get_asset(symbol)
    return asset is not None and asset.get("tradeable", False)
