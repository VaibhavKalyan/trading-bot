"""
config.py — Central configuration loaded from .env
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── Roostoo API ──────────────────────────────────────────────────────────────
BASE_URL        = "https://mock-api.roostoo.com"
API_KEY         = os.getenv("ROOSTOO_API_KEY", "")
SECRET_KEY      = os.getenv("ROOSTOO_SECRET_KEY", "")

# ── Bot behaviour ────────────────────────────────────────────────────────────
LOOP_INTERVAL   = int(os.getenv("LOOP_INTERVAL_SECONDS", "60"))   # seconds
MAX_POS_SIZE    = float(os.getenv("MAX_POSITION_SIZE", "0.10"))    # 10 % of portfolio
STOP_LOSS_PCT   = float(os.getenv("STOP_LOSS_PCT", "0.02"))        # 2 % stop loss
MAX_DRAWDOWN    = float(os.getenv("MAX_DRAWDOWN_PCT", "0.15"))      # 15 % halt threshold

# ── Trading pairs to monitor ─────────────────────────────────────────────────
# These are the pairs available on Roostoo. Adjust after calling /v3/exchangeInfo
TRADE_PAIRS = [
    "BTC/USD",
    "ETH/USD",
    "BNB/USD",
    "SOL/USD",
    "XRP/USD",
]

# ── Strategy parameters ──────────────────────────────────────────────────────
RSI_PERIOD      = 14
RSI_OVERSOLD    = 35     # buy signal when RSI below this
RSI_OVERBOUGHT  = 65     # sell signal when RSI above this
EMA_SHORT       = 9      # fast EMA
EMA_LONG        = 21     # slow EMA

# ── Binance pair mapping (for historical data) ───────────────────────────────
BINANCE_SYMBOL_MAP = {
    "BTC/USD":  "BTCUSDT",
    "ETH/USD":  "ETHUSDT",
    "BNB/USD":  "BNBUSDT",
    "SOL/USD":  "SOLUSDT",
    "XRP/USD":  "XRPUSDT",
}
