#!/usr/bin/env python3
"""
Wheel Strategy Engine — Automated options income strategy
Sells cash-secured puts → if assigned, sell covered calls → repeat
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

import alpaca_trade_api as alpaca

from alpaca_client import (
    get_alpaca,
    get_account,
    get_clock,
    is_market_open,
    get_latest_price,
    place_limit_order,
    get_open_orders,
    cancel_all_orders,
)

log = logging.getLogger(__name__)

# ─── Config ──────────────────────────────────────────────────────────────────

@dataclass
class WheelConfig:
    max_position_pct: float = 0.10       # Max 10% portfolio per position
    put_strike_pct_below: float = 0.10   # Put strike ~10% below current
    call_strike_pct_above: float = 0.10 # Call strike ~10% above cost basis
    expiration_days: int = 21            # ~3 weeks out
    close_profit_pct: float = 0.50       # Close when 50% profit
    min_premium_pct: float = 0.01        # Minimum 1% premium to be worth it
    max_strike_distance_pct: float = 0.20 # Max 20% OTM for puts


@dataclass
class WheelPosition:
    symbol: str
    stage: str  # "put" or "call"
    strike: float
    premium: float
    qty: int = 100
    expiration: str = ""
    cost_basis: float = 0.0       # Only for call stage (what you paid for shares)
    opened_at: str = ""
    contract_id: str = ""
    notes: str = ""


class WheelStrategy:
    """
    The Wheel Strategy:
    
    Stage 1 - Cash Secured Put (CSP):
    - Sell a put option at strike ~10% below current price
    - Collect premium upfront
    - If assigned: you buy shares at the strike price
    - If expired: sell another put, keep collecting
    
    Stage 2 - Covered Call:
    - You now own 100 shares (from assignment or already)
    - Sell a call at ~10% above your cost basis
    - Collect premium
    - If called away: you sold shares at the strike
    - Go back to Stage 1
    
    Key Rules:
    - NEVER sell a put without enough cash to buy if assigned
    - NEVER sell a call below your cost basis
    - Close at 50% profit OR before expiration
    """

    def __init__(self, config: WheelConfig = None):
        self.api = get_alpaca()
        self.config = config or WheelConfig()
        self.data_file = Path(__file__).parent / "wheel_positions.json"
        self.positions: dict[str, WheelPosition] = self._load()
        self.trade_log_file = Path(__file__).parent / "wheel_trades.json"
        self.trade_log: list = self._load_trades()

    def _load(self) -> dict:
        if self.data_file.exists():
            try:
                data = json.loads(self.data_file.read_text())
                return {k: WheelPosition(**v) for k, v in data.items()}
            except Exception:
                pass
        return {}

    def _save(self):
        with open(self.data_file, "w") as f:
            json.dump({k: asdict(v) for k, v in self.positions.items()}, f, indent=2)

    def _load_trades(self) -> list:
        if self.trade_log_file.exists():
            try:
                return json.loads(self.trade_log_file.read_text())
            except Exception:
                pass
        return []

    def _log_trade(self, action: str, symbol: str, details: dict):
        entry = {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "symbol": symbol,
            **details,
        }
        self.trade_log.append(entry)
        with open(self.trade_log_file, "w") as f:
            json.dump(self.trade_log[-100:], f, indent=2)  # Keep last 100

    # ─── Stage Detection ───────────────────────────────────────────────────────

    def get_account_value(self) -> float:
        return float(self.api.get_account().equity)

    def get_cash(self) -> float:
        return float(self.api.get_account().cash)

    def get_positions(self):
        return self.api.list_positions()

    def get_symbol_positions(self, symbol: str) -> list:
        return [p for p in self.get_positions() if p.symbol == symbol]

    def what_stage(self, symbol: str) -> str | None:
        """
        Determine what stage we're at for a symbol:
        - None: no position
        - "put": sold a put, waiting for assignment/expiry
        - "call": own shares, sold covered call
        - "hold": own shares, no call sold yet
        """
        if symbol in self.positions:
            return self.positions[symbol].stage
        
        # Check if we own shares
        shares = self.get_symbol_positions(symbol)
        if shares:
            return "hold"  # Own shares, need to sell a call
        
        return None

    # ─── Stage 1: Cash Secured Put ───────────────────────────────────────────

    def open_csp(self, symbol: str, amount: float = None) -> Optional[dict]:
        """
        Stage 1: Sell a Cash Secured Put
        Sell a put option, collect premium.
        If assigned (stock drops below strike), we buy shares.
        """
        current_price = get_latest_price(symbol)
        if not current_price:
            log.warning(f"Cannot get price for {symbol}")
            return None

        cash = self.get_cash()
        equity = self.get_account_value()
        
        # Calculate max position
        max_cost = equity * self.config.max_position_pct
        max_shares = int(max_cost / current_price)
        
        if max_shares < 100:
            log.warning(f"Not enough buying power for {symbol}: need ~${current_price * 100:.2f}")
            return None
        
        # Calculate put strike (~10% below)
        strike = round(current_price * (1 - self.config.put_strike_pct_below), 2)
        
        # Calculate how many contracts we can safely sell
        # Each contract = 100 shares, we need cash to cover assignment
        max_contracts = min(max_shares // 100, int(cash / (strike * 100)))
        
        if max_contracts < 1:
            log.warning(f"Not enough cash to sell CSP for {symbol}: need ${strike * 100:.2f} collateral")
            return None
        
        # Estimate premium (~1% of stock price per week, 3 weeks out)
        weeks = self.config.expiration_days / 7
        premium_per_share = max(
            current_price * self.config.min_premium_pct * weeks,
            0.50  # Minimum $0.50/share
        )
        
        # Check if premium is worth it
        premium_pct = premium_per_share / strike
        if premium_pct < self.config.min_premium_pct:
            log.info(f"Premium too low for {symbol}: {premium_pct:.2%} (min {self.config.min_premium_pct:.2%})")
        
        qty = 100  # 1 contract
        total_premium = round(premium_per_share * qty, 2)
        
        # Place the short put (simulated as limit sell since Alpaca paper doesn't do options)
        # In a real setup with options, you'd use: api.submit_order(type='limit', ...)
        # For paper trading without options, we simulate the premium collection
        
        log.info(f"[CSP] Selling put on {symbol}: strike=${strike}, premium=${total_premium:.2f}")
        log.info(f"[CSP] If assigned: buying 100 shares at ${strike} (net cost: ${strike - premium_per_share:.2f}/share)")
        
        # Record the position
        expiration = (datetime.now() + timedelta(days=self.config.expiration_days)).strftime("%Y-%m-%d")
        
        self.positions[symbol] = WheelPosition(
            symbol=symbol,
            stage="put",
            strike=strike,
            premium=total_premium,
            qty=qty,
            expiration=expiration,
            opened_at=datetime.now().isoformat(),
            notes=f"CSP opened: price=${current_price}, strike=${strike}, premium=${total_premium:.2f}",
        )
        self._save()
        
        self._log_trade("open_csp", symbol, {
            "price": current_price,
            "strike": strike,
            "premium": total_premium,
            "expiration": expiration,
            "qty": qty,
        })
        
        return {
            "action": "open_csp",
            "symbol": symbol,
            "strike": strike,
            "premium": total_premium,
            "expiration": expiration,
            "net_cost_if_assigned": round(strike - premium_per_share, 2),
        }

    # ─── Stage 2: Covered Call ────────────────────────────────────────────────

    def open_covered_call(self, symbol: str) -> Optional[dict]:
        """
        Stage 2: Sell a Covered Call
        We own 100 shares. Sell a call at ~10% above cost basis.
        Collect premium. If called away, profit = (strike - cost) + premium.
        """
        shares = self.get_symbol_positions(symbol)
        if not shares:
            log.warning(f"Don't own {symbol}, can't sell covered call")
            return None
        
        pos = shares[0]
        qty = int(pos.qty)
        cost_basis = float(pos.avg_entry_price)
        current_price = get_latest_price(symbol) or cost_basis
        
        # Calculate call strike (~10% above cost basis)
        target_strike = round(cost_basis * (1 + self.config.call_strike_pct_above), 2)
        
        # Estimate premium
        weeks = self.config.expiration_days / 7
        premium_per_share = max(
            cost_basis * self.config.min_premium_pct * weeks,
            0.50
        )
        
        total_premium = round(premium_per_share * 100, 2)
        
        log.info(f"[CALL] Selling covered call on {symbol}: strike=${target_strike}, premium=${total_premium:.2f}")
        log.info(f"[CALL] Cost basis: ${cost_basis}, if called away at ${target_strike}: ${target_strike - cost_basis:.2f}/share profit + ${premium_per_share:.2f} premium")
        
        expiration = (datetime.now() + timedelta(days=self.config.expiration_days)).strftime("%Y-%m-%d")
        
        self.positions[symbol] = WheelPosition(
            symbol=symbol,
            stage="call",
            strike=target_strike,
            premium=total_premium,
            qty=qty,
            cost_basis=cost_basis,
            expiration=expiration,
            opened_at=datetime.now().isoformat(),
            notes=f"Covered call opened: cost_basis=${cost_basis}, strike=${target_strike}, premium=${total_premium:.2f}",
        )
        self._save()
        
        self._log_trade("open_call", symbol, {
            "cost_basis": cost_basis,
            "strike": target_strike,
            "premium": total_premium,
            "expiration": expiration,
            "qty": qty,
            "profit_if_called": round(target_strike - cost_basis + premium_per_share, 2),
        })
        
        return {
            "action": "open_call",
            "symbol": symbol,
            "cost_basis": cost_basis,
            "strike": target_strike,
            "premium": total_premium,
            "expiration": expiration,
            "profit_if_called": round(target_strike - cost_basis + premium_per_share, 2),
        }

    # ─── Assignment Handling ─────────────────────────────────────────────────

    def check_assignments(self):
        """
        Check if any put positions got assigned (stock dropped below strike)
        or if any call positions got called away (stock rose above strike).
        
        In paper trading, we simulate this by checking current price vs strike.
        """
        to_remove = []
        
        for symbol, pos in self.positions.items():
            current_price = get_latest_price(symbol)
            if not current_price:
                continue
            
            if pos.stage == "put":
                # Check if assigned (price below strike)
                if current_price < pos.strike:
                    log.warning(f"[ASSIGNMENT] {symbol} put assigned: price=${current_price} < strike=${pos.strike}")
                    self._log_trade("assigned_put", symbol, {
                        "strike": pos.strike,
                        "price": current_price,
                        "premium_collected": pos.premium,
                        "net_cost": round(pos.strike - (pos.premium / 100), 2),
                    })
                    # Move to call stage (we now own shares)
                    pos.stage = "hold"
                    pos.notes += f" | ASSIGNED at ${current_price}"
                    self._save()
                    log.info(f"[WHEEL] Now holding {symbol} shares, move to covered call stage")
                
                # Check if option expired (past expiration date)
                elif datetime.now().strftime("%Y-%m-%d") >= pos.expiration:
                    log.info(f"[EXPIRED] {symbol} put expired worthless, keep premium")
                    self._log_trade("expired_put", symbol, {
                        "premium_kept": pos.premium,
                    })
                    del self.positions[symbol]
                    self._save()
            
            elif pos.stage == "call":
                # Check if called away (price above strike)
                if current_price > pos.strike:
                    log.warning(f"[CALLED AWAY] {symbol} called away: price=${current_price} > strike=${pos.strike}")
                    profit = (pos.strike - pos.cost_basis) * pos.qty + pos.premium
                    self._log_trade("called_away", symbol, {
                        "strike": pos.strike,
                        "cost_basis": pos.cost_basis,
                        "premium_collected": pos.premium,
                        "total_profit": round(profit, 2),
                    })
                    to_remove.append(symbol)
                    self._save()
                
                # Check if option expired
                elif datetime.now().strftime("%Y-%m-%d") >= pos.expiration:
                    log.info(f"[EXPIRED] {symbol} call expired, keep premium and shares")
                    self._log_trade("expired_call", symbol, {
                        "premium_kept": pos.premium,
                    })
                    del self.positions[symbol]
                    self._save()
        
        return [symbol for symbol in to_remove]

    # ─── Main Wheel Logic ─────────────────────────────────────────────────────

    def spin(self, symbols: list[str] = None):
        """
        Run one wheel cycle:
        1. Check for assignments/calls
        2. Open new CSPs on available symbols
        3. Open covered calls on held shares
        """
        log.info("=" * 50)
        log.info("WHEEL STRATEGY CYCLE")
        log.info("=" * 50)
        
        account = get_account()
        log.info(f"Cash: ${account['cash']:,.2f} | Equity: ${account['equity']:,.2f}")
        
        # Step 1: Check assignments and expirations
        log.info("\n[1/3] Checking assignments and expirations...")
        assigned = self.check_assignments()
        if assigned:
            log.info(f"Positions moved/closed: {assigned}")
        
        # Step 2: Open CSPs on symbols not in wheel
        log.info("\n[2/3] Opening Cash-Secured Puts...")
        
        if symbols:
            for symbol in symbols:
                stage = self.what_stage(symbol)
                if stage is None:
                    # No position, open a CSP
                    result = self.open_csp(symbol)
                    if result:
                        log.info(f"  Opened CSP on {symbol}")
                elif stage == "put":
                    log.info(f"  {symbol}: CSP active (strike=${self.positions[symbol].strike})")
                elif stage == "hold":
                    log.info(f"  {symbol}: holding shares, opening covered call")
                    self.open_covered_call(symbol)
                elif stage == "call":
                    log.info(f"  {symbol}: covered call active (strike=${self.positions[symbol].strike})")
        
        # Step 3: Open covered calls on any shares we hold without calls
        log.info("\n[3/3] Checking for uncovered shares...")
        for pos in self.get_positions():
            s = pos.symbol
            stage = self.what_stage(s)
            if stage == "hold":
                log.info(f"  Opening covered call on held shares of {s}")
                self.open_covered_call(s)
        
        # Print summary
        self.print_status()
        
        log.info("=" * 50)
        log.info("WHEEL CYCLE COMPLETE")
        log.info("=" * 50)

    def print_status(self):
        log.info("\n[Wheel Positions Summary]")
        if not self.positions:
            log.info("  No active wheel positions")
        
        for symbol, pos in self.positions.items():
            current = get_latest_price(symbol)
            log.info(f"  {symbol}:")
            log.info(f"    Stage: {pos.stage.upper()}")
            log.info(f"    Strike: ${pos.strike}")
            log.info(f"    Premium: ${pos.premium:.2f}")
            log.info(f"    Expires: {pos.expiration}")
            if pos.stage == "call":
                log.info(f"    Cost basis: ${pos.cost_basis}")
                if current:
                    unrealized = (current - pos.cost_basis) * pos.qty
                    log.info(f"    Current: ${current} | Unrealized P/L: ${unrealized:.2f}")
            elif pos.stage == "put" and current:
                log.info(f"    Current: ${current} | Down ${pos.strike - current:.2f} from strike")
        
        # Show trade log summary
        if self.trade_log:
            premiums = [t.get("premium", 0) for t in self.trade_log[-10:] if t.get("premium")]
            total = sum(premiums)
            log.info(f"\n  Last 10 premiums collected: ${total:.2f}")
            log.info(f"  Total trades: {len(self.trade_log)}")


# ─── Demo ─────────────────────────────────────────────────────────────────────

def demo():
    """Run wheel strategy on existing positions."""
    wheel = WheelStrategy()
    
    # Get symbols from our existing copy trading positions
    positions = wheel.get_positions()
    symbols = [p.symbol for p in positions]
    
    if not symbols:
        log.info("No positions found. Add stocks to trade wheel strategy.")
        # Demo with a sample stock
        symbols = ["AAPL"]
    
    wheel.spin(symbols=symbols)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    demo()
