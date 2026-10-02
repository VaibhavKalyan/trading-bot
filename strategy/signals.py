"""
strategy/signals.py
Signal generation: combines RSI + EMA crossover to produce BUY / SELL / HOLD.

Strategy Logic:
  LONG ENTRY  (BUY)  : EMA_SHORT > EMA_LONG (uptrend) AND RSI crosses up through oversold level
  LONG EXIT   (SELL) : RSI crosses above overbought level OR EMA_SHORT < EMA_LONG (trend reversal)
  SHORT ENTRY        : EMA_SHORT < EMA_LONG (downtrend) AND RSI crosses down through overbought level
  SHORT EXIT         : RSI crosses below oversold level OR EMA_SHORT > EMA_LONG

This avoids HFT — signals only fire on confirmed bar closes (1h candles).
"""
import pandas as pd
import logging

import config
from strategy.indicators import compute_rsi, compute_ema, compute_atr

logger = logging.getLogger(__name__)

# Signal constants
BUY        = "BUY"
SELL       = "SELL"
SHORT_OPEN = "SHORT_OPEN"
SHORT_CLOSE= "SHORT_CLOSE"
HOLD       = "HOLD"


def generate_signal(df: pd.DataFrame) -> dict:
    """
    Analyse OHLCV data and return a trading signal.

    Args:
        df: DataFrame with columns [open, high, low, close, volume]
            Must have at least EMA_LONG + 5 rows.

    Returns:
        dict with keys:
          signal   : BUY | SELL | SHORT_OPEN | SHORT_CLOSE | HOLD
          rsi      : current RSI value
          ema_short: current short EMA
          ema_long : current long EMA
          atr      : current ATR (for stop-loss sizing)
          price    : last close price
    """
    result = {
        "signal":    HOLD,
        "rsi":       None,
        "ema_short": None,
        "ema_long":  None,
        "atr":       None,
        "price":     None,
    }

    min_rows = config.EMA_LONG + config.RSI_PERIOD + 5
    if len(df) < min_rows:
        logger.warning(f"Not enough data: {len(df)} rows, need {min_rows}")
        return result

    close = df["close"]

    rsi       = compute_rsi(close, config.RSI_PERIOD)
    ema_short = compute_ema(close, config.EMA_SHORT)
    ema_long  = compute_ema(close, config.EMA_LONG)
    atr       = compute_atr(df)

    # Current and previous bar values
    rsi_now   = rsi.iloc[-1]
    rsi_prev  = rsi.iloc[-2]
    es_now    = ema_short.iloc[-1]
    el_now    = ema_long.iloc[-1]
    es_prev   = ema_short.iloc[-2]
    el_prev   = ema_long.iloc[-2]
    atr_now   = atr.iloc[-1]
    price     = close.iloc[-1]

    result.update({
        "rsi":       round(rsi_now, 2),
        "ema_short": round(es_now, 4),
        "ema_long":  round(el_now, 4),
        "atr":       round(atr_now, 4),
        "price":     round(price, 4),
    })

    uptrend   = es_now  > el_now
    downtrend = es_now  < el_now
    ema_bullish_cross = (es_now > el_now) and (es_prev <= el_prev)
    ema_bearish_cross = (es_now < el_now) and (es_prev >= el_prev)

    rsi_bouncing_up   = (rsi_now > config.RSI_OVERSOLD)   and (rsi_prev <= config.RSI_OVERSOLD)
    rsi_dropping_down = (rsi_now < config.RSI_OVERBOUGHT) and (rsi_prev >= config.RSI_OVERBOUGHT)

    # ── LONG signals ─────────────────────────────────────────────────────────
    if uptrend and rsi_bouncing_up:
        result["signal"] = BUY
        logger.info(f"BUY signal  | RSI={rsi_now:.1f} | EMA_S={es_now:.2f} > EMA_L={el_now:.2f}")

    # FIX #2: SELL when RSI overbought OR EMA bearish cross (regardless of trend direction)
    # The old condition wrongly required "not uptrend" which overlapped with SHORT_OPEN logic.
    elif rsi_now > config.RSI_OVERBOUGHT or ema_bearish_cross:
        result["signal"] = SELL
        logger.info(f"SELL signal | RSI={rsi_now:.1f} | ema_bearish_cross={ema_bearish_cross}")

    # ── SHORT signals ─────────────────────────────────────────────────────────
    elif downtrend and rsi_dropping_down:
        result["signal"] = SHORT_OPEN
        logger.info(f"SHORT OPEN  | RSI={rsi_now:.1f} | EMA_S={es_now:.2f} < EMA_L={el_now:.2f}")

    elif (uptrend and rsi_now < config.RSI_OVERSOLD) or ema_bullish_cross:
        result["signal"] = SHORT_CLOSE
        logger.info(f"SHORT CLOSE | RSI={rsi_now:.1f}")

    return result
