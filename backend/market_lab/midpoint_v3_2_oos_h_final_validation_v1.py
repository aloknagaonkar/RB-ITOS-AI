from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from market_lab.midpoint_v3_2_oos_h_freeze_contract_v1 import (
    EXIT_POLICY_ID,
    load_json,
    verify_contract_files,
)

RESEARCH_VERSION = "MIDPOINT_V3_2_OOS_H_FINAL_VALIDATION_V1"


def final_decision(
    *,
    trade_count: int,
    mean_net_pct: float | None,
    profit_factor: float | None,
    integrity_ok: bool,
    minimum_trades: int = 10,
) -> tuple[str, list[str]]:
    reasons: list[str] = []

    if not integrity_ok:
        return "FAIL_INTEGRITY", ["OPERATIONAL_OR_FREEZE_INTEGRITY_FAILED"]

    if trade_count < minimum_trades:
        return "HOLD_INSUFFICIENT_SAMPLE", [
            f"REALIZED_TRADES_{trade_count}_BELOW_PREDECLARED_MINIMUM_{minimum_trades}"
        ]

    if mean_net_pct is None or profit_factor is None:
        return "FAIL_ECONOMICS", ["MISSING_MEAN_OR_PROFIT_FACTOR"]

    if math.isfinite(profit_factor) and mean_net_pct > 0.0 and profit_factor > 1.0:
        reasons.extend(["MEAN_NET_POSITIVE", "PROFIT_FACTOR_GT_1"])
        return "PASS_CANDIDATE_FOR_PAPER_TRADING_REVIEW", reasons

    if math.isinf(profit_factor) and mean_net_pct > 0.0:
        return "PASS_CANDIDATE_FOR_PAPER_TRADING_REVIEW", [
            "MEAN_NET_POSITIVE",
            "NO_AGGREGATE_LOSS_DENOMINATOR",
        ]

    return "FAIL_ECONOMICS", [
        f"MEAN_NET_PCT={mean_net_pct}",
        f"PROFIT_FACTOR={profit_factor}",
    ]


def validate(
    *,
    contract: dict[str, Any],
    replay: dict[str, Any],
) -> dict[str, Any]:
    file_mismatches = verify_contract_files(contract)
    integrity_issues: list[str] = list(file_mismatches)

    if contract.get("status") != "FROZEN":
        integrity_issues.append("CONTRACT_NOT_FROZEN")
    if replay.get("research_version") != "MIDPOINT_V3_2_OOS_H_FROZEN_EXIT_REPLAY_V1":
        integrity_issues.append("UNEXPECTED_REPLAY_VERSION")
    if replay.get("block") != "OOS_H":
        integrity_issues.append("REPLAY_NOT_OOS_H_ONLY")
    if replay.get("frozen_policy_id") != EXIT_POLICY_ID:
        integrity_issues.append("FROZEN_POLICY_MISMATCH")
    integrity = replay.get("integrity") or {}
    required_true = (
        "single_frozen_policy_only",
        "entry_open_reconciled_to_ohlc",
        "complete_15m_path_required",
        "exact_contract_only",
        "oos_h_only",
    )
    for key in required_true:
        if integrity.get(key) is not True:
            integrity_issues.append(f"INTEGRITY_FLAG_NOT_TRUE:{key}")
    if integrity.get("alternative_exit_search_performed") is not False:
        integrity_issues.append("ALTERNATIVE_EXIT_SEARCH_WAS_PERFORMED")

    summary = replay.get("summary") or {}
    trade_count = int(summary.get("trade_count") or 0)
    mean_net = summary.get("mean_net_pct")
    pf = summary.get("profit_factor")

    gate = contract.get("final_validation_gate") or {}
    minimum = int(gate.get("minimum_realized_trades_for_pass_fail", 10))
    decision, reasons = final_decision(
        trade_count=trade_count,
        mean_net_pct=mean_net,
        profit_factor=pf,
        integrity_ok=not integrity_issues,
        minimum_trades=minimum,
    )

    return {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "block": "OOS_H",
        "frozen_policy_id": EXIT_POLICY_ID,
        "final_decision": decision,
        "decision_reasons": reasons,
        "headline": summary,
        "direction_summaries": replay.get("direction_summaries"),
        "integrity_issues": integrity_issues,
        "paper_trading_status": (
            "ELIGIBLE_FOR_MANUAL_APPROVAL_REVIEW"
            if decision == "PASS_CANDIDATE_FOR_PAPER_TRADING_REVIEW"
            else "NOT_APPROVED"
        ),
        "live_trading_status": "DISABLED",
        "governance": {
            "this_is_one_shot_oos_h_validation": True,
            "oos_h_is_now_consumed": True,
            "oos_h_must_not_be_reused_as_fresh_holdout": True,
            "failure_must_not_trigger_retune_then_retest_on_h": True,
            "pass_does_not_authorize_live_trading": True,
            "paper_trading_requires_separate_manual_review": True,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze-contract", required=True)
    parser.add_argument("--replay", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    result = validate(
        contract=load_json(Path(args.freeze_contract)),
        replay=load_json(Path(args.replay)),
    )
    result["output"] = args.output
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
