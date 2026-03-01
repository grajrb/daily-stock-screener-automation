# Weekly Stock Picker — Monday Market Open Edition

A high-conviction stock screener for NSE (Nifty 500) that finds the best stocks to buy every Monday morning. Uses **8 strict filters** — a stock must pass ALL of them to make the list.

## How It Works

Every Sunday/Monday before market open, run the script. It screens all 500 Nifty stocks through:

| # | Filter | What It Checks |
|---|--------|----------------|
| 1 | **Trend** | Price above rising SMA50 & SMA200, golden cross (Stage-2 uptrend) |
| 2 | **Momentum** | RSI 50-75, MACD bullish, ADX > 20 (trending, not overbought) |
| 3 | **Volume** | Volume spike > 1.3x 20-day avg + rising On-Balance Volume |
| 4 | **Relative Strength** | Outperforming Nifty 50 over last 1 month |
| 5 | **52-Week Position** | Within 15% of 52W high, at least 25% above 52W low |
| 6 | **Fundamentals** | YoY revenue & profit growth > 8% (scraped from screener.in) |
| 7 | **News Sentiment** | Not heavily negative (Google News RSS + VADER analysis) |
| 8 | **Risk-Reward** | Minimum 2:1 ratio (target +15%, stop-loss ~5-7% below) |

Only stocks passing **ALL 8 filters** appear in the final list.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run the full scan (takes 10-15 min)
python weekly_stock_picker.py

# Faster scan — skip screener.in fundamentals
python weekly_stock_picker.py --fast

# Check your open trades for exit signals
python weekly_stock_picker.py --check-portfolio
```

## Output

- `monday_picks_YYYY-MM-DD.csv` — This week's picks with Entry, Target, Stop-Loss
- `active_trades.json` — Portfolio tracker (auto-updated)
- Console printout with full trade plan

## How To Trade

1. **BUY** at the Entry Price on Monday after 9:30 AM (let first 15 min settle)
2. **SET STOP-LOSS** immediately at the Stop_Loss price
3. **HOLD** — don't panic-sell on small dips
4. **SELL** when the stock hits the Target price (~15% up)
5. If a stock goes up 10%+, trail your stop-loss to your entry price
6. Run `--check-portfolio` weekly to see which trades to exit
7. Max hold: 60 days — review if target not hit

## Risk Management

- **Position sizing:** Never more than 15% of capital in one stock
- **Risk per trade:** ~2% of total capital
- **Expected win rate:** ~60-70% (not 100% — no system can guarantee that)
- **Why it still works:** Winners (+15%) are bigger than losers (~5-7%)

## Project Structure

```
weekly_stock_picker.py   # The main script — run this
config.json              # Filter thresholds (editable)
requirements.txt         # Python dependencies
active_trades.json       # Auto-generated portfolio tracker
monday_picks_*.csv       # Auto-generated weekly reports
README.md                # This file
```

## Requirements

- Python 3.8+
- Internet connection (fetches live data from NSE, Yahoo Finance, screener.in, Google News)

## Disclaimer

No screener can guarantee 100% that a stock will go up. Stock markets carry inherent risk. This tool uses the strictest multi-factor filters to find high-probability setups, but some trades will still fail. **Always use the stop-loss.** Never invest money you can't afford to lose.