from __future__ import annotations

"""
Descriptive Arm C bullish-vs-bearish split.

Research only:
- consumes the already-built MIDPOINT_OI_VWAP_CONTROLLED_COMPARISON_V1 artifact
- does not change Arm C rules
- does not tune thresholds
- does not use OOS E/F/G/H
- reports direction and block stability for the existing Arm C population
"""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any

RESEARCH_VERSION = "MIDPOINT_ARM_C_DIRECTION_SPLIT_V1"
HORIZONS = (1, 3, 5, 10, 15)
ALLOWED_BLOCKS = {"TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D"}
FORBIDDEN_BLOCKS = {"OOS_E", "OOS_F", "OOS_G", "OOS_H"}


def profit_factor(values: list[float]) -> float | None:
    gains = sum(v for v in values if v > 0)
    losses = abs(sum(v for v in values if v <= 0))
    return gains / losses if losses else None


def metric_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {
            "count": 0,
            "positive_count": 0,
            "win_rate_pct": None,
            "mean_pct": None,
            "median_pct": None,
            "sum_pct_points": None,
            "profit_factor": None,
            "best_pct": None,
            "worst_pct": None,
        }
    pos = [v for v in values if v > 0]
    return {
        "count": len(values),
        "positive_count": len(pos),
        "win_rate_pct": 100.0 * len(pos) / len(values),
        "mean_pct": mean(values),
        "median_pct": median(values),
        "sum_pct_points": sum(values),
        "profit_factor": profit_factor(values),
        "best_pct": max(values),
        "worst_pct": min(values),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out = {
        "trade_count": len(rows),
        "direction_counts": dict(Counter(str(r.get("direction")) for r in rows)),
        "block_counts": dict(Counter(str(r.get("block")) for r in rows)),
    }
    for h in HORIZONS:
        vals = []
        for r in rows:
            v = (r.get("net_returns_pct") or {}).get(f"{h}m")
            if v is not None:
                vals.append(float(v))
        out[f"net_{h}m"] = metric_summary(vals)
    return out


def validate_rows(rows: list[dict[str, Any]]) -> list[str]:
    issues = []
    for i, r in enumerate(rows):
        block = str(r.get("block") or "")
        if block in FORBIDDEN_BLOCKS:
            issues.append(f"row[{i}] forbidden block {block}")
        elif block not in ALLOWED_BLOCKS:
            issues.append(f"row[{i}] unsupported block {block!r}")
        d = str(r.get("direction") or "")
        if d not in {"BULLISH", "BEARISH"}:
            issues.append(f"row[{i}] invalid direction {d!r}")
    return issues


def delta(a: dict[str, Any], b: dict[str, Any], key: str) -> float | None:
    av = a.get(key)
    bv = b.get(key)
    if av is None or bv is None:
        return None
    return float(av) - float(bv)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--comparison",
        default="data/historical-evidence/midpoint-oi-vwap-controlled-comparison-v1-development.json",
    )
    ap.add_argument(
        "--output",
        default="data/historical-evidence/midpoint-arm-c-direction-split-v1-development.json",
    )
    args = ap.parse_args()

    src = json.loads(Path(args.comparison).read_text(encoding="utf-8"))
    arm_c = src.get("arm_c") or {}
    rows = arm_c.get("trades") or []
    if not isinstance(rows, list):
        raise SystemExit("arm_c.trades missing or invalid in comparison artifact")

    issues = validate_rows(rows)
    if issues:
        raise SystemExit("Integrity failure:\n" + "\n".join(issues[:20]))

    bullish = [r for r in rows if r.get("direction") == "BULLISH"]
    bearish = [r for r in rows if r.get("direction") == "BEARISH"]

    by_block = {}
    for block in sorted(ALLOWED_BLOCKS):
        br = [r for r in rows if r.get("block") == block]
        by_block[block] = {
            "ALL": summarize(br),
            "BULLISH": summarize([r for r in br if r.get("direction") == "BULLISH"]),
            "BEARISH": summarize([r for r in br if r.get("direction") == "BEARISH"]),
        }

    bs = summarize(bullish)
    rs = summarize(bearish)
    direction_delta = {}
    for h in HORIZONS:
        b = bs[f"net_{h}m"]
        r = rs[f"net_{h}m"]
        direction_delta[f"net_{h}m_bearish_minus_bullish"] = {
            "mean_pct_points": delta(r, b, "mean_pct"),
            "median_pct_points": delta(r, b, "median_pct"),
            "win_rate_pct_points": delta(r, b, "win_rate_pct"),
            "profit_factor_delta": delta(r, b, "profit_factor"),
        }

    doc = {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "research_status": "DESCRIPTIVE_ONLY_NO_RULE_CHANGE",
        "source_research_version": src.get("research_version"),
        "population": {
            "arm_c_trade_count": len(rows),
            "bullish_count": len(bullish),
            "bearish_count": len(bearish),
        },
        "overall": summarize(rows),
        "bullish": bs,
        "bearish": rs,
        "bearish_minus_bullish": direction_delta,
        "by_block": by_block,
        "integrity": {
            "source_arm_c_rules_modified": False,
            "threshold_tuning_performed": False,
            "direction_filter_promoted": False,
            "future_outcome_used_for_selection": False,
            "oos_e_f_g_h_used": False,
            "paper_or_live_order_emission_allowed": False,
        },
        "interpretation_guard": (
            "This study is descriptive. A stronger historical direction must not be "
            "converted into a production filter without fresh precommitted OOS validation."
        ),
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2, allow_nan=False) + "\n", encoding="utf-8")

    print(json.dumps({
        "research_version": RESEARCH_VERSION,
        "population": doc["population"],
        "bullish": bs,
        "bearish": rs,
        "bearish_minus_bullish": direction_delta,
        "output": str(out),
    }, indent=2))


if __name__ == "__main__":
    main()
