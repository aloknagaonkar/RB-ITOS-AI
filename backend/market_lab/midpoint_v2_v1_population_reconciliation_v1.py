from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from market_lab import midpoint_break_strength_failure_v2 as strength
from market_lab import midpoint_failure_diagnostics_v2_2 as diagnostics
from market_lab import midpoint_stable_feature_state_machine_v3_2 as state
from market_lab.midpoint_v2_structural_reconstruction_v1 import (
    ALLOWED_DEVELOPMENT_BLOCKS,
    build_leakage_safe_checkpoint_rows,
    build_t3_events,
    load_json,
    prepare_rows,
)

RESEARCH_VERSION = "MIDPOINT_V2_V1_POPULATION_RECONCILIATION_V1"


def event_identity(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("block")),
        str(row.get("session_date")),
        str(row.get("setup_type")),
        str(row.get("direction")),
    )


def labelled_checkpoint_rows(
    framework: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Diagnostic-only reconstruction of the OLD development population.

    This intentionally mirrors the historical labelled development path so we
    can compare it with the new leakage-safe prospective population. These
    labels MUST NOT be used to select V2 trades.
    """
    rows: list[dict[str, Any]] = []

    for event in framework.get("events") or []:
        block = str(event.get("block") or "")
        if block not in ALLOWED_DEVELOPMENT_BLOCKS:
            continue

        outcome = event.get("primary_outcome")
        direction = strength.direction_for_event(event)
        if direction not in {"BULLISH", "BEARISH"}:
            continue
        label = strength.outcome_label(direction, outcome)
        if label not in {"CONTINUATION", "REVERSAL"}:
            continue

        for cp in strength.CHECKPOINTS:
            snap = strength.snapshot_at(event, cp)
            if snap is None:
                continue

            ce = strength.oi_state(snap, "CE")
            pe = strength.oi_state(snap, "PE")
            oi = strength.classify_oi_pair(direction, ce, pe)
            oi.update(
                {
                    "ce_state": ce,
                    "pe_state": pe,
                    "ce_premium_change_5m_pct": strength.first_num(
                        snap,
                        ("ce_5m_premium_change_pct", "ce_premium_change_5m_pct"),
                    ),
                    "ce_oi_change_5m_pct": strength.first_num(
                        snap,
                        ("ce_5m_oi_change_pct", "ce_oi_change_5m_pct"),
                    ),
                    "pe_premium_change_5m_pct": strength.first_num(
                        snap,
                        ("pe_5m_premium_change_pct", "pe_premium_change_5m_pct"),
                    ),
                    "pe_oi_change_5m_pct": strength.first_num(
                        snap,
                        ("pe_5m_oi_change_pct", "pe_oi_change_5m_pct"),
                    ),
                }
            )
            rows.append(
                {
                    "block": block,
                    "session_date": event.get("session_date"),
                    "setup_type": event.get("setup_type"),
                    "direction": direction,
                    "primary_outcome": outcome,
                    "outcome_label": label,
                    "checkpoint_minutes": cp,
                    "checkpoint_label": "T0" if cp == 0 else f"T+{cp}",
                    "timestamp": snap.get("timestamp"),
                    "price_features": strength.extract_features(snap, direction),
                    "oi": oi,
                }
            )
    return rows


def prepare_labelled_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    original = diagnostics.ALLOWED_BLOCKS
    diagnostics.ALLOWED_BLOCKS = set(ALLOWED_DEVELOPMENT_BLOCKS)
    try:
        return diagnostics.prepare_rows(rows)
    finally:
        diagnostics.ALLOWED_BLOCKS = original


def old_labelled_events(
    rows: list[dict[str, Any]],
    rules: dict[str, Any],
) -> list[dict[str, Any]]:
    return state.build_events(rows, rules)


def summarize_event(ev: dict[str, Any]) -> dict[str, Any]:
    return {
        "block": ev.get("block"),
        "session_date": ev.get("session_date"),
        "setup_type": ev.get("setup_type"),
        "direction": ev.get("direction"),
        "t3_state": ev.get("t3_state"),
        "outcome_label": ev.get("outcome_label"),
        "primary_outcome": ev.get("primary_outcome"),
        "t1_observation_state": ev.get("t1_observation_state"),
        "price_pass_ratio": (ev.get("t3_score") or {}).get("price_pass_ratio"),
        "oi_quality": (ev.get("t3_score") or {}).get("oi_quality"),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--framework", required=True)
    ap.add_argument("--frozen-state", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    framework = load_json(Path(args.framework))
    frozen_state = load_json(Path(args.frozen_state))
    rules = frozen_state.get("t3_train_only_rules")
    if not isinstance(rules, dict) or not rules:
        raise SystemExit("Missing frozen t3_train_only_rules")

    # Old labelled development population.
    labelled_rows = prepare_labelled_rows(labelled_checkpoint_rows(framework))
    old_events = old_labelled_events(labelled_rows, rules)
    old_confirmed = [
        e for e in old_events if e.get("t3_state") == "CONFIRM_CONTINUATION"
    ]

    # New leakage-safe prospective population.
    safe_rows, _ = build_leakage_safe_checkpoint_rows(framework)
    safe_prepared = prepare_rows(safe_rows)
    safe_events = build_t3_events(safe_prepared, rules)
    safe_confirmed = [
        e for e in safe_events if e.get("t3_state") == "CONFIRM_CONTINUATION"
    ]

    old_ids = {event_identity(e) for e in old_confirmed}
    safe_ids = {event_identity(e) for e in safe_confirmed}

    safe_only_ids = sorted(safe_ids - old_ids)
    old_only_ids = sorted(old_ids - safe_ids)

    # Map source framework metadata for diagnostic explanation only.
    source_map = {}
    for e in framework.get("events") or []:
        direction = strength.direction_for_event(e)
        if direction not in {"BULLISH", "BEARISH"}:
            continue
        key = (
            str(e.get("block")),
            str(e.get("session_date")),
            str(e.get("setup_type")),
            direction,
        )
        source_map[key] = {
            "primary_outcome": e.get("primary_outcome"),
            "historical_outcome_label": strength.outcome_label(
                direction, e.get("primary_outcome")
            ),
            "boundary_break_timestamp": e.get("boundary_break_timestamp"),
            "continuation_timestamp": e.get("continuation_timestamp"),
            "reclaim_timestamp": e.get("reclaim_timestamp"),
        }

    safe_event_map = {event_identity(e): e for e in safe_confirmed}
    old_event_map = {event_identity(e): e for e in old_confirmed}

    safe_only = []
    for key in safe_only_ids:
        ev = safe_event_map[key]
        safe_only.append(
            {
                **summarize_event(ev),
                "diagnostic_source_metadata": source_map.get(key),
                "reason_for_population_difference": (
                    "PASSED_FROZEN_T3_RULES_IN_LEAKAGE_SAFE_POPULATION_BUT_"
                    "WAS_NOT_ELIGIBLE_UNDER_HISTORICAL_FUTURE_LABEL_FILTER"
                ),
            }
        )

    old_only = []
    for key in old_only_ids:
        ev = old_event_map[key]
        old_only.append(
            {
                **summarize_event(ev),
                "diagnostic_source_metadata": source_map.get(key),
                "reason_for_population_difference": (
                    "HISTORICAL_LABELLED_CONFIRMATION_NOT_PRESENT_IN_"
                    "LEAKAGE_SAFE_RECONSTRUCTION"
                ),
            }
        )

    result = {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "old_labelled_population": {
            "event_count": len(old_events),
            "confirmed_count": len(old_confirmed),
            "t3_state_counts": dict(
                sorted(Counter(str(e.get("t3_state")) for e in old_events).items())
            ),
        },
        "leakage_safe_population": {
            "event_count": len(safe_events),
            "confirmed_count": len(safe_confirmed),
            "t3_state_counts": dict(
                sorted(Counter(str(e.get("t3_state")) for e in safe_events).items())
            ),
        },
        "reconciliation": {
            "common_confirmed_count": len(old_ids & safe_ids),
            "safe_only_confirmed_count": len(safe_only_ids),
            "old_only_confirmed_count": len(old_only_ids),
            "safe_only_confirmed": safe_only,
            "old_only_confirmed": old_only,
        },
        "interpretation_guard": {
            "future_labels_used_for_v2_candidate_selection": False,
            "future_labels_used_only_for_population_reconciliation": True,
            "v1_files_modified": False,
            "pnl_used": False,
            "oos_h_used": False,
            "promotion_allowed_from_this_audit": False,
        },
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
