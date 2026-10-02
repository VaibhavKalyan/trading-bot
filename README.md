# Team154-log(n) APAC Quant Trading Hackathon 2026

> **Strategy:** RSI(14) + EMA(9/21) Crossover with Long & Short positions  
> **Platform:** Roostoo Mock Exchange | **Cloud:** AWS EC2 ap-southeast-2  
> **Sponsors:** Susquehanna × AWS

---

## Strategy Overview

Our bot implements a **trend-following + mean-reversion hybrid** strategy:

### Signal Generation
- **EMA Crossover** (9-period vs 21-period) determines the market **trend direction**
- **RSI(14)** identifies **entry timing** within that trend (oversold/overbought extremes)

| Condition | Signal |
|-----------|--------|
| EMA_9 > EMA_21 AND RSI crosses above 35 (oversold bounce) | **BUY** (long entry) |
| RSI crosses above 65 OR EMA bearish cross | **SELL** (close long) |
| EMA_9 < EMA_21 AND RSI crosses below 65 (overbought drop) | **SHORT OPEN** |
| RSI crosses below 35 OR EMA bullish cross | **SHORT CLOSE** |

**Why this works:** We only enter longs in an uptrend and shorts in a downtrend. RSI ensures we enter at a value point rather than chasing momentum — this improves the Sortino ratio by filtering out low-quality entries.

### Data Sources
- **Historical OHLCV**: Binance Public API (free, no key needed) — 1-hour candles
- **Live prices**: Roostoo `/v3/ticker` endpoint

### Risk Management
- **Max position size**: 10% of portfolio per trade
- **Stop-loss**: 2% below entry for longs, 2% above entry for shorts
- **Max drawdown guard**: Bot halts automatically if portfolio drops >15% from peak
- **No HFT**: Bot runs on 60-second loop, signals on 1-hour candles

---

## Project Structure

```
trading-bot/
├── bot.py                  ← Main entry point (run this)
├── config.py               ← All settings & parameters
├── requirements.txt
├── .env.example            ← Copy to .env and fill credentials
├── api/
│   └── roostoo_client.py   ← Roostoo API wrapper (auth, orders, balance)
├── strategy/
│   ├── indicators.py       ← RSI, EMA, ATR calculations
│   └── signals.py          ← Signal generation logic
├── risk/
│   └── manager.py          ← Position sizing, stop-loss, drawdown
├── data/
│   └── fetcher.py          ← Binance OHLCV fetcher
└── logs/                   ← Auto-generated trade logs
```

---

## Setup & Running

### 1. Clone and install dependencies
```bash
git clone https://github.com/YOUR_USERNAME/trading-bot.git
cd trading-bot
pip install -r requirements.txt
```

### 2. Configure API credentials
```bash
cp .env.example .env
nano .env   # Add your Roostoo API key and secret
```

### 3. Run locally (testing)
```bash
python bot.py
```

### 4. Deploy on AWS EC2 (competition)
```bash
# SSH into EC2 via Session Manager, then:
git clone https://github.com/YOUR_USERNAME/trading-bot.git
cd trading-bot
pip install -r requirements.txt
cp .env.example .env && nano .env

# Start in tmux so it keeps running after you disconnect
tmux
python bot.py
# Press Ctrl+B then D to detach
```

To reattach later:
```bash
tmux attach
```

---

## Configuration

Edit `config.py` or `.env` to tune the bot:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `LOOP_INTERVAL_SECONDS` | 60 | How often bot checks market |
| `MAX_POSITION_SIZE` | 0.10 | Max 10% of portfolio per trade |
| `STOP_LOSS_PCT` | 0.02 | 2% stop-loss |
| `MAX_DRAWDOWN_PCT` | 0.15 | Halt if drawdown > 15% |
| `RSI_PERIOD` | 14 | RSI window |
| `RSI_OVERSOLD` | 35 | RSI buy threshold |
| `RSI_OVERBOUGHT` | 65 | RSI sell threshold |
| `EMA_SHORT` | 9 | Fast EMA period |
| `EMA_LONG` | 21 | Slow EMA period |

---

## Portfolio Curation Philosophy

We prioritise **risk-adjusted returns** over raw PnL, targeting:
- **High Sortino Ratio**: Minimise downside volatility by only entering high-conviction setups (trend + RSI confirmation)
- **High Calmar Ratio**: Strict 15% max drawdown halt + 2% per-trade stop-losses
- **Consistent Sharpe**: Diversified across 5 pairs to smooth equity curve

**Transaction fee strategy**: We use **MARKET orders** (0.1% fee) only when signal is strong. This ensures execution but we remain mindful of fee drag on performance.

---

## Trade Logging

Every order attempt is logged to `logs/bot_YYYYMMDD_HHMMSS.log` with:
- Timestamp, pair, signal, RSI, EMA values
- Order side, quantity, price
- API response (success/failure)
- Portfolio value + drawdown after each cycle
