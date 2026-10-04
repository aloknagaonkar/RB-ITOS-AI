#!/usr/bin/env python3
"""Validate Hilega entry-filter observations for explicitly selected sessions.

Replays the unchanged canonical directional coordinator from immutable cached
one-minute NIFTY candles, rebuilds causal entry indicators, attaches the three
research candidate decisions, and compares replay events with the recorded
directional audit when it is available.  NIFTY points only; no option P&L.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from market_lab.hilega_directional_coordinator_v1 import (
    BEARISH_ENTRY_EVENTS,
    BEARISH_EXIT_EVENTS,
    BULLISH_ENTRY_EVENTS,
    BULLISH_EXIT_EVENTS,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE = Path(
    "data/historical-evidence/hilega-milega-underlying-cache-v1"
)
DEFAULT_AUDIT = Path(
    "data/live-observation/hilega-directional-v1/step-audit.jsonl"
)
DEFAULT_OUTPUT = Path(
    "data/historical-evidence/hilega-entry-filter-date-validation-v1"
)
DEFAULT_DATES = ("2026-09-30", "2026-10-01")
FLAT_EPSILON = 0.10


def load_script(name: str, filename: str):
    path = ROOT / "scripts" / filename
    if not path.is_file():
        raise FileNotFoundError(path)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def validate_dates(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        day = date.fromisoformat(value)
        text = day.isoformat()
        if text not in result:
            result.append(text)
    if not result:
        raise ValueError("at least one date is required")
    return sorted(result)


def build_feature_lookup(cache_root: Path, through: str, audit_module):
    bars_by_day: dict[str, list[Any]] = {}
    diagnostics: list[dict[str, Any]] = []
    for path in sorted(cache_root.glob("*.json")):
        try:
            session = date.fromisoformat(path.stem).isoformat()
        except ValueError:
            continue
        if session > through:
            continue
        minutes, source_diagnostics = audit_module.load_minutes(path)
        bars, issues = audit_module.aggregate_five_minute(
            minutes, date.fromisoformat(session)
        )
        if issues or len(bars) != 75:
            diagnostics.append({
                "session_date": session,
                "status": "EXCLUDED_INCOMPLETE",
                "five_minute_bars": len(bars),
                "issues": issues,
                "source_diagnostics": source_diagnostics,
            })
            continue
        bars_by_day[session] = bars

    if not bars_by_day:
        raise ValueError(f"no complete cached sessions through {through}")
    features, indicator_diagnostics = audit_module.feature_rows(
        bars_by_day,
        slope_window=3,
        flat_epsilon=FLAT_EPSILON,
        label_horizon=3,
        atr_multiple=0.50,
    )
    lookup: dict[tuple[str, str], dict[str, Any]] = {}
    for row in features:
        stamp = str(row["timestamp"])
        lookup[(str(row["session_date"]), stamp[11:16])] = row
    return sorted(bars_by_day), lookup, diagnostics, indicator_diagnostics


def attach_candidates(trade: dict[str, Any], filters_module) -> dict[str, Any]:
    enriched = filters_module.enrich(trade)
    required = filters_module.RAW_FEATURES
    missing = [name for name in required if enriched.get(name) is None]
    if missing:
        return {
            **enriched,
            "candidate_status": "UNAVAILABLE",
            "candidate_issue": "MISSING_ENTRY_FEATURES:" + ",".join(missing),
            "wma_flat_warning": None,
            "large_gain_alignment_keep": None,
            "alignment_support_count": None,
            "alignment_candidate_points": None,
            "flat_confirmation_reject": None,
            "flat_confirmation_keep": None,
            "flat_weakness_count": None,
            "flat_weakness_reasons": "",
            "flat_confirmation_candidate_points": None,
        }
    decision = filters_module.evaluate_entry(enriched)
    return {
        **enriched,
        **decision,
        "candidate_status": "AVAILABLE",
        "candidate_issue": None,
        "alignment_candidate_points": (
            float(enriched["captured_points"])
            if decision["large_gain_alignment_keep"] else 0.0
        ),
        "flat_confirmation_candidate_points": (
            float(enriched["captured_points"])
            if decision["flat_confirmation_keep"] else 0.0
        ),
    }


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows


def event_direction(event: str) -> str | None:
    if event in BULLISH_ENTRY_EVENTS or event in BULLISH_EXIT_EVENTS:
        return "BULLISH"
    if event in BEARISH_ENTRY_EVENTS or event in BEARISH_EXIT_EVENTS:
        return "BEARISH"
    return None


def recorded_events(path: Path, selected_dates: set[str]) -> set[tuple[str, str, str]]:
    result: set[tuple[str, str, str]] = set()
    for row in read_jsonl(path):
        stage = str(row.get("stage") or "")
        if stage not in {"DIRECTIONAL_DECISION", "DIRECTIONAL_SESSION_CUTOFF"}:
            continue
        payload = row.get("payload") or {}
        timestamp = payload.get("bar_timestamp") or payload.get("cutoff_timestamp")
        if not isinstance(timestamp, str) or timestamp[:10] not in selected_dates:
            continue
        for event in payload.get("accepted_events") or []:
            direction = event_direction(str(event))
            if direction is not None:
                result.add((timestamp, str(event), direction))
    return result


def replay_events(trades: list[dict[str, Any]]) -> set[tuple[str, str, str]]:
    result: set[tuple[str, str, str]] = set()
    for trade in trades:
        result.add((
            str(trade["entry_timestamp"]),
            str(trade["entry_event"]),
            str(trade["direction"]),
        ))
        result.add((
            str(trade["exit_timestamp"]),
            str(trade["exit_event"]),
            str(trade["direction"]),
        ))
    return result


def event_parity(
    trades: list[dict[str, Any]], audit_path: Path, selected_dates: set[str]
) -> dict[str, Any]:
    replayed = replay_events(trades)
    recorded = recorded_events(audit_path, selected_dates)
    if not recorded:
        return {
            "status": "RECORDED_AUDIT_UNAVAILABLE",
            "replayed_event_count": len(replayed),
            "recorded_event_count": 0,
            "matched": 0,
            "only_replayed": sorted(replayed),
            "only_recorded": [],
        }
    return {
        "status": "PASS" if replayed == recorded else "DIFFERENCE",
        "replayed_event_count": len(replayed),
        "recorded_event_count": len(recorded),
        "matched": len(replayed & recorded),
        "only_replayed": sorted(replayed - recorded),
        "only_recorded": sorted(recorded - replayed),
    }


def daily_summary(rows: list[dict[str, Any]], selected_dates: list[str]):
    output: list[dict[str, Any]] = []
    for session in selected_dates:
        trades = [row for row in rows if row["session_date"] == session]
        control = sum(float(row["captured_points"]) for row in trades)
        available = [
            row for row in trades if row.get("candidate_status") == "AVAILABLE"
        ]
        unavailable = [
            row for row in trades if row.get("candidate_status") != "AVAILABLE"
        ]
        comparable_control = sum(
            float(row["captured_points"]) for row in available
        )
        alignment = sum(
            float(row.get("alignment_candidate_points") or 0.0)
            for row in available
        )
        confirmation = sum(
            float(row.get("flat_confirmation_candidate_points") or 0.0)
            for row in available
        )
        output.append({
            "session_date": session,
            "signals": len(trades),
            "bullish": sum(row["direction"] == "BULLISH" for row in trades),
            "bearish": sum(row["direction"] == "BEARISH" for row in trades),
            "control_points_all_signals": control,
            "candidate_available_signals": len(available),
            "candidate_unavailable_signals": len(unavailable),
            "candidate_comparable_control_points": comparable_control,
            "large_gain_alignment_points_available": alignment,
            "large_gain_alignment_delta_available": alignment - comparable_control,
            "flat_confirmation_points_available": confirmation,
            "flat_confirmation_delta_available": confirmation - comparable_control,
            "flat_wma_warnings": sum(
                row.get("wma_flat_warning") is True for row in trades
            ),
            "alignment_kept": sum(
                row.get("large_gain_alignment_keep") is True for row in trades
            ),
            "flat_confirmation_rejected": sum(
                row.get("flat_confirmation_reject") is True for row in trades
            ),
        })
    return output


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                fields.append(key)
                seen.add(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def yn(value: Any) -> str:
    if value is None:
        return "UNAVAILABLE"
    return "KEEP" if bool(value) else "REJECT"


def number_text(value: Any, *, signed: bool = False) -> str:
    if value in (None, ""):
        return "UNAVAILABLE"
    number = float(value)
    return f"{number:+.4f}" if signed else f"{number:.4f}"


def print_trade(index: int, row: dict[str, Any]) -> None:
    print(f"SIGNAL {index} {row['session_date']} {row['direction']} {row['route']}")
    print(
        "  entry", row["entry_timestamp"], f"NIFTY={float(row['entry_price']):.2f}",
        row["entry_event"],
    )
    print(
        "  exit ", row["exit_timestamp"], f"NIFTY={float(row['exit_price']):.2f}",
        row["exit_event"],
    )
    print(
        "  points",
        f"captured={float(row['captured_points']):+.2f}",
        f"MFE={float(row['mfe_points']):+.2f}",
        f"MAE={float(row['mae_points']):+.2f}",
        f"giveback={float(row['giveback_points']):+.2f}",
    )
    print(
        "  indicators",
        f"RSI9={number_text(row.get('entry_rsi9'))}",
        f"EMA3={number_text(row.get('entry_ema3_rsi'))}",
        f"WMA21={number_text(row.get('entry_wma21_rsi'))}",
        f"gap={number_text(row.get('entry_ema_minus_wma'), signed=True)}",
    )
    print(
        "  slopes",
        f"RSI={number_text(row.get('entry_rsi9_slope_3'), signed=True)}",
        f"EMA={number_text(row.get('entry_ema3_rsi_slope_3'), signed=True)}",
        f"WMA={number_text(row.get('entry_wma21_rsi_slope_3'), signed=True)}",
        f"gap={number_text(row.get('entry_ema_minus_wma_slope_3'), signed=True)}",
    )
    if row.get("candidate_status") != "AVAILABLE":
        print(
            "  observations",
            "candidate=UNAVAILABLE",
            f"issue={row.get('candidate_issue')}",
            "control_points_preserved=true",
        )
        return
    print(
        "  observations",
        f"flat_warning={row['wma_flat_warning']}",
        f"alignment={yn(row['large_gain_alignment_keep'])}",
        f"support={row['alignment_support_count']}/5",
        f"flat_confirmation={yn(row['flat_confirmation_keep'])}",
        f"weakness={row['flat_weakness_count']}/3",
        f"reasons={row['flat_weakness_reasons'] or 'NONE'}",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dates", nargs="+", default=list(DEFAULT_DATES))
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--live-audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    selected_dates = validate_dates(args.dates)
    audit_module = load_script(
        "hilega_indicator_audit_for_dates", "audit_hilega_indicator_dataset_v2.py"
    )
    alignment_module = load_script(
        "hilega_alignment_for_dates", "research_hilega_alignment_points_490.py"
    )
    filters_module = load_script(
        "hilega_filters_for_dates", "research_hilega_entry_filter_candidates.py"
    )

    sessions, feature_lookup, excluded, indicator_diagnostics = build_feature_lookup(
        args.cache_root, max(selected_dates), audit_module
    )
    missing = [session for session in selected_dates if session not in sessions]
    if missing:
        raise SystemExit(
            "STOP: complete cached NIFTY session unavailable for " + ", ".join(missing)
        )

    trades, _ = alignment_module.replay(
        cache_root=args.cache_root,
        all_sessions=sessions,
        analysis_sessions=selected_dates,
        feature_lookup=feature_lookup,
        flat_epsilon=FLAT_EPSILON,
    )
    selected = [
        attach_candidates(trade, filters_module)
        for trade in trades
        if trade["session_date"] in set(selected_dates)
    ]
    unavailable = [row for row in selected if row["candidate_status"] != "AVAILABLE"]

    parity = event_parity(selected, args.live_audit, set(selected_dates))
    summary = daily_summary(selected, selected_dates)
    args.output_root.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_root / "signal-details.csv", selected)
    write_csv(args.output_root / "daily-summary.csv", summary)
    report = {
        "model": "HILEGA_ENTRY_FILTER_DATE_VALIDATION_V1",
        "dates": selected_dates,
        "measurement": "NIFTY_DIRECTIONAL_POINTS",
        "signals": selected,
        "daily_summary": summary,
        "recorded_audit_parity": parity,
        "feature_diagnostics": indicator_diagnostics,
        "excluded_incomplete_cache_sessions": excluded,
        "safety": {
            "research_only": True,
            "observation_only": True,
            "live_strategy_modified": False,
            "execution_enabled": False,
            "paper_order_enabled": False,
            "quantity": None,
            "order_sent": False,
        },
    }
    (args.output_root / "report.json").write_text(
        json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8"
    )

    print("HILEGA DATE VALIDATION", selected_dates, "signals", len(selected))
    print("Candidate unavailable signals:", len(unavailable))
    for row in unavailable:
        print(
            "  UNAVAILABLE",
            row["session_date"], row["entry_timestamp"], row["direction"],
            row["candidate_issue"],
        )
    print("Recorded audit parity:", parity)
    for index, row in enumerate(selected, start=1):
        print_trade(index, row)
    print("DAILY SUMMARY")
    for row in summary:
        print(row)
    print("Output:", args.output_root / "report.json")
    print("Read only: live strategy, audits, services and orders untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
