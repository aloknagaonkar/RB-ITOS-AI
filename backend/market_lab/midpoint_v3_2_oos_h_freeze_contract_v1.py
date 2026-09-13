from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RESEARCH_VERSION = "MIDPOINT_V3_2_OOS_H_FREEZE_CONTRACT_V1"
ENTRY_VERSION = "MIDPOINT_STABLE_FEATURE_STATE_MACHINE_V3_2"
EXIT_POLICY_ID = "SL5_BE5_TRAIL3_AFTER10_TIME15"
ENTRY_RULE = "EXACT_NEXT_MINUTE_OPEN_AFTER_T3"
CONTRACT_RULE = "EXACT_MOVING_ATM_AT_T3_NO_NEAREST_FALLBACK"
ROUND_TRIP_COST_PCT_POINTS = 0.5

FROZEN_EXIT = {
    "initial_stop_pct": 5.0,
    "breakeven_trigger_pct": 5.0,
    "trail_activation_pct": 10.0,
    "trail_distance_pct": 3.0,
    "max_hold_minutes": 15,
    "breakeven_and_trailing_activate_next_bar": True,
    "gap_through_stop_exits_at_open": True,
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def build_contract(
    *,
    robustness_payload: dict[str, Any],
    files: list[Path],
) -> dict[str, Any]:
    if robustness_payload.get("research_version") != "MIDPOINT_V3_2_TEMPORAL_DEPENDENCE_ROBUSTNESS_V1":
        raise ValueError("unexpected robustness research version")
    assessment = robustness_payload.get("research_assessment") or {}
    if assessment.get("label") != "ROBUSTNESS_SUPPORTIVE":
        raise ValueError("OOS-H may only be opened after ROBUSTNESS_SUPPORTIVE")
    leakage = robustness_payload.get("leakage_guard") or {}
    if leakage.get("oos_h_used") is not False:
        raise ValueError("robustness payload does not prove OOS-H was untouched")
    if leakage.get("entry_state_machine_modified") is not False:
        raise ValueError("entry state machine was modified")
    if leakage.get("exit_policy_modified") is not False:
        raise ValueError("exit policy was modified")

    if not files:
        raise ValueError("at least one --freeze-file is required")

    file_hashes = {}
    for path in files:
        if not path.exists() or not path.is_file():
            raise ValueError(f"freeze file not found: {path}")
        file_hashes[str(path)] = {
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        }

    return {
        "status": "FROZEN",
        "research_version": RESEARCH_VERSION,
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "entry_version": ENTRY_VERSION,
        "exit_policy_id": EXIT_POLICY_ID,
        "entry_rule": ENTRY_RULE,
        "contract_rule": CONTRACT_RULE,
        "round_trip_cost_pct_points": ROUND_TRIP_COST_PCT_POINTS,
        "exit_parameters": dict(FROZEN_EXIT),
        "final_validation_gate": {
            "minimum_realized_trades_for_pass_fail": 10,
            "pass_requires_mean_net_pct_gt": 0.0,
            "pass_requires_profit_factor_gt": 1.0,
            "hold_if_realized_trades_below": 10,
            "operational_integrity_required": True,
            "decision_is_predeclared_before_oos_h": True,
        },
        "source_robustness": {
            "research_version": robustness_payload.get("research_version"),
            "assessment": assessment.get("label"),
            "frozen_policy_id": robustness_payload.get("frozen_policy_id"),
        },
        "file_hashes": file_hashes,
        "governance": {
            "oos_h_opened_before_contract": False,
            "entry_changes_after_freeze_allowed": False,
            "exit_changes_after_freeze_allowed": False,
            "threshold_changes_after_freeze_allowed": False,
            "alternative_exit_search_on_oos_h_allowed": False,
            "oos_h_reuse_for_retuning_allowed": False,
            "paper_or_live_order_emission_allowed": False,
        },
    }


def verify_contract_files(contract: dict[str, Any]) -> list[str]:
    mismatches: list[str] = []
    for text_path, expected in (contract.get("file_hashes") or {}).items():
        path = Path(text_path)
        if not path.exists():
            mismatches.append(f"MISSING:{text_path}")
            continue
        actual = sha256_file(path)
        if actual != expected.get("sha256"):
            mismatches.append(f"HASH_MISMATCH:{text_path}")
    return mismatches


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--robustness", required=True)
    parser.add_argument("--freeze-file", action="append", default=[], required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    payload = load_json(Path(args.robustness))
    contract = build_contract(
        robustness_payload=payload,
        files=[Path(x) for x in args.freeze_file],
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(contract, indent=2))


if __name__ == "__main__":
    main()
