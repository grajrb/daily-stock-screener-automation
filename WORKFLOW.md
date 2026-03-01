# Stock Screener — Step-by-Step Workflow

## Weekly Routine

### 1. Sunday Evening — Run Both Screeners

```bash
# Full scan with fundamentals + sentiment (best accuracy, ~15 min each)
python weekly_stock_picker.py
python swing_breakout_screener.py
```

This gives you two lists:
- **Weekly picks** — strict 8-filter checklist, 1-4 week holds
- **Swing picks** — scored 10-factor ranking, 1-2 month holds

### 2. Monday 9:30-9:45 AM — Place Orders

- Wait 15 minutes after market open (let the noise settle)
- Buy at the **Entry Price** shown in the report
- **Immediately set stop-loss** at the SL price — never skip this
- Position size: max 10-15% of capital per stock, max 2% capital at risk per trade

### 3. Wednesday or Thursday — Mid-Week Check

```bash
python backtester.py --check-only
```

Checks all open positions (both weekly + swing) against live prices. If any hit target or stop-loss, they're auto-closed in the DB.

### 4. Friday Evening — Full Backtest + Learning

```bash
python backtester.py
```

This does two things:
- Checks all open positions
- **Runs the learning engine** — analyses closed trades, compares losers vs winners, and auto-adjusts parameters for next week

### 5. Monthly — Performance Review

```bash
python backtester.py --report
```

Shows win rate, avg returns, tuned parameters, recent failures, and run history.

---

## Key Rules for Maximum Benefit

| Rule | Why |
|------|-----|
| **Run backtester every Friday** | Learning only works with data — the more it runs, the smarter it gets |
| **Never remove your stop-loss** | The math works because wins (+15%) are bigger than losses (~5-7%) |
| **Use both screeners together** | Weekly = high conviction, fewer picks. Swing = more opportunities, scored ranking |
| **Prioritize "STRONG BUY" signals** | These passed the most factors with the highest scores |
| **Run `--fast` during the week** | Full scan on Sunday, quick checks mid-week |
| **Don't override the algorithm** | After 20+ trades, the backtester starts tuning filters based on YOUR actual results |

---

## The Self-Improvement Cycle

```
Week 1-4:   Screener uses default parameters
             ↓
Week 5+:    backtester.py has enough closed trades (5+)
             ↓  analyses: "losers had RSI > 72, winners had RSI 55-65"
             ↓  auto-adjusts: rsi_max from 75 → 70
             ↓
Week 6+:    Screeners load tuned params from DB
             ↓  picks are now filtered with learned thresholds
             ↓
             Win rate improves over time
```

The system needs **at least 5 closed trades** per screener before learning kicks in. After that, every `python backtester.py` run makes the next scan smarter.

---

## Quick Reference

| When | Command | Time |
|------|---------|------|
| Sunday evening | `python weekly_stock_picker.py` | ~15 min |
| Sunday evening | `python swing_breakout_screener.py` | ~15 min |
| Mid-week | `python backtester.py --check-only` | ~2 min |
| Friday evening | `python backtester.py` | ~2 min |
| Monthly | `python backtester.py --report` | instant |
| If algo acting weird | `python backtester.py --reset` | instant |

---

## What Each Script Does

### `weekly_stock_picker.py`
- Scans Nifty 500 through **8 strict filters** (ALL must pass)
- Filters: Trend, Momentum, Volume, Relative Strength, 52-Week, Fundamentals, Sentiment, Risk-Reward
- Target: **+15%** | Stop-loss: **~7% below entry**
- Best for: Short-term high-conviction trades

### `swing_breakout_screener.py`
- Scores Nifty 500 across **10 weighted factors**
- Factors: Trend, Momentum, Volume, Bollinger, Relative Strength, Consolidation, Fundamentals, Sentiment, 52W Proximity, Bulk Deals
- Target: **+10-20%** | Stop-loss: **ATR-based**
- Best for: Medium-term swing trades with bigger upside

### `backtester.py`
- Checks all open positions against live market prices
- Auto-closes positions that hit target, stop-loss, or expiry
- **Learns from failures**: compares technical profiles of losers vs winners
- Adjusts filter thresholds and scoring weights automatically
- Tuned parameters saved to SQLite, loaded on next screener run

### `db.py`
- Shared SQLite database layer (`screener.db`)
- Tables: `picks`, `trade_outcomes`, `algo_params`, `run_log`
- All picks, outcomes, and tuned parameters in one file

---

## Position Sizing Guide

| Capital | Per Trade (15%) | Risk Per Trade (2%) | Max Open Trades |
|---------|----------------|---------------------|-----------------|
| ₹1,00,000 | ₹15,000 | ₹2,000 | 6-7 |
| ₹5,00,000 | ₹75,000 | ₹10,000 | 6-7 |
| ₹10,00,000 | ₹1,50,000 | ₹20,000 | 6-7 |

**Never put more than 15% of total capital into a single stock.**

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| No stocks pass filters | Market conditions are weak — wait, don't lower filters |
| Too many picks | Use `--top 5` to limit |
| Slow scan | Use `--fast` to skip fundamentals + sentiment |
| Win rate dropping | Run `python backtester.py` to trigger learning |
| Algo feels off | `python backtester.py --reset` to go back to defaults |
| Want to see DB contents | Use any SQLite viewer on `screener.db` |
