"""False-positive diagnostics for frozen midpoint V3.2 confirmations.

Purpose
-------
Explain the small set of V3.2 T+3 CONFIRM_CONTINUATION events whose future
structural outcome was REVERSAL, without changing the frozen V3.2 rule.

Inputs
------
- MIDPOINT_STABLE_FEATURE_STATE_MACHINE_V3_2 JSON
- MIDPOINT_FAILURE_DIAGNOSTICS_V2_2 JSON
- MIDPOINT_V3_2_EXACT_OPTION_ECONOMICS_V1 JSON

This module:
- identifies confirmed true continuations vs confirmed structural false positives;
- compares the exact T+3 observable features that existed at decision time;
- compares T+1 observation state, OI quality, exact OI transition, and block;
- attributes option-economic damage descriptively;
- never promotes a filter or changes the V3.2 state machine.

No OOS_E/F/G/H. OOS-H remains pristine.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any, Sequence

RESEARCH_VERSION = "MIDPOINT_V3_2_FALSE_POSITIVE_DIAGNOSTICS_V1"
STATE_VERSION = "MIDPOINT_STABLE_FEATURE_STATE_MACHINE_V3_2"
DIAG_VERSION = "MIDPOINT_FAILURE_DIAGNOSTICS_V2_2"
ECON_VERSION = "MIDPOINT_V3_2_EXACT_OPTION_ECONOMICS_V1"
ALLOWED_BLOCKS = {"TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D"}

FEATURES = (
    "acceptance_pct",
    "momentum_5m_directional",
    "progress_points",
    "giveback_from_best_checkpoint_points",
    "consecutive_closes",
    "velocity",
)

def load_json(path: Path) -> dict[str, Any]:
    x = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(x, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return x

def finite(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None

def normalize_block(v: Any) -> str:
    return str(v).strip().upper().replace("-", "_")

def event_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        normalize_block(row.get("block")),
        str(row.get("session_date")),
        str(row.get("setup_type")),
        str(row.get("primary_outcome")),
    )

def validate(state: dict[str, Any], diag: dict[str, Any], econ: dict[str, Any]) -> None:
    expected = (
        ("state", state, STATE_VERSION),
        ("diagnostics", diag, DIAG_VERSION),
        ("economics", econ, ECON_VERSION),
    )
    for name, payload, version in expected:
        if payload.get("research_version") != version:
            raise ValueError(
                f"{name} must be {version}, got {payload.get('research_version')!r}"
            )
        guard = payload.get("leakage_guard") or {}
        if guard.get("oos_e_f_g_h_used") is not False:
            raise ValueError(f"{name} does not prove E/F/G/H excluded")
        if guard.get("oos_h_used") is not False:
            raise ValueError(f"{name} does not prove H excluded")

def stats(values: Sequence[float]) -> dict[str, Any]:
    vals = [v for v in values if v is not None and math.isfinite(v)]
    if not vals:
        return {"count": 0, "mean": None, "median": None, "min": None, "max": None}
    return {
        "count": len(vals),
        "mean": sum(vals) / len(vals),
        "median": median(vals),
        "min": min(vals),
        "max": max(vals),
    }

def feature_values(rows: Sequence[dict[str, Any]], feature: str) -> list[float]:
    out = []
    for r in rows:
        v = finite((r.get("price_features") or {}).get(feature))
        if v is not None:
            out.append(v)
    return out

def summarize_feature_groups(
    true_rows: Sequence[dict[str, Any]],
    false_rows: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    out = {}
    for feature in FEATURES:
        t = stats(feature_values(true_rows, feature))
        f = stats(feature_values(false_rows, feature))
        out[feature] = {
            "true_continuation": t,
            "false_positive_reversal": f,
            "median_gap_true_minus_false": (
                t["median"] - f["median"]
                if t["median"] is not None and f["median"] is not None
                else None
            ),
        }
    return out

def economic_summary(trades: Sequence[dict[str, Any]]) -> dict[str, Any]:
    out = {"count": len(trades)}
    for h in (1, 3, 5, 10, 15):
        gross = [
            finite((r.get("gross_returns_pct") or {}).get(f"{h}m"))
            for r in trades
        ]
        net = [
            finite((r.get("net_returns_pct") or {}).get(f"{h}m"))
            for r in trades
        ]
        gross = [v for v in gross if v is not None]
        net = [v for v in net if v is not None]
        out[f"gross_{h}m"] = stats(gross)
        out[f"net_{h}m"] = stats(net)

    mfe = [finite(r.get("mfe_pct_15m")) for r in trades]
    mae = [finite(r.get("mae_pct_15m")) for r in trades]
    out["mfe_15m"] = stats([v for v in mfe if v is not None])
    out["mae_15m"] = stats([v for v in mae if v is not None])
    return out

def analyze(
    state: dict[str, Any],
    diag: dict[str, Any],
    econ: dict[str, Any],
) -> dict[str, Any]:
    validate(state, diag, econ)

    confirmed = [
        e for e in state.get("events", [])
        if e.get("t3_state") == "CONFIRM_CONTINUATION"
    ]

    t3_rows = {}
    for r in diag.get("rows", []):
        if int(r.get("checkpoint_minutes", -1)) != 3:
            continue
        t3_rows[event_key(r)] = r

    econ_rows = {}
    for r in econ.get("trades", []):
        econ_rows[event_key(r)] = r

    true_events = [
        e for e in confirmed if e.get("outcome_label") == "CONTINUATION"
    ]
    false_events = [
        e for e in confirmed if e.get("outcome_label") == "REVERSAL"
    ]

    true_t3 = [t3_rows[event_key(e)] for e in true_events if event_key(e) in t3_rows]
    false_t3 = [t3_rows[event_key(e)] for e in false_events if event_key(e) in t3_rows]
    true_econ = [econ_rows[event_key(e)] for e in true_events if event_key(e) in econ_rows]
    false_econ = [econ_rows[event_key(e)] for e in false_events if event_key(e) in econ_rows]

    def event_summary(events: Sequence[dict[str, Any]]) -> dict[str, Any]:
        return {
            "count": len(events),
            "by_direction": dict(Counter(str(e.get("direction")) for e in events)),
            "by_block": dict(Counter(normalize_block(e.get("block")) for e in events)),
            "t1_observation_state": dict(Counter(
                str(e.get("t1_observation_state")) for e in events
            )),
            "oi_quality": dict(Counter(
                str((e.get("t3_score") or {}).get("oi_quality"))
                for e in events
            )),
            "exact_oi_transition_t1_to_t3": dict(Counter(
                str(e.get("exact_oi_transition_t1_to_t3"))
                for e in events
            )),
        }

    false_details = []
    for e in false_events:
        key = event_key(e)
        d = t3_rows.get(key, {})
        p = econ_rows.get(key, {})
        false_details.append({
            "block": normalize_block(e.get("block")),
            "session_date": e.get("session_date"),
            "direction": e.get("direction"),
            "setup_type": e.get("setup_type"),
            "primary_outcome": e.get("primary_outcome"),
            "t1_observation_state": e.get("t1_observation_state"),
            "oi_quality": (e.get("t3_score") or {}).get("oi_quality"),
            "exact_oi_transition_t1_to_t3": e.get(
                "exact_oi_transition_t1_to_t3"
            ),
            "t3_price_features": {
                feature: (d.get("price_features") or {}).get(feature)
                for feature in FEATURES
            },
            "t3_price_pass_ratio": (e.get("t3_score") or {}).get(
                "price_pass_ratio"
            ),
            "gross_returns_pct": p.get("gross_returns_pct"),
            "net_returns_pct": p.get("net_returns_pct"),
            "mfe_pct_15m": p.get("mfe_pct_15m"),
            "mae_pct_15m": p.get("mae_pct_15m"),
            "target_stop": p.get("target_stop"),
        })

    return {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "state_machine_version": STATE_VERSION,
        "confirmed_candidate_count": len(confirmed),
        "true_continuation_confirmed_count": len(true_events),
        "false_positive_reversal_confirmed_count": len(false_events),
        "confirm_precision_recomputed": (
            len(true_events) / len(confirmed) if confirmed else None
        ),
        "true_confirmation_profile": event_summary(true_events),
        "false_positive_profile": event_summary(false_events),
        "t3_feature_comparison": summarize_feature_groups(true_t3, false_t3),
        "economic_attribution": {
            "true_continuation_confirmations": economic_summary(true_econ),
            "false_positive_reversal_confirmations": economic_summary(false_econ),
        },
        "false_positive_details": false_details,
        "interpretation_guard": {
            "future_outcome_used_for_diagnostics_only": True,
            "future_outcome_allowed_as_entry_feature": False,
            "pnl_used_for_diagnostics_only": True,
            "pnl_allowed_for_state_machine_tuning_in_this_module": False,
            "no_filter_promoted": True,
        },
        "leakage_guard": {
            "state_machine_rules_modified": False,
            "new_threshold_selected": False,
            "oos_a_b_c_d_used_as_diagnostics": True,
            "oos_e_f_g_h_used": False,
            "oos_h_used": False,
            "research_only": True,
            "research_emits_trade_order": False,
        },
    }

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--state-machine", required=True)
    p.add_argument("--diagnostics", required=True)
    p.add_argument("--economics", required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()

    result = analyze(
        load_json(Path(a.state_machine)),
        load_json(Path(a.diagnostics)),
        load_json(Path(a.economics)),
    )
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "status": result["status"],
        "research_version": result["research_version"],
        "confirmed_candidate_count": result["confirmed_candidate_count"],
        "true_continuation_confirmed_count": result["true_continuation_confirmed_count"],
        "false_positive_reversal_confirmed_count": result["false_positive_reversal_confirmed_count"],
        "confirm_precision_recomputed": result["confirm_precision_recomputed"],
        "true_confirmation_profile": result["true_confirmation_profile"],
        "false_positive_profile": result["false_positive_profile"],
        "t3_feature_comparison": result["t3_feature_comparison"],
        "economic_attribution": result["economic_attribution"],
        "interpretation_guard": result["interpretation_guard"],
        "leakage_guard": result["leakage_guard"],
        "output": str(out),
    }, indent=2))

if __name__ == "__main__":
    main()
