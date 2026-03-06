"""
swing_breakout_screener.py — Swing-Trade Screener (1-2 Month Horizon)
======================================================================
Multi-factor weighted scoring system that finds stocks with 10-20%+
upside potential over 1-2 months.

Unlike weekly_stock_picker.py (strict checklist), this uses a SCORING
approach — more stocks pass, ranked by composite score.

Run anytime. Best on weekends for the following week.

Usage:
    python swing_breakout_screener.py                  # Full scan
    python swing_breakout_screener.py --fast            # Skip fundamentals
    python swing_breakout_screener.py --top 20          # Top 20 stocks
    python swing_breakout_screener.py --check-portfolio # Check open swing trades

All picks are stored in SQLite (screener.db) and backtested automatically.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from tabulate import tabulate

import db

warnings.filterwarnings("ignore")

try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    _VADER = True
except ImportError:
    _VADER = False

try:
    from bs4 import BeautifulSoup
    _BS4 = True
except ImportError:
    _BS4 = False

try:
    import feedparser
    _FEED = True
except ImportError:
    _FEED = False

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

# Default scoring weights — these get auto-tuned by the backtester
DEFAULT_WEIGHTS = {
    "w_trend": 2.0,
    "w_momentum": 2.0,
    "w_volume": 1.8,
    "w_bollinger": 1.2,
    "w_rel_strength": 1.5,
    "w_consolidation": 1.3,
    "w_fundamentals": 1.5,
    "w_sentiment": 1.0,
    "w_52w_proximity": 0.8,
    "w_bulk_deals": 0.6,
}

DEFAULT_FILTERS = {
    "min_price": 50,
    "max_price": 50000,
    "min_avg_volume_20d": 100_000,
    "min_avg_traded_value_20d": 5_000_000,
    "rsi_low": 45,
    "rsi_high": 75,
    "min_adx": 22,
    "volume_spike_threshold": 1.2,
    "sma_50_rising_days": 10,
    "bollinger_squeeze_pctile": 25,
    "consolidation_range_pct": 8,
    "pct_from_52w_high_max": 15,
    "min_composite_score": 58,
    "parallel_workers": 10,
    "top_n": 10,
    "max_per_sector": 2,
}


def load_tuned_params(conn) -> Tuple[dict, dict]:
    """Load algo params from DB, falling back to defaults."""
    weights = dict(DEFAULT_WEIGHTS)
    filters = dict(DEFAULT_FILTERS)
    tuned = db.get_all_algo_params(conn, "swing")
    for k, v in tuned.items():
        if k in weights:
            weights[k] = v
        elif k in filters:
            filters[k] = v
    return weights, filters


# ─── DATA FETCHING ────────────────────────────────────────────────────────────

def get_nifty500_symbols() -> Tuple[List[str], Dict[str, str]]:
    """Returns (symbol_list, {symbol: industry}) from NSE CSV."""
    print("[1/7] Fetching Nifty 500 constituents...")
    for url in [
        "https://archives.nseindia.com/content/indices/ind_nifty500list.csv",
        "https://www1.nseindia.com/content/indices/ind_nifty500list.csv",
    ]:
        try:
            df = pd.read_csv(url, timeout=15)
            symbols = df["Symbol"].tolist()
            sector_map = {}
            if "Industry" in df.columns:
                sector_map = dict(zip(df["Symbol"], df["Industry"]))
            print(f"     {len(symbols)} stocks loaded")
            return symbols, sector_map
        except Exception:
            continue
    print("     [WARN] Using Nifty 50 fallback")
    return [
        "RELIANCE","TCS","HDFCBANK","INFY","ICICIBANK","HINDUNILVR","ITC",
        "SBIN","BHARTIARTL","KOTAKBANK","LT","AXISBANK","ASIANPAINT","MARUTI",
        "BAJFINANCE","TITAN","SUNPHARMA","HCLTECH","NTPC","TATAMOTORS",
        "ULTRACEMCO","WIPRO","POWERGRID","NESTLEIND","ONGC","JSWSTEEL",
        "TATASTEEL","ADANIENT","ADANIPORTS","BAJAJFINSV","COALINDIA","GRASIM",
        "TECHM","CIPLA","DRREDDY","BPCL","DIVISLAB","APOLLOHOSP","EICHERMOT",
        "HEROMOTOCO","TATACONSUM","BRITANNIA","SBILIFE","HDFCLIFE","M&M",
        "INDUSINDBK","HINDALCO","UPL","BAJAJ-AUTO","LTIM",
    ], {}


def get_nifty50_history(period="1y") -> pd.DataFrame:
    print("[2/7] Fetching Nifty 50 benchmark...")
    try:
        hist = yf.Ticker("^NSEI").history(period=period)
        if hist.empty:
            raise ValueError
        print(f"     {len(hist)} days loaded")
        return hist
    except Exception:
        print("     [WARN] Nifty 50 fetch failed")
        return pd.DataFrame()


def fetch_bulk_deals() -> Dict[str, int]:
    print("[3/7] Fetching bulk/block deals...")
    deals = {}
    if not _BS4:
        print("     [SKIP] bs4 not installed")
        return deals
    try:
        resp = requests.get(
            "https://archives.nseindia.com/content/equities/bulk.csv",
            headers=HEADERS, timeout=15
        )
        if resp.status_code == 200:
            from io import StringIO
            df = pd.read_csv(StringIO(resp.text))
            if "Symbol" in df.columns:
                deals = df["Symbol"].value_counts().to_dict()
                print(f"     {len(deals)} symbols with deals")
    except Exception as e:
        print(f"     [WARN] {e}")
    return deals


def fetch_news_sentiment(symbol: str) -> float:
    if not _VADER or not _FEED:
        return 0.0
    try:
        url = f"https://news.google.com/rss/search?q={symbol}+NSE+stock&hl=en-IN&gl=IN&ceid=IN:en"
        feed = feedparser.parse(url)
        if not feed.entries:
            return 0.0
        analyzer = SentimentIntensityAnalyzer()
        scores = [analyzer.polarity_scores(e.get("title", ""))["compound"] for e in feed.entries[:5]]
        return sum(scores) / len(scores) if scores else 0.0
    except Exception:
        return 0.0


def scrape_fundamentals(symbol: str) -> Dict[str, Optional[float]]:
    result = {"rev_growth": None, "profit_growth": None}
    if not _BS4:
        return result
    try:
        for suffix in ["/consolidated/", "/"]:
            url = f"https://www.screener.in/company/{symbol}{suffix}"
            resp = requests.get(url, headers=HEADERS, timeout=12)
            if resp.status_code == 200:
                break
        else:
            return result
        soup = BeautifulSoup(resp.text, "lxml")
        quarters = None
        for sec in soup.find_all("section"):
            h2 = sec.find("h2")
            if h2 and "quarter" in h2.get_text(strip=True).lower():
                quarters = sec
                break
        if not quarters:
            return result
        table = quarters.find("table")
        if not table:
            return result
        rows = table.find_all("tr")
        if len(rows) < 2 or len([th.get_text(strip=True) for th in rows[0].find_all("th")]) < 6:
            return result

        def _parse(label):
            for tr in rows[1:]:
                first = tr.find("td") or tr.find("th")
                if first and label in first.get_text(strip=True).lower():
                    vals = []
                    for c in tr.find_all("td"):
                        txt = c.get_text(strip=True).replace(",", "")
                        try: vals.append(float(txt))
                        except ValueError: vals.append(None)
                    return vals
            return []

        def _yoy(vals):
            if len(vals) >= 5 and vals[-1] is not None and vals[-5] is not None and vals[-5] != 0:
                return ((vals[-1] - vals[-5]) / abs(vals[-5])) * 100
            return None

        rev = _parse("sales") or _parse("revenue")
        profit = _parse("net profit") or _parse("profit")
        result["rev_growth"] = _yoy(rev)
        result["profit_growth"] = _yoy(profit)
    except Exception:
        pass
    return result


# ─── TECHNICAL INDICATORS ─────────────────────────────────────────────────────

def compute_rsi(s, period=14):
    d = s.diff()
    g = d.where(d > 0, 0.0).ewm(com=period-1, adjust=False).mean()
    l = (-d.where(d < 0, 0.0)).ewm(com=period-1, adjust=False).mean()
    return 100 - (100 / (1 + g / l.replace(0, np.nan)))

def compute_macd(s):
    e12 = s.ewm(span=12, adjust=False).mean()
    e26 = s.ewm(span=26, adjust=False).mean()
    line = e12 - e26
    sig = line.ewm(span=9, adjust=False).mean()
    return line, sig, line - sig

def compute_adx(h, l, c, period=14):
    pdm = h.diff(); mdm = -l.diff()
    pdm = pdm.where((pdm > mdm) & (pdm > 0), 0.0)
    mdm = mdm.where((mdm > pdm) & (mdm > 0), 0.0)
    tr = pd.concat([h-l, (h-c.shift(1)).abs(), (l-c.shift(1)).abs()], axis=1).max(axis=1)
    atr = tr.ewm(span=period, adjust=False).mean()
    pdi = 100 * (pdm.ewm(span=period, adjust=False).mean() / atr)
    mdi = 100 * (mdm.ewm(span=period, adjust=False).mean() / atr)
    dx = 100 * ((pdi - mdi).abs() / (pdi + mdi + 1e-10))
    return dx.ewm(span=period, adjust=False).mean()

def compute_atr(h, l, c, period=14):
    tr = pd.concat([h-l, (h-c.shift(1)).abs(), (l-c.shift(1)).abs()], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()

def compute_bollinger(c, period=20, mult=2.0):
    sma = c.rolling(period).mean()
    std = c.rolling(period).std()
    return sma + mult*std, sma - mult*std, (2*mult*std/sma*100)


# ─── STOCK ANALYSIS (scoring-based) ──────────────────────────────────────────

def analyze_stock(symbol, weights, filters, nifty_hist, bulk_deals, skip_fund=False):
    """Analyze one stock with weighted multi-factor scoring. Returns dict or None."""
    try:
        hist = yf.Ticker(f"{symbol}.NS").history(period="1y")
    except Exception:
        return None
    if hist is None or len(hist) < 201:
        return None

    c = hist["Close"]; h = hist["High"]; l = hist["Low"]; v = hist["Volume"]
    latest = hist.iloc[-1]
    price = float(latest["Close"])

    if price < filters["min_price"] or price > filters["max_price"]:
        return None
    avg_vol = float(v.tail(20).mean())
    if avg_vol < filters["min_avg_volume_20d"]:
        return None
    if avg_vol * price < filters["min_avg_traded_value_20d"]:
        return None

    # SMAs
    sma20 = float(c.rolling(20).mean().iloc[-1])
    sma50_s = c.rolling(50).mean()
    sma50 = float(sma50_s.iloc[-1])
    sma150 = float(c.rolling(150).mean().iloc[-1])
    sma200_s = c.rolling(200).mean()
    sma200 = float(sma200_s.iloc[-1])

    # Hard filter: must be above both SMAs
    if not (price > sma50 and price > sma200):
        return None

    # ── TREND SCORE ───────────────────────────────────────────────────
    trend = 0.0
    if price > sma50: trend += 1.0
    if price > sma200: trend += 1.0
    if sma50 > sma200: trend += 1.0
    sma50_rising = sma50_s.iloc[-1] > sma50_s.iloc[-filters["sma_50_rising_days"]]
    sma200_rising = sma200_s.iloc[-1] > sma200_s.iloc[-10]
    if sma50_rising: trend += 0.5
    if sma200_rising: trend += 0.5
    if price > sma150 > sma200 and sma50 > sma150: trend += 1.0
    trend_score = min(trend / 5.0, 1.0)

    # ── MOMENTUM SCORE ────────────────────────────────────────────────
    rsi_val = float(compute_rsi(c).iloc[-1])
    ml, ms, mh = compute_macd(c)
    macd_bull = bool(ml.iloc[-1] > ms.iloc[-1])
    macd_cross = False
    for i in range(-5, 0):
        if ml.iloc[i-1] < ms.iloc[i-1] and ml.iloc[i] > ms.iloc[i]:
            macd_cross = True; break
    adx_val = float(compute_adx(h, l, c).iloc[-1])

    mom = 0.0
    if filters["rsi_low"] <= rsi_val <= filters["rsi_high"]: mom += 1.0
    if macd_bull: mom += 1.0
    if mh.iloc[-1] > 0: mom += 0.5
    if macd_cross: mom += 1.0
    if adx_val >= filters["min_adx"]: mom += 0.5
    momentum_score = min(mom / 4.0, 1.0)

    # ── VOLUME SCORE ──────────────────────────────────────────────────
    vol_spike = float(latest["Volume"] / avg_vol) if avg_vol > 0 else 0
    obv = (v * ((c.diff() > 0).astype(int) * 2 - 1)).cumsum()
    obv_rising = bool(obv.iloc[-1] > obv.iloc[-20])

    vol_sc = 0.0
    if vol_spike >= filters["volume_spike_threshold"]: vol_sc += 1.0
    vol3 = float(v.tail(3).mean()); vol10 = float(v.tail(10).mean())
    if vol10 > 0 and vol3/vol10 > 1.2: vol_sc += 0.5
    if obv_rising: vol_sc += 0.5
    volume_score = min(vol_sc / 2.0, 1.0)

    # Hard gate: reject if volume spike below threshold AND OBV not rising
    if vol_spike < filters["volume_spike_threshold"] and not obv_rising:
        return None

    # Hard gate: ADX must show a real trend
    if adx_val < filters["min_adx"]:
        return None

    # ── BOLLINGER SCORE ───────────────────────────────────────────────
    upper, lower, bw = compute_bollinger(c)
    bb_bw = float(bw.iloc[-1])
    bw_vals = bw.dropna().values
    bb_pctile = float((bw_vals < bb_bw).sum() / len(bw_vals) * 100) if len(bw_vals) > 20 else 50
    bb_squeeze = bb_pctile <= filters["bollinger_squeeze_pctile"]
    near_upper = price >= float(upper.iloc[-1]) * 0.98

    boll = 0.0
    if bb_squeeze: boll += 1.0
    if bb_squeeze and near_upper: boll += 0.5
    bollinger_score = min(boll / 1.5, 1.0)

    # ── RELATIVE STRENGTH SCORE ───────────────────────────────────────
    rs1m = rs3m = 0.0
    if not nifty_hist.empty and len(c) >= 63:
        st1m = float((c.iloc[-1]/c.iloc[-21]-1)*100)
        st3m = float((c.iloc[-1]/c.iloc[-63]-1)*100)
        nc = nifty_hist["Close"]
        n1m = float((nc.iloc[-1]/nc.iloc[-21]-1)*100) if len(nc) >= 21 else 0
        n3m = float((nc.iloc[-1]/nc.iloc[-63]-1)*100) if len(nc) >= 63 else 0
        rs1m = st1m - n1m; rs3m = st3m - n3m

    rs_sc = 0.0
    if rs1m > 0: rs_sc += 0.5
    if rs3m > 0: rs_sc += 0.5
    if rs1m > 5: rs_sc += 0.5
    if rs3m > 10: rs_sc += 0.5
    rel_strength_score = min(rs_sc / 2.0, 1.0)

    # ── CONSOLIDATION SCORE ───────────────────────────────────────────
    r20 = hist.tail(20)
    rng_hi = float(r20["High"].max()); rng_lo = float(r20["Low"].min())
    rng_pct = (rng_hi - rng_lo) / rng_lo * 100 if rng_lo > 0 else 100
    tight = rng_pct <= filters["consolidation_range_pct"]
    near_hi = price >= rng_hi * 0.97

    cons = 0.0
    if tight: cons += 1.0
    if near_hi: cons += 0.5
    if tight and near_hi and vol_spike > 1.2: cons += 0.5
    consolidation_score = min(cons / 2.0, 1.0)

    # ── FUNDAMENTALS SCORE ────────────────────────────────────────────
    rev_gr = profit_gr = None
    if not skip_fund:
        fund = scrape_fundamentals(symbol)
        rev_gr = fund["rev_growth"]; profit_gr = fund["profit_growth"]
    fund_sc = 0.0
    if rev_gr is not None and rev_gr >= 10: fund_sc += 0.5
    if profit_gr is not None and profit_gr >= 10: fund_sc += 0.5
    if rev_gr is not None and rev_gr >= 25: fund_sc += 0.25
    if profit_gr is not None and profit_gr >= 25: fund_sc += 0.25
    fundamental_score = min(fund_sc / 1.5, 1.0)

    # ── SENTIMENT SCORE ───────────────────────────────────────────────
    sentiment = fetch_news_sentiment(symbol)
    sent_sc = 0.0
    if sentiment > 0.15: sent_sc = 1.0
    elif sentiment > 0.05: sent_sc = 0.5
    elif sentiment < -0.15: sent_sc = -0.3
    sentiment_score = max(0.0, min(sent_sc, 1.0))

    # ── 52W PROXIMITY SCORE ───────────────────────────────────────────
    hi52 = float(h.max()); lo52 = float(l.min())
    from_hi = (hi52 - price) / hi52 * 100 if hi52 > 0 else 100
    from_lo = (price - lo52) / lo52 * 100 if lo52 > 0 else 0

    prox = 0.0
    if from_hi <= filters["pct_from_52w_high_max"]: prox += 0.5
    if from_hi <= 5: prox += 0.5
    if from_lo > 30: prox += 0.25
    proximity_score = min(prox / 1.25, 1.0)

    # ── BULK DEALS SCORE ──────────────────────────────────────────────
    deal_count = bulk_deals.get(symbol, 0)
    bulk_score = 1.0 if deal_count >= 3 else (0.5 if deal_count >= 1 else 0.0)

    # ── COMPOSITE SCORE ───────────────────────────────────────────────
    raw = (
        trend_score * weights["w_trend"]
        + momentum_score * weights["w_momentum"]
        + volume_score * weights["w_volume"]
        + bollinger_score * weights["w_bollinger"]
        + rel_strength_score * weights["w_rel_strength"]
        + consolidation_score * weights["w_consolidation"]
        + fundamental_score * weights["w_fundamentals"]
        + sentiment_score * weights["w_sentiment"]
        + proximity_score * weights["w_52w_proximity"]
        + bulk_score * weights["w_bulk_deals"]
    )
    max_w = sum(weights.values())
    composite = (raw / max_w) * 100 if max_w > 0 else 0

    if composite < filters["min_composite_score"]:
        return None

    # ── TRADE LEVELS ──────────────────────────────────────────────────
    atr14 = float(compute_atr(h, l, c, 14).iloc[-1])
    entry = round(price, 2)
    t1 = round(price * 1.10, 2)
    t2 = round(price * 1.15, 2)
    t3 = round(price * 1.20, 2)
    sl_atr = price - 2.5 * atr14
    sl_sma = sma50 * 0.97
    sl = round(min(sl_atr, sl_sma), 2)
    risk = entry - sl
    rr = round((t2 - entry) / risk, 2) if risk > 0 else 0.0
    risk_pct = round((1 - sl / price) * 100, 1)

    # Hard gate: risk-reward must be at least 2:1
    if rr < 2.0:
        return None

    # ── SIGNAL ────────────────────────────────────────────────────────
    strong = sum([trend_score >= 0.8, momentum_score >= 0.6, volume_score >= 0.5, rs1m > 3, rr >= 2.0])
    if composite >= 65 and strong >= 4: signal = "STRONG BUY"
    elif composite >= 55 and strong >= 3: signal = "BUY"
    else: signal = "AVOID"

    reasons = []
    if trend_score >= 0.8: reasons.append("Stage-2 uptrend")
    if macd_bull: reasons.append("MACD bullish")
    if macd_cross: reasons.append("Fresh MACD cross")
    if bb_squeeze: reasons.append("BB squeeze")
    if vol_spike >= 1.5: reasons.append(f"Vol {vol_spike:.1f}x")
    if tight and near_hi: reasons.append("Breakout from base")
    if rs1m > 5: reasons.append(f"RS +{rs1m:.1f}%")
    if rev_gr and rev_gr > 15: reasons.append(f"Rev +{rev_gr:.0f}%")
    if profit_gr and profit_gr > 15: reasons.append(f"Profit +{profit_gr:.0f}%")
    if sentiment > 0.15: reasons.append("Positive news")
    if from_hi < 5: reasons.append("Near 52W high")
    if deal_count > 0: reasons.append(f"{deal_count} bulk deal(s)")

    return {
        "ticker": symbol, "last_close": price, "entry": entry,
        "target_10": t1, "target_15": t2, "target_20": t3,
        "stop_loss": sl, "upside_pct": 15.0, "risk_pct": risk_pct,
        "risk_reward": rr, "composite_score": round(composite, 1),
        "confidence": signal,
        "rsi": round(rsi_val, 1), "adx": round(adx_val, 1),
        "macd_bullish": 1 if macd_bull else 0,
        "vol_spike": round(vol_spike, 2),
        "rel_str_1m": round(rs1m, 1), "rel_str_3m": round(rs3m, 1),
        "pct_from_52w_hi": round(from_hi, 1),
        "rev_growth": rev_gr, "profit_growth": profit_gr,
        "news_sentiment": round(sentiment, 3),
        "trend_sc": round(trend_score, 2), "mom_sc": round(momentum_score, 2),
        "vol_sc": round(volume_score, 2), "boll_sc": round(bollinger_score, 2),
        "rs_sc": round(rel_strength_score, 2), "cons_sc": round(consolidation_score, 2),
        "fund_sc": round(fundamental_score, 2), "sent_sc": round(sentiment_score, 2),
        "prox_sc": round(proximity_score, 2), "bulk_sc": round(bulk_score, 2),
        "rationale": " | ".join(reasons) if reasons else "Moderate setup",
    }


# ─── PARALLEL RUNNER ──────────────────────────────────────────────────────────

def run_screening(symbols, weights, filters, nifty_hist, bulk_deals, skip_fund=False):
    results = []
    total = len(symbols); done = 0; errors = 0
    print(f"\n[5/7] Screening {total} stocks (scoring mode)...\n")

    def _task(sym):
        return analyze_stock(sym, weights, filters, nifty_hist, bulk_deals, skip_fund)

    with ThreadPoolExecutor(max_workers=filters["parallel_workers"]) as pool:
        futures = {pool.submit(_task, s): s for s in symbols}
        for fut in as_completed(futures):
            done += 1
            try:
                r = fut.result()
                if r: results.append(r)
            except Exception:
                errors += 1
            if done % 25 == 0 or done == total:
                print(f"     [{done}/{total}] Passed: {len(results)} | Errors: {errors}", end="\r")

    print(f"\n\n     {len(results)} candidates from {total} stocks\n")
    return results


# ─── SAVE TO DB ───────────────────────────────────────────────────────────────

def save_picks_to_db(conn, results, top_n, sector_map, max_per_sector=2):
    """Save top picks to SQLite, enforcing sector cap and skipping weekly duplicates."""
    results.sort(key=lambda x: x["composite_score"], reverse=True)
    today = datetime.now().strftime("%Y-%m-%d")

    # Get tickers already picked by weekly screener today
    weekly_today = {r["ticker"] for r in db.get_open_picks(conn, "weekly")}

    sector_counts = {}  # industry -> count
    top = []
    for r in results:
        if len(top) >= top_n:
            break
        # Skip if already in weekly picks
        if r["ticker"] in weekly_today:
            continue
        # Skip AVOID signals
        if r.get("confidence") == "AVOID":
            continue
        # Enforce sector cap
        sector = sector_map.get(r["ticker"], "Unknown")
        if sector_counts.get(sector, 0) >= max_per_sector:
            continue
        sector_counts[sector] = sector_counts.get(sector, 0) + 1
        top.append(r)

    count = 0
    for r in top:
        row_id = db.insert_pick(conn, {
            "run_date": today, "screener_type": "swing",
            "ticker": r["ticker"], "last_close": r["last_close"],
            "entry_price": r["entry"], "target": r["target_15"],
            "stop_loss": r["stop_loss"], "upside_pct": r["upside_pct"],
            "risk_pct": r["risk_pct"], "risk_reward": r["risk_reward"],
            "confidence": r["confidence"], "rsi": r["rsi"], "adx": r["adx"],
            "macd_bullish": r["macd_bullish"], "vol_spike": r["vol_spike"],
            "rel_str_1m": r["rel_str_1m"], "rel_str_3m": r["rel_str_3m"],
            "pct_from_52w_hi": r["pct_from_52w_hi"],
            "rev_growth": r["rev_growth"], "profit_growth": r["profit_growth"],
            "news_sentiment": r["news_sentiment"],
            "composite_score": r["composite_score"],
            "rationale": r["rationale"], "filters_json": json.dumps(r),
        })
        if row_id: count += 1
    print(f"     {count} new picks saved to database")
    return top


def check_portfolio(conn):
    """Check open swing trades for exit signals."""
    open_picks = db.get_open_picks(conn, "swing")
    if not open_picks:
        print("No open swing trades.")
        return

    print(f"\n{'='*80}")
    print(f"  SWING PORTFOLIO CHECK — {datetime.now().strftime('%Y-%m-%d')}")
    print(f"  Open trades: {len(open_picks)}")
    print(f"{'='*80}\n")

    rows = []
    for p in open_picks:
        try:
            hist = yf.Ticker(f"{p['ticker']}.NS").history(period="5d")
            if hist.empty: continue
            current = float(hist["Close"].iloc[-1])
            entry = p["entry_price"]; target = p["target"]; sl = p["stop_loss"]
            pnl = (current / entry - 1) * 100
            days = (datetime.now() - datetime.strptime(p["run_date"], "%Y-%m-%d")).days

            # Track max/min since entry for detailed outcome logging
            try:
                full_hist = yf.Ticker(f"{p['ticker']}.NS").history(start=p["run_date"])
                max_price = float(full_hist["High"].max()) if not full_hist.empty else current
                min_price = float(full_hist["Low"].min()) if not full_hist.empty else current
            except Exception:
                max_price, min_price = current, current

            action = "HOLD"
            status = None
            if current >= target:
                action = "SELL (TARGET HIT)"; status = "TARGET_HIT"
            elif current <= sl:
                action = "SELL (STOP-LOSS)"; status = "STOP_LOSS"
            elif days > 120:
                action = "REVIEW (>120 days)"; status = "EXPIRED"
            elif pnl > 10:
                action = f"HOLD (trail SL to {entry:.2f})"

            if status:
                db.close_pick(conn, p["id"], status, current,
                              datetime.now().strftime("%Y-%m-%d"), round(pnl, 2), days)
                db.insert_outcome(conn, {
                    "pick_id": p["id"], "check_date": datetime.now().strftime("%Y-%m-%d"),
                    "current_price": current, "pnl_pct": round(pnl, 2),
                    "hit_target": 1 if status == "TARGET_HIT" else 0,
                    "hit_stop_loss": 1 if status == "STOP_LOSS" else 0,
                    "max_price_since": max_price, "min_price_since": min_price,
                    "action_taken": action,
                })

            rows.append({
                "Ticker": p["ticker"], "Entry": entry, "Current": round(current, 2),
                "Target": target, "SL": sl, "P&L_%": f"{pnl:+.1f}%",
                "Days": days, "Action": action,
            })
        except Exception:
            rows.append({"Ticker": p["ticker"], "Action": "ERROR"})

    if rows:
        print(tabulate(pd.DataFrame(rows), headers="keys", tablefmt="grid", showindex=False))

    stats = db.get_performance_stats(conn, "swing")
    if stats["total"] > 0:
        print(f"\n--- Swing Performance ---")
        print(f"Total: {stats['total']} | Wins: {stats['wins']} | Losses: {stats['losses']} | "
              f"Win Rate: {stats['win_rate']:.0f}%")
    print()


# ─── DISPLAY ──────────────────────────────────────────────────────────────────

def display_results(top_picks, conn):
    date_str = datetime.now().strftime("%Y-%m-%d")
    csv_path = f"swing_picks_{date_str}.csv"

    rows = []
    for r in top_picks:
        rows.append({
            "Ticker": r["ticker"], "Signal": r["confidence"],
            "Score": r["composite_score"], "Close": r["last_close"],
            "Entry": r["entry"], "Target_10%": r["target_10"],
            "Target_15%": r["target_15"], "Target_20%": r["target_20"],
            "Stop_Loss": r["stop_loss"], "R:R": r["risk_reward"],
            "RSI": r["rsi"], "ADX": r["adx"], "Vol": f"{r['vol_spike']}x",
            "RS_1M": f"{r['rel_str_1m']:+.1f}%",
            "From_52W_Hi": f"{r['pct_from_52w_hi']:.1f}%",
            "Rev_Gr": f"{r['rev_growth']:.0f}%" if r["rev_growth"] else "N/A",
            "Profit_Gr": f"{r['profit_growth']:.0f}%" if r["profit_growth"] else "N/A",
            "Rationale": r["rationale"],
        })
    df = pd.DataFrame(rows)
    df.to_csv(csv_path, index=False)

    print(f"\n{'='*100}")
    print(f"  SWING-TRADE PICKS — {date_str} (1-2 Month Horizon)")
    print(f"{'='*100}\n")

    display = ["Ticker", "Signal", "Score", "Close", "Target_15%", "Stop_Loss", "R:R", "Rationale"]
    print(tabulate(df[display], headers="keys", tablefmt="grid", showindex=False))

    stats = db.get_performance_stats(conn, "swing")
    if stats["total"] > 0:
        print(f"\n--- Historical: {stats['total']} trades | Win Rate: {stats['win_rate']:.0f}% ---")

    print(f"\n  Saved: {csv_path} + screener.db")
    print(f"  Check trades: python swing_breakout_screener.py --check-portfolio\n")


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Swing-Trade Screener (1-2 month horizon, 10-20% upside)")
    parser.add_argument("--fast", action="store_true", help="Skip fundamental scraping")
    parser.add_argument("--top", type=int, default=None)
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--check-portfolio", action="store_true")
    args = parser.parse_args()

    conn = db.get_conn()

    if args.check_portfolio:
        check_portfolio(conn)
        conn.close()
        return

    print("\n" + "="*70)
    print("  SWING-TRADE BREAKOUT SCREENER (1-2 Month Horizon)")
    print("  Target: 10-20% upside | Scoring-based ranking")
    print("="*70 + "\n")

    weights, filters = load_tuned_params(conn)
    if args.top: filters["top_n"] = args.top
    if args.workers: filters["parallel_workers"] = args.workers

    symbols, sector_map = get_nifty500_symbols()
    if not symbols: sys.exit(1)

    nifty_hist = get_nifty50_history()
    bulk_deals = fetch_bulk_deals()

    print("[4/7] Market regime check...")
    regime_ok = True
    regime_reason = ""
    try:
        nifty_close = nifty_hist["Close"]
        sma20 = float(nifty_close.rolling(20).mean().iloc[-1])
        current_nifty = float(nifty_close.iloc[-1])
        if current_nifty <= sma20:
            regime_ok = False
            regime_reason = (f"Nifty 50 ({current_nifty:.0f}) below 20-SMA ({sma20:.0f})")
        print(f"     Nifty 50: {current_nifty:.0f} | 20-SMA: {sma20:.0f} | "
              f"{'ABOVE (OK)' if current_nifty > sma20 else 'BELOW (BLOCKED)'}")
    except Exception:
        print("     [WARN] Could not check Nifty regime")
    try:
        india_vix = yf.Ticker("^INDIAVIX").history(period="5d")
        if not india_vix.empty:
            vix_val = float(india_vix["Close"].iloc[-1])
            print(f"     India VIX: {vix_val:.1f}")
            if vix_val > 20:
                regime_ok = False
                regime_reason += f" | India VIX ({vix_val:.1f}) > 20"
    except Exception:
        pass
    try:
        sp = yf.Ticker("^GSPC").history(period="5d")
        print(f"     S&P 500: {float(sp['Close'].pct_change().iloc[-1]*100):+.2f}%")
    except Exception:
        pass

    if not regime_ok:
        print(f"\n  MARKET REGIME BLOCKED: {regime_reason}")
        print("  Sitting out \u2014 capital preservation > chasing picks.\n")
        db.log_run(conn, "swing", len(symbols), 0, None, filters, notes=f"BLOCKED: {regime_reason}")
        conn.close()
        sys.exit(0)

    results = run_screening(symbols, weights, filters, nifty_hist, bulk_deals, skip_fund=args.fast)
    if not results:
        print("\nNo stocks passed. Try --fast or wait for better market conditions.")
        sys.exit(0)

    print("[6/7] Saving to database...")
    max_per_sector = filters.get("max_per_sector", 2)
    top = save_picks_to_db(conn, results, filters["top_n"], sector_map, max_per_sector)

    stats = db.get_performance_stats(conn, "swing")
    db.log_run(conn, "swing", len(symbols), len(results), stats.get("win_rate"), filters)

    print("[7/7] Generating report...")
    display_results(top, conn)
    conn.close()


if __name__ == "__main__":
    main()
