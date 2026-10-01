"""
data/fetcher.py
Fetches OHLCV (candlestick) data from Binance public API.
No API key needed — free and reliable for signal generation.
"""
import time
import requests
import pandas as pd
import logging

import config

logger = logging.getLogger(__name__)

BINANCE_BASE = "https://api.binance.com/api/v3"


def get_ohlcv(roostoo_pair: str, interval: str = "1h", limit: int = 100) -> pd.DataFrame:
    """
    Fetch OHLCV candles from Binance for a given Roostoo pair.

    Args:
        roostoo_pair: e.g. "BTC/USD"
        interval:     Binance interval string: "1m","5m","15m","1h","4h","1d"
        limit:        Number of candles to fetch (max 1000)

    Returns:
        DataFrame with columns: [open_time, open, high, low, close, volume]
    """
    symbol = config.BINANCE_SYMBOL_MAP.get(roostoo_pair)
    if not symbol:
        logger.warning(f"No Binance mapping for {roostoo_pair}")
        return pd.DataFrame()

    try:
        resp = requests.get(
            f"{BINANCE_BASE}/klines",
            params={"symbol": symbol, "interval": interval, "limit": limit},
            timeout=15,
        )
        resp.raise_for_status()
        raw = resp.json()

        df = pd.DataFrame(raw, columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades",
            "taker_buy_base", "taker_buy_quote", "ignore",
        ])

        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)

        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
        df.set_index("open_time", inplace=True)

        return df[["open", "high", "low", "close", "volume"]]

    except Exception as e:
        logger.error(f"Failed to fetch OHLCV for {roostoo_pair}: {e}")
        return pd.DataFrame()


def get_live_price(roostoo_pair: str, ticker_data: dict) -> float:
    """
    Extract the latest price for a pair from Roostoo ticker data.

    Args:
        roostoo_pair: e.g. "BTC/USD"
        ticker_data:  Response from roostoo_client.get_ticker()

    Returns:
        LastPrice float, or 0.0 if not found
    """
    pair_data = ticker_data.get(roostoo_pair, {})
    return float(pair_data.get("LastPrice", 0.0))
