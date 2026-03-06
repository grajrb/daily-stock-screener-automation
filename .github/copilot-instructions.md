# Daily Stock Screener Automation — Copilot Skills

## Project Overview

Indian stock market screener system that identifies high-probability buy candidates from Nifty 500 stocks. Stores all data in SQLite (`screener.db`). Learns from past failures to auto-improve filter thresholds and scoring weights. Has a hard market regime gate that blocks picks when the broad market is weak.

## Architecture & Files

| File                         | Purpose                                                                                       |
| ---------------------------- | --------------------------------------------------------------------------------------------- |
| `weekly_stock_picker.py`     | Single best pick of the week, strict 8-filter checklist. Regime-gated. Horizon: 1-4 weeks.    |
| `swing_breakout_screener.py` | Top 10 swing trades with sector cap, weighted 10-factor scoring. Regime-gated.                |
| `backtester.py`              | Checks open picks vs market, analyses losses, adjusts algo params. Pure-loss learning.        |
| `db.py`                      | Shared SQLite layer — tables: `picks`, `trade_outcomes`, `algo_params`, `run_log`.            |
| `config.json`                | User-editable config (top_n, min_price, workers, filters).                                    |
| `requirements.txt`           | pandas, numpy, yfinance, requests, beautifulsoup4, lxml, tabulate, feedparser, vaderSentiment |

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

1. **Market regime check**: Nifty 50 must be above 20-SMA AND India VIX ≤ 20 — otherwise picks are BLOCKED
2. Fetches Nifty 500 tickers
3. Parallel-downloads ~1 year price data from Yahoo Finance
4. Calculates: RSI, ADX, MACD, 50/200 SMA, Bollinger Bands, volume spike, relative strength vs Nifty50, 52-week distance, fundamentals, news sentiment
5. Applies 8 strict filters (ALL must pass): Trend, Momentum (ADX ≥ 25), Volume, Relative Strength, 52-Week, Fundamentals, Sentiment, Risk-Reward
6. Ranks all passing stocks by composite rank score (ADX, R:R, volume, RS, fundamentals)
7. Outputs **only the #1 best stock** (top_n = 1)
8. Stop-loss = wider of 2.5× ATR or 3% below SMA50

## How It Works — Swing Screener

1. **Market regime check**: Same as weekly — blocked if market is weak
2. Same data fetch as weekly
3. Calculates 10 scoring factors with tunable weights (loaded from `algo_params` table)
4. **Hard gates**: ADX ≥ 22, volume + OBV check, risk-reward ≥ 2:1, min composite score 58
5. Composite score = weighted sum; top picks ranked
6. **Sector cap**: max 2 per industry, no duplicates from weekly picks
7. Only STRONG BUY and BUY signals output (WATCH eliminated)
8. Stop-loss = wider of 2.5× ATR or 3% below SMA50

## Self-Learning (backtester.py)

- Compares open picks against live prices → closes TARGET_HIT / STOP_LOSS / EXPIRED
- Analyses failure patterns: median RSI, ADX, volume, RS of losers vs winners
- **Pure-loss learning**: when win rate is 0%, tightens ADX, volume, 52W, RSI thresholds from loser data alone
- Adjusts params using learning rate 0.3, clamped to safe bounds
- Kicks in after **3 closed trades** (not 5)
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
- **Two paradigms**: Weekly = strict filters (1 best stock), Swing = composite scoring (top 10 with sector cap)
- **Market regime gate** — Both screeners check Nifty vs 20-SMA + India VIX before producing any picks
- **Self-tuning**: backtester.py auto-adjusts filter thresholds and scoring weights based on win/loss analysis
- **Pure-loss learning**: tightens all filters from loser data alone when win rate is 0%
- **ThreadPoolExecutor** for parallel screening (default 10 workers)
- **Wider stop-losses** — wider of 2.5× ATR or 3% below SMA50 (not tighter)
- **Sector cap**: max 2 swing picks per industry, no cross-screener duplicates
- **Target**: 15% for weekly, 10-20%+ for swing

## When User Asks To...

- "Run the screener" → `python weekly_stock_picker.py` for weekly, `python swing_breakout_screener.py` for swing
- "Check portfolio" → `python backtester.py` (checks both) or `--check-portfolio` flag on individual screeners
- "Improve the algorithm" → `python backtester.py` triggers auto-learning
- "Show performance" → `python backtester.py --report`
- "Add a new filter" → Edit the `FILTERS` dict in the relevant screener, add corresponding analysis in `backtester.py`
- "Change target %" → Edit `config.json` or `FILTERS` dict in the screener
- "Market blocked, force picks" → Don't. The regime gate exists for a reason. Wait for market to improve.

## Tech Stack

- Python 3.13, Windows
- No external DB required (SQLite built-in)
- No API keys needed (all free data sources)
