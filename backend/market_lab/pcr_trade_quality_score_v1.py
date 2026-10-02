"""Score a frozen PCR Trade Quality Classifier v1 on a research block.

The frozen model is never retrained or recalibrated here.  Backtest outcomes are
used only after the decision for diagnostic evaluation of an already-scored
holdout block.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from .pcr_trade_quality_classifier_v1 import (
    CONFIDENCE_PROFILE,
    CONTRACT_RULE,
    ENTRY_RULE,
    FEATURE_NAMES,
    MODEL_VERSION,
    _predict,
    _profit_factor,
    build_block_rows,
)


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    returns = [float(r["net_realized_return_pct"]) for r in rows]
    return {
        "trade_count": len(rows),
        "positive_count": sum(x > 0 for x in returns),
        "positive_pct": 100.0 * sum(x > 0 for x in returns) / len(returns) if returns else None,
        "mean_net_return_pct": sum(returns) / len(returns) if returns else None,
        "sum_net_return_pct_points": sum(returns),
        "profit_factor": _profit_factor(returns),
    }


def score(
    model_path: str | Path,
    methodology_path: str | Path,
    backtest_path: str | Path,
    evidence_path: str | Path,
    positioning_path: str | Path,
    *,
    block_name: str,
) -> dict[str, Any]:
    model_doc = json.loads(Path(model_path).read_text(encoding="utf-8"))
    if model_doc.get("status") != "AVAILABLE" or model_doc.get("model_version") != MODEL_VERSION:
        raise ValueError("model must be AVAILABLE PCR_TRADE_QUALITY_CLASSIFIER_V1")
    if model_doc.get("confidence_profile") != CONFIDENCE_PROFILE:
        raise ValueError("model confidence profile mismatch")
    if model_doc.get("entry_rule") != ENTRY_RULE or model_doc.get("contract_selection_rule") != CONTRACT_RULE:
        raise ValueError("model entry/contract rules mismatch")
    if block_name in set(model_doc.get("development_blocks", [])):
        block_role = "DEVELOPMENT_DIAGNOSTIC"
    else:
        block_role = "HOLDOUT_DIAGNOSTIC_OR_VALIDATION"

    rows = build_block_rows(block_name, methodology_path, backtest_path, evidence_path, positioning_path)
    scored: list[dict[str, Any]] = []
    for row in rows:
        dkey = row["direction"].lower()
        direction_model = model_doc.get("directions", {}).get(dkey)
        if not direction_model:
            continue
        p = _predict(direction_model["model"], row)
        threshold = float(direction_model["decision_threshold"])
        decision = "TRADE_ALLOWED" if p >= threshold else "NO_TRADE"
        scored.append({
            "block": block_name,
            "block_role": block_role,
            "direction": row["direction"],
            "session_date": row["session_date"],
            "stage2_timestamp": row["stage2_timestamp"],
            "confirmation_timestamp": row["confirmation_timestamp"],
            "quality_probability": p,
            "decision_threshold": threshold,
            "decision": decision,
            "net_realized_return_pct": row["net_realized_return_pct"],
            "positive_label": row["positive_label"],
        })

    directions: dict[str, Any] = {}
    for direction in ("BEARISH", "BULLISH"):
        subset = [r for r in scored if r["direction"] == direction]
        allowed = [r for r in subset if r["decision"] == "TRADE_ALLOWED"]
        rejected = [r for r in subset if r["decision"] == "NO_TRADE"]
        directions[direction.lower()] = {
            "direction": direction,
            "candidate_count": len(subset),
            "allowed_count": len(allowed),
            "rejected_count": len(rejected),
            "allowed_rate_pct": 100.0 * len(allowed) / len(subset) if subset else None,
            "allowed_metrics": _metrics(allowed),
            "rejected_metrics": _metrics(rejected),
        }

    allowed_all = [r for r in scored if r["decision"] == "TRADE_ALLOWED"]
    rejected_all = [r for r in scored if r["decision"] == "NO_TRADE"]
    return {
        "status": "AVAILABLE",
        "model_version": MODEL_VERSION,
        "model_source": str(model_path),
        "block_name": block_name,
        "block_role": block_role,
        "confidence_profile": CONFIDENCE_PROFILE,
        "entry_rule": ENTRY_RULE,
        "contract_selection_rule": CONTRACT_RULE,
        "decision_rule": "DIRECTION_SPECIFIC_FROZEN_PROBABILITY_THRESHOLD",
        "leakage_guard": {
            "model_retrained_on_scored_block": False,
            "threshold_recalibrated_on_scored_block": False,
            "future_return_features_used_for_decision": False,
            "feature_names": list(FEATURE_NAMES),
        },
        "directions": directions,
        "combined": {
            "candidate_count": len(scored),
            "allowed_count": len(allowed_all),
            "rejected_count": len(rejected_all),
            "allowed_metrics": _metrics(allowed_all),
            "rejected_metrics": _metrics(rejected_all),
        },
        "decisions": scored,
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Score frozen PCR Trade Quality Classifier v1")
    p.add_argument("--model", required=True)
    p.add_argument("--methodology", required=True)
    p.add_argument("--backtest", required=True)
    p.add_argument("--evidence", required=True)
    p.add_argument("--positioning", required=True)
    p.add_argument("--block-name", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    result = score(
        args.model, args.methodology, args.backtest, args.evidence, args.positioning,
        block_name=args.block_name,
    )
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "model_version": result["model_version"],
        "block_name": result["block_name"],
        "block_role": result["block_role"],
        "leakage_guard": result["leakage_guard"],
        "bearish": result["directions"]["bearish"],
        "bullish": result["directions"]["bullish"],
        "combined": result["combined"],
        "output": str(out),
    }, indent=2))


if __name__ == "__main__":
    main()
