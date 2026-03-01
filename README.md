# Daily Stock Screener Automation

Indian stock market screener system that scans **Nifty 500** stocks to find high-probability buy candidates.  
Uses SQLite for all data, learns from past failures, and auto-improves over time.

---

## Quick Start

```bash
pip install -r requirements.txt

# Weekly picks (Monday morning, strict 8-filter checklist)
python weekly_stock_picker.py

# Swing picks (1-2 month horizon, 10-factor scoring)
python swing_breakout_screener.py

# Check portfolio & auto-learn from wins/losses
python backtester.py
```

---

## How It Works

## The Two Screeners

### `weekly_stock_picker.py` — Weekly (1-4 weeks)
- **Method**: Strict 8-filter checklist — ALL must pass
- **Filters**: Trend (SMA/MACD), Momentum (RSI 50-75 + ADX >20), Volume spike, Relative strength vs Nifty50, 52-week proximity, Fundamentals, News sentiment, Risk-reward ratio
- **Target**: 15% upside | **Stop-loss**: 7% below entry
- **Best run on**: Monday morning before market opens

### `swing_breakout_screener.py` — Swing (1-2 months)
- **Method**: Weighted 10-factor scoring, ranked by composite score
- **Factors**: Trend alignment, momentum, volume, Bollinger position, relative strength, consolidation breakout, fundamentals, sentiment, 52-week position, bulk deals
- **Target**: 10-20%+ | **Stop-loss**: ATR-based
- **Weights auto-tuned** from past performance via `backtester.py`

---

## Self-Learning System

### `backtester.py` — Auto-Improvement Engine
- Checks all open picks against live market prices
- Closes positions that hit target, stop-loss, or expiry
- **Analyses failure patterns**: compares technical profiles of losers vs winners
- **Auto-adjusts parameters** with learning rate 0.3, clamped to safe bounds
- Tuned parameters saved to SQLite and loaded on next screener run

```bash
python backtester.py                  # Full: check + learn
python backtester.py --check-only     # Just check positions
python backtester.py --learn-only     # Just learn from history
python backtester.py --report         # Detailed performance report
python backtester.py --reset          # Reset all tuned params to defaults
```

---

## CLI Reference

| Command | Description |
|---|---|
| `python weekly_stock_picker.py` | Full weekly scan |
| `python weekly_stock_picker.py --fast` | Skip fundamentals + sentiment |
| `python weekly_stock_picker.py --check-portfolio` | Check open weekly trades |
| `python swing_breakout_screener.py` | Full swing scan |
| `python swing_breakout_screener.py --fast` | Skip fundamentals + sentiment |
| `python swing_breakout_screener.py --check-portfolio` | Check open swing trades |
| `python backtester.py` | Check all open + learn from failures |
| `python backtester.py --report` | Full performance report |

---

## Architecture

```
weekly_stock_picker.py    ──┐
                            ├──► db.py ──► screener.db (SQLite)
swing_breakout_screener.py ──┤
                            │
backtester.py ──────────────┘
    ├── Checks open picks vs market
    ├── Records outcomes
    ├── Analyses failures
    └── Adjusts algo_params → loaded by screeners on next run
```

### SQLite Tables (`screener.db`)
- **picks** — Every pick with full technicals, entry/target/SL, status
- **trade_outcomes** — Backtest check results
- **algo_params** — Self-tuning parameters (auto-adjusted by backtester)
- **run_log** — Audit trail of every run

---

## Data Sources (all free, no API keys)
- **Nifty 500 list**: NSE archives CSV
- **Price data**: Yahoo Finance via `yfinance`
- **News sentiment**: Google News RSS → VADER
- **Fundamentals**: screener.in quarterly results
- **Bulk deals**: NSE bulk deals CSV

## How To Trade

1. **BUY** at the Entry Price on Monday after 9:30 AM (let first 15 min settle)
2. **SET STOP-LOSS** immediately at the Stop_Loss price
3. **HOLD** — don't panic-sell on small dips
4. **SELL** when the stock hits the Target price
5. If a stock goes up 10%+, trail your stop-loss to your entry price
6. Run `python backtester.py` weekly to check exits and learn
7. Max hold: 60 days (weekly) or 120 days (swing) — review if target not hit

## Config

Edit `config.json` to change defaults:
```json
{
  "screener_settings": {
    "top_n": 10,
    "min_price": 50,
    "parallel_workers": 10
  }
}
```

## Project Structure

```
weekly_stock_picker.py       # Monday morning picks (strict 8-filter checklist)
swing_breakout_screener.py   # 1-2 month swing trade picks (10-factor scoring)
backtester.py                # Auto-learning: checks picks, adjusts parameters
db.py                        # Shared SQLite database layer
config.json                  # User-editable configuration
requirements.txt             # Python dependencies
screener.db                  # Auto-generated SQLite database
monday_picks_*.csv           # Auto-generated weekly reports
swing_picks_*.csv            # Auto-generated swing reports
.github/copilot-instructions.md  # Copilot project memory
```

## Requirements

- Python 3.10+
- Internet connection (fetches live data from NSE, Yahoo Finance, screener.in, Google News)
- No external database (SQLite built-in)
- No API keys needed

## Disclaimer

No screener can guarantee 100% that a stock will go up. Stock markets carry inherent risk. This tool uses the strictest multi-factor filters to find high-probability setups, but some trades will still fail. **Always use the stop-loss.** Never invest money you can't afford to lose.