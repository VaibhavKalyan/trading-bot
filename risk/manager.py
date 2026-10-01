"""
risk/manager.py
Risk management: position sizing, stop-loss tracking, drawdown guard.

Key responsibilities:
  1. Calculate how many coins to buy given portfolio constraints
  2. Track entry prices and trigger stop-losses
  3. Halt bot if portfolio drawdown exceeds MAX_DRAWDOWN threshold
"""
import logging
import config

logger = logging.getLogger(__name__)


class RiskManager:
    def __init__(self, initial_usd: float = 100_000.0):
        self.initial_usd   = initial_usd
        self.peak_usd      = initial_usd   # for drawdown tracking
        self.halted        = False         # True if drawdown limit breached
        self.positions     = {}            # pair -> {"entry_price": float, "quantity": float}
        self.short_positions = {}          # pair -> {"entry_price": float, "quantity": float}

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
            pair    = f"{coin}/USD"
            price   = ticker.get(pair, {}).get("LastPrice", 0)
            total  += (holdings.get("Free", 0) + holdings.get("Lock", 0)) * price
        return total

    def update_peak(self, current_value: float):
        if current_value > self.peak_usd:
            self.peak_usd = current_value

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

    # ── Position sizing ───────────────────────────────────────────────────────

    def calc_buy_quantity(self, pair: str, price: float, usd_free: float) -> float:
        """
        Calculate coin quantity to buy.

        Uses MAX_POS_SIZE fraction of available USD, capped at what's available.
        Returns 0.0 if position already open for this pair.
        """
        if pair in self.positions:
            logger.info(f"Already holding {pair}, skipping BUY")
            return 0.0

        budget = min(usd_free * config.MAX_POS_SIZE, usd_free * 0.95)
        if budget < 1.0 or price <= 0:
            return 0.0

        quantity = budget / price
        logger.info(f"Sizing BUY {pair}: {quantity:.6f} coins @ ${price:.2f} (budget=${budget:.2f})")
        return quantity

    def calc_sell_quantity(self, pair: str, wallet: dict) -> float:
        """
        Calculate quantity to sell (close entire long position).
        """
        coin = pair.split("/")[0]
        free = wallet.get(coin, {}).get("Free", 0.0)
        if free <= 0:
            logger.info(f"No {coin} to sell")
            return 0.0
        return free

    def calc_short_quantity(self, pair: str, price: float, usd_free: float) -> float:
        """Calculate quantity for short position (uses same sizing as long)."""
        if pair in self.short_positions:
            logger.info(f"Already shorting {pair}, skipping SHORT_OPEN")
            return 0.0

        budget = usd_free * config.MAX_POS_SIZE
        if budget < 1.0 or price <= 0:
            return 0.0
        return budget / price

    # ── Entry / Stop-Loss tracking ────────────────────────────────────────────

    def record_entry(self, pair: str, quantity: float, price: float):
        """Record a long entry."""
        self.positions[pair] = {"entry_price": price, "quantity": quantity}
        logger.info(f"[ENTRY] {pair} | qty={quantity:.6f} | price=${price:.2f}")

    def record_short_entry(self, pair: str, quantity: float, price: float):
        self.short_positions[pair] = {"entry_price": price, "quantity": quantity}
        logger.info(f"[SHORT ENTRY] {pair} | qty={quantity:.6f} | price=${price:.2f}")

    def clear_position(self, pair: str):
        self.positions.pop(pair, None)
        logger.info(f"[EXIT] Long position closed: {pair}")

    def clear_short_position(self, pair: str):
        self.short_positions.pop(pair, None)
        logger.info(f"[SHORT EXIT] Short position closed: {pair}")

    def is_stop_loss_hit(self, pair: str, current_price: float) -> bool:
        """
        Returns True if price dropped more than STOP_LOSS_PCT below entry.
        """
        pos = self.positions.get(pair)
        if not pos:
            return False
        entry   = pos["entry_price"]
        trigger = entry * (1 - config.STOP_LOSS_PCT)
        if current_price <= trigger:
            logger.warning(f"🛑 STOP-LOSS hit for {pair}: ${current_price:.2f} <= ${trigger:.2f}")
            return True
        return False

    def is_short_stop_hit(self, pair: str, current_price: float) -> bool:
        """Returns True if price rose more than STOP_LOSS_PCT above short entry."""
        pos = self.short_positions.get(pair)
        if not pos:
            return False
        entry   = pos["entry_price"]
        trigger = entry * (1 + config.STOP_LOSS_PCT)
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
