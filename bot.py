"""
bot.py — Main trading bot entry point.

Run with:  python bot.py

What it does every LOOP_INTERVAL seconds:
  1. Fetch all market tickers from Roostoo
  2. For each pair: fetch OHLCV from Binance → generate signal
  3. Check stop-losses on open positions
  4. Execute BUY / SELL / SHORT_OPEN / SHORT_CLOSE orders
  5. Check global drawdown — halt if breached
  6. Log everything
"""
import time
import logging
import sys
from datetime import datetime

import config
from api import roostoo_client as rc
from data.fetcher import get_ohlcv, get_live_price
from strategy.signals import generate_signal, BUY, SELL, SHORT_OPEN, SHORT_CLOSE, HOLD
from risk.manager import RiskManager

# ── Logging setup ──────────────────────────────────────────────────────────────
log_filename = f"logs/bot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    handlers=[
        logging.FileHandler(log_filename),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


# ── Sanity check ───────────────────────────────────────────────────────────────
def check_config():
    if not config.API_KEY or not config.SECRET_KEY:
        logger.error("API_KEY or SECRET_KEY not set! Create a .env file from .env.example")
        sys.exit(1)

    # Test connectivity
    try:
        server_time = rc.get_server_time()
        logger.info(f"✅ Connected to Roostoo. Server time: {server_time}")
    except Exception as e:
        logger.error(f"❌ Cannot reach Roostoo API: {e}")
        sys.exit(1)


# ── Main trading loop ──────────────────────────────────────────────────────────
def run():
    check_config()

    # Discover available pairs from exchange
    try:
        info   = rc.get_exchange_info()
        pairs  = [p for p in info.get("TradePairs", {}).keys() if info["TradePairs"][p]["CanTrade"]]
        pairs  = [p for p in pairs if p in config.TRADE_PAIRS]  # only our configured ones
        logger.info(f"Trading pairs: {pairs}")
    except Exception as e:
        logger.warning(f"Could not fetch exchange info ({e}), using config pairs")
        pairs = config.TRADE_PAIRS

    # Get initial portfolio value
    try:
        wallet   = rc.get_balance()
        ticker   = rc.get_ticker()
        risk_mgr = RiskManager(initial_usd=100_000.0)
        init_val = risk_mgr.portfolio_value(wallet, ticker)
        logger.info(f"💰 Initial portfolio value: ${init_val:,.2f}")
    except Exception as e:
        logger.error(f"Could not get initial balance: {e}")
        risk_mgr = RiskManager()

    iteration = 0

    while True:
        iteration += 1
        logger.info(f"\n{'='*60}")
        logger.info(f"ITERATION {iteration} | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"{'='*60}")

        try:
            # ── Step 1: Fetch live market data ────────────────────────────────
            ticker = rc.get_ticker()
            wallet = rc.get_balance()
            usd_free = wallet.get("USD", {}).get("Free", 0.0)

            current_value = risk_mgr.portfolio_value(wallet, ticker)
            risk_mgr.update_peak(current_value)
            logger.info(risk_mgr.summary(current_value))

            # ── Step 2: Halt check ────────────────────────────────────────────
            if risk_mgr.check_halt(current_value):
                logger.critical("🚨 Bot halted due to max drawdown. Exiting.")
                break

            # ── Step 3: Stop-loss checks (before new signals) ─────────────────
            for pair in list(risk_mgr.positions.keys()):
                price = get_live_price(pair, ticker)
                if price > 0 and risk_mgr.is_stop_loss_hit(pair, price):
                    qty = risk_mgr.calc_sell_quantity(pair, wallet)
                    if qty > 0:
                        result = rc.place_order(pair, "SELL", qty)
                        if result.get("Success"):
                            risk_mgr.clear_position(pair)

            for pair in list(risk_mgr.short_positions.keys()):
                price = get_live_price(pair, ticker)
                if price > 0 and risk_mgr.is_short_stop_hit(pair, price):
                    pos_qty = risk_mgr.short_positions[pair]["quantity"]
                    result  = rc.close_short(pair, pos_qty)
                    if result.get("Success"):
                        risk_mgr.clear_short_position(pair)

            # ── Step 4: Signal generation & order execution ───────────────────
            for pair in pairs:
                try:
                    df = get_ohlcv(pair, interval="1h", limit=60)
                    if df.empty:
                        continue

                    sig = generate_signal(df)
                    price = get_live_price(pair, ticker)

                    logger.info(
                        f"{pair} | signal={sig['signal']} | "
                        f"price=${price:.4f} | RSI={sig['rsi']} | "
                        f"EMA_S={sig['ema_short']} EMA_L={sig['ema_long']}"
                    )

                    if sig["signal"] == BUY:
                        qty = risk_mgr.calc_buy_quantity(pair, price, usd_free)
                        if qty > 0:
                            result = rc.place_order(pair, "BUY", qty)
                            if result.get("Success"):
                                risk_mgr.record_entry(pair, qty, price)
                                usd_free -= qty * price  # update local estimate

                    elif sig["signal"] == SELL:
                        qty = risk_mgr.calc_sell_quantity(pair, wallet)
                        if qty > 0:
                            result = rc.place_order(pair, "SELL", qty)
                            if result.get("Success"):
                                risk_mgr.clear_position(pair)

                    elif sig["signal"] == SHORT_OPEN:
                        qty = risk_mgr.calc_short_quantity(pair, price, usd_free)
                        if qty > 0:
                            result = rc.open_short(pair, qty)
                            if result.get("Success"):
                                risk_mgr.record_short_entry(pair, qty, price)

                    elif sig["signal"] == SHORT_CLOSE:
                        if pair in risk_mgr.short_positions:
                            pos_qty = risk_mgr.short_positions[pair]["quantity"]
                            result  = rc.close_short(pair, pos_qty)
                            if result.get("Success"):
                                risk_mgr.clear_short_position(pair)

                    # Small delay between pairs to avoid rate limits
                    time.sleep(1)

                except Exception as e:
                    logger.error(f"Error processing {pair}: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"Loop error: {e}", exc_info=True)

        # ── Step 5: Wait for next iteration ──────────────────────────────────
        logger.info(f"💤 Sleeping {config.LOOP_INTERVAL}s until next cycle...")
        time.sleep(config.LOOP_INTERVAL)


if __name__ == "__main__":
    logger.info("🚀 Roostoo Trading Bot starting...")
    logger.info(f"Strategy: RSI({config.RSI_PERIOD}) + EMA({config.EMA_SHORT}/{config.EMA_LONG})")
    logger.info(f"Max position: {config.MAX_POS_SIZE:.0%} | Stop loss: {config.STOP_LOSS_PCT:.0%} | Max drawdown: {config.MAX_DRAWDOWN:.0%}")
    run()
