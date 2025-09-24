
"""Compare two watchlist CSV reports (previous evening ~18:30 and next morning ~09:10)

Purpose:
    - Accept two CSV file paths (evening_report, morning_report)
    - Validate expected columns
    - Compute day-over-day deltas for key metrics
    - Detect target compression / pivot anomalies (e.g., R levels collapsing)
    - Generate a composite BuyRankScore emphasizing improvements + stability
    - Output:
        * Console summary
        * CSV of recommendations (compare_output_YYYY-MM-DD.csv) for morning date
        * Optional Markdown summary

Scoring Heuristics (adjustable):
    - Base: morning Potential_Gainer_Score (normalized)
    - Positive boosts:
        * Score momentum: (MorningScore - EveningScore) / max(|EveningScore|,1)
        * News improvement (Score_News delta > 0)
        * Volume persistence: min(MorningVolumeScore / EveningVolumeScore, 1.5)
    - Negative adjustments:
        * Target compression (Target1_Potential_% drops sharply) -> penalize if morning < 40% of evening and evening > 1%
        * Anomaly penalty if all Target_1..Target_4 equal OR Pivot ordering invalid (detected via Entry_Zone text heuristics)
        * Excess proximity to 52W high (e.g., <5% away) reduces fresh upside

Buy Classification:
    - Strong Buy: BuyRankScore >= 0.75 and no anomaly
    - Buy: 0.55 <= score < 0.75 and no severe anomaly
    - Watch: 0.35 <= score < 0.55 or mild anomaly
    - Avoid: < 0.35 or anomaly severe

Assumptions:
    - Conventional column set produced by intraday_watchlist_generator.py
    - Script kept independent (no import back into generator to avoid circular dependencies for now)

Future Enhancements:
    - Inject configuration JSON for weights
    - Integrate proper pivot/level parsing rather than regex heuristics
"""
from __future__ import annotations

import argparse
import datetime as dt
import math
import os
import re
from dataclasses import dataclass
from typing import List, Dict, Any, Tuple

import pandas as pd

REQUIRED_COLS = [
    'Ticker','Signal','Last_Close','Potential_Gainer_Score','Score_Price','Score_Volume',
    'Score_Momentum','Score_Global','Score_Proximity','Score_VolPenalty','Score_News',
    'Target1_Potential_%','Est_Days_To_Target1','ATR14','AvgAbsPctMove20','Pct_From_52W_High',
    'Entry_Zone','Target_1','Target_2','Target_3','Target_4','Stop_Loss'
]

@dataclass
class AnomalyFlags:
    equal_targets: bool = False
    invalid_entry_zone: bool = False
    target_compression: bool = False
    missing_columns: bool = False

@dataclass
class ComparisonRow:
    ticker: str
    evening_score: float
    morning_score: float
    score_change_pct: float
    evening_target1_pct: float
    morning_target1_pct: float
    target1_change_pct: float
    volume_score_e: float
    volume_score_m: float
    news_e: float
    news_m: float
    proximity_pct_from_high: float
    anomaly: AnomalyFlags
    buy_rank: float
    classification: str


def _safe_float(x) -> float:
    try:
        if x in (None, ''):
            return float('nan')
        return float(str(x).replace('%',''))
    except Exception:
        return float('nan')


def load_watchlist(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")
    df = pd.read_csv(path)
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        # We'll flag later
        print(f"[WARN] Missing columns in {path}: {missing}")
    return df


def detect_anomalies(row: pd.Series, evening_row: pd.Series | None) -> AnomalyFlags:
    flags = AnomalyFlags()
    # Equal targets
    t1, t2, t3, t4 = row.get('Target_1'), row.get('Target_2'), row.get('Target_3'), row.get('Target_4')
    if pd.notna(t1) and t1 == t2 == t3 == t4:
        flags.equal_targets = True

    # Entry zone sanity: expect pattern R1 (...) and Pivot (...)
    ez = str(row.get('Entry_Zone',''))
    pivot_match = re.search(r'Pivot \((\d+\.?\d*)\)', ez)
    r1_match = re.search(r'R1 \((\d+\.?\d*)\)', ez)
    if pivot_match and r1_match:
        pivot_val = float(pivot_match.group(1))
        r1_val = float(r1_match.group(1))
        if pivot_val >= r1_val:
            flags.invalid_entry_zone = True
    else:
        # if we cannot parse both, mark as suspicious
        flags.invalid_entry_zone = True

    # Target compression: big drop of target1 potential
    if evening_row is not None:
        e_pct = _safe_float(evening_row.get('Target1_Potential_%'))
        m_pct = _safe_float(row.get('Target1_Potential_%'))
        if e_pct > 1.0 and m_pct < 0.4 * e_pct:
            flags.target_compression = True
    return flags


def compute_buy_rank(evening_row: pd.Series, morning_row: pd.Series, anomalies: AnomalyFlags) -> Tuple[float, str]:
    # Extract values
    eve_score = _safe_float(evening_row.get('Potential_Gainer_Score'))
    mor_score = _safe_float(morning_row.get('Potential_Gainer_Score'))
    base = mor_score / (eve_score + 1e-6) if eve_score > 0 else 0.0
    base = max(0.0, min(base, 2.0))  # clamp

    # Improvements
    score_change = (mor_score - eve_score) / (abs(eve_score) + 1e-6)
    volume_ratio = 0.0
    eve_vol = _safe_float(evening_row.get('Score_Volume'))
    mor_vol = _safe_float(morning_row.get('Score_Volume'))
    if eve_vol > 0:
        volume_ratio = min(mor_vol / eve_vol, 1.5)

    news_delta = _safe_float(morning_row.get('Score_News')) - _safe_float(evening_row.get('Score_News'))

    # Target1 potentials
    eve_t1 = _safe_float(evening_row.get('Target1_Potential_%'))
    mor_t1 = _safe_float(morning_row.get('Target1_Potential_%'))
    target_compression_penalty = 0.15 if anomalies.target_compression else 0.0

    # Proximity penalty (<5% to 52W high)
    proximity = _safe_float(morning_row.get('Pct_From_52W_High'))
    proximity_penalty = 0.0
    if not math.isnan(proximity):
        if proximity < 5:
            proximity_penalty = 0.15
        elif proximity < 10:
            proximity_penalty = 0.05

    # Anomaly penalties
    anomaly_penalty = 0.0
    if anomalies.equal_targets:
        anomaly_penalty += 0.25
    if anomalies.invalid_entry_zone:
        anomaly_penalty += 0.20

    # Weighting scheme
    score = 0.30 * base + 0.25 * max(score_change, -0.5) + 0.20 * volume_ratio + 0.10 * max(news_delta, 0) + 0.05 * (eve_t1/10 if eve_t1 > 0 else 0) + 0.10 * (mor_t1/5 if mor_t1 > 0 else 0)

    score -= (target_compression_penalty + proximity_penalty + anomaly_penalty)
    score = max(0.0, score)
    # Normalize to 0-1 range (heuristic scaling)
    score = min(score / 1.2, 1.0)

    if anomalies.equal_targets or anomalies.invalid_entry_zone:
        if score < 0.55:
            classification = 'Avoid'
        else:
            classification = 'Watch'
    else:
        if score >= 0.75:
            classification = 'Strong Buy'
        elif score >= 0.55:
            classification = 'Buy'
        elif score >= 0.35:
            classification = 'Watch'
            
        else:
            classification = 'Avoid'
    return score, classification


def compare_watchlists(evening_csv: str, morning_csv: str, output_markdown: bool = True) -> pd.DataFrame:
    eve = load_watchlist(evening_csv)
    mor = load_watchlist(morning_csv)
    # Align on tickers present in both
    common = sorted(set(eve['Ticker']).intersection(set(mor['Ticker'])))
    rows: List[Dict[str, Any]] = []

    eve_index = eve.set_index('Ticker')
    mor_index = mor.set_index('Ticker')

    for t in common:
        e_row = eve_index.loc[t]
        m_row = mor_index.loc[t]
        anomalies = detect_anomalies(m_row, e_row)
        buy_rank, classification = compute_buy_rank(e_row, m_row, anomalies)
        rows.append({
            'Ticker': t,
            'Evening_Score': _safe_float(e_row.get('Potential_Gainer_Score')),
            'Morning_Score': _safe_float(m_row.get('Potential_Gainer_Score')),
            'Score_Change_%': (( _safe_float(m_row.get('Potential_Gainer_Score')) - _safe_float(e_row.get('Potential_Gainer_Score')) ) / (abs(_safe_float(e_row.get('Potential_Gainer_Score'))) + 1e-6))*100,
            'Evening_Target1_%': _safe_float(e_row.get('Target1_Potential_%')),
            'Morning_Target1_%': _safe_float(m_row.get('Target1_Potential_%')),
            'Target1_Change_%': (( _safe_float(m_row.get('Target1_Potential_%')) - _safe_float(e_row.get('Target1_Potential_%')) ) / (abs(_safe_float(e_row.get('Target1_Potential_%'))) + 1e-6))*100 if _safe_float(e_row.get('Target1_Potential_%'))>0 else float('nan'),
            'Volume_Score_E': _safe_float(e_row.get('Score_Volume')),
            'Volume_Score_M': _safe_float(m_row.get('Score_Volume')),
            'News_E': _safe_float(e_row.get('Score_News')),
            'News_M': _safe_float(m_row.get('Score_News')),
            'Pct_From_52W_High': _safe_float(m_row.get('Pct_From_52W_High')),
            'Equal_Targets_Flag': anomalies.equal_targets,
            'Invalid_Entry_Flag': anomalies.invalid_entry_zone,
            'Target_Compression_Flag': anomalies.target_compression,
            'BuyRankScore': round(buy_rank,4),
            'Classification': classification
        })

    result_df = pd.DataFrame(rows)
    result_df.sort_values(['Classification','BuyRankScore'], ascending=[True, False], inplace=True)

    # Save outputs
    morning_date = _infer_date_from_filename(morning_csv)
    out_csv = f"compare_output_{morning_date}.csv" if morning_date else "compare_output.csv"
    result_df.to_csv(out_csv, index=False)
    print(f"[INFO] Comparison written to {out_csv}")

    if output_markdown:
        md_path = out_csv.replace('.csv', '.md')
        _write_markdown(md_path, evening_csv, morning_csv, result_df)
        print(f"[INFO] Markdown summary written to {md_path}")
    return result_df


def _infer_date_from_filename(path: str) -> str | None:
    base = os.path.basename(path)
    m = re.search(r'(\d{4}-\d{2}-\d{2})', base)
    return m.group(1) if m else None


def _write_markdown(path: str, evening_csv: str, morning_csv: str, df: pd.DataFrame) -> None:
    lines = []
    lines.append(f"# Watchlist Comparison\n")
    lines.append(f"Evening file: `{os.path.basename(evening_csv)}`  ")
    lines.append(f"Morning file: `{os.path.basename(morning_csv)}`\n")
    lines.append("### Summary\n")
    lines.append(f"Tickers compared: {len(df)}\n")
    anomalies = df[(df['Equal_Targets_Flag']) | (df['Invalid_Entry_Flag']) | (df['Target_Compression_Flag'])]
    if not anomalies.empty:
        lines.append("Detected anomalies in: " + ", ".join(anomalies['Ticker'].tolist()) + "\n")
    lines.append("\n### Rankings\n")
    display_cols = ['Ticker','Classification','BuyRankScore','Evening_Score','Morning_Score','Score_Change_%','Evening_Target1_%','Morning_Target1_%','Target1_Change_%','Volume_Score_E','Volume_Score_M','News_E','News_M','Pct_From_52W_High','Equal_Targets_Flag','Invalid_Entry_Flag','Target_Compression_Flag']
    sub = df[display_cols].copy()
    lines.append(sub.to_markdown(index=False))
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def main():
    parser = argparse.ArgumentParser(description='Compare evening and morning watchlist CSVs and produce buy recommendations.')
    parser.add_argument('--evening', required=True, help='Path to evening (previous day 18:30) CSV')
    parser.add_argument('--morning', required=True, help='Path to morning (current day 09:10) CSV')
    parser.add_argument('--no-markdown', action='store_true', help='Disable markdown output')
    args = parser.parse_args()

    compare_watchlists(args.evening, args.morning, output_markdown=not args.no_markdown)

if __name__ == '__main__':
    main()
