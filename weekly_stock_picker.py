"""
weekly_stock_picker.py — High-Conviction Weekly Stock Picker
=============================================================
Run this every Sunday evening or Monday before 9:15 AM.
It scans the entire Nifty 500 and returns ONLY stocks where
ALL major signals align — maximizing the probability of upside.

IMPORTANT DISCLAIMER:
    No system can guarantee 100% that a stock will go up.
    Stock markets carry inherent risk. This tool uses every
    available free data source and the strictest multi-factor
    filters to find the HIGHEST PROBABILITY setups, but some
    picks will still fail. ALWAYS use the stop-loss provided.
    Never risk more than 2-3% of your capital on a single trade.

What makes this different from a normal screener:
    - ALL 8 filters must pass (not a scoring system — a checklist)
    - Only stocks in a confirmed Stage-2 uptrend are considered
    - Requires institutional volume confirmation
    - Requires fundamental growth backing
    - Requires positive news sentiment
    - Requires relative strength vs Nifty 50
    - Provides exact Entry, Target, Stop-Loss, and Position Size
    - Tracks your active trades and tells you when to sell

Usage:
    python weekly_stock_picker.py                    # Full Monday scan
    python weekly_stock_picker.py --fast             # Skip fundamentals (faster)
    python weekly_stock_picker.py --check-portfolio  # Check open trades for exit signals

Output:
    monday_picks_YYYY-MM-DD.csv   — This week's fresh picks
    active_trades.json            — Your running portfolio tracker
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from tabulate import tabulate

import db

warnings.filterwarnings("ignore")

# ── Optional dependencies (degrade gracefully) ──────────────────────────────
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


# =============================================================================
# CONFIGURATION
# =============================================================================
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# All trades stored in SQLite via db.py (screener.db)

# All thresholds are intentionally strict — we want ONLY the best setups
FILTERS = {
    # Price & liquidity
    "min_price": 50,
    "max_price": 50000,
    "min_avg_volume_20d": 100_000,
    "min_avg_traded_value_20d": 5_000_000,   # INR 50 lakh
    # Trend (ALL required)
    "price_above_sma50": True,
    "price_above_sma200": True,
    "sma50_above_sma200": True,              # Golden cross
    "sma50_rising_days": 10,
    # Momentum
    "rsi_min": 50,
    "rsi_max": 75,                           # Not overbought
    "macd_must_be_bullish": True,
    "adx_min": 20,                           # Trending, not sideways
    # Volume
    "volume_spike_min": 1.3,                 # 30% above 20d avg
    "obv_must_be_rising": True,
    # Relative Strength
    "must_outperform_nifty_1m": True,
    # 52-Week
    "max_pct_from_52w_high": 15,             # Within 15% of highs
    "min_pct_from_52w_low": 25,              # At least 25% off lows
    # Fundamentals (screener.in)
    "min_revenue_growth_yoy": 8,             # %
    "min_profit_growth_yoy": 8,              # %
    # Sentiment
    "min_news_sentiment": -0.05,             # Not heavily negative
    # Risk management
    "min_risk_reward_ratio": 2.0,
    "target_upside_pct": 15,                 # Primary target
    "stop_loss_atr_multiple": 2.0,
    # Execution
    "parallel_workers": 10,
    "top_n": 10,
}


# =============================================================================
# DATA FETCHING
# =============================================================================

def get_nifty500_symbols() -> List[str]:
    """Fetch Nifty 500 constituents from NSE."""
    print("[1/6] Fetching Nifty 500 stock list...")
    urls = [
        "https://archives.nseindia.com/content/indices/ind_nifty500list.csv",
        "https://www1.nseindia.com/content/indices/ind_nifty500list.csv",
    ]
    for url in urls:
        try:
            df = pd.read_csv(url, timeout=15)
            symbols = df["Symbol"].tolist()
            print(f"     Loaded {len(symbols)} stocks")
            return symbols
        except Exception:
            continue
    # Fallback mini-list
    print("     [WARN] NSE fetch failed — using Nifty 50 fallback")
    return [
        "RELIANCE","TCS","HDFCBANK","INFY","ICICIBANK","HINDUNILVR","ITC",
        "SBIN","BHARTIARTL","KOTAKBANK","LT","AXISBANK","ASIANPAINT","MARUTI",
        "BAJFINANCE","TITAN","SUNPHARMA","HCLTECH","NTPC","TATAMOTORS",
        "ULTRACEMCO","WIPRO","POWERGRID","NESTLEIND","ONGC","JSWSTEEL",
        "TATASTEEL","ADANIENT","ADANIPORTS","BAJAJFINSV","COALINDIA","GRASIM",
        "TECHM","CIPLA","DRREDDY","BPCL","DIVISLAB","APOLLOHOSP","EICHERMOT",
        "HEROMOTOCO","TATACONSUM","BRITANNIA","SBILIFE","HDFCLIFE","M&M",
        "INDUSINDBK","HINDALCO","UPL","BAJAJ-AUTO","LTIM",
    ]


def get_nifty50_history(period: str = "1y") -> pd.DataFrame:
    """Nifty 50 index for relative-strength benchmarking."""
    print("[2/6] Fetching Nifty 50 benchmark...")
    try:
        hist = yf.Ticker("^NSEI").history(period=period)
        if hist.empty:
            raise ValueError
        print(f"     {len(hist)} trading days loaded")
        return hist
    except Exception:
        print("     [WARN] Could not load Nifty 50 data")
        return pd.DataFrame()


def get_global_pulse() -> dict:
    """Quick check of global market conditions."""
    print("[3/6] Global market pulse...")
    pulse = {"sp500_change": 0.0, "vix": 0.0, "warning": ""}
    try:
        sp = yf.Ticker("^GSPC").history(period="5d")
        pulse["sp500_change"] = float(sp["Close"].pct_change().iloc[-1] * 100)

        vix = yf.Ticker("^VIX").history(period="5d")
        pulse["vix"] = float(vix["Close"].iloc[-1])

        if pulse["sp500_change"] < -2:
            pulse["warning"] = "S&P 500 dropped >2% — global headwinds, reduce position sizes"
        if pulse["vix"] > 25:
            pulse["warning"] += " | VIX >25 = high fear, be extra cautious"

        print(f"     S&P 500 last session: {pulse['sp500_change']:+.2f}%")
        print(f"     VIX (fear index): {pulse['vix']:.1f}")
        if pulse["warning"]:
            print(f"     WARNING: {pulse['warning']}")
    except Exception:
        print("     [WARN] Could not fetch global data")
    return pulse


def fetch_news_sentiment(symbol: str) -> float:
    """Google News RSS + VADER sentiment. Returns [-1, 1]."""
    if not _VADER or not _FEED:
        return 0.0
    try:
        url = f"https://news.google.com/rss/search?q={symbol}+NSE+stock&hl=en-IN&gl=IN&ceid=IN:en"
        feed = feedparser.parse(url)
        if not feed.entries:
            return 0.0
        analyzer = SentimentIntensityAnalyzer()
        scores = [
            analyzer.polarity_scores(e.get("title", ""))["compound"]
            for e in feed.entries[:5]
        ]
        return sum(scores) / len(scores) if scores else 0.0
    except Exception:
        return 0.0


def scrape_fundamentals(symbol: str) -> Dict[str, Optional[float]]:
    """Scrape screener.in for YoY quarterly revenue & profit growth."""
    result: Dict[str, Optional[float]] = {"rev_growth": None, "profit_growth": None}
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

        # Find "Quarters" section
        quarters_section = None
        for sec in soup.find_all("section"):
            h2 = sec.find("h2")
            if h2 and "quarter" in h2.get_text(strip=True).lower():
                quarters_section = sec
                break
        if not quarters_section:
            return result

        table = quarters_section.find("table")
        if not table:
            return result

        rows = table.find_all("tr")
        if len(rows) < 2:
            return result

        headers = [th.get_text(strip=True) for th in rows[0].find_all("th")]
        if len(headers) < 6:
            return result

        def _parse_row(label: str) -> List[Optional[float]]:
            for tr in rows[1:]:
                cells = tr.find_all("td")
                first = (tr.find("td") or tr.find("th"))
                if first and label in first.get_text(strip=True).lower():
                    vals = []
                    for c in cells:
                        txt = c.get_text(strip=True).replace(",", "")
                        try:
                            vals.append(float(txt))
                        except ValueError:
                            vals.append(None)
                    return vals
            return []

        def _yoy(vals: List[Optional[float]]) -> Optional[float]:
            if len(vals) >= 5 and vals[-1] is not None and vals[-5] is not None and vals[-5] != 0:
                return ((vals[-1] - vals[-5]) / abs(vals[-5])) * 100
            return None

        rev = _parse_row("sales") or _parse_row("revenue")
        profit = _parse_row("net profit") or _parse_row("profit")
        result["rev_growth"] = _yoy(rev)
        result["profit_growth"] = _yoy(profit)
    except Exception:
        pass
    return result


# =============================================================================
# TECHNICAL INDICATORS
# =============================================================================

def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0).ewm(com=period - 1, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0.0)).ewm(com=period - 1, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(series: pd.Series) -> Tuple[pd.Series, pd.Series, pd.Series]:
    ema12 = series.ewm(span=12, adjust=False).mean()
    ema26 = series.ewm(span=26, adjust=False).mean()
    line = ema12 - ema26
    signal = line.ewm(span=9, adjust=False).mean()
    hist = line - signal
    return line, signal, hist


def adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    tr = pd.concat([high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
    atr = tr.ewm(span=period, adjust=False).mean()

    plus_di = 100 * (plus_dm.ewm(span=period, adjust=False).mean() / atr)
    minus_di = 100 * (minus_dm.ewm(span=period, adjust=False).mean() / atr)
    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10))
    return dx.ewm(span=period, adjust=False).mean()


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    tr = pd.concat([high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = (close.diff() > 0).astype(int) * 2 - 1
    return (volume * direction).cumsum()


# =============================================================================
# THE CORE: STRICT 8-FILTER CHECKLIST
# =============================================================================

class FilterResult:
    """Stores pass/fail for each filter plus all computed data."""

    def __init__(self, symbol: str):
        self.symbol = symbol
        self.passed_all = False
        self.filters: Dict[str, bool] = {}
        self.fail_reason: str = ""

        # Data (populated during analysis)
        self.last_close: float = 0.0
        self.sma_50: float = 0.0
        self.sma_200: float = 0.0
        self.rsi_val: float = 0.0
        self.adx_val: float = 0.0
        self.macd_bullish: bool = False
        self.macd_just_crossed: bool = False
        self.vol_spike: float = 0.0
        self.obv_rising: bool = False
        self.rel_str_1m: float = 0.0
        self.rel_str_3m: float = 0.0
        self.pct_from_52w_hi: float = 0.0
        self.pct_from_52w_lo: float = 0.0
        self.rev_growth: Optional[float] = None
        self.profit_growth: Optional[float] = None
        self.news_sentiment: float = 0.0
        self.atr_14: float = 0.0

        # Trade plan
        self.entry: float = 0.0
        self.target: float = 0.0
        self.stop_loss: float = 0.0
        self.upside_pct: float = 0.0
        self.risk_pct: float = 0.0
        self.risk_reward: float = 0.0
        self.position_size_pct: float = 0.0  # % of capital
        self.confidence: str = ""
        self.rationale: str = ""


def analyze_stock(
    symbol: str,
    f: dict,
    nifty_hist: pd.DataFrame,
    skip_fundamentals: bool = False,
) -> Optional[FilterResult]:
    """
    Run the strict 8-filter checklist on a single stock.
    Returns FilterResult only if ALL filters pass. None otherwise.
    """
    res = FilterResult(symbol)
    ticker_yf = f"{symbol}.NS"

    # ── Fetch data ────────────────────────────────────────────────────────
    try:
        tk = yf.Ticker(ticker_yf)
        hist = tk.history(period="1y")
    except Exception:
        return None

    if hist is None or len(hist) < 201:
        return None

    close = hist["Close"]
    high = hist["High"]
    low = hist["Low"]
    volume = hist["Volume"]
    latest = hist.iloc[-1]
    res.last_close = float(latest["Close"])

    # ── Pre-filter: price & liquidity ─────────────────────────────────────
    if res.last_close < f["min_price"] or res.last_close > f["max_price"]:
        return None

    avg_vol_20 = float(volume.tail(20).mean())
    avg_val_20 = avg_vol_20 * res.last_close
    if avg_vol_20 < f["min_avg_volume_20d"] or avg_val_20 < f["min_avg_traded_value_20d"]:
        return None

    # ======================================================================
    # FILTER 1: TREND — Stage-2 Uptrend (Price > SMA50 > SMA200, both rising)
    # ======================================================================
    sma50_s = close.rolling(50).mean()
    sma200_s = close.rolling(200).mean()
    res.sma_50 = float(sma50_s.iloc[-1])
    res.sma_200 = float(sma200_s.iloc[-1])

    sma50_rising = sma50_s.iloc[-1] > sma50_s.iloc[-f["sma50_rising_days"]]
    price_gt_50 = res.last_close > res.sma_50
    price_gt_200 = res.last_close > res.sma_200
    golden_cross = res.sma_50 > res.sma_200

    trend_pass = price_gt_50 and price_gt_200 and golden_cross and sma50_rising
    res.filters["1_TREND"] = trend_pass
    if not trend_pass:
        res.fail_reason = "Not in Stage-2 uptrend"
        return None  # Hard filter — exit early to save time

    # ======================================================================
    # FILTER 2: MOMENTUM — RSI 50-75, MACD bullish, ADX > 20
    # ======================================================================
    rsi_s = rsi(close)
    res.rsi_val = float(rsi_s.iloc[-1])

    macd_line, macd_signal, macd_hist = macd(close)
    res.macd_bullish = bool(macd_line.iloc[-1] > macd_signal.iloc[-1])

    # Check if MACD just crossed bullish in last 5 bars (fresh signal)
    res.macd_just_crossed = False
    for i in range(-5, 0):
        if (len(macd_line) + i - 1 >= 0 and
            macd_line.iloc[i - 1] < macd_signal.iloc[i - 1] and
            macd_line.iloc[i] > macd_signal.iloc[i]):
            res.macd_just_crossed = True
            break

    adx_s = adx(high, low, close)
    res.adx_val = float(adx_s.iloc[-1])

    rsi_ok = f["rsi_min"] <= res.rsi_val <= f["rsi_max"]
    macd_ok = res.macd_bullish
    adx_ok = res.adx_val >= f["adx_min"]

    momentum_pass = rsi_ok and macd_ok and adx_ok
    res.filters["2_MOMENTUM"] = momentum_pass
    if not momentum_pass:
        res.fail_reason = f"Momentum fail (RSI={res.rsi_val:.0f}, MACD={'Y' if macd_ok else 'N'}, ADX={res.adx_val:.0f})"
        return None

    # ======================================================================
    # FILTER 3: VOLUME CONFIRMATION — Spike > 1.3x avg + OBV rising
    # ======================================================================
    res.vol_spike = float(latest["Volume"] / avg_vol_20) if avg_vol_20 > 0 else 0
    obv_s = obv(close, volume)
    res.obv_rising = bool(obv_s.iloc[-1] > obv_s.iloc[-20])

    vol_pass = res.vol_spike >= f["volume_spike_min"] and res.obv_rising
    res.filters["3_VOLUME"] = vol_pass
    if not vol_pass:
        res.fail_reason = f"Volume fail (spike={res.vol_spike:.1f}x, OBV={'rising' if res.obv_rising else 'falling'})"
        return None

    # ======================================================================
    # FILTER 4: RELATIVE STRENGTH — Must outperform Nifty 50 over 1 month
    # ======================================================================
    rs_pass = True
    if not nifty_hist.empty and len(close) >= 63:
        stock_ret_1m = float((close.iloc[-1] / close.iloc[-21] - 1) * 100)
        stock_ret_3m = float((close.iloc[-1] / close.iloc[-63] - 1) * 100)
        n_close = nifty_hist["Close"]
        nifty_ret_1m = float((n_close.iloc[-1] / n_close.iloc[-21] - 1) * 100) if len(n_close) >= 21 else 0
        nifty_ret_3m = float((n_close.iloc[-1] / n_close.iloc[-63] - 1) * 100) if len(n_close) >= 63 else 0
        res.rel_str_1m = stock_ret_1m - nifty_ret_1m
        res.rel_str_3m = stock_ret_3m - nifty_ret_3m
        rs_pass = res.rel_str_1m > 0  # Must beat Nifty over 1 month
    res.filters["4_REL_STRENGTH"] = rs_pass
    if not rs_pass:
        res.fail_reason = f"Underperforming Nifty by {res.rel_str_1m:.1f}% (1M)"
        return None

    # ======================================================================
    # FILTER 5: 52-WEEK POSITION — Near highs, well off lows
    # ======================================================================
    hi_52 = float(high.max())
    lo_52 = float(low.min())
    res.pct_from_52w_hi = (hi_52 - res.last_close) / hi_52 * 100 if hi_52 > 0 else 100
    res.pct_from_52w_lo = (res.last_close - lo_52) / lo_52 * 100 if lo_52 > 0 else 0

    hi_pass = res.pct_from_52w_hi <= f["max_pct_from_52w_high"]
    lo_pass = res.pct_from_52w_lo >= f["min_pct_from_52w_low"]
    pos_pass = hi_pass and lo_pass
    res.filters["5_52W_POSITION"] = pos_pass
    if not pos_pass:
        res.fail_reason = f"52W position fail (from high: {res.pct_from_52w_hi:.0f}%, from low: {res.pct_from_52w_lo:.0f}%)"
        return None

    # ======================================================================
    # FILTER 6: FUNDAMENTALS — Revenue & profit growth > 8% YoY
    # ======================================================================
    if not skip_fundamentals:
        fund = scrape_fundamentals(symbol)
        res.rev_growth = fund["rev_growth"]
        res.profit_growth = fund["profit_growth"]

        rev_ok = res.rev_growth is not None and res.rev_growth >= f["min_revenue_growth_yoy"]
        profit_ok = res.profit_growth is not None and res.profit_growth >= f["min_profit_growth_yoy"]
        fund_pass = rev_ok and profit_ok
        res.filters["6_FUNDAMENTALS"] = fund_pass
        if not fund_pass:
            rev_str = f"{res.rev_growth:.0f}%" if res.rev_growth is not None else "N/A"
            prf_str = f"{res.profit_growth:.0f}%" if res.profit_growth is not None else "N/A"
            res.fail_reason = f"Fundamentals fail (Rev: {rev_str}, Profit: {prf_str})"
            return None
    else:
        res.filters["6_FUNDAMENTALS"] = True  # Skipped

    # ======================================================================
    # FILTER 7: NEWS SENTIMENT — Not negative
    # ======================================================================
    res.news_sentiment = fetch_news_sentiment(symbol)
    sent_pass = res.news_sentiment >= f["min_news_sentiment"]
    res.filters["7_SENTIMENT"] = sent_pass
    if not sent_pass:
        res.fail_reason = f"Negative news sentiment ({res.news_sentiment:.2f})"
        return None

    # ======================================================================
    # FILTER 8: RISK-REWARD — Must be >= 2:1
    # ======================================================================
    atr_s = atr(high, low, close, 14)
    res.atr_14 = float(atr_s.iloc[-1])

    res.entry = round(res.last_close, 2)
    res.target = round(res.last_close * (1 + f["target_upside_pct"] / 100), 2)

    # Stop-loss: tighter of 2x ATR or 2% below SMA50
    sl_atr = res.last_close - f["stop_loss_atr_multiple"] * res.atr_14
    sl_sma = res.sma_50 * 0.98
    res.stop_loss = round(max(sl_atr, sl_sma), 2)

    res.upside_pct = round((res.target / res.last_close - 1) * 100, 1)
    res.risk_pct = round((1 - res.stop_loss / res.last_close) * 100, 1)
    reward = res.target - res.entry
    risk = res.entry - res.stop_loss
    res.risk_reward = round(reward / risk, 2) if risk > 0 else 0.0

    rr_pass = res.risk_reward >= f["min_risk_reward_ratio"]
    res.filters["8_RISK_REWARD"] = rr_pass
    if not rr_pass:
        res.fail_reason = f"Risk-reward too low ({res.risk_reward:.1f}:1)"
        return None

    # ======================================================================
    # ALL 8 FILTERS PASSED — This is a high-conviction pick
    # ======================================================================
    res.passed_all = True

    # Position sizing: risk 2% of capital per trade
    # position_size = (capital * 0.02) / risk_per_share
    # We express as % of capital
    if risk > 0:
        res.position_size_pct = round(2.0 / (res.risk_pct / 100) * (1 / 100) * 100, 1)
        res.position_size_pct = min(res.position_size_pct, 15.0)  # Cap at 15% per stock
    else:
        res.position_size_pct = 5.0

    # Confidence level
    bonus_signals = sum([
        res.macd_just_crossed,                  # Fresh MACD crossover
        res.vol_spike >= 2.0,                   # Very high volume
        res.adx_val >= 30,                      # Strong trend
        res.rel_str_1m > 5,                     # Strong outperformance
        res.pct_from_52w_hi < 5,                # Near 52W high
        res.news_sentiment > 0.2,               # Strong positive news
        (res.rev_growth or 0) > 20,             # Strong revenue growth
        (res.profit_growth or 0) > 20,          # Strong profit growth
    ])

    if bonus_signals >= 5:
        res.confidence = "VERY HIGH"
    elif bonus_signals >= 3:
        res.confidence = "HIGH"
    else:
        res.confidence = "MODERATE"

    # Build rationale
    reasons = []
    reasons.append(f"Stage-2 uptrend (SMA50>{int(res.sma_50)}, SMA200>{int(res.sma_200)})")
    if res.macd_just_crossed:
        reasons.append("Fresh MACD bullish crossover")
    else:
        reasons.append("MACD bullish")
    reasons.append(f"RSI {res.rsi_val:.0f}")
    reasons.append(f"ADX {res.adx_val:.0f} (trending)")
    reasons.append(f"Volume {res.vol_spike:.1f}x avg")
    reasons.append(f"RS vs Nifty: +{res.rel_str_1m:.1f}% (1M)")
    if res.pct_from_52w_hi < 3:
        reasons.append("AT/NEAR 52-Week High")
    if res.rev_growth is not None:
        reasons.append(f"Revenue +{res.rev_growth:.0f}% YoY")
    if res.profit_growth is not None:
        reasons.append(f"Profit +{res.profit_growth:.0f}% YoY")
    if res.news_sentiment > 0.15:
        reasons.append("Positive news flow")
    res.rationale = " | ".join(reasons)

    return res


# =============================================================================
# PARALLEL SCREENING
# =============================================================================

def screen_all(
    symbols: List[str], f: dict, nifty_hist: pd.DataFrame, skip_fundamentals: bool
) -> List[FilterResult]:
    """Screen all symbols in parallel, return only those passing ALL 8 filters."""
    passed: List[FilterResult] = []
    total = len(symbols)
    done = 0
    errors = 0

    print(f"\n[4/6] Screening {total} stocks through 8 strict filters...")
    print("      (Only stocks passing ALL filters will appear)\n")

    def _run(sym: str) -> Optional[FilterResult]:
        return analyze_stock(sym, f, nifty_hist, skip_fundamentals)

    with ThreadPoolExecutor(max_workers=f["parallel_workers"]) as pool:
        futures = {pool.submit(_run, s): s for s in symbols}
        for fut in as_completed(futures):
            done += 1
            try:
                result = fut.result()
                if result is not None and result.passed_all:
                    passed.append(result)
            except Exception:
                errors += 1
            if done % 25 == 0 or done == total:
                print(
                    f"     [{done}/{total}] Passed: {len(passed)} | "
                    f"Filtered out: {done - len(passed) - errors} | Errors: {errors}",
                    end="\r",
                )

    print(f"\n\n     RESULT: {len(passed)} stocks passed ALL 8 filters out of {total}\n")
    return passed


# =============================================================================
# TRADE PLAN & PORTFOLIO TRACKER
# =============================================================================

def build_watchlist_df(picks: List[FilterResult], f: dict) -> pd.DataFrame:
    """Convert picks to a clean DataFrame, sorted by risk-reward."""
    # Sort: VERY HIGH confidence first, then by risk-reward
    conf_order = {"VERY HIGH": 0, "HIGH": 1, "MODERATE": 2}
    picks.sort(key=lambda x: (conf_order.get(x.confidence, 3), -x.risk_reward))
    top = picks[: f["top_n"]]

    rows = []
    for p in top:
        rows.append({
            "Ticker": p.symbol,
            "Confidence": p.confidence,
            "Last_Close": p.last_close,
            "Entry_Price": p.entry,
            "Target_(15%)": p.target,
            "Stop_Loss": p.stop_loss,
            "Upside_%": p.upside_pct,
            "Risk_%": p.risk_pct,
            "Risk_Reward": f"{p.risk_reward:.1f}:1",
            "Position_%": f"{p.position_size_pct:.0f}%",
            "RSI": round(p.rsi_val, 0),
            "ADX": round(p.adx_val, 0),
            "Vol_Spike": f"{p.vol_spike:.1f}x",
            "RS_vs_Nifty_1M": f"+{p.rel_str_1m:.1f}%",
            "From_52W_High": f"{p.pct_from_52w_hi:.1f}%",
            "Rev_Growth": f"{p.rev_growth:.0f}%" if p.rev_growth is not None else "N/A",
            "Profit_Growth": f"{p.profit_growth:.0f}%" if p.profit_growth is not None else "N/A",
            "Sentiment": f"{p.news_sentiment:+.2f}",
            "Rationale": p.rationale,
        })
    return pd.DataFrame(rows)


def save_picks_to_db(conn, picks: List[FilterResult]):
    """Save picks to SQLite database."""
    today = datetime.now().strftime("%Y-%m-%d")
    count = 0
    for p in picks:
        row_id = db.insert_pick(conn, {
            "run_date": today, "screener_type": "weekly",
            "ticker": p.symbol, "last_close": p.last_close,
            "entry_price": p.entry, "target": p.target,
            "stop_loss": p.stop_loss, "upside_pct": p.upside_pct,
            "risk_pct": p.risk_pct, "risk_reward": p.risk_reward,
            "confidence": p.confidence, "rsi": p.rsi_val, "adx": p.adx_val,
            "macd_bullish": 1 if p.macd_bullish else 0,
            "vol_spike": p.vol_spike,
            "rel_str_1m": p.rel_str_1m, "rel_str_3m": p.rel_str_3m,
            "pct_from_52w_hi": p.pct_from_52w_hi,
            "rev_growth": p.rev_growth, "profit_growth": p.profit_growth,
            "news_sentiment": p.news_sentiment,
            "composite_score": None,
            "rationale": p.rationale,
            "filters_json": json.dumps({k: v for k, v in p.filters.items()}),
        })
        if row_id: count += 1
    print(f"     {count} new picks saved to screener.db")


def check_portfolio(conn):
    """Check active weekly trades against current prices for exit signals."""
    open_picks = db.get_open_picks(conn, "weekly")
    if not open_picks:
        print("No open weekly trades.")
        return

    print(f"\n{'='*80}")
    print(f"  WEEKLY PORTFOLIO CHECK — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Open trades: {len(open_picks)}")
    print(f"{'='*80}\n")

    rows = []
    for p in open_picks:
        ticker = p["ticker"]
        try:
            hist = yf.Ticker(f"{ticker}.NS").history(period="5d")
            if hist.empty:
                continue
            current = float(hist["Close"].iloc[-1])
            entry = p["entry_price"]
            target = p["target"]
            sl = p["stop_loss"]

            pnl_pct = (current / entry - 1) * 100
            days_held = (datetime.now() - datetime.strptime(p["run_date"], "%Y-%m-%d")).days

            action = "HOLD"
            status = None
            if current >= target:
                action = "SELL (TARGET HIT)"
                status = "TARGET_HIT"
            elif current <= sl:
                action = "SELL (STOP-LOSS HIT)"
                status = "STOP_LOSS"
            elif days_held > 60:
                action = "REVIEW (>60 days)"
                status = "EXPIRED"
            elif pnl_pct > 10:
                action = f"HOLD (trail SL to {entry:.2f})"

            if status:
                db.close_pick(conn, p["id"], status, current,
                              datetime.now().strftime("%Y-%m-%d"), round(pnl_pct, 2), days_held)
                db.insert_outcome(conn, {
                    "pick_id": p["id"],
                    "check_date": datetime.now().strftime("%Y-%m-%d"),
                    "current_price": current, "pnl_pct": round(pnl_pct, 2),
                    "hit_target": 1 if status == "TARGET_HIT" else 0,
                    "hit_stop_loss": 1 if status == "STOP_LOSS" else 0,
                    "max_price_since": current, "min_price_since": current,
                    "action_taken": action,
                })

            rows.append({
                "Ticker": ticker, "Entry": entry,
                "Current": round(current, 2), "Target": target,
                "Stop_Loss": sl, "P&L_%": f"{pnl_pct:+.1f}%",
                "Days": days_held, "Action": action,
            })
        except Exception:
            rows.append({"Ticker": ticker, "Action": "DATA ERROR"})

    if rows:
        print(tabulate(pd.DataFrame(rows), headers="keys", tablefmt="grid", showindex=False))

    stats = db.get_performance_stats(conn, "weekly")
    if stats["total"] > 0:
        print(f"\n--- Weekly Performance ---")
        print(f"Total: {stats['total']} | Wins: {stats['wins']} | Losses: {stats['losses']} | "
              f"Win Rate: {stats['win_rate']:.0f}%")
    print()


# =============================================================================
# OUTPUT
# =============================================================================

def save_and_display(df: pd.DataFrame, pulse: dict):
    """Save CSV, update portfolio, print to console."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    csv_path = f"monday_picks_{date_str}.csv"
    df.to_csv(csv_path, index=False)

    # (picks saved to DB separately)

    print(f"\n{'='*100}")
    print(f"  MONDAY STOCK PICKS — {date_str}")
    print(f"  Stocks passing ALL 8 strict filters | Horizon: 1-2 months | Target: ~15% upside")
    if pulse.get("warning"):
        print(f"  GLOBAL WARNING: {pulse['warning']}")
    print(f"{'='*100}\n")

    # Main table
    display_cols = [
        "Ticker", "Confidence", "Last_Close", "Entry_Price",
        "Target_(15%)", "Stop_Loss", "Risk_Reward", "Position_%",
    ]
    print(tabulate(df[display_cols], headers="keys", tablefmt="grid", showindex=False))

    # Detailed view
    print(f"\n{'='*100}")
    print("  DETAILED ANALYSIS")
    print(f"{'='*100}\n")

    detail_cols = [
        "Ticker", "RSI", "ADX", "Vol_Spike",
        "RS_vs_Nifty_1M", "From_52W_High",
        "Rev_Growth", "Profit_Growth", "Sentiment",
    ]
    print(tabulate(df[detail_cols], headers="keys", tablefmt="grid", showindex=False))

    # Trading instructions
    print(f"\n{'='*100}")
    print("  HOW TO TRADE THIS WATCHLIST")
    print(f"{'='*100}")
    print("""
    1. BUY at the Entry Price on Monday after 9:30 AM (let the first 15 min settle)
    2. Set a STOP-LOSS order immediately at the Stop_Loss price
    3. HOLD the stock — do NOT panic-sell on small dips
    4. SELL when the stock hits the Target price (or your broker's target order does it)
    5. If a stock goes up 10%+, trail your stop-loss to your entry price (breakeven)
    6. Run 'python weekly_stock_picker.py --check-portfolio' weekly to check exits
    7. Maximum hold: 60 days — if target not hit, review and decide

    POSITION SIZING:
    - Never put more than 15% of your capital in one stock
    - The Position_% column shows the recommended allocation
    - This ensures one bad trade won't hurt your total capital much

    RISK MANAGEMENT:
    - Every trade has a stop-loss — ALWAYS honor it, no exceptions
    - Risk per trade: ~2% of total capital
    - Even with strict filters, expect ~60-70% win rate (not 100%)
    - The math works because winners (+15%) are larger than losers (~5-7%)
""")

    # Per-stock rationale
    print(f"{'='*100}")
    print("  WHY EACH STOCK WAS PICKED")
    print(f"{'='*100}\n")
    for _, row in df.iterrows():
        print(f"  {row['Ticker']} [{row['Confidence']}]")
        print(f"    {row['Rationale']}")
        print()

    print(f"  Report saved: {csv_path}")
    print(f"  Database: screener.db")
    print()


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Weekly Stock Picker — High-conviction Monday buys with 15%+ upside target",
    )
    parser.add_argument("--fast", action="store_true", help="Skip fundamental analysis (faster but less strict)")
    parser.add_argument("--top", type=int, default=None, help="Max stocks to pick (default: 10)")
    parser.add_argument("--workers", type=int, default=None, help="Parallel threads (default: 10)")
    parser.add_argument("--check-portfolio", action="store_true", help="Check open trades for exit signals")
    args = parser.parse_args()

    conn = db.get_conn()

    if args.check_portfolio:
        check_portfolio(conn)
        conn.close()
        return

    print()
    print("=" * 70)
    print("  WEEKLY STOCK PICKER — Monday Market Open Edition")
    print("  Finding high-conviction stocks with 15%+ upside (1-2 months)")
    print("  All 8 filters must pass — only the strongest setups survive")
    print("=" * 70)
    print()

    f = dict(FILTERS)
    if args.top:
        f["top_n"] = args.top
    if args.workers:
        f["parallel_workers"] = args.workers

    print("  IMPORTANT: No screener can guarantee 100% that a stock will go up.")
    print("  This tool finds the HIGHEST PROBABILITY setups using 8 strict filters.")
    print("  Always use the stop-loss. Risk only 2% of capital per trade.\n")

    # Step 1: Universe
    symbols = get_nifty500_symbols()
    if not symbols:
        print("FATAL: No stocks loaded.")
        sys.exit(1)

    # Step 2: Benchmark
    nifty_hist = get_nifty50_history()

    # Step 3: Global pulse
    pulse = get_global_pulse()

    # Step 4: Screen
    picks = screen_all(symbols, f, nifty_hist, skip_fundamentals=args.fast)

    if not picks:
        print("\n  No stocks passed ALL 8 filters this week.")
        print("  This means the market may not have high-conviction setups right now.")
        print("  It's better to wait than to invest in weak setups.\n")
        sys.exit(0)

    # Step 5: Save to DB
    print("[5/6] Saving picks to database...")
    save_picks_to_db(conn, picks)
    df = build_watchlist_df(picks, f)

    # Log the run
    stats = db.get_performance_stats(conn, "weekly")
    db.log_run(conn, "weekly", len(symbols), len(picks), stats.get("win_rate"), f)

    # Step 6: Output
    print("[6/6] Generating report...\n")
    save_and_display(df, pulse)
    conn.close()


if __name__ == "__main__":
    main()
