"""
backtester.py — Auto-Learning Backtester
=========================================
Checks every open pick against real market data, records outcomes,
then analyses FAILURES to automatically adjust filter parameters
so future picks improve over time.

Usage:
    python backtester.py                  # Check all open picks + learn
    python backtester.py --check-only     # Just check picks, no learning
    python backtester.py --learn-only     # Just run learning on existing data
    python backtester.py --report         # Show full performance report
    python backtester.py --reset          # Reset all learned params to defaults
"""

import argparse
import json
import statistics
import warnings
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yfinance as yf
from tabulate import tabulate

import db

warnings.filterwarnings("ignore")


# ─── CONFIGURATION ────────────────────────────────────────────────────────────

# Minimum closed trades before learning kicks in
MIN_TRADES_FOR_LEARNING = 3

# How aggressively to adjust params (0.0 = no change, 1.0 = fully adopt new value)
LEARNING_RATE = 0.3

# Bounds for adjustable parameters (param_name -> (min, max, default))
WEEKLY_PARAM_BOUNDS = {
    "rsi_min":               (40.0,  65.0,  50.0),
    "rsi_max":               (65.0,  85.0,  75.0),
    "adx_min":               (18.0,  35.0,  25.0),
    "volume_spike_min":      (1.0,   2.5,   1.3),
    "max_pct_from_52w_high": (5.0,   25.0,  15.0),
    "min_pct_from_52w_low":  (10.0,  40.0,  25.0),
    "target_upside_pct":     (8.0,   25.0,  15.0),
    "min_risk_reward_ratio": (1.5,   4.0,   2.0),
}

SWING_PARAM_BOUNDS = {
    # Scoring weights
    "w_trend":          (0.5, 4.0, 2.0),
    "w_momentum":       (0.5, 4.0, 2.0),
    "w_volume":         (0.5, 4.0, 1.8),
    "w_bollinger":      (0.2, 3.0, 1.2),
    "w_rel_strength":   (0.3, 3.0, 1.5),
    "w_consolidation":  (0.3, 3.0, 1.3),
    "w_fundamentals":   (0.3, 3.0, 1.5),
    "w_sentiment":      (0.1, 2.5, 1.0),
    "w_52w_proximity":  (0.1, 2.0, 0.8),
    "w_bulk_deals":     (0.1, 2.0, 0.6),
    # Filter thresholds
    "min_composite_score":      (40.0, 75.0, 58.0),
    "rsi_low":                  (35.0, 55.0, 45.0),
    "rsi_high":                 (65.0, 80.0, 75.0),
    "min_adx":                  (15.0, 35.0, 22.0),
    "volume_spike_threshold":   (1.0,  2.5,  1.2),
    "pct_from_52w_high_max":    (5.0,  25.0, 15.0),
    "consolidation_range_pct":  (4.0,  15.0, 8.0),
}


# ─── CHECK OPEN PICKS ────────────────────────────────────────────────────────

def check_open_picks(conn, screener_type: str) -> List[dict]:
    """Fetch current prices for all open picks and close any that hit target/SL."""
    open_picks = db.get_open_picks(conn, screener_type)
    if not open_picks:
        return []

    results = []
    today = datetime.now().strftime("%Y-%m-%d")

    for p in open_picks:
        ticker = p["ticker"]
        try:
            hist = yf.Ticker(f"{ticker}.NS").history(period="5d")
            if hist.empty:
                results.append({"ticker": ticker, "status": "NO DATA"})
                continue

            current = float(hist["Close"].iloc[-1])
            entry = p["entry_price"]
            target = p["target"]
            sl = p["stop_loss"]
            pnl_pct = round((current / entry - 1) * 100, 2)
            days_held = (datetime.now() - datetime.strptime(p["run_date"], "%Y-%m-%d")).days

            # Also get high/low since entry for more detailed tracking
            try:
                full_hist = yf.Ticker(f"{ticker}.NS").history(start=p["run_date"])
                max_price = float(full_hist["High"].max()) if not full_hist.empty else current
                min_price = float(full_hist["Low"].min()) if not full_hist.empty else current
            except Exception:
                max_price, min_price = current, current

            status = None
            action = "HOLD"

            if current >= target:
                status = "TARGET_HIT"
                action = "CLOSED: TARGET HIT"
            elif current <= sl:
                status = "STOP_LOSS"
                action = "CLOSED: STOP-LOSS HIT"
            elif screener_type == "weekly" and days_held > 60:
                status = "EXPIRED"
                action = "CLOSED: EXPIRED (>60 days)"
            elif screener_type == "swing" and days_held > 120:
                status = "EXPIRED"
                action = "CLOSED: EXPIRED (>120 days)"

            if status:
                db.close_pick(conn, p["id"], status, current, today, pnl_pct, days_held)
                db.insert_outcome(conn, {
                    "pick_id": p["id"],
                    "check_date": today,
                    "current_price": current,
                    "pnl_pct": pnl_pct,
                    "hit_target": 1 if status == "TARGET_HIT" else 0,
                    "hit_stop_loss": 1 if status == "STOP_LOSS" else 0,
                    "max_price_since": max_price,
                    "min_price_since": min_price,
                    "action_taken": action,
                })

            results.append({
                "Ticker": ticker,
                "Type": screener_type,
                "Entry": round(entry, 2),
                "Current": round(current, 2),
                "Target": round(target, 2),
                "SL": round(sl, 2),
                "P&L%": f"{pnl_pct:+.1f}%",
                "Days": days_held,
                "Max": round(max_price, 2),
                "Min": round(min_price, 2),
                "Action": action,
            })
        except Exception as e:
            results.append({"Ticker": ticker, "Type": screener_type, "Action": f"ERROR: {e}"})

    return results


def check_all_open(conn) -> List[dict]:
    """Check picks from both screeners."""
    results = []
    for stype in ("weekly", "swing"):
        results.extend(check_open_picks(conn, stype))
    return results


# ─── LEARNING ENGINE ──────────────────────────────────────────────────────────

def _analyze_weekly_failures(conn) -> Dict[str, float]:
    """
    Analyse failed weekly picks to find which filter ranges led to losses.
    Returns suggested new parameter values.
    """
    failures = db.get_failure_analysis(conn, "weekly")
    winners = db.get_historical_picks(conn, "weekly")
    winners = [w for w in winners if w["status"] == "TARGET_HIT"]

    if len(failures) < 2:
        return {}

    suggestions = {}

    # — RSI analysis —
    fail_rsi = [f["rsi"] for f in failures if f["rsi"] is not None]
    win_rsi = [w["rsi"] for w in winners if w["rsi"] is not None]
    if fail_rsi and win_rsi:
        fail_med = statistics.median(fail_rsi)
        win_med = statistics.median(win_rsi)
        # If failures have higher RSI, tighten the max; if lower RSI, raise the min
        if fail_med > win_med + 3:
            suggestions["rsi_max"] = max(60.0, win_med + 5)
        if fail_med < win_med - 3:
            suggestions["rsi_min"] = min(60.0, win_med - 5)

    # — ADX analysis —
    fail_adx = [f["adx"] for f in failures if f["adx"] is not None]
    win_adx = [w["adx"] for w in winners if w["adx"] is not None]
    if fail_adx and win_adx:
        fail_med = statistics.median(fail_adx)
        win_med = statistics.median(win_adx)
        if win_med > fail_med + 2:
            suggestions["adx_min"] = win_med - 3  # Raise minimum ADX threshold

    # — Volume spike analysis —
    fail_vol = [f["vol_spike"] for f in failures if f["vol_spike"] is not None]
    win_vol = [w["vol_spike"] for w in winners if w["vol_spike"] is not None]
    if fail_vol and win_vol:
        fail_med = statistics.median(fail_vol)
        win_med = statistics.median(win_vol)
        if win_med > fail_med + 0.2:
            suggestions["volume_spike_min"] = win_med - 0.1

    # — 52-week proximity —
    fail_52w = [f["pct_from_52w_hi"] for f in failures if f["pct_from_52w_hi"] is not None]
    win_52w = [w["pct_from_52w_hi"] for w in winners if w["pct_from_52w_hi"] is not None]
    if fail_52w and win_52w:
        fail_med = statistics.median(fail_52w)
        win_med = statistics.median(win_52w)
        if fail_med > win_med + 3:
            suggestions["max_pct_from_52w_high"] = win_med + 2

    # — Relative strength —
    fail_rs = [f["rel_str_1m"] for f in failures if f["rel_str_1m"] is not None]
    win_rs = [w["rel_str_1m"] for w in winners if w["rel_str_1m"] is not None]
    if fail_rs and win_rs:
        fail_med = statistics.median(fail_rs)
        win_med = statistics.median(win_rs)
        # If winners have much higher RS, raise min threshold for 52w_low
        if win_med > fail_med + 5:
            suggestions["min_pct_from_52w_low"] = max(15.0, win_med - 10)

    return suggestions


def _analyze_swing_failures(conn) -> Dict[str, float]:
    """
    Analyse failed swing picks to find which scoring weights AND filter
    thresholds need adjustment.  Returns suggested new parameter values.
    """
    failures = db.get_failure_analysis(conn, "swing")
    winners = db.get_historical_picks(conn, "swing")
    winners = [w for w in winners if w["status"] == "TARGET_HIT"]

    if len(failures) < 2:
        return {}

    suggestions = {}

    # ── Part 1: Adjust SCORING WEIGHTS via separation analysis ─────────
    indicators = {
        "rsi": "w_momentum",
        "adx": "w_trend",
        "vol_spike": "w_volume",
        "pct_from_52w_hi": "w_52w_proximity",
        "rel_str_1m": "w_rel_strength",
        "rev_growth": "w_fundamentals",
        "news_sentiment": "w_sentiment",
    }

    for indicator, weight_name in indicators.items():
        fail_vals = [f[indicator] for f in failures if f[indicator] is not None]
        win_vals = [w[indicator] for w in winners if w[indicator] is not None]

        if not fail_vals or not win_vals:
            continue

        fail_med = statistics.median(fail_vals)
        win_med = statistics.median(win_vals)

        if abs(win_med - fail_med) > 0:
            combined_std = (statistics.stdev(fail_vals + win_vals) + 0.001)
            separation = abs(win_med - fail_med) / combined_std

            if separation > 0.5:
                _, max_w, default_w = SWING_PARAM_BOUNDS.get(weight_name, (0.1, 4.0, 1.0))
                current = db.get_algo_param(conn, "swing", weight_name, default_w)
                suggestions[weight_name] = min(max_w, current + 0.2)
            elif separation < 0.1:
                min_w, _, default_w = SWING_PARAM_BOUNDS.get(weight_name, (0.1, 4.0, 1.0))
                current = db.get_algo_param(conn, "swing", weight_name, default_w)
                suggestions[weight_name] = max(min_w, current - 0.1)

    # ── Part 2: Adjust FILTER THRESHOLDS based on win/loss distributions ─

    # RSI range
    fail_rsi = [f["rsi"] for f in failures if f["rsi"] is not None]
    win_rsi = [w["rsi"] for w in winners if w["rsi"] is not None]
    if fail_rsi and win_rsi:
        fail_med = statistics.median(fail_rsi)
        win_med = statistics.median(win_rsi)
        if fail_med > win_med + 3:
            suggestions["rsi_high"] = max(65.0, win_med + 5)
        if fail_med < win_med - 3:
            suggestions["rsi_low"] = min(55.0, win_med - 5)

    # ADX minimum
    fail_adx = [f["adx"] for f in failures if f["adx"] is not None]
    win_adx = [w["adx"] for w in winners if w["adx"] is not None]
    if fail_adx and win_adx:
        fail_med = statistics.median(fail_adx)
        win_med = statistics.median(win_adx)
        if win_med > fail_med + 2:
            suggestions["min_adx"] = win_med - 3

    # Volume spike
    fail_vol = [f["vol_spike"] for f in failures if f["vol_spike"] is not None]
    win_vol = [w["vol_spike"] for w in winners if w["vol_spike"] is not None]
    if fail_vol and win_vol:
        fail_med = statistics.median(fail_vol)
        win_med = statistics.median(win_vol)
        if win_med > fail_med + 0.2:
            suggestions["volume_spike_threshold"] = win_med - 0.1

    # 52-week proximity
    fail_52w = [f["pct_from_52w_hi"] for f in failures if f["pct_from_52w_hi"] is not None]
    win_52w = [w["pct_from_52w_hi"] for w in winners if w["pct_from_52w_hi"] is not None]
    if fail_52w and win_52w:
        fail_med = statistics.median(fail_52w)
        win_med = statistics.median(win_52w)
        if fail_med > win_med + 3:
            suggestions["pct_from_52w_high_max"] = win_med + 2

    # Composite score minimum — raise if losers have lower scores
    fail_cs = [f["composite_score"] for f in failures if f.get("composite_score") is not None]
    win_cs = [w["composite_score"] for w in winners if w.get("composite_score") is not None]
    if fail_cs and win_cs:
        fail_med = statistics.median(fail_cs)
        win_med = statistics.median(win_cs)
        if win_med > fail_med + 3:
            suggestions["min_composite_score"] = (fail_med + win_med) / 2

    return suggestions


def _tighten_from_pure_losses(conn, screener_type: str, bounds: dict) -> Dict[str, float]:
    """When win rate is 0% and there are no winners to compare against,
    tighten filters based on the characteristics of the losing trades.
    The idea: if ALL picks lost, the current thresholds are too loose."""
    failures = db.get_failure_analysis(conn, screener_type)
    if len(failures) < 2:
        return {}

    suggestions = {}

    # Tighten ADX — losers had weak ADX, raise the minimum
    fail_adx = [f["adx"] for f in failures if f["adx"] is not None]
    if fail_adx:
        med = statistics.median(fail_adx)
        param = "adx_min" if screener_type == "weekly" else "min_adx"
        _, max_val, default = bounds.get(param, (15, 30, 20))
        current = db.get_algo_param(conn, screener_type, param, default)
        # Push minimum up toward median of losers (they should have been filtered)
        suggestions[param] = min(max_val, med + 2)

    # Tighten volume — losers had weak volume
    fail_vol = [f["vol_spike"] for f in failures if f["vol_spike"] is not None]
    if fail_vol:
        med = statistics.median(fail_vol)
        param = "volume_spike_min" if screener_type == "weekly" else "volume_spike_threshold"
        _, max_val, default = bounds.get(param, (1.0, 2.5, 1.3))
        suggestions[param] = min(max_val, med + 0.2)

    # Tighten 52-week proximity — losers were too far from high
    fail_52w = [f["pct_from_52w_hi"] for f in failures if f["pct_from_52w_hi"] is not None]
    if fail_52w:
        med = statistics.median(fail_52w)
        param = "max_pct_from_52w_high" if screener_type == "weekly" else "pct_from_52w_high_max"
        min_val, _, default = bounds.get(param, (5, 25, 15))
        suggestions[param] = max(min_val, med - 1)

    # Tighten RSI — narrow the band
    fail_rsi = [f["rsi"] for f in failures if f["rsi"] is not None]
    if fail_rsi:
        med = statistics.median(fail_rsi)
        rsi_max_param = "rsi_max" if screener_type == "weekly" else "rsi_high"
        if med > 65:
            _, max_val, default = bounds.get(rsi_max_param, (65, 85, 75))
            suggestions[rsi_max_param] = max(65.0, med - 3)

    # For swing: raise min composite score
    if screener_type == "swing":
        fail_cs = [f["composite_score"] for f in failures
                    if f.get("composite_score") is not None]
        if fail_cs:
            med = statistics.median(fail_cs)
            _, max_val, default = bounds.get("min_composite_score", (30, 65, 45))
            # Push threshold above median of losers
            suggestions["min_composite_score"] = min(max_val, med + 3)

    return suggestions


def learn_from_history(conn) -> dict:
    """
    Main learning function. Analyses closed trades, finds patterns in failures,
    and adjusts parameters for both screeners.

    Returns a report of what was changed.
    """
    report = {"weekly": {}, "swing": {}}

    for screener_type in ("weekly", "swing"):
        stats = db.get_performance_stats(conn, screener_type)
        if stats["total"] < MIN_TRADES_FOR_LEARNING:
            report[screener_type]["status"] = (
                f"Not enough data ({stats['total']}/{MIN_TRADES_FOR_LEARNING} trades). "
                "Skipping learning."
            )
            continue

        # Get current win rate
        win_rate = stats["win_rate"] or 0
        report[screener_type]["win_rate"] = win_rate
        report[screener_type]["total_trades"] = stats["total"]
        report[screener_type]["changes"] = []

        # Run failure analysis
        if screener_type == "weekly":
            suggestions = _analyze_weekly_failures(conn)
            bounds = WEEKLY_PARAM_BOUNDS
        else:
            suggestions = _analyze_swing_failures(conn)
            bounds = SWING_PARAM_BOUNDS

        # If zero wins, use pure-loss tightening instead
        if win_rate == 0 and not suggestions:
            suggestions = _tighten_from_pure_losses(conn, screener_type, bounds)

        if not suggestions:
            report[screener_type]["status"] = "No parameter adjustments needed."
            continue

        # Apply suggestions with learning rate and bounds
        for param_name, suggested_value in suggestions.items():
            min_val, max_val, default_val = bounds.get(param_name, (0, 100, suggested_value))
            current_val = db.get_algo_param(conn, screener_type, param_name, default_val)

            # Blend current and suggested using learning rate
            new_val = current_val + LEARNING_RATE * (suggested_value - current_val)
            new_val = round(max(min_val, min(max_val, new_val)), 4)

            if abs(new_val - current_val) < 0.01:
                continue  # Skip negligible changes

            reason = (
                f"Win rate: {win_rate:.0f}% | "
                f"Adjusted from {current_val:.4f} to {new_val:.4f} "
                f"(suggested: {suggested_value:.4f}, lr={LEARNING_RATE})"
            )
            db.set_algo_param(conn, screener_type, param_name, new_val, default_val, reason)

            report[screener_type]["changes"].append({
                "param": param_name,
                "old": current_val,
                "new": new_val,
                "suggested": suggested_value,
                "reason": reason,
            })

        if not report[screener_type]["changes"]:
            report[screener_type]["status"] = "Analysis complete, no changes needed."
        else:
            report[screener_type]["status"] = f"{len(report[screener_type]['changes'])} params adjusted."

    return report


# ─── PERFORMANCE REPORT ──────────────────────────────────────────────────────

def print_performance_report(conn):
    """Print a comprehensive performance report for both screeners."""
    print(f"\n{'='*90}")
    print(f"  PERFORMANCE REPORT — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*90}\n")

    for stype in ("weekly", "swing"):
        stats = db.get_performance_stats(conn, stype)
        print(f"  [{stype.upper()} SCREENER]")

        if stats["total"] == 0:
            print(f"    No closed trades yet.\n")
            continue

        print(f"    Total closed: {stats['total']}")
        print(f"    Wins: {stats['wins']}  |  Losses: {stats['losses']}")
        print(f"    Win Rate: {stats['win_rate']:.1f}%")
        if stats["avg_win_return"] is not None:
            print(f"    Avg Win Return: +{stats['avg_win_return']:.1f}%")
        if stats["avg_loss_return"] is not None:
            print(f"    Avg Loss Return: {stats['avg_loss_return']:.1f}%")
        if stats["avg_days"] is not None:
            print(f"    Avg Days Held: {stats['avg_days']:.0f}")

        # Show current tuned params
        params = db.get_all_algo_params(conn, stype)
        if params:
            print(f"\n    Current Tuned Parameters:")
            for k, v in sorted(params.items()):
                bounds = (SWING_PARAM_BOUNDS if stype == "swing" else WEEKLY_PARAM_BOUNDS).get(k)
                default_str = f" (default: {bounds[2]})" if bounds else ""
                print(f"      {k:30s} = {v:.4f}{default_str}")

        # Show recent failures
        failures = db.get_failure_analysis(conn, stype)
        if failures:
            print(f"\n    Recent Failures ({min(len(failures), 5)}):")
            for f in failures[:5]:
                ret = f.get("actual_return_pct")
                ret_str = f"{ret:+.1f}%" if ret is not None else "N/A"
                print(f"      {f['ticker']:12s} {f['run_date']}  Return: {ret_str}  "
                      f"RSI: {f.get('rsi', 'N/A')}  ADX: {f.get('adx', 'N/A')}")

        print()

    # Show open positions
    for stype in ("weekly", "swing"):
        open_picks = db.get_open_picks(conn, stype)
        if open_picks:
            print(f"  [{stype.upper()}] Open Positions: {len(open_picks)}")
            rows = []
            for p in open_picks[:10]:
                days = (datetime.now() - datetime.strptime(p["run_date"], "%Y-%m-%d")).days
                rows.append({
                    "Ticker": p["ticker"], "Entry": p["entry_price"],
                    "Target": p["target"], "SL": p["stop_loss"],
                    "Days": days, "Confidence": p.get("confidence", ""),
                })
            print(tabulate(pd.DataFrame(rows), headers="keys", tablefmt="simple", showindex=False))
            print()

    # Run log summary
    runs = conn.execute("""
        SELECT screener_type, COUNT(*) as runs, SUM(stocks_passed) as total_picks,
               MIN(run_date) as first_run, MAX(run_date) as last_run
        FROM run_log
        GROUP BY screener_type
    """).fetchall()
    if runs:
        print(f"  Run History:")
        for r in runs:
            print(f"    {r['screener_type']:8s}: {r['runs']} runs | "
                  f"{r['total_picks'] or 0} total picks | "
                  f"First: {r['first_run']} | Last: {r['last_run']}")
    print()


# ─── RESET PARAMS ────────────────────────────────────────────────────────────

def reset_params(conn):
    """Reset all learned parameters to defaults."""
    conn.execute("DELETE FROM algo_params")
    conn.commit()
    print("All learned parameters reset to defaults.")


# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Auto-Learning Backtester — checks picks, analyses failures, adjusts parameters"
    )
    parser.add_argument("--check-only", action="store_true",
                        help="Only check open picks, don't learn")
    parser.add_argument("--learn-only", action="store_true",
                        help="Only run learning on existing closed trades")
    parser.add_argument("--report", action="store_true",
                        help="Show full performance report")
    parser.add_argument("--reset", action="store_true",
                        help="Reset all learned parameters to defaults")
    args = parser.parse_args()

    conn = db.get_conn()

    if args.reset:
        reset_params(conn)
        conn.close()
        return

    if args.report:
        print_performance_report(conn)
        conn.close()
        return

    # Check open picks (unless learn-only)
    if not args.learn_only:
        print(f"\n{'='*80}")
        print(f"  BACKTESTER — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print(f"{'='*80}\n")

        print("[1] Checking open positions against market data...\n")
        results = check_all_open(conn)

        if results:
            df = pd.DataFrame(results)
            print(tabulate(df, headers="keys", tablefmt="grid", showindex=False))
        else:
            print("  No open positions to check.")

        closed_today = [r for r in results if "CLOSED" in r.get("Action", "")]
        if closed_today:
            print(f"\n  {len(closed_today)} position(s) closed today.")

    # Learn from history (unless check-only)
    if not args.check_only:
        print(f"\n[2] Analysing closed trades for learning...\n")
        report = learn_from_history(conn)

        for stype in ("weekly", "swing"):
            info = report[stype]
            print(f"  [{stype.upper()}] {info.get('status', 'N/A')}")

            if info.get("changes"):
                for c in info["changes"]:
                    print(f"    {c['param']:30s}: {c['old']:.4f} -> {c['new']:.4f}"
                          f"  (suggested: {c['suggested']:.4f})")

        # Show updated performance
        print()
        for stype in ("weekly", "swing"):
            stats = db.get_performance_stats(conn, stype)
            if stats["total"] > 0:
                print(f"  [{stype.upper()}] Win Rate: {stats['win_rate']:.0f}% "
                      f"({stats['wins']}/{stats['total']})")

    conn.close()
    print("\nDone.\n")


if __name__ == "__main__":
    main()
