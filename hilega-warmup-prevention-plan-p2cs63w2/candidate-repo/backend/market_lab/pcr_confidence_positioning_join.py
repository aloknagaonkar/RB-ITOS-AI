"""Combine frozen Stage-2 severity evidence with positioning-confirmation timing.

Research-only. This module does not emit BUY/SELL/CE/PE orders. It takes the
100-session discriminator as the frozen bucket specification, uses the fresh-OOS
validation file only to select severity features that survived unchanged, and
then measures outcome rates by severity tier and first positioning-confirmation
arrival time on the supplied evidence/positioning block.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path
from typing import Any

from .pcr_bidirectional_discriminator import _bucket_index, _events, _load
from .pcr_positioning_event_join import OFFSETS, TARGET_COMBINED, _confirmation_at, _dt, _load_positioning

OFFSET_GROUPS = (
    "T0",
    "T_PLUS_1",
    "T_PLUS_2",
    "T_PLUS_3",
    "T_PLUS_4_5",
    "NO_CONFIRMATION_WITHIN_5M",
)


def _pct(n: int, d: int) -> float | None:
    return 100.0 * n / d if d else None


def _load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _feature_specs(
    frozen_spec: dict[str, Any],
    validation: dict[str, Any],
    direction: str,
) -> list[dict[str, Any]]:
    """Return only features that survived fresh OOS validation."""
    dkey = direction.lower()
    frozen_items = {
        str(x.get("feature")): x
        for x in frozen_spec.get(dkey, {}).get("frozen_train_buckets", [])
    }
    result: list[dict[str, Any]] = []
    for item in validation.get(dkey, {}).get("features", []):
        if not item.get("expected_direction_confirmed"):
            continue
        feature = str(item.get("feature"))
        frozen = frozen_items.get(feature)
        if not frozen:
            continue
        cuts = [float(x) for x in frozen.get("train_cut_points", [])]
        if len(cuts) != 3:
            continue
        expected = str(item.get("expected_monotonic", "")).upper()
        if expected not in {"INCREASING", "DECREASING"}:
            continue
        result.append({
            "feature": feature,
            "train_cut_points": cuts,
            "expected_monotonic": expected,
        })
    return result


def _favorable_score(bucket_idx: int, monotonic: str) -> int:
    # 0..3 where 3 is always the most favorable frozen quartile.
    if monotonic == "INCREASING":
        return bucket_idx
    return 3 - bucket_idx


def _tier(scores: list[int]) -> str:
    if not scores:
        return "UNAVAILABLE"
    max_score = 3 * len(scores)
    total = sum(scores)
    if total == max_score:
        return "VERY_HIGH"
    ratio = total / max_score
    if ratio >= 2 / 3:
        return "HIGH"
    if ratio >= 1 / 3:
        return "MEDIUM"
    return "LOW"


def _first_confirmation(
    positioning: dict,
    session: str,
    event_dt,
    direction: str,
) -> tuple[int | None, list[float], list[int]]:
    for offset in OFFSETS:
        rows = positioning.get((session, event_dt + timedelta(minutes=offset)), [])
        confirmed, strikes, strike_offsets = _confirmation_at(rows, direction)
        if confirmed:
            return offset, strikes, strike_offsets
    return None, [], []


def _offset_group(offset: int | None) -> str:
    if offset is None:
        return "NO_CONFIRMATION_WITHIN_5M"
    if offset == 0:
        return "T0"
    if offset == 1:
        return "T_PLUS_1"
    if offset == 2:
        return "T_PLUS_2"
    if offset == 3:
        return "T_PLUS_3"
    return "T_PLUS_4_5"


def _summary(rows: list[dict[str, Any]], direction: str) -> dict[str, Any]:
    true_label = f"TRUE_{direction}_REVERSAL"
    false_label = f"FALSE_{direction}_WARNING"
    counts = Counter(str(x["outcome"]) for x in rows)
    t = counts[true_label]
    f = counts[false_label]
    return {
        "event_count": len(rows),
        "true_reversal_count": t,
        "false_warning_count": f,
        "other_outcome_count": len(rows) - t - f,
        "true_vs_false_rate_pct": _pct(t, t + f),
        "true_reversal_rate_all_pct": _pct(t, len(rows)),
        "outcome_counts": dict(sorted(counts.items())),
    }


def analyze(
    spec_path: str | Path,
    validation_path: str | Path,
    evidence_path: str | Path,
    positioning_path: str | Path,
) -> dict[str, Any]:
    frozen = _load_json(spec_path)
    validation = _load_json(validation_path)
    evidence = _load(evidence_path)
    positioning = _load_positioning(positioning_path)

    if frozen.get("status") != "AVAILABLE":
        raise ValueError("frozen discriminator spec is not AVAILABLE")
    if validation.get("status") != "AVAILABLE":
        raise ValueError("fresh-OOS validation report is not AVAILABLE")

    report: dict[str, Any] = {
        "status": "AVAILABLE",
        "spec_source": str(spec_path),
        "validation_source": str(validation_path),
        "evidence_source": str(evidence_path),
        "positioning_source": str(positioning_path),
        "row_count": len(evidence),
        "session_count": len({str(r["session_date"]) for r in evidence}),
        "methodology": [
            "Stage-2 definitions remain frozen and only first-entry events are counted.",
            "Severity cut points come from the frozen 100-session TRAIN specification and are not recalculated here.",
            "Only severity features that preserved their expected monotonic relationship on the fresh-OOS validation report are included.",
            "Each included feature contributes a 0..3 favorable-quartile score; the composite tier is descriptive and has not itself been OOS validated.",
            "Positioning confirmation is the first STRONG_BULLISH/STRONG_BEARISH observation from exact T0 through T0+5m.",
            "Outcome rates are descriptive research labels, not option premium win rates or trade-entry performance.",
        ],
        "limitations": [
            "The joint severity+timing matrix is evaluated on the same fresh block used to confirm the individual severity relationships, so the composite tier is exploratory rather than pristine OOS proof.",
            "No option premium entry, stop, target, slippage, brokerage, or P&L is included.",
            "A future untouched block or premium backtest is required before turning any timing cell into a trading rule.",
        ],
        "directions": {},
    }

    for direction in ("BEARISH", "BULLISH"):
        specs = _feature_specs(frozen, validation, direction)
        events = _events(evidence, direction)
        enriched: list[dict[str, Any]] = []

        for event in events:
            feature_rows = []
            scores: list[int] = []
            complete = True
            for fs in specs:
                value = event.get(fs["feature"])
                if not isinstance(value, (int, float)):
                    complete = False
                    feature_rows.append({
                        "feature": fs["feature"],
                        "value": None,
                        "bucket": None,
                        "favorable_score": None,
                    })
                    continue
                idx = _bucket_index(float(value), fs["train_cut_points"])
                score = _favorable_score(idx, fs["expected_monotonic"])
                scores.append(score)
                feature_rows.append({
                    "feature": fs["feature"],
                    "value": float(value),
                    "bucket": f"Q{idx + 1}",
                    "favorable_score": score,
                })

            if not complete or len(scores) != len(specs):
                confidence_tier = "UNAVAILABLE"
                confidence_score = None
            else:
                confidence_tier = _tier(scores)
                confidence_score = sum(scores)

            session = str(event["session_date"])
            event_dt = _dt(event["event_time"])
            first_offset, strikes, strike_offsets = _first_confirmation(
                positioning, session, event_dt, direction
            )
            enriched.append({
                "session_date": session,
                "timestamp": event_dt.isoformat(),
                "direction": direction,
                "outcome": str(event["label"]),
                "confidence_tier": confidence_tier,
                "confidence_score": confidence_score,
                "severity_features": feature_rows,
                "first_confirmation_offset_minutes": first_offset,
                "confirmation_offset_group": _offset_group(first_offset),
                "first_confirmation_strikes": strikes,
                "first_confirmation_strike_offsets": strike_offsets,
            })

        by_tier: dict[str, Any] = {}
        for tier in ("LOW", "MEDIUM", "HIGH", "VERY_HIGH", "UNAVAILABLE"):
            selected = [x for x in enriched if x["confidence_tier"] == tier]
            by_tier[tier] = _summary(selected, direction)

        by_offset: dict[str, Any] = {}
        for group in OFFSET_GROUPS:
            selected = [x for x in enriched if x["confirmation_offset_group"] == group]
            by_offset[group] = _summary(selected, direction)

        matrix: dict[str, Any] = {}
        for tier in ("LOW", "MEDIUM", "HIGH", "VERY_HIGH"):
            matrix[tier] = {}
            for group in OFFSET_GROUPS:
                selected = [
                    x for x in enriched
                    if x["confidence_tier"] == tier
                    and x["confirmation_offset_group"] == group
                ]
                matrix[tier][group] = _summary(selected, direction)

        early_confirmed = [
            x for x in enriched
            if x["first_confirmation_offset_minutes"] is not None
            and int(x["first_confirmation_offset_minutes"]) <= 2
        ]
        late_confirmed = [
            x for x in enriched
            if x["first_confirmation_offset_minutes"] is not None
            and int(x["first_confirmation_offset_minutes"]) >= 3
        ]
        no_confirm = [x for x in enriched if x["first_confirmation_offset_minutes"] is None]

        report["directions"][direction.lower()] = {
            "direction": direction,
            "target_positioning": TARGET_COMBINED[direction],
            "confirmed_severity_features": specs,
            "stage_2_event_count": len(enriched),
            "confidence_tier_summary": by_tier,
            "confirmation_timing_summary": by_offset,
            "early_confirmation_t0_to_t2": _summary(early_confirmed, direction),
            "late_confirmation_t3_to_t5": _summary(late_confirmed, direction),
            "no_confirmation_within_5m": _summary(no_confirm, direction),
            "severity_timing_matrix": matrix,
            "events": enriched,
        }

    return report


def main() -> None:
    p = argparse.ArgumentParser(description="Combine frozen PCR severity tiers with positioning timing")
    p.add_argument("--spec", required=True, help="Frozen 100-session bidirectional discriminator JSON")
    p.add_argument("--validation", required=True, help="Fresh-OOS bucket validation JSON")
    p.add_argument("--evidence", required=True, help="Evidence CSV for the analysis block")
    p.add_argument("--positioning", required=True, help="Historical positioning sidecar CSV for the same block")
    p.add_argument("--output", required=True)
    args = p.parse_args()

    result = analyze(args.spec, args.validation, args.evidence, args.positioning)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    compact = {"status": result["status"], "output": str(out)}
    for key in ("bearish", "bullish"):
        d = result["directions"][key]
        compact[key] = {
            "stage_2_event_count": d["stage_2_event_count"],
            "confirmed_severity_features": [x["feature"] for x in d["confirmed_severity_features"]],
            "early_confirmation_t0_to_t2": d["early_confirmation_t0_to_t2"],
            "late_confirmation_t3_to_t5": d["late_confirmation_t3_to_t5"],
            "no_confirmation_within_5m": d["no_confirmation_within_5m"],
        }
    print(json.dumps(compact, indent=2))


if __name__ == "__main__":
    main()
