"""
risk/manager.py
Risk management: position sizing, stop-loss tracking, drawdown guard.

Key responsibilities:
  1. Calculate how many coins to buy given portfolio constraints
  2. Track entry prices and trigger stop-losses (ATR-based, dynamic)
  3. Halt bot if portfolio drawdown exceeds MAX_DRAWDOWN threshold
  4. Persist state to disk so positions survive restarts  [FIX #1]
  5. Enforce cooldown after stop-loss to prevent immediate re-entry [FIX #7]
"""
import json
import logging
import os
import time

import config

logger = logging.getLogger(__name__)

STATE_FILE = "risk_state.json"


class RiskManager:
    def __init__(self, initial_usd: float = 100_000.0):
        self.initial_usd     = initial_usd
        self.peak_usd        = initial_usd   # for drawdown tracking
        self.halted          = False
        self.positions       = {}            # pair -> {"entry_price", "quantity", "stop_price"}
        self.short_positions = {}            # pair -> {"entry_price", "quantity", "stop_price"}
        self.cooldown        = {}            # pair -> expiry timestamp (FIX #7)
        self._load_state()                   # restore from disk on startup (FIX #1)

    # ── State persistence (FIX #1) ────────────────────────────────────────────

    def _save_state(self):
        """Persist positions and peak_usd to disk so we survive EC2 restarts."""
        state = {
            "peak_usd":        self.peak_usd,
            "positions":       self.positions,
            "short_positions": self.short_positions,
        }
        try:
            with open(STATE_FILE, "w") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save state: {e}")

    def _load_state(self):
        """Restore positions from disk after a restart."""
        if not os.path.exists(STATE_FILE):
            logger.info("No saved state found — starting fresh.")
            return
        try:
            with open(STATE_FILE) as f:
                state = json.load(f)
            self.peak_usd        = state.get("peak_usd", self.peak_usd)
            self.positions       = state.get("positions", {})
            self.short_positions = state.get("short_positions", {})
            logger.info(
                f"♻️  Restored state from disk | "
                f"Peak=${self.peak_usd:,.2f} | "
                f"Longs={list(self.positions.keys())} | "
                f"Shorts={list(self.short_positions.keys())}"
            )
        except Exception as e:
            logger.error(f"Failed to load state (starting fresh): {e}")

    # ── Portfolio value ───────────────────────────────────────────────────────

    def portfolio_value(self, wallet: dict, ticker: dict) -> float:
        """
        Compute total portfolio value in USD.

        Args:
            wallet: from roostoo_client.get_balance()
            ticker: from roostoo_client.get_ticker()
        """
        total = wallet.get("USD", {}).get("Free", 0) + wallet.get("USD", {}).get("Lock", 0)
        for coin, holdings in wallet.items():
            if coin == "USD":
                continue
            pair   = f"{coin}/USD"
            price  = ticker.get(pair, {}).get("LastPrice", 0)
            total += (holdings.get("Free", 0) + holdings.get("Lock", 0)) * price
        return total

    def update_peak(self, current_value: float):
        if current_value > self.peak_usd:
            self.peak_usd = current_value
            self._save_state()

    def drawdown(self, current_value: float) -> float:
        """Drawdown as a fraction (0.0 – 1.0)."""
        return (self.peak_usd - current_value) / self.peak_usd if self.peak_usd > 0 else 0.0

    def check_halt(self, current_value: float) -> bool:
        """Returns True and sets self.halted if drawdown breaches threshold."""
        dd = self.drawdown(current_value)
        if dd >= config.MAX_DRAWDOWN:
            logger.critical(f"🚨 MAX DRAWDOWN BREACHED: {dd:.1%} — HALTING BOT")
            self.halted = True
        return self.halted

    # ── Cooldown (FIX #7) ────────────────────────────────────────────────────

    def set_cooldown(self, pair: str, seconds: int = 3600):
        """Block new entries for `seconds` after a stop-loss (default 1 hour)."""
        self.cooldown[pair] = time.time() + seconds
        logger.info(f"⏳ Cooldown set for {pair} — no new entries for {seconds}s")

    def is_in_cooldown(self, pair: str) -> bool:
        """Returns True if this pair is still cooling down after a stop-loss."""
        expiry = self.cooldown.get(pair, 0)
        if time.time() < expiry:
            remaining = int(expiry - time.time())
            logger.info(f"⏳ {pair} in cooldown — {remaining}s remaining")
            return True
        # Cooldown expired — clean it up
        self.cooldown.pop(pair, None)
        return False

    # ── Position sizing ───────────────────────────────────────────────────────

    def calc_buy_quantity(self, pair: str, price: float, usd_free: float) -> float:
        """
        Calculate coin quantity to buy.
        Uses MAX_POS_SIZE fraction of available USD.
        Returns 0.0 if position already open or pair in cooldown.
        """
        if pair in self.positions:
            logger.info(f"Already holding {pair}, skipping BUY")
            return 0.0
        if self.is_in_cooldown(pair):
            return 0.0

        # FIX #4: removed the useless min(x*0.10, x*0.95) — 10% < 95% always
        budget = usd_free * config.MAX_POS_SIZE
        if budget < 1.0 or price <= 0:
            return 0.0

        quantity = budget / price
        logger.info(f"Sizing BUY {pair}: {quantity:.6f} coins @ ${price:.2f} (budget=${budget:.2f})")
        return quantity

    def calc_sell_quantity(self, pair: str, wallet: dict) -> float:
        """Calculate quantity to sell (close entire long position)."""
        coin = pair.split("/")[0]
        free = wallet.get(coin, {}).get("Free", 0.0)
        if free <= 0:
            logger.info(f"No {coin} to sell")
            return 0.0
        return free

    def calc_short_quantity(self, pair: str, price: float, usd_free: float) -> float:
        """Calculate quantity for short position (same sizing as long)."""
        if pair in self.short_positions:
            logger.info(f"Already shorting {pair}, skipping SHORT_OPEN")
            return 0.0
        if self.is_in_cooldown(pair):
            return 0.0

        budget = usd_free * config.MAX_POS_SIZE
        if budget < 1.0 or price <= 0:
            return 0.0
        return budget / price

    # ── Stop price calculation (FIX #5) ──────────────────────────────────────

    def _calc_stop_price_long(self, price: float, atr: float = None) -> float:
        """
        Dynamic stop-loss for longs using ATR (FIX #5).
        Uses 2x ATR as stop distance, with STOP_LOSS_PCT as a minimum floor.
        On a volatile day the stop widens; on a quiet day it tightens.
        """
        fixed_stop = price * (1 - config.STOP_LOSS_PCT)
        if atr and atr > 0:
            atr_stop = price - (2.0 * atr)
            return min(atr_stop, fixed_stop)   # most conservative (lowest) of the two
        return fixed_stop

    def _calc_stop_price_short(self, price: float, atr: float = None) -> float:
        """Dynamic stop-loss for shorts using ATR (FIX #5)."""
        fixed_stop = price * (1 + config.STOP_LOSS_PCT)
        if atr and atr > 0:
            atr_stop = price + (2.0 * atr)
            return max(atr_stop, fixed_stop)   # most conservative (highest) of the two
        return fixed_stop

    # ── Entry / Stop-Loss tracking ────────────────────────────────────────────

    def record_entry(self, pair: str, quantity: float, price: float, atr: float = None):
        """Record a long entry with a dynamic ATR-based stop price."""
        stop_price = self._calc_stop_price_long(price, atr)
        self.positions[pair] = {
            "entry_price": price,
            "quantity":    quantity,
            "stop_price":  stop_price,
        }
        logger.info(f"[ENTRY] {pair} | qty={quantity:.6f} | price=${price:.2f} | stop=${stop_price:.2f}")
        self._save_state()   # FIX #1: persist immediately

    def record_short_entry(self, pair: str, quantity: float, price: float, atr: float = None):
        """Record a short entry with a dynamic ATR-based stop price."""
        stop_price = self._calc_stop_price_short(price, atr)
        self.short_positions[pair] = {
            "entry_price": price,
            "quantity":    quantity,
            "stop_price":  stop_price,
        }
        logger.info(f"[SHORT ENTRY] {pair} | qty={quantity:.6f} | price=${price:.2f} | stop=${stop_price:.2f}")
        self._save_state()   # FIX #1: persist immediately

    def clear_position(self, pair: str):
        self.positions.pop(pair, None)
        logger.info(f"[EXIT] Long position closed: {pair}")
        self._save_state()   # FIX #1: persist immediately

    def clear_short_position(self, pair: str):
        self.short_positions.pop(pair, None)
        logger.info(f"[SHORT EXIT] Short position closed: {pair}")
        self._save_state()   # FIX #1: persist immediately

    def is_stop_loss_hit(self, pair: str, current_price: float) -> bool:
        """Returns True if price dropped below the stored stop price."""
        pos = self.positions.get(pair)
        if not pos:
            return False
        # FIX #5: use stored stop_price (ATR-based) instead of recalculating with fixed %
        trigger = pos.get("stop_price", pos["entry_price"] * (1 - config.STOP_LOSS_PCT))
        if current_price <= trigger:
            logger.warning(f"🛑 STOP-LOSS hit for {pair}: ${current_price:.2f} <= ${trigger:.2f}")
            return True
        return False

    def is_short_stop_hit(self, pair: str, current_price: float) -> bool:
        """Returns True if price rose above the stored short stop price."""
        pos = self.short_positions.get(pair)
        if not pos:
            return False
        # FIX #5: use stored stop_price (ATR-based)
        trigger = pos.get("stop_price", pos["entry_price"] * (1 + config.STOP_LOSS_PCT))
        if current_price >= trigger:
            logger.warning(f"🛑 SHORT STOP-LOSS hit for {pair}: ${current_price:.2f} >= ${trigger:.2f}")
            return True
        return False

    def summary(self, current_value: float) -> str:
        pnl = current_value - self.initial_usd
        pct = (pnl / self.initial_usd) * 100
        dd  = self.drawdown(current_value) * 100
        return (
            f"Portfolio=${current_value:,.2f} | "
            f"PnL=${pnl:+,.2f} ({pct:+.2f}%) | "
            f"Drawdown={dd:.2f}% | "
            f"Positions={list(self.positions.keys())} | "
            f"Shorts={list(self.short_positions.keys())}"
        )
