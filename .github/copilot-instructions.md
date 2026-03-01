# Daily Stock Screener Automation — Copilot Skills

## Project Overview
Indian stock market screener system that identifies high-probability buy candidates from Nifty 500 stocks. Stores all data in SQLite (`screener.db`). Learns from past failures to auto-improve filter thresholds and scoring weights.

## Architecture & Files

| File | Purpose |
|---|---|
| `weekly_stock_picker.py` | Monday morning picks, strict 8-filter checklist. Horizon: 1-4 weeks. |
| `swing_breakout_screener.py` | 1-2 month swing trades, weighted 10-factor scoring. |
| `backtester.py` | Checks open picks vs market, analyses losses, adjusts algo params automatically. |
| `db.py` | Shared SQLite layer — tables: `picks`, `trade_outcomes`, `algo_params`, `run_log`. |
| `config.json` | User-editable config (top_n, min_price, workers, filters). |
| `requirements.txt` | pandas, numpy, yfinance, requests, beautifulsoup4, lxml, tabulate, feedparser, vaderSentiment |

## SQLite Schema (`screener.db`)
- **picks** — Every stock pick (weekly + swing), entry/target/SL, status tracking (OPEN/TARGET_HIT/STOP_LOSS/EXPIRED)  
- **trade_outcomes** — Backtest check results (PnL, max/min price since entry)  
- **algo_params** — Self-tuning parameters per screener (auto-adjusted by backtester.py)  
- **run_log** — Audit trail of every screener run  

## Data Sources
- **Nifty 500 list**: NSE archives CSV (`https://archives.nseindia.com/content/indices/ind_nifty500list.csv`)
- **OHLCV + Technicals**: Yahoo Finance via `yfinance` (`{TICKER}.NS` suffix)
- **News Sentiment**: Google News RSS → VADER sentiment
- **Fundamentals**: screener.in quarterly results page
- **Bulk Deals**: NSE bulk deals CSV

## How It Works — Weekly Screener
1. Fetches Nifty 500 tickers
2. Parallel-downloads ~6 months price data from Yahoo Finance
3. Calculates: RSI, ADX, MACD, 50/200 SMA, Bollinger Bands, volume spike, relative strength vs Nifty50, 52-week distance, fundamentals, news sentiment
4. Applies 8 strict filters (ALL must pass): Trend, Momentum, Volume, Relative Strength, 52-Week, Fundamentals, Sentiment, Risk-Reward
5. Saves picks to `screener.db` and generates CSV report

## How It Works — Swing Screener
1. Same data fetch as weekly
2. Calculates 10 scoring factors with tunable weights (loaded from `algo_params` table)
3. Composite score = weighted sum; picks passing minimum threshold are ranked
4. Top N by score saved to DB

## Self-Learning (backtester.py)
- Compares open picks against live prices → closes TARGET_HIT / STOP_LOSS / EXPIRED
- Analyses failure patterns: median RSI, ADX, volume, RS of losers vs winners
- Adjusts params using learning rate 0.3, clamped to safe bounds
- Parameters stored in `algo_params` table, loaded automatically on next screener run

## CLI Commands
```bash
# Weekly screener
python weekly_stock_picker.py               # Full scan
python weekly_stock_picker.py --fast        # Skip fundamentals+sentiment
python weekly_stock_picker.py --check-portfolio  # Check open weekly trades

# Swing screener  
python swing_breakout_screener.py           # Full scan
python swing_breakout_screener.py --fast    # Skip fundamentals+sentiment
python swing_breakout_screener.py --check-portfolio  # Check open swing trades

# Backtester
python backtester.py                        # Check all open + learn from failures
python backtester.py --check-only           # Just check picks
python backtester.py --learn-only           # Just run learning
python backtester.py --report               # Full performance report
python backtester.py --reset                # Reset learned params to defaults
```

## Key Design Decisions
- **Indian market only** — Nifty 500 universe, `.NS` Yahoo suffix, INR prices
- **SQLite not CSV/JSON** — All picks, outcomes, params in one `screener.db` file
- **Two paradigms**: Weekly = strict filters (all must pass), Swing = composite scoring (top N)
- **Self-tuning**: backtester.py auto-adjusts filter thresholds and scoring weights based on win/loss analysis
- **ThreadPoolExecutor** for parallel screening (default 10 workers)
- **Stop-loss always set** — 7% below entry for weekly, based on ATR for swing
- **Target**: 15% for weekly, ATR-based for swing (10-20%+ expected)

## When User Asks To...
- "Run the screener" → `python weekly_stock_picker.py` for weekly, `python swing_breakout_screener.py` for swing
- "Check portfolio" → `python backtester.py` (checks both) or `--check-portfolio` flag on individual screeners
- "Improve the algorithm" → `python backtester.py` triggers auto-learning
- "Show performance" → `python backtester.py --report`
- "Add a new filter" → Edit the `FILTERS` dict in the relevant screener, add corresponding analysis in `backtester.py`
- "Change target %" → Edit `config.json` or `FILTERS` dict in the screener

## Tech Stack
- Python 3.13, Windows
- No external DB required (SQLite built-in)
- No API keys needed (all free data sources)
