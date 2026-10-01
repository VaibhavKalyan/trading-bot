"""
api/roostoo_client.py
Handles all communication with the Roostoo Mock Exchange API.
Authentication: HMAC-SHA256 signed requests.
"""
import hashlib
import hmac
import time
import urllib.parse
import requests
import logging

import config

logger = logging.getLogger(__name__)

BASE_URL = config.BASE_URL


def _timestamp() -> str:
    """Return current UTC time as a 13-digit millisecond timestamp string."""
    return str(int(time.time() * 1000))


def _sign(params: dict) -> str:
    """
    Build the HMAC-SHA256 signature required by Roostoo.

    Steps (per Roostoo docs):
      1. Sort params by key
      2. Join as key=value pairs with '&'
      3. HMAC-SHA256 with your SECRET_KEY
    """
    sorted_params = sorted(params.items())
    query_string  = urllib.parse.urlencode(sorted_params)
    signature = hmac.new(
        config.SECRET_KEY.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return signature


def _signed_headers() -> dict:
    return {
        "RST-API-KEY": config.API_KEY,
        "Content-Type": "application/x-www-form-urlencoded",
    }


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC endpoints (no auth)
# ─────────────────────────────────────────────────────────────────────────────

def get_server_time() -> int:
    """Return Roostoo server time in milliseconds."""
    resp = requests.get(f"{BASE_URL}/v3/serverTime", timeout=10)
    resp.raise_for_status()
    return resp.json()["ServerTime"]


def get_exchange_info() -> dict:
    """Return exchange info including available trading pairs."""
    resp = requests.get(f"{BASE_URL}/v3/exchangeInfo", timeout=10)
    resp.raise_for_status()
    return resp.json()


# ─────────────────────────────────────────────────────────────────────────────
# TIMESTAMP-SIGNED endpoints (RCL_TSCheck)
# ─────────────────────────────────────────────────────────────────────────────

def get_ticker(pair: str = None) -> dict:
    """
    Get market ticker data.
    Returns all pairs if `pair` is None, or just the specified pair.
    """
    params = {"timestamp": _timestamp()}
    if pair:
        params["pair"] = pair

    resp = requests.get(
        f"{BASE_URL}/v3/ticker",
        params=params,
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("Success", True) and pair:
        logger.warning(f"Ticker error for {pair}: {data.get('ErrMsg')}")
    return data.get("Data", {})


# ─────────────────────────────────────────────────────────────────────────────
# SIGNED endpoints (RCL_TopLevelCheck)
# ─────────────────────────────────────────────────────────────────────────────

def get_balance() -> dict:
    """Return current wallet balances."""
    params = {"timestamp": _timestamp()}
    sig    = _sign(params)
    headers = {**_signed_headers(), "MSG-SIGNATURE": sig}

    resp = requests.get(
        f"{BASE_URL}/v3/balance",
        params=params,
        headers=headers,
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("Success"):
        logger.error(f"Balance error: {data.get('ErrMsg')}")
    return data.get("Wallet", {})


def get_pending_count() -> dict:
    """Return count of pending (open) orders."""
    params = {"timestamp": _timestamp()}
    sig    = _sign(params)
    headers = {**_signed_headers(), "MSG-SIGNATURE": sig}

    resp = requests.get(
        f"{BASE_URL}/v3/pending_count",
        params=params,
        headers=headers,
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def place_order(pair: str, side: str, quantity: float, order_type: str = "MARKET", price: float = None) -> dict:
    """
    Place a buy or sell order.

    Args:
        pair:       e.g. "BTC/USD"
        side:       "BUY" or "SELL"
        quantity:   Amount of coin to buy/sell
        order_type: "MARKET" (default) or "LIMIT"
        price:      Required for LIMIT orders

    Returns:
        API response dict
    """
    params = {
        "pair":      pair,
        "side":      side,
        "type":      order_type,
        "quantity":  str(round(quantity, 8)),
        "timestamp": _timestamp(),
    }
    if order_type == "LIMIT" and price is not None:
        params["price"] = str(round(price, 8))

    sig     = _sign(params)
    headers = {**_signed_headers(), "MSG-SIGNATURE": sig}

    resp = requests.post(
        f"{BASE_URL}/v3/place_order",
        data=params,
        headers=headers,
        timeout=10,
    )
    resp.raise_for_status()
    result = resp.json()
    logger.info(f"[ORDER] {side} {quantity:.6f} {pair} @ {order_type} → {result}")
    return result


def cancel_order(order_id: str, pair: str) -> dict:
    """Cancel an open order by ID."""
    params = {
        "orderId":   order_id,
        "pair":      pair,
        "timestamp": _timestamp(),
    }
    sig     = _sign(params)
    headers = {**_signed_headers(), "MSG-SIGNATURE": sig}

    resp = requests.post(
        f"{BASE_URL}/v3/cancel_order",
        data=params,
        headers=headers,
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def query_order(order_id: str, pair: str) -> dict:
    """Query the status of a specific order."""
    params = {
        "orderId":   order_id,
        "pair":      pair,
        "timestamp": _timestamp(),
    }
    sig     = _sign(params)
    headers = {**_signed_headers(), "MSG-SIGNATURE": sig}

    resp = requests.get(
        f"{BASE_URL}/v3/query_order",
        params=params,
        headers=headers,
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def open_short(pair: str, quantity: float) -> dict:
    """Open a short position (1x only — no leverage)."""
    params = {
        "pair":      pair,
        "quantity":  str(round(quantity, 8)),
        "timestamp": _timestamp(),
    }
    sig     = _sign(params)
    headers = {**_signed_headers(), "MSG-SIGNATURE": sig}

    resp = requests.post(
        f"{BASE_URL}/v3/open_short",
        data=params,
        headers=headers,
        timeout=10,
    )
    resp.raise_for_status()
    result = resp.json()
    logger.info(f"[SHORT OPEN] {quantity:.6f} {pair} → {result}")
    return result


def close_short(pair: str, quantity: float) -> dict:
    """Close a short position."""
    params = {
        "pair":      pair,
        "quantity":  str(round(quantity, 8)),
        "timestamp": _timestamp(),
    }
    sig     = _sign(params)
    headers = {**_signed_headers(), "MSG-SIGNATURE": sig}

    resp = requests.post(
        f"{BASE_URL}/v3/close_short",
        data=params,
        headers=headers,
        timeout=10,
    )
    resp.raise_for_status()
    result = resp.json()
    logger.info(f"[SHORT CLOSE] {quantity:.6f} {pair} → {result}")
    return result


def get_short_positions() -> dict:
    """Return all open short positions."""
    params = {"timestamp": _timestamp()}
    sig    = _sign(params)
    headers = {**_signed_headers(), "MSG-SIGNATURE": sig}

    resp = requests.get(
        f"{BASE_URL}/v3/short_positions",
        params=params,
        headers=headers,
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()
