"""OI-state validation patch for midpoint four-arm decision research.

This module does NOT retune or replace the frozen V1 entry classifier.

It consumes:
- OPENING_CANDLE_MIDPOINT_REVERSAL_FRAMEWORK_V1_1
- MIDPOINT_FOUR_ARM_DECISION_RESEARCH_V1

and enriches every decision row with explicit CE/PE positioning states:

Premium ↑ + OI ↑ = LONG_BUILDUP
Premium ↓ + OI ↑ = SHORT_BUILDUP
Premium ↓ + OI ↓ = LONG_UNWINDING
Premium ↑ + OI ↓ = SHORT_COVERING

Directional support definitions:

Bearish arms:
    CE SHORT_BUILDUP + PE LONG_BUILDUP = STRONG_BEARISH

Bullish arms:
    CE LONG_BUILDUP + PE SHORT_BUILDUP = STRONG_BULLISH

Secondary directional support is also recorded, but it is NOT promoted to a
trade rule in this patch. This is deliberately diagnostic so that we do not
change the entry rule after observing option P&L.

No OOS-E/F/G/H are used.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

RESEARCH_VERSION = "MIDPOINT_FOUR_ARM_OI_STATE_VALIDATION_V1"
FRAMEWORK_VERSION = "OPENING_CANDLE_MIDPOINT_REVERSAL_FRAMEWORK_V1_1"
DECISION_VERSION = "MIDPOINT_FOUR_ARM_DECISION_RESEARCH_V1"

ALLOWED_BLOCKS = {"TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D"}

ARM_META = {
    "RED_BEARISH_CONTINUATION": {
        "direction": "BEARISH",
        "snapshot_kind": "PRIMARY",
        "supportive_strong": ("SHORT_BUILDUP", "LONG_BUILDUP"),
        "supportive_secondary": {
            ("SHORT_BUILDUP", "SHORT_COVERING"),
            ("LONG_UNWINDING", "LONG_BUILDUP"),
        },
    },
    "RED_BULLISH_RECLAIM": {
        "direction": "BULLISH",
        "snapshot_kind": "RECLAIM",
        "supportive_strong": ("LONG_BUILDUP", "SHORT_BUILDUP"),
        "supportive_secondary": {
            ("SHORT_COVERING", "SHORT_BUILDUP"),
            ("LONG_BUILDUP", "LONG_UNWINDING"),
        },
    },
    "GREEN_BULLISH_CONTINUATION": {
        "direction": "BULLISH",
        "snapshot_kind": "PRIMARY",
        "supportive_strong": ("LONG_BUILDUP", "SHORT_BUILDUP"),
        "supportive_secondary": {
            ("SHORT_COVERING", "SHORT_BUILDUP"),
            ("LONG_BUILDUP", "LONG_UNWINDING"),
        },
    },
    "GREEN_BEARISH_RECLAIM": {
        "direction": "BEARISH",
        "snapshot_kind": "RECLAIM",
        "supportive_strong": ("SHORT_BUILDUP", "LONG_BUILDUP"),
        "supportive_secondary": {
            ("SHORT_BUILDUP", "SHORT_COVERING"),
            ("LONG_UNWINDING", "LONG_BUILDUP"),
        },
    },
}


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("JSON root must be an object")
    return payload


def validate_sources(
    framework: dict[str, Any],
    decisions: dict[str, Any],
) -> None:
    if framework.get("research_version") != FRAMEWORK_VERSION:
        raise ValueError(
            f"expected framework {FRAMEWORK_VERSION}, got {framework.get('research_version')!r}"
        )
    if decisions.get("research_version") != DECISION_VERSION:
        raise ValueError(
            f"expected decisions {DECISION_VERSION}, got {decisions.get('research_version')!r}"
        )

    fguard = framework.get("leakage_guard") or {}
    dguard = decisions.get("leakage_guard") or {}

    if fguard.get("oos_e_f_g_h_used") is not False or fguard.get("oos_h_used") is not False:
        raise ValueError("framework leakage guard failed")
    if dguard.get("oos_e_f_g_h_used") is not False or dguard.get("oos_h_used") is not False:
        raise ValueError("decision leakage guard failed")

    blocks = {
        row.get("block")
        for arm in decisions.get("arms", {}).values()
        for row in arm.get("rows", [])
    }
    if not blocks.issubset(ALLOWED_BLOCKS):
        raise ValueError(f"forbidden block present: {sorted(blocks - ALLOWED_BLOCKS)}")


def _event_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("block")),
        str(row.get("session_date")),
        str(row.get("arm")),
    )


def _framework_event_index(
    framework: dict[str, Any],
) -> dict[tuple[str, str, str], dict[str, Any]]:
    by_basic: dict[tuple[str, str, str], dict[str, Any]] = {}
    for event in framework.get("events", []):
        block = str(event.get("block"))
        session = str(event.get("session_date"))
        setup = str(event.get("setup_type"))
        by_basic[(block, session, setup)] = event
    return by_basic


def _snapshot_at(
    event: dict[str, Any],
    kind: str,
    offset: int = 3,
) -> dict[str, Any] | None:
    key = "snapshots" if kind == "PRIMARY" else "reclaim_snapshots"
    for snapshot in event.get(key, []) or []:
        if snapshot.get("offset_minutes") == offset:
            return snapshot
    return None


def _state(snapshot: dict[str, Any], side: str) -> str | None:
    # Existing positioning research exposes side-specific 5m state fields.
    value = snapshot.get(f"{side.lower()}_5m_state")
    if value in {
        "LONG_BUILDUP",
        "SHORT_BUILDUP",
        "LONG_UNWINDING",
        "SHORT_COVERING",
    }:
        return value
    return None


def classify_oi_support(
    *,
    ce_state: str | None,
    pe_state: str | None,
    direction: str,
) -> dict[str, Any]:
    if ce_state is None or pe_state is None:
        return {
            "status": "UNAVAILABLE",
            "combined_oi_state": "UNAVAILABLE",
            "support_level": "UNAVAILABLE",
            "directionally_supportive": None,
        }

    meta = next(
        m for m in ARM_META.values()
        if m["direction"] == direction
    )
    pair = (ce_state, pe_state)

    if pair == meta["supportive_strong"]:
        combined = "STRONG_BEARISH" if direction == "BEARISH" else "STRONG_BULLISH"
        level = "STRONG"
        supportive = True
    elif pair in meta["supportive_secondary"]:
        combined = "BEARISH_SUPPORTIVE" if direction == "BEARISH" else "BULLISH_SUPPORTIVE"
        level = "SECONDARY"
        supportive = True
    else:
        combined = "MIXED_OR_OPPOSING"
        level = "NONE"
        supportive = False

    return {
        "status": "AVAILABLE",
        "combined_oi_state": combined,
        "support_level": level,
        "directionally_supportive": supportive,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    support = Counter(row["oi_validation"]["support_level"] for row in rows)
    combined = Counter(row["oi_validation"]["combined_oi_state"] for row in rows)

    trade_rows = [row for row in rows if row.get("decision") == "TRADE_NOW"]
    trade_support = Counter(
        row["oi_validation"]["support_level"]
        for row in trade_rows
    )

    return {
        "count": len(rows),
        "oi_support_levels": dict(support),
        "combined_oi_states": dict(combined),
        "trade_now_count": len(trade_rows),
        "trade_now_oi_support_levels": dict(trade_support),
        "trade_now_strong_or_secondary_count": sum(
            row["oi_validation"]["support_level"] in {"STRONG", "SECONDARY"}
            for row in trade_rows
        ),
        "trade_now_strong_or_secondary_pct": (
            100.0
            * sum(
                row["oi_validation"]["support_level"] in {"STRONG", "SECONDARY"}
                for row in trade_rows
            )
            / len(trade_rows)
            if trade_rows
            else None
        ),
    }


def analyze(
    framework: dict[str, Any],
    decisions: dict[str, Any],
) -> dict[str, Any]:
    validate_sources(framework, decisions)
    event_index = _framework_event_index(framework)

    enriched_rows: list[dict[str, Any]] = []

    for arm_name, arm in decisions.get("arms", {}).items():
        if arm_name not in ARM_META:
            continue
        meta = ARM_META[arm_name]

        for row in arm.get("rows", []):
            block = str(row.get("block"))
            session = str(row.get("session_date"))

            source_setup = (
                "RED_BREAK"
                if arm_name.startswith("RED_")
                else "GREEN_BREAK"
            )
            event = event_index.get((block, session, source_setup))
            if event is None:
                raise ValueError(
                    f"framework event missing for {block} {session} {source_setup}"
                )

            snapshot = _snapshot_at(event, meta["snapshot_kind"], 3)
            if snapshot is None:
                raise ValueError(
                    f"T+3 snapshot missing for {block} {session} {arm_name}"
                )

            ce_state = _state(snapshot, "CE")
            pe_state = _state(snapshot, "PE")
            validation = classify_oi_support(
                ce_state=ce_state,
                pe_state=pe_state,
                direction=meta["direction"],
            )
            validation.update({
                "ce_5m_state": ce_state,
                "pe_5m_state": pe_state,
                "source_combined_5m": snapshot.get("combined_5m"),
                "ce_5m_premium_change_pct": snapshot.get("ce_5m_premium_change_pct"),
                "ce_5m_oi_change_pct": snapshot.get("ce_5m_oi_change_pct"),
                "pe_5m_premium_change_pct": snapshot.get("pe_5m_premium_change_pct"),
                "pe_5m_oi_change_pct": snapshot.get("pe_5m_oi_change_pct"),
            })

            enriched = dict(row)
            enriched["oi_validation"] = validation

            if validation["support_level"] == "STRONG":
                enriched["reason_codes"] = list(row.get("reason_codes") or []) + [
                    "OI_STATE_STRONGLY_SUPPORTIVE"
                ]
            elif validation["support_level"] == "SECONDARY":
                enriched["reason_codes"] = list(row.get("reason_codes") or []) + [
                    "OI_STATE_SUPPORTIVE"
                ]
            elif validation["support_level"] == "NONE":
                enriched["reason_codes"] = list(row.get("reason_codes") or []) + [
                    "OI_STATE_NOT_SUPPORTIVE"
                ]

            enriched_rows.append(enriched)

    arm_summaries = {
        arm_name: summarize([
            row for row in enriched_rows if row.get("arm") == arm_name
        ])
        for arm_name in ARM_META
    }
    block_summaries = {
        block: summarize([
            row for row in enriched_rows if row.get("block") == block
        ])
        for block in ("TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D")
    }

    promoted_trade_rows = [
        row
        for row in enriched_rows
        if row.get("decision") == "TRADE_NOW"
        and row.get("arm") in {
            "RED_BEARISH_CONTINUATION",
            "GREEN_BULLISH_CONTINUATION",
        }
    ]

    promoted_summary = summarize(promoted_trade_rows)

    return {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "framework_version": FRAMEWORK_VERSION,
        "decision_version": DECISION_VERSION,
        "research_status": "OI_STATE_DIAGNOSTIC_VALIDATION_ONLY",
        "oi_state_definitions": {
            "LONG_BUILDUP": "premium_up_and_oi_up",
            "SHORT_BUILDUP": "premium_down_and_oi_up",
            "LONG_UNWINDING": "premium_down_and_oi_down",
            "SHORT_COVERING": "premium_up_and_oi_down",
        },
        "directional_support_rules": {
            "STRONG_BEARISH": "CE SHORT_BUILDUP + PE LONG_BUILDUP",
            "STRONG_BULLISH": "CE LONG_BUILDUP + PE SHORT_BUILDUP",
            "BEARISH_SECONDARY": [
                "CE SHORT_BUILDUP + PE SHORT_COVERING",
                "CE LONG_UNWINDING + PE LONG_BUILDUP",
            ],
            "BULLISH_SECONDARY": [
                "CE SHORT_COVERING + PE SHORT_BUILDUP",
                "CE LONG_BUILDUP + PE LONG_UNWINDING",
            ],
        },
        "important_guard": (
            "OI state is diagnostic in V1. It does not change TRADE_NOW/WAIT/CANCEL "
            "because the entry classifier was already frozen before option P&L review."
        ),
        "promoted_primary_trade_now_oi_summary": promoted_summary,
        "arm_summaries": arm_summaries,
        "block_summaries": block_summaries,
        "leakage_guard": {
            "entry_decisions_modified": False,
            "score_cutoffs_modified": False,
            "oi_state_used_as_new_trade_gate": False,
            "pnl_used_to_define_oi_support": False,
            "oos_e_f_g_h_used": False,
            "oos_h_used": False,
            "research_emits_trade_order": False,
        },
        "rows": enriched_rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Explicit OI buildup-state validation for midpoint four-arm research"
    )
    parser.add_argument("--framework", required=True)
    parser.add_argument("--decisions", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    result = analyze(
        load_json(Path(args.framework)),
        load_json(Path(args.decisions)),
    )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "status": result["status"],
        "research_version": RESEARCH_VERSION,
        "promoted_primary_trade_now_oi_summary": result[
            "promoted_primary_trade_now_oi_summary"
        ],
        "arm_summaries": result["arm_summaries"],
        "block_summaries": result["block_summaries"],
        "leakage_guard": result["leakage_guard"],
        "output": str(output),
    }, indent=2))


if __name__ == "__main__":
    main()
