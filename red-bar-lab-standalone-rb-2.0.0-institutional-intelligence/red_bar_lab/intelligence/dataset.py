from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Iterable

import pandas as pd

from red_bar_lab.strategy.signal_view import sequence_signal_attempts
from red_bar_lab.strategy.trade_outcome import (
    benchmark_summary,
    summarize_actionable_models,
)

ENTRY_FEATURE_COLUMNS = (
    "signal_id","signal_label","signal_sequence","level_type","direction",
    "trading_date","entry_timestamp","entry_hour","entry_minute","weekday",
    "entry_price","level_value","cross_timestamp",
    "confirmation_delay_minutes","cross_open","cross_high","cross_low",
    "cross_close","confirmation_open","confirmation_high","confirmation_low",
    "confirmation_close","risk_points",
    "session_open","previous_close","previous_high","previous_low",
    "gap_points","gap_pct","minutes_from_open",
    "price_from_open_points","price_from_open_pct",
    "session_high_so_far","session_low_so_far","session_range_so_far",
    "session_range_position","distance_to_previous_high",
    "distance_to_previous_low","opening_range_15_high","opening_range_15_low",
    "opening_range_15_position","atr14_5m","ema9_5m","ema21_5m",
    "trend_5m","realized_volatility_30m_pct",
    "volume_current_1m","volume_avg_20m","relative_volume_20m",
    "volume_trend_5m","price_volume_state",
    "compression_ratio_20m","structure_state","breakout_strength",
    "range_width_20m","higher_high_count_20m","lower_low_count_20m",
    "bullish_structure_score","bearish_structure_score",
    "options_entry_aligned",
    "option_expiry","option_snapshot_timestamp",
    "option_snapshot_delay_seconds","option_spot_price","atm_strike",
    "total_call_oi","total_put_oi","pcr_oi",
    "total_call_oi_change","total_put_oi_change","pcr_oi_change",
    "call_wall_strike","put_wall_strike","max_pain_strike",
    "atm_call_iv","atm_put_iv","atm_call_delta","atm_put_delta",
    "atm_call_gamma","atm_put_gamma","atm_call_theta","atm_put_theta",
    "atm_call_vega","atm_put_vega",
)

POST_TRADE_LABEL_COLUMNS = (
    "actionable_total","actionable_success","actionable_failed",
    "actionable_breakeven","actionable_success_rate_pct","signal_quality",
    "best_actionable_exit","best_actionable_points","worst_actionable_exit",
    "worst_actionable_points","actionable_completed_at","mfe_points",
    "mae_points","benchmark_status","benchmark_final_points",
    "benchmark_mfe","benchmark_mae",
)

FORBIDDEN_PREDICTION_COLUMNS = set(POST_TRADE_LABEL_COLUMNS) | {
    "current_price","live_points","targets_hit","next_target",
    "points_to_next_target","quality_explanation","actionable_score",
    "quality_band","quality_symbol",
}

_CONTEXT_FIELDS = (
    "session_open","previous_close","previous_high","previous_low",
    "gap_points","gap_pct","minutes_from_open",
    "price_from_open_points","price_from_open_pct",
    "session_high_so_far","session_low_so_far","session_range_so_far",
    "session_range_position","distance_to_previous_high",
    "distance_to_previous_low","opening_range_15_high","opening_range_15_low",
    "opening_range_15_position","atr14_5m","ema9_5m","ema21_5m",
    "trend_5m","realized_volatility_30m_pct",
)


def _ts(value):
    if value in (None, ""):
        return None
    try:
        return pd.Timestamp(value)
    except Exception:
        return None


def _risk(signal):
    entry = signal.get("underlying_entry")
    if entry is None:
        return None
    if signal.get("direction") == "BULLISH":
        stop = signal.get("cross_low")
    elif signal.get("direction") == "BEARISH":
        stop = signal.get("cross_high")
    else:
        return None
    return (
        abs(float(entry) - float(stop))
        if stop is not None else None
    )


def build_training_rows(
    signal_rows,
    trade_rows,
    context_rows=None,
    volume_structure_rows=None,
    feature_rows=None,
):
    sequenced = sequence_signal_attempts(signal_rows)
    grouped = defaultdict(list)
    for row in trade_rows:
        if row.get("signal_id"):
            grouped[str(row["signal_id"])].append(row)

    context_by_signal = {
        str(row.get("signal_id")): row
        for row in (context_rows or [])
        if row.get("signal_id")
    }
    volume_structure_by_signal = {
        str(row.get("signal_id")): row
        for row in (volume_structure_rows or [])
        if row.get("signal_id")
    }
    feature_by_signal = {
        str(row.get("signal_id")): row
        for row in (feature_rows or [])
        if row.get("signal_id")
    }

    out = []
    for signal in sequenced:
        signal_id = str(signal.get("signal_id") or "")
        if not signal_id:
            continue

        linked = grouped.get(signal_id, [])
        actionable = summarize_actionable_models(linked)
        if actionable.get("signal_lifecycle") != "COMPLETED":
            continue

        benchmark = benchmark_summary(linked)
        entry = _ts(signal.get("confirmation_timestamp"))
        cross = _ts(signal.get("cross_timestamp"))
        context = context_by_signal.get(signal_id, {})
        volume_structure = volume_structure_by_signal.get(
            signal_id, {}
        )
        feature_store_row = feature_by_signal.get(signal_id, {})

        mfe = [
            float(r["session_mfe_points"])
            for r in linked
            if str(r.get("exit_model")) != "EOD_HOLD"
            and r.get("session_mfe_points") is not None
        ]
        mae = [
            float(r["session_mae_points"])
            for r in linked
            if str(r.get("exit_model")) != "EOD_HOLD"
            and r.get("session_mae_points") is not None
        ]

        row = {
            "signal_id": signal_id,
            "signal_label": signal.get("signal_label"),
            "signal_sequence": signal.get("signal_sequence"),
            "level_type": signal.get("level_type"),
            "direction": signal.get("direction"),
            "trading_date": signal.get("trading_date"),
            "entry_timestamp": entry.isoformat() if entry is not None else None,
            "entry_hour": entry.hour if entry is not None else None,
            "entry_minute": entry.minute if entry is not None else None,
            "weekday": entry.day_name() if entry is not None else None,
            "entry_price": signal.get("underlying_entry"),
            "level_value": signal.get("level_value"),
            "cross_timestamp": cross.isoformat() if cross is not None else None,
            "confirmation_delay_minutes": signal.get(
                "confirmation_delay_minutes"
            ),
            "cross_open": signal.get("cross_open"),
            "cross_high": signal.get("cross_high"),
            "cross_low": signal.get("cross_low"),
            "cross_close": signal.get("cross_close"),
            "confirmation_open": signal.get("confirmation_open"),
            "confirmation_high": signal.get("confirmation_high"),
            "confirmation_low": signal.get("confirmation_low"),
            "confirmation_close": signal.get("confirmation_close"),
            "risk_points": _risk(signal),

            "actionable_total": actionable.get("actionable_total"),
            "actionable_success": actionable.get("actionable_success"),
            "actionable_failed": actionable.get("actionable_failed"),
            "actionable_breakeven": actionable.get("actionable_breakeven"),
            "actionable_success_rate_pct": actionable.get(
                "actionable_success_rate_pct"
            ),
            "signal_quality": actionable.get("signal_quality"),
            "best_actionable_exit": actionable.get("best_actionable_exit"),
            "best_actionable_points": actionable.get(
                "best_actionable_points"
            ),
            "worst_actionable_exit": actionable.get(
                "worst_actionable_exit"
            ),
            "worst_actionable_points": actionable.get(
                "worst_actionable_points"
            ),
            "actionable_completed_at": actionable.get(
                "actionable_completed_at"
            ),
            "mfe_points": max(mfe) if mfe else None,
            "mae_points": max(mae) if mae else None,
            "benchmark_status": benchmark.get("benchmark_status"),
            "benchmark_final_points": benchmark.get(
                "benchmark_final_points"
            ),
            "benchmark_mfe": benchmark.get("benchmark_mfe"),
            "benchmark_mae": benchmark.get("benchmark_mae"),
        }

        for field in ENTRY_FEATURE_COLUMNS:
            if field in row:
                continue
            if feature_store_row:
                row[field] = feature_store_row.get(field)
            elif field in _CONTEXT_FIELDS:
                row[field] = context.get(field)
            else:
                row[field] = volume_structure.get(field)

        out.append(row)

    out.sort(
        key=lambda r: (
            str(r.get("trading_date") or ""),
            str(r.get("entry_timestamp") or ""),
            str(r.get("signal_id") or ""),
        )
    )
    return out


def prediction_feature_frame(rows):
    frame = pd.DataFrame(list(rows))
    for col in ENTRY_FEATURE_COLUMNS:
        if col not in frame.columns:
            frame[col] = None
    return frame.loc[:, list(ENTRY_FEATURE_COLUMNS)].copy()


def label_frame(rows):
    frame = pd.DataFrame(list(rows))
    for col in POST_TRADE_LABEL_COLUMNS:
        if col not in frame.columns:
            frame[col] = None
    return frame.loc[:, list(POST_TRADE_LABEL_COLUMNS)].copy()


def validate_no_lookahead_features(columns: Iterable[str]) -> None:
    bad = sorted(set(columns) & FORBIDDEN_PREDICTION_COLUMNS)
    if bad:
        raise ValueError(
            "Look-ahead features are forbidden for prediction: "
            + ", ".join(bad)
        )


def write_training_dataset(rows, output_path: Path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(output_path, index=False)
    return output_path
