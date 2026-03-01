"""
db.py — SQLite Database Layer
==============================
Shared database for both weekly_stock_picker.py and swing_breakout_screener.py.

Tables:
    picks          — Every stock pick ever made (weekly + swing)
    trade_outcomes — Actual results after backtest checks
    algo_params    — Self-tuning filter parameters (learned from wins/losses)
    run_log        — Audit trail of every screener run
"""

import json
import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screener.db")


def get_conn() -> sqlite3.Connection:
    """Get a connection to the SQLite database, creating tables if needed."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _create_tables(conn)
    return conn


def _create_tables(conn: sqlite3.Connection):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS picks (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        run_date        TEXT NOT NULL,
        screener_type   TEXT NOT NULL CHECK(screener_type IN ('weekly', 'swing')),
        ticker          TEXT NOT NULL,
        last_close      REAL,
        entry_price     REAL,
        target          REAL,
        stop_loss       REAL,
        upside_pct      REAL,
        risk_pct        REAL,
        risk_reward     REAL,
        confidence      TEXT,
        rsi             REAL,
        adx             REAL,
        macd_bullish    INTEGER,
        vol_spike       REAL,
        rel_str_1m      REAL,
        rel_str_3m      REAL,
        pct_from_52w_hi REAL,
        rev_growth      REAL,
        profit_growth   REAL,
        news_sentiment  REAL,
        composite_score REAL,
        rationale       TEXT,
        filters_json    TEXT,
        status          TEXT DEFAULT 'OPEN' CHECK(status IN ('OPEN','TARGET_HIT','STOP_LOSS','EXPIRED','CLOSED')),
        exit_date       TEXT,
        exit_price      REAL,
        actual_return_pct REAL,
        days_held       INTEGER,
        created_at      TEXT DEFAULT (datetime('now')),
        UNIQUE(run_date, screener_type, ticker)
    );

    CREATE TABLE IF NOT EXISTS trade_outcomes (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        pick_id         INTEGER NOT NULL REFERENCES picks(id),
        check_date      TEXT NOT NULL,
        current_price   REAL,
        pnl_pct         REAL,
        hit_target      INTEGER DEFAULT 0,
        hit_stop_loss   INTEGER DEFAULT 0,
        max_price_since REAL,
        min_price_since REAL,
        action_taken    TEXT,
        created_at      TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS algo_params (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        screener_type   TEXT NOT NULL CHECK(screener_type IN ('weekly', 'swing')),
        param_name      TEXT NOT NULL,
        param_value     REAL NOT NULL,
        default_value   REAL NOT NULL,
        reason          TEXT,
        updated_at      TEXT DEFAULT (datetime('now')),
        UNIQUE(screener_type, param_name)
    );

    CREATE TABLE IF NOT EXISTS run_log (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        run_date        TEXT NOT NULL,
        screener_type   TEXT NOT NULL,
        stocks_scanned  INTEGER,
        stocks_passed   INTEGER,
        win_rate_at_run REAL,
        params_snapshot TEXT,
        notes           TEXT,
        created_at      TEXT DEFAULT (datetime('now'))
    );

    CREATE INDEX IF NOT EXISTS idx_picks_status ON picks(status);
    CREATE INDEX IF NOT EXISTS idx_picks_screener ON picks(screener_type, run_date);
    CREATE INDEX IF NOT EXISTS idx_picks_ticker ON picks(ticker);
    """)
    conn.commit()


# ─── PICKS ────────────────────────────────────────────────────────────────────

def insert_pick(conn: sqlite3.Connection, data: dict) -> int:
    """Insert a new pick. Returns the row id. Skips if duplicate."""
    try:
        cur = conn.execute("""
            INSERT OR IGNORE INTO picks (
                run_date, screener_type, ticker, last_close, entry_price,
                target, stop_loss, upside_pct, risk_pct, risk_reward,
                confidence, rsi, adx, macd_bullish, vol_spike,
                rel_str_1m, rel_str_3m, pct_from_52w_hi,
                rev_growth, profit_growth, news_sentiment,
                composite_score, rationale, filters_json
            ) VALUES (
                :run_date, :screener_type, :ticker, :last_close, :entry_price,
                :target, :stop_loss, :upside_pct, :risk_pct, :risk_reward,
                :confidence, :rsi, :adx, :macd_bullish, :vol_spike,
                :rel_str_1m, :rel_str_3m, :pct_from_52w_hi,
                :rev_growth, :profit_growth, :news_sentiment,
                :composite_score, :rationale, :filters_json
            )
        """, data)
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        return 0


def get_open_picks(conn: sqlite3.Connection, screener_type: Optional[str] = None) -> List[dict]:
    """Get all open picks, optionally filtered by screener type."""
    if screener_type:
        rows = conn.execute(
            "SELECT * FROM picks WHERE status='OPEN' AND screener_type=? ORDER BY run_date DESC",
            (screener_type,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM picks WHERE status='OPEN' ORDER BY run_date DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def close_pick(conn: sqlite3.Connection, pick_id: int, status: str, exit_price: float,
               exit_date: str, actual_return_pct: float, days_held: int):
    """Close an open pick with outcome."""
    conn.execute("""
        UPDATE picks SET status=?, exit_date=?, exit_price=?,
        actual_return_pct=?, days_held=? WHERE id=?
    """, (status, exit_date, exit_price, actual_return_pct, days_held, pick_id))
    conn.commit()


def get_historical_picks(conn: sqlite3.Connection, screener_type: str,
                         limit: int = 200) -> List[dict]:
    """Get closed picks for performance analysis."""
    rows = conn.execute("""
        SELECT * FROM picks
        WHERE screener_type=? AND status != 'OPEN'
        ORDER BY run_date DESC LIMIT ?
    """, (screener_type, limit)).fetchall()
    return [dict(r) for r in rows]


def get_all_picks_for_ticker(conn: sqlite3.Connection, ticker: str) -> List[dict]:
    rows = conn.execute(
        "SELECT * FROM picks WHERE ticker=? ORDER BY run_date DESC", (ticker,)
    ).fetchall()
    return [dict(r) for r in rows]


# ─── TRADE OUTCOMES ───────────────────────────────────────────────────────────

def insert_outcome(conn: sqlite3.Connection, data: dict):
    conn.execute("""
        INSERT INTO trade_outcomes (
            pick_id, check_date, current_price, pnl_pct,
            hit_target, hit_stop_loss, max_price_since, min_price_since,
            action_taken
        ) VALUES (
            :pick_id, :check_date, :current_price, :pnl_pct,
            :hit_target, :hit_stop_loss, :max_price_since, :min_price_since,
            :action_taken
        )
    """, data)
    conn.commit()


# ─── ALGO PARAMS (self-tuning) ───────────────────────────────────────────────

def get_algo_param(conn: sqlite3.Connection, screener_type: str, param_name: str,
                   default: float) -> float:
    """Get a tuned param value, or return default if not yet tuned."""
    row = conn.execute(
        "SELECT param_value FROM algo_params WHERE screener_type=? AND param_name=?",
        (screener_type, param_name)
    ).fetchone()
    return row["param_value"] if row else default


def set_algo_param(conn: sqlite3.Connection, screener_type: str, param_name: str,
                   value: float, default_value: float, reason: str = ""):
    """Set or update a tuned algo parameter."""
    conn.execute("""
        INSERT INTO algo_params (screener_type, param_name, param_value, default_value, reason, updated_at)
        VALUES (?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(screener_type, param_name) DO UPDATE SET
            param_value=excluded.param_value,
            reason=excluded.reason,
            updated_at=excluded.updated_at
    """, (screener_type, param_name, value, default_value, reason))
    conn.commit()


def get_all_algo_params(conn: sqlite3.Connection, screener_type: str) -> Dict[str, float]:
    rows = conn.execute(
        "SELECT param_name, param_value FROM algo_params WHERE screener_type=?",
        (screener_type,)
    ).fetchall()
    return {r["param_name"]: r["param_value"] for r in rows}


# ─── RUN LOG ──────────────────────────────────────────────────────────────────

def log_run(conn: sqlite3.Connection, screener_type: str, stocks_scanned: int,
            stocks_passed: int, win_rate: Optional[float], params: dict, notes: str = ""):
    conn.execute("""
        INSERT INTO run_log (run_date, screener_type, stocks_scanned, stocks_passed,
                            win_rate_at_run, params_snapshot, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.now().strftime("%Y-%m-%d"),
        screener_type,
        stocks_scanned,
        stocks_passed,
        win_rate,
        json.dumps(params),
        notes,
    ))
    conn.commit()


# ─── PERFORMANCE STATS ───────────────────────────────────────────────────────

def get_performance_stats(conn: sqlite3.Connection, screener_type: str) -> dict:
    """Calculate win rate and average returns from closed trades."""
    rows = conn.execute("""
        SELECT status, actual_return_pct, days_held
        FROM picks
        WHERE screener_type=? AND status != 'OPEN'
    """, (screener_type,)).fetchall()

    if not rows:
        return {"total": 0, "wins": 0, "losses": 0, "win_rate": None,
                "avg_win_return": None, "avg_loss_return": None, "avg_days": None}

    wins = [r for r in rows if r["status"] == "TARGET_HIT"]
    losses = [r for r in rows if r["status"] in ("STOP_LOSS", "EXPIRED")]
    total = len(wins) + len(losses)

    return {
        "total": total,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": (len(wins) / total * 100) if total > 0 else None,
        "avg_win_return": (sum(r["actual_return_pct"] or 0 for r in wins) / len(wins)) if wins else None,
        "avg_loss_return": (sum(r["actual_return_pct"] or 0 for r in losses) / len(losses)) if losses else None,
        "avg_days": (sum(r["days_held"] or 0 for r in rows) / len(rows)) if rows else None,
    }


def get_failure_analysis(conn: sqlite3.Connection, screener_type: str) -> List[dict]:
    """Get details of failed trades for pattern analysis."""
    rows = conn.execute("""
        SELECT ticker, run_date, entry_price, exit_price, stop_loss, target,
               actual_return_pct, days_held, rsi, adx, vol_spike,
               rel_str_1m, pct_from_52w_hi, rev_growth, profit_growth,
               news_sentiment, confidence, rationale
        FROM picks
        WHERE screener_type=? AND status IN ('STOP_LOSS', 'EXPIRED')
        ORDER BY run_date DESC
    """, (screener_type,)).fetchall()
    return [dict(r) for r in rows]
