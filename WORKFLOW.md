# Stock Screener — Step-by-Step Workflow

## Weekly Routine

### 1. Friday Evening — Run Backtester (Learn from This Week)

```bash
python backtester.py
```

This checks all open positions AND runs the learning engine. The system analyses closed trades (losers vs winners) and auto-adjusts filter thresholds and scoring weights for next week.

### 2. Sunday Evening — Run Both Screeners

```bash
# Full scan with fundamentals + sentiment (best accuracy, ~15 min each)
python weekly_stock_picker.py
python swing_breakout_screener.py
```

This gives you:
- **Weekly pick** — the single highest-conviction stock of the week (8-filter checklist, ALL must pass)
- **Swing picks** — top 10 scored/ranked picks (10-factor scoring, 1-2 month holds)

**Important**: Both screeners now check the **market regime first**. If Nifty 50 is below its 20-day SMA or India VIX > 20, the screener **will not produce any picks** — it's safer to sit out in a weak market.

### 3. Monday 9:30-9:45 AM — Place Orders

- Wait 15 minutes after market open (let the noise settle)
- Buy at the **Entry Price** shown in the report
- **Immediately set stop-loss** at the SL price — never skip this
- Position size: max 10-15% of capital per stock, max 2% capital at risk per trade

### 4. Wednesday or Thursday — Mid-Week Check

```bash
python backtester.py --check-only
```

Checks all open positions (both weekly + swing) against live prices. If any hit target or stop-loss, they're auto-closed in the DB.

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
| **Never remove your stop-loss** | The math works because wins (+15%) are bigger than losses (~5-8%) |
| **Respect the market regime gate** | If the screener says "BLOCKED", don't force trades — sit out |
| **Prioritize "STRONG BUY" signals** | These passed the most factors with the highest scores |
| **Weekly = 1 stock only** | Concentrate capital on the single best opportunity, don't dilute |
| **Run `--fast` during the week** | Full scan on Sunday, quick checks mid-week |
| **Don't override the algorithm** | After 3+ closed trades, the backtester starts tuning filters based on YOUR actual results |

---

## Safety Mechanisms (New)

| Mechanism | What It Does |
|-----------|--------------|
| **Market regime gate** | Blocks ALL picks if Nifty 50 < 20-SMA or India VIX > 20 |
| **Sector cap** | Max 2 swing picks per sector — prevents correlated blowups |
| **No cross-screener duplicates** | Same stock won't appear in both weekly and swing picks |
| **Volume hard gate (swing)** | Rejects stocks with low volume AND falling OBV |
| **ADX hard gate** | Weekly: ADX ≥ 25, Swing: ADX ≥ 22 — only real trends pass |
| **R:R hard gate (swing)** | Rejects setups with risk-reward < 2:1 |
| **Wider stop-losses** | 2.5× ATR or 3% below SMA50 (the wider one), giving room to breathe |
| **Pure-loss learning** | Backtester tightens filters even when win rate is 0% |

---

## The Self-Improvement Cycle

```
Week 1-2:   Screener uses default parameters
             ↓
Week 3+:    backtester.py has enough closed trades (3+)
             ↓  analyses: "losers had RSI > 72, winners had RSI 55-65"
             ↓  auto-adjusts: rsi_max from 75 → 70
             ↓  (if 0% wins: tightens ADX, volume, 52W from loser data alone)
             ↓
Week 4+:    Screeners load tuned params from DB
             ↓  picks are now filtered with learned thresholds
             ↓
             Win rate improves over time
```

The system needs **at least 3 closed trades** per screener before learning kicks in. After that, every `python backtester.py` run makes the next scan smarter.

---

## Quick Reference

| When | Command | Time |
|------|---------|------|
| Friday evening | `python backtester.py` | ~2 min |
| Sunday evening | `python weekly_stock_picker.py` | ~15 min |
| Sunday evening | `python swing_breakout_screener.py` | ~15 min |
| Mid-week | `python backtester.py --check-only` | ~2 min |
| Monthly | `python backtester.py --report` | instant |
| If algo acting weird | `python backtester.py --reset` | instant |

---

## What Each Script Does

### `weekly_stock_picker.py`
- Checks market regime first (Nifty vs 20-SMA, India VIX) — **blocks picks if market is weak**
- Scans Nifty 500 through **8 strict filters** (ALL must pass)
- Filters: Trend, Momentum (RSI 50-75, ADX ≥ 25), Volume (1.3x+ spike), Relative Strength, 52-Week, Fundamentals, Sentiment, Risk-Reward
- Ranks all passing stocks and outputs **only the #1 best pick**
- Target: **+15%** | Stop-loss: **wider of 2.5× ATR or 3% below SMA50**
- Best for: Concentrated high-conviction weekly trade

### `swing_breakout_screener.py`
- Checks market regime first — **blocks picks if market is weak**
- Scores Nifty 500 across **10 weighted factors**
- Factors: Trend, Momentum, Volume, Bollinger, Relative Strength, Consolidation, Fundamentals, Sentiment, 52W Proximity, Bulk Deals
- **Hard gates**: ADX ≥ 22, volume+OBV check, risk-reward ≥ 2:1, min composite score 58
- **Sector cap**: max 2 picks per industry — no correlated blowups
- **No duplicates**: skips stocks already in weekly picks
- Only outputs **STRONG BUY** and **BUY** signals (no WATCH)
- Target: **+10-20%** | Stop-loss: **wider of 2.5× ATR or 3% below SMA50**
- Best for: Medium-term swing trades with bigger upside

### `backtester.py`
- Checks all open positions against live market prices
- Auto-closes positions that hit target, stop-loss, or expiry
- **Learns from failures**: compares technical profiles of losers vs winners
- **Pure-loss learning**: when win rate is 0%, tightens all filter thresholds from loser data alone
- Adjusts filter thresholds and scoring weights automatically (learning rate 0.3)
- Kicks in after **3+ closed trades** (previously 5)
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
