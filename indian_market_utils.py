"""
indian_market_utils.py — Indian Market Specific Utilities
==========================================================
Shared functions used by both screeners for India-specific data.

Features:
    - Reliable Nifty 500 / Nifty 50 fetching with DB cache
    - Delivery volume % from NSE
    - F&O segment detection
    - PE ratio fetching
    - FII/DII net activity
    - Market breadth (advance/decline, % above 50-SMA)
    - Trailing stop calculation
"""

import json
import logging
import os
import re
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests
import yfinance as yf

import db

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
}

# NSE's cookie-based access — we maintain a session
_nse_session: Optional[requests.Session] = None


def _get_nse_session() -> requests.Session:
    """Get or create a persistent NSE session with cookie handling."""
    global _nse_session
    if _nse_session is None:
        _nse_session = requests.Session()
        _nse_session.headers.update(HEADERS)
        # Warm up the session by hitting NSE homepage
        try:
            _nse_session.get("https://www.nseindia.com", timeout=10)
        except Exception:
            pass
    return _nse_session


# ─── SYMBOL FETCHING WITH DB CACHE ──────────────────────────────────────────

def fetch_nifty500_symbols(conn) -> Tuple[List[str], Dict[str, str]]:
    """
    Fetch Nifty 500 constituents with DB caching.
    Returns (symbol_list, {symbol: industry}).
    Falls back to DB cache if NSE is unreachable.
    """
    print("[1/7] Fetching Nifty 500 constituents...")

    # Check DB cache age
    cache_age = db.get_cache_age(conn, "nifty500")
    max_age = 7  # Refresh weekly

    # Try NSE live fetch if cache is missing or stale
    if cache_age is None or cache_age >= max_age:
        symbols, sector_map = _try_nse_fetch("nifty500")
        if symbols:
            print(f"     {len(symbols)} stocks loaded from NSE")
            # Save to cache
            db.set_cached_symbols(conn, "nifty500", symbols, sector_map)
            return symbols, sector_map
        print("     [WARN] NSE fetch failed", end="")

    # Fallback to DB cache
    cached_syms, cached_sectors = db.get_cached_symbols(conn, "nifty500")
    if cached_syms:
        print(f"     {len(cached_syms)} stocks from DB cache (age: {cache_age or 0}d)")
        return cached_syms, cached_sectors

    # Last resort: hardcoded Nifty 50 fallback
    fallback = _get_nifty50_fallback()
    print("     [WARN] Using Nifty 50 as fallback")
    return fallback, {}


def fetch_nifty50_symbols(conn) -> List[str]:
    """Fetch Nifty 50 constituents with caching."""
    cache_age = db.get_cache_age(conn, "nifty50")

    if cache_age is None or cache_age >= 14:
        symbols, _ = _try_nse_fetch("nifty50")
        if symbols:
            db.set_cached_symbols(conn, "nifty50", symbols, {})
            return symbols

    cached_syms, _ = db.get_cached_symbols(conn, "nifty50")
    if cached_syms:
        return cached_syms

    return _get_nifty50_fallback()


def _try_nse_fetch(index_name: str) -> Tuple[List[str], Dict[str, str]]:
    """
    Try multiple URLs to fetch NSE index constituents.
    index_name: 'nifty500' or 'nifty50'
    """
    file_map = {
        "nifty500": "ind_nifty500list.csv",
        "nifty50": "ind_nifty50list.csv",
    }
    filename = file_map.get(index_name, f"ind_{index_name}list.csv")

    urls = [
        f"https://nsearchives.nseindia.com/content/indices/{filename}",
        f"https://archives.nseindia.com/content/indices/{filename}",
        f"https://www1.nseindia.com/content/indices/{filename}",
    ]

    for url in urls:
        try:
            session = _get_nse_session()
            resp = session.get(url, timeout=15)
            if resp.status_code != 200:
                continue
            from io import StringIO
            df = pd.read_csv(StringIO(resp.text))
            if "Symbol" not in df.columns:
                continue
            symbols = df["Symbol"].tolist()
            sector_map = {}
            if "Industry" in df.columns:
                sector_map = dict(zip(df["Symbol"], df["Industry"]))
            return symbols, sector_map
        except Exception:
            continue
    return [], {}


def _get_nifty50_fallback() -> List[str]:
    """Hardcoded Nifty 50 fallback list."""
    return [
        "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "HINDUNILVR", "ITC",
        "SBIN", "BHARTIARTL", "KOTAKBANK", "LT", "AXISBANK", "ASIANPAINT", "MARUTI",
        "BAJFINANCE", "TITAN", "SUNPHARMA", "HCLTECH", "NTPC", "TATAMOTORS",
        "ULTRACEMCO", "WIPRO", "POWERGRID", "NESTLEIND", "ONGC", "JSWSTEEL",
        "TATASTEEL", "ADANIENT", "ADANIPORTS", "BAJAJFINSV", "COALINDIA", "GRASIM",
        "TECHM", "CIPLA", "DRREDDY", "BPCL", "DIVISLAB", "APOLLOHOSP", "EICHERMOT",
        "HEROMOTOCO", "TATACONSUM", "BRITANNIA", "SBILIFE", "HDFCLIFE", "M&M",
        "INDUSINDBK", "HINDALCO", "UPL", "BAJAJ-AUTO", "LTIM",
    ]


# ─── NIFTY YAHOO TICKER RETRY ──────────────────────────────────────────────

def yahoo_ticker(symbol: str) -> str:
    """Get Yahoo ticker with retry for known problematic symbols."""
    # Map of known symbol issues
    symbol_map = {
        "LTIM": "LTIM.NS",        # LTI + Mindtree merger (should work, but just in case)
    }
    return symbol_map.get(symbol, f"{symbol}.NS")


def fetch_yahoo_data(symbol: str, period: str = "1y") -> Optional[pd.DataFrame]:
    """
    Fetch Yahoo Finance data with retry logic for problematic symbols.
    Tries alternative ticker formats if the primary one fails.
    """
    primary = yahoo_ticker(symbol)
    alternatives = [f"{symbol}.BO"]  # BSE as backup

    for ticker in [primary] + alternatives:
        try:
            hist = yf.Ticker(ticker).history(period=period)
            if hist is not None and len(hist) >= 200:
                return hist
        except Exception:
            continue
    return None


# ─── DELIVERY VOLUME % ─────────────────────────────────────────────────────

def fetch_delivery_volume(symbol: str) -> Optional[float]:
    """
    Fetch delivery volume % from NSE.
    Returns percentage (0-100) of traded volume that was delivered.
    Returns None if unavailable.
    """
    try:
        session = _get_nse_session()
        url = f"https://www.nseindia.com/api/quote-equity?symbol={symbol}"
        resp = session.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            # NSE returns delivery data in securityInfo
            sec_info = data.get("securityInfo", {})
            if sec_info.get("deliveryQuantity"):
                delivered = float(sec_info.get("deliveryQuantity", 0))
                traded = float(sec_info.get("totalTradedVolume", 1))
                if traded > 0:
                    return round((delivered / traded) * 100, 1)
    except Exception:
        pass
    return None


# ─── F&O SEGMENT CHECK ─────────────────────────────────────────────────────

def is_fo_stock(symbol: str) -> bool:
    """
    Check if a stock is in the F&O (Futures & Options) segment.
    Uses NSE's F&O derivatives list.
    """
    try:
        session = _get_nse_session()
        url = "https://nsearchives.nseindia.com/content/fo/fo_mktlots.csv"
        resp = session.get(url, timeout=10)
        if resp.status_code == 200:
            from io import StringIO
            df = pd.read_csv(StringIO(resp.text))
            fo_symbols = set(df.iloc[:, 0].astype(str).str.strip().str.upper())
            return symbol.upper() in fo_symbols
    except Exception:
        pass
    # Fallback: check if it's in the known F&O list (major large-cap stocks)
    known_fo = {
        "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "HINDUNILVR", "ITC",
        "SBIN", "BHARTIARTL", "KOTAKBANK", "LT", "AXISBANK", "ASIANPAINT", "MARUTI",
        "BAJFINANCE", "TITAN", "SUNPHARMA", "HCLTECH", "NTPC", "TATAMOTORS",
        "ULTRACEMCO", "WIPRO", "POWERGRID", "NESTLEIND", "ONGC", "JSWSTEEL",
        "TATASTEEL", "ADANIENT", "ADANIPORTS", "BAJAJFINSV", "COALINDIA", "GRASIM",
        "TECHM", "CIPLA", "DRREDDY", "BPCL", "DIVISLAB", "APOLLOHOSP", "EICHERMOT",
        "HEROMOTOCO", "TATACONSUM", "BRITANNIA", "SBILIFE", "HDFCLIFE", "M&M",
        "INDUSINDBK", "HINDALCO", "UPL", "BAJAJ-AUTO", "LTIM",
        "BANDHANBNK", "BANKBARODA", "BHEL", "BIOCON", "CADILAHC", "DABUR",
        "FEDERALBNK", "GAIL", "GODREJCP", "HAVELLS", "HDFCAMC", "HINDZINC",
        "IBULHSGFIN", "ICICIPRULI", "IOC", "IRCTC", "MARICO", "MCDOWELL-N",
        "MUTHOOTFIN", "NAUKRI", "NIACL", "PIDILITIND", "PNB", "PEL", "SRTRANSFIN",
        "TORNTPHARM", "TRENT", "TVSMOTOR", "VEDL", "YESBANK", "ZEEL",
    }
    return symbol.upper() in known_fo


# ─── PE RATIO ──────────────────────────────────────────────────────────────

def fetch_pe_ratio(symbol: str) -> Optional[float]:
    """
    Fetch PE ratio from Yahoo Finance or NSE.
    """
    try:
        # Try Yahoo Finance first
        ticker = yahoo_ticker(symbol)
        tk = yf.Ticker(ticker)
        info = tk.info
        if info and info.get("trailingPE"):
            return round(float(info["trailingPE"]), 2)
        if info and info.get("forwardPE"):
            return round(float(info["forwardPE"]), 2)
    except Exception:
        pass

    try:
        # Try NSE as backup
        session = _get_nse_session()
        url = f"https://www.nseindia.com/api/quote-equity?symbol={symbol}"
        resp = session.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            pe = data.get("securityInfo", {}).get("pe")
            if pe is not None:
                return round(float(pe), 2)
    except Exception:
        pass

    return None


# ─── FII/DII ACTIVITY ──────────────────────────────────────────────────────

def fetch_fii_dii_activity() -> Tuple[Optional[float], Optional[float]]:
    """
    Fetch latest FII and DII net activity in equity (INR Crores).
    Returns (fii_net_equity, dii_net_equity).
    Uses NSE's FII/DII activity endpoint.
    """
    try:
        # NSE's FII/DII activity API
        url = "https://www.nseindia.com/api/reports?type=fiidiistats&date="
        session = _get_nse_session()
        resp = session.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                latest = data[-1]  # Most recent entry
                fii = latest.get("fiiEquity", 0)
                dii = latest.get("diiEquity", 0)
                return (float(fii), float(dii))
    except Exception:
        pass

    # Fallback: try alternative NSE endpoint
    try:
        today = datetime.now().strftime("%d-%b-%Y")
        url = f"https://www.nseindia.com/api/fiidii?date={today}"
        session = _get_nse_session()
        resp = session.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, dict):
                fii = data.get("fiiEquity", 0)
                dii = data.get("diiEquity", 0)
                return (float(fii), float(dii))
    except Exception:
        pass

    return (None, None)


# ─── MARKET BREADTH ────────────────────────────────────────────────────────

def compute_market_breadth(symbols: List[str], min_stocks: int = 100) -> dict:
    """
    Compute market breadth from a list of stock symbols.
    Returns dict with advance/decline count and % above 50-SMA.

    Since we can't scan 500 stocks daily, this estimates breadth
    from the available Nifty 50 / Nifty 500 constituents.
    """
    result = {
        "advance_count": 0,
        "decline_count": 0,
        "pct_above_sma50": 0.0,
    }

    if not symbols or len(symbols) < min_stocks:
        return result

    advances = 0
    declines = 0
    above_sma50 = 0
    total_checked = 0

    # Sample a subset for speed (Nifty 500 is too slow for all)
    sample_size = min(200, len(symbols))
    sampled = symbols[:sample_size]

    for sym in sampled:
        try:
            hist = fetch_yahoo_data(sym, period="3mo")
            if hist is None or len(hist) < 50:
                continue
            close = hist["Close"]
            current = float(close.iloc[-1])
            prev = float(close.iloc[-2])
            sma50 = float(close.rolling(50).mean().iloc[-1])

            if current > sma50:
                above_sma50 += 1
            if current > prev:
                advances += 1
            else:
                declines += 1
            total_checked += 1
        except Exception:
            continue

    if total_checked > 0:
        result["advance_count"] = advances
        result["decline_count"] = declines
        result["pct_above_sma50"] = round((above_sma50 / total_checked) * 100, 1)

    return result


# ─── TRAILING STOP ─────────────────────────────────────────────────────────

def compute_trailing_stop(entry_price: float, current_price: float,
                           activate_pct: float = 10.0,
                           drawdown_pct: float = 5.0) -> Optional[float]:
    """
    Compute trailing stop for a trade.

    Args:
        entry_price: Entry price of the trade
        current_price: Current market price
        activate_pct: % profit needed to activate trailing stop (default 10%)
        drawdown_pct: % allowed drawdown from peak (default 5%)

    Returns:
        New trailing stop price, or None if not yet activated.
    """
    profit_pct = ((current_price / entry_price) - 1) * 100

    if profit_pct < activate_pct:
        return None  # Trailing stop not yet activated

    # Trail stop at drawdown_pct below current price
    trail_stop = round(current_price * (1 - drawdown_pct / 100), 2)
    return trail_stop


def update_trailing_stops(conn, screener_type: str):
    """
    Update trailing stops for all open picks of a given screener type.
    Called during portfolio check.
    """
    open_picks = db.get_open_picks(conn, screener_type)
    updated = 0

    for p in open_picks:
        try:
            current_price = p.get("exit_price") or p.get("last_close")
            # Fetch current price
            hist = yf.Ticker(yahoo_ticker(p["ticker"])).history(period="5d")
            if hist.empty:
                continue
            current = float(hist["Close"].iloc[-1])
            entry = p["entry_price"]

            new_stop = compute_trailing_stop(entry, current)
            if new_stop is not None:
                existing_stop = p.get("trailing_stop") or p["stop_loss"]
                if new_stop > existing_stop:  # Only update if better
                    db.update_trailing_stop(conn, p["id"], new_stop)
                    updated += 1
        except Exception:
            continue

    return updated


# ─── MARKET REGIME ENHANCED CHECK ──────────────────────────────────────────

def enhanced_regime_check(conn) -> dict:
    """
    Enhanced market regime check with breadth validation.
    Returns dict with all regime indicators.
    Returns dict with:
        ok: bool — whether market is healthy for trading
        reason: str — explanation if blocked
        indicators: dict — all measured values
        breadth: dict — market breadth data
        fii_dii: dict — FII/DII activity
    """
    result = {
        "ok": True,
        "reason": "",
        "indicators": {},
        "breadth": {},
        "fii_dii": {},
    }

    # 1. Nifty vs 20-SMA
    try:
        nifty = yf.Ticker("^NSEI").history(period="2mo")
        if not nifty.empty:
            nclose = nifty["Close"]
            sma20 = float(nclose.rolling(20).mean().iloc[-1])
            current = float(nclose.iloc[-1])
            result["indicators"]["nifty_close"] = current
            result["indicators"]["nifty_sma20"] = sma20
            result["indicators"]["nifty_above_sma20"] = current > sma20

            if current <= sma20:
                result["ok"] = False
                result["reason"] += (f"Nifty ({current:.0f}) below 20-SMA ({sma20:.0f}). ")

        print(f"     Nifty 50: {float(nifty['Close'].iloc[-1]):.0f} | "
              f"20-SMA: {sma20:.0f} | "
              f"{'ABOVE (OK)' if current > sma20 else 'BELOW (BLOCKED)'}")
    except Exception:
        print("     [WARN] Could not check Nifty")

    # 2. India VIX
    try:
        vix = yf.Ticker("^INDIAVIX").history(period="5d")
        if not vix.empty:
            vix_val = float(vix["Close"].iloc[-1])
            result["indicators"]["india_vix"] = vix_val
            print(f"     India VIX: {vix_val:.1f}")
            if vix_val > 20:
                result["ok"] = False
                result["reason"] += f"VIX ({vix_val:.1f}) > 20 (fear). "
    except Exception:
        print("     [WARN] Could not fetch India VIX")

    # 3. S&P 500 pulse
    try:
        sp = yf.Ticker("^GSPC").history(period="5d")
        if not sp.empty:
            sp_chg = float(sp["Close"].pct_change().iloc[-1] * 100)
            result["indicators"]["sp500_change"] = sp_chg
            print(f"     S&P 500: {sp_chg:+.2f}%")
    except Exception:
        pass

    # 4. Market Breadth from DB cache or compute
    breadth_data = db.get_latest_breadth(conn)
    if breadth_data:
        result["breadth"] = {
            "advance_count": breadth_data.get("advance_count"),
            "decline_count": breadth_data.get("decline_count"),
            "pct_above_sma50": breadth_data.get("pct_above_sma50"),
            "fii_net_equity": breadth_data.get("fii_net_equity"),
            "dii_net_equity": breadth_data.get("dii_net_equity"),
        }
        pct_above = result["breadth"]["pct_above_sma50"]
        if pct_above and pct_above < 40:
            result["ok"] = False
            result["reason"] += f"Breadth weak: {pct_above:.0f}% stocks above SMA50. "
        print(f"     Breadth: {result['breadth'].get('advance_count', 'N/A')}A / "
              f"{result['breadth'].get('decline_count', 'N/A')}D | "
              f"{pct_above or 'N/A'}% above SMA50")
        fii = result["breadth"].get("fii_net_equity")
        dii = result["breadth"].get("dii_net_equity")
        if fii is not None:
            print(f"     FII: {fii:+.0f} Cr | DII: {dii or 0:+.0f} Cr")

    # 5. FII/DII activity
    fii_net, dii_net = fetch_fii_dii_activity()
    result["fii_dii"]["fii_net"] = fii_net
    result["fii_dii"]["dii_net"] = dii_net
    if fii_net is not None and fii_net < -1000:
        result["ok"] = False
        result["reason"] += f"FII selling {fii_net:.0f} Cr. "

    return result


# ─── SECTOR DIVERSIFICATION CHECK ──────────────────────────────────────────

def get_sector_concentration(top_picks: List[dict], sector_map: Dict[str, str]) -> dict:
    """
    Analyze sector concentration in picks.
    Returns dict with sector counts and warnings.
    """
    sectors = {}
    for p in top_picks:
        sec = sector_map.get(p.get("ticker", ""), "Unknown")
        sectors[sec] = sectors.get(sec, 0) + 1

    warnings = []
    for sec, count in sectors.items():
        if count >= 3:
            warnings.append(f"{sec}: {count} picks (high concentration)")

    return {
        "sector_counts": sectors,
        "warnings": warnings,
    }