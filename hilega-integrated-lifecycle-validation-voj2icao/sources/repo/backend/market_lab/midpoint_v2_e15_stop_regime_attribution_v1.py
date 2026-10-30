from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from statistics import mean, median
from typing import Any

RESEARCH_VERSION = "MIDPOINT_V2_E15_STOP_REGIME_ATTRIBUTION_V1"
EXPECTED_EXIT_VERSION = "MIDPOINT_V2_EXIT_DURATION_COMPARISON_V1"
EXPECTED_STOP_PATH_VERSION = "MIDPOINT_V2_STOP_PATH_DIAGNOSTICS_V1"

ALLOWED_ARMS = {"BASE_THEN_GO", "FAILED_BREAK_RECLAIM"}


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def event_key(row: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(row.get("block")),
        str(row.get("session_date")),
        str(row.get("entry_arm")),
        str(row.get("entry_direction")),
        str(row.get("entry_timestamp")),
    )


def classify_stop_regime(row: dict[str, Any]) -> str:
    reason = str(row.get("exit_reason") or "")
    if reason not in {"STOP_TOUCH", "STOP_GAP"}:
        return "NOT_STOP_EXIT"

    hist = row.get("stop_history") or []
    if not hist:
        return "UNKNOWN_STOP_REGIME"

    last = hist[-1]
    if bool(last.get("trail_active")):
        return "TRAILING"
    if bool(last.get("breakeven_active")):
        return "BREAKEVEN"
    return "INITIAL_SL5"


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    stop_rows = [r for r in rows if r["stop_regime"] != "NOT_STOP_EXIT"]
    initial = [r for r in rows if r["stop_regime"] == "INITIAL_SL5"]

    initial_final = [
        float(r["stop_path_final_15m_net_pct"])
        for r in initial
        if r.get("stop_path_final_15m_net_pct") is not None
    ]

    return {
        "trade_count": len(rows),
        "stop_exit_count": len(stop_rows),
        "stop_regime_counts": dict(
            sorted(Counter(r["stop_regime"] for r in rows).items())
        ),
        "initial_sl5_count": len(initial),
        "initial_sl5_then_recovered_to_entry_count": sum(
            bool(r.get("stop_path_recovered_to_entry")) for r in initial
        ),
        "initial_sl5_then_reached_plus5_count": sum(
            bool(r.get("stop_path_reached_plus5")) for r in initial
        ),
        "initial_sl5_then_reached_plus10_count": sum(
            bool(r.get("stop_path_reached_plus10")) for r in initial
        ),
        "initial_sl5_but_final_15m_net_positive_count": sum(
            float(r["stop_path_final_15m_net_pct"]) > 0
            for r in initial
            if r.get("stop_path_final_15m_net_pct") is not None
        ),
        "initial_sl5_final_15m_net_mean_pct": (
            mean(initial_final) if initial_final else None
        ),
        "initial_sl5_final_15m_net_median_pct": (
            median(initial_final) if initial_final else None
        ),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exit-comparison", required=True)
    ap.add_argument("--stop-path", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    exit_doc = load_json(Path(args.exit_comparison))
    stop_doc = load_json(Path(args.stop_path))

    if exit_doc.get("research_version") != EXPECTED_EXIT_VERSION:
        raise SystemExit(
            f"unexpected exit comparison version={exit_doc.get('research_version')!r}"
        )
    if stop_doc.get("research_version") != EXPECTED_STOP_PATH_VERSION:
        raise SystemExit(
            f"unexpected stop-path version={stop_doc.get('research_version')!r}"
        )

    if exit_doc.get("candidate_count") != 17 or stop_doc.get("candidate_count") != 17:
        raise SystemExit("expected 17 candidates in both inputs")

    if (exit_doc.get("integrity") or {}).get("oos_h_used"):
        raise SystemExit("OOS-H forbidden in exit comparison")
    if (stop_doc.get("integrity") or {}).get("oos_h_used"):
        raise SystemExit("OOS-H forbidden in stop-path diagnostics")

    e15_rows = [
        r for r in (exit_doc.get("rows") or [])
        if r.get("policy_id") == "E15"
    ]
    if len(e15_rows) != 17:
        raise SystemExit(f"expected 17 E15 rows, got {len(e15_rows)}")

    stop_idx = {event_key(r): r for r in (stop_doc.get("rows") or [])}
    if len(stop_idx) != 17:
        raise SystemExit(f"expected 17 unique stop-path rows, got {len(stop_idx)}")

    rows = []
    for e in e15_rows:
        key = event_key(e)
        s = stop_idx.get(key)
        if s is None:
            raise SystemExit(f"stop-path join missing for {key}")

        regime = classify_stop_regime(e)
        rows.append({
            "block": e.get("block"),
            "session_date": e.get("session_date"),
            "entry_arm": e.get("entry_arm"),
            "entry_direction": e.get("entry_direction"),
            "entry_timestamp": e.get("entry_timestamp"),
            "exit_timestamp": e.get("exit_timestamp"),
            "exit_reason": e.get("exit_reason"),
            "exit_price": e.get("exit_price"),
            "net_return_pct": e.get("net_return_pct"),
            "stop_regime": regime,
            "active_stop_at_exit": (
                (e.get("stop_history") or [{}])[-1].get("active_stop")
                if e.get("stop_history")
                else None
            ),
            "stop_path_raw_sl5_hit": s.get("stop5_hit"),
            "stop_path_raw_sl5_hit_minute": s.get("stop5_hit_minute"),
            "stop_path_recovered_to_entry": s.get("recovered_to_entry_after_stop"),
            "stop_path_reached_plus5": s.get("reached_plus5_after_stop"),
            "stop_path_reached_plus10": s.get("reached_plus10_after_stop"),
            "stop_path_final_15m_net_pct": s.get("final_15m_net_pct"),
        })

    result = {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "source_exit_version": EXPECTED_EXIT_VERSION,
        "source_stop_path_version": EXPECTED_STOP_PATH_VERSION,
        "candidate_count": 17,
        "overall_summary": summarize(rows),
        "arm_summaries": {
            arm: summarize([r for r in rows if r["entry_arm"] == arm])
            for arm in ("BASE_THEN_GO", "FAILED_BREAK_RECLAIM")
        },
        "direction_summaries": {
            direction: summarize(
                [r for r in rows if r["entry_direction"] == direction]
            )
            for direction in ("BULLISH", "BEARISH")
        },
        "rows": rows,
        "integrity": {
            "e15_only": True,
            "actual_active_stop_state_used": True,
            "raw_sl5_cross_not_treated_as_exit_regime": True,
            "alternative_stop_thresholds_tested": False,
            "entry_logic_modified": False,
            "exit_logic_modified": False,
            "oos_h_used": False,
        },
        "governance": {
            "diagnostic_only": True,
            "no_stop_parameter_promoted": True,
            "no_arm_or_direction_filter_promoted": True,
            "fresh_oos_required_before_any_v2_promotion": True,
            "paper_or_live_order_emission_allowed": False,
        },
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
