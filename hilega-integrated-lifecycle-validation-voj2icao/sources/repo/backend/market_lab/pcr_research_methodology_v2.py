"""Leakage-guarded PCR research methodology v2.

Primary changes versus the exploratory v1 join:
1. Confidence features are selected only from an explicit frozen profile.  The
   current holdout's labels/validation report are never an input.
2. Positioning confirmation freezes the T0 ATM strike and follows that exact
   strike from T0 through T0+5 minutes.  No panel-any or moving-ATM substitute
   is permitted.
3. The exact T0 option instrument keys are carried forward so downstream
   premium research can follow the same contract without strike substitution.

Research only.  No order placement or live execution.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .pcr_bidirectional_discriminator import _bucket_index, _events, _load

OFFSETS = tuple(range(6))
TARGET_COMBINED = {
    "BEARISH": "STRONG_BEARISH",
    "BULLISH": "STRONG_BULLISH",
}

# Feature identity and monotonic direction were frozen before the next pristine
# validation block.  Cut points are still read from the original 100-session
# TRAIN discriminator, never from the current holdout.
PROFILES: dict[str, dict[str, list[tuple[str, str]]]] = {
    "FROZEN_D5_D15": {
        "BEARISH": [
            ("fixed_pcr_change_5m", "INCREASING"),
            ("fixed_pcr_change_15m", "INCREASING"),
        ],
        "BULLISH": [
            ("fixed_pcr_change_5m", "DECREASING"),
            ("fixed_pcr_change_15m", "DECREASING"),
        ],
    },
    # Predeclared diagnostic hypothesis.  Do not select it after viewing a
    # holdout and then call the result OOS validation.
    "DELTA5_ONLY": {
        "BEARISH": [("fixed_pcr_change_5m", "INCREASING")],
        "BULLISH": [("fixed_pcr_change_5m", "DECREASING")],
    },
}
DEFAULT_PROFILE = "FROZEN_D5_D15"


def _dt(value: Any) -> datetime:
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def _finite_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _strike_key(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not d.is_finite():
        return None
    return d.normalize()


def _load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _frozen_specs(frozen: dict[str, Any], direction: str, profile: str) -> list[dict[str, Any]]:
    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r}; choose from {sorted(PROFILES)}")
    by_feature = {
        str(item.get("feature")): item
        for item in frozen.get(direction.lower(), {}).get("frozen_train_buckets", [])
    }
    result: list[dict[str, Any]] = []
    for feature, monotonic in PROFILES[profile][direction]:
        item = by_feature.get(feature)
        if not item:
            raise ValueError(f"frozen TRAIN spec missing feature {feature!r} for {direction}")
        cuts = [_finite_float(x) for x in item.get("train_cut_points", [])]
        if len(cuts) != 3 or any(x is None for x in cuts):
            raise ValueError(f"feature {feature!r} does not have three frozen TRAIN cut points")
        result.append({
            "feature": feature,
            "train_cut_points": [float(x) for x in cuts if x is not None],
            "expected_monotonic": monotonic,
        })
    return result


def _favorable_score(bucket_idx: int, monotonic: str) -> int:
    return bucket_idx if monotonic == "INCREASING" else 3 - bucket_idx


def _tier(scores: list[int]) -> str:
    if not scores:
        return "UNAVAILABLE"
    maximum = 3 * len(scores)
    total = sum(scores)
    if total == maximum:
        return "VERY_HIGH"
    ratio = total / maximum
    if ratio >= 2 / 3:
        return "HIGH"
    if ratio >= 1 / 3:
        return "MEDIUM"
    return "LOW"


def _load_positioning(path: str | Path) -> tuple[
    dict[tuple[str, datetime], list[dict[str, Any]]],
    dict[tuple[str, datetime, Decimal], dict[str, Any]],
]:
    required = {
        "session_date", "timestamp", "strike", "strike_offset", "combined_5m",
        "ce_5m_state", "pe_5m_state", "ce_instrument_key", "pe_instrument_key",
    }
    by_time: dict[tuple[str, datetime], list[dict[str, Any]]] = {}
    by_strike: dict[tuple[str, datetime, Decimal], dict[str, Any]] = {}
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError("positioning CSV missing columns: " + ", ".join(sorted(missing)))
        for raw in reader:
            dt = _dt(raw["timestamp"])
            session = str(raw["session_date"])
            strike = _strike_key(raw.get("strike"))
            try:
                strike_offset = int(raw.get("strike_offset", ""))
            except (TypeError, ValueError):
                strike_offset = None
            row = dict(raw)
            row["dt"] = dt
            row["strike_key"] = strike
            row["strike_offset_int"] = strike_offset
            by_time.setdefault((session, dt), []).append(row)
            if strike is not None:
                key = (session, dt, strike)
                if key in by_strike:
                    raise ValueError(f"duplicate positioning row for {session} {dt.isoformat()} strike={strike}")
                by_strike[key] = row
    return by_time, by_strike


def _t0_atm(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    exact = [r for r in rows if r.get("strike_offset_int") == 0]
    return exact[0] if len(exact) == 1 else None


def _confirmation_timeline(
    by_strike: dict[tuple[str, datetime, Decimal], dict[str, Any]],
    *,
    session: str,
    t0: datetime,
    t0_atm: dict[str, Any] | None,
    direction: str,
) -> tuple[int | None, str, list[dict[str, Any]]]:
    if t0_atm is None or t0_atm.get("strike_key") is None:
        return None, "UNAVAILABLE_T0_ATM", []
    strike: Decimal = t0_atm["strike_key"]
    target = TARGET_COMBINED[direction]
    first: int | None = None
    missing = False
    timeline: list[dict[str, Any]] = []
    for offset in OFFSETS:
        ts = t0 + timedelta(minutes=offset)
        row = by_strike.get((session, ts, strike))
        if row is None:
            missing = True
            timeline.append({
                "offset_minutes": offset,
                "timestamp": ts.isoformat(),
                "available": False,
                "combined_5m": None,
                "ce_5m_state": None,
                "pe_5m_state": None,
                "confirmed": False,
            })
            continue
        confirmed = row.get("combined_5m") == target
        if confirmed and first is None:
            first = offset
        timeline.append({
            "offset_minutes": offset,
            "timestamp": ts.isoformat(),
            "available": True,
            "combined_5m": row.get("combined_5m"),
            "ce_5m_state": row.get("ce_5m_state"),
            "pe_5m_state": row.get("pe_5m_state"),
            "confirmed": confirmed,
        })
    if first is not None:
        return first, "CONFIRMED", timeline
    if missing:
        return None, "UNAVAILABLE_INCOMPLETE_TIMELINE", timeline
    return None, "NOT_CONFIRMED", timeline


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


def _summary(events: list[dict[str, Any]], direction: str) -> dict[str, Any]:
    true_label = f"TRUE_{direction}_REVERSAL"
    false_label = f"FALSE_{direction}_WARNING"
    counts = Counter(str(e.get("outcome")) for e in events)
    true_count = counts[true_label]
    false_count = counts[false_label]
    denom = true_count + false_count
    return {
        "event_count": len(events),
        "true_reversal_count": true_count,
        "false_warning_count": false_count,
        "true_vs_false_rate_pct": 100.0 * true_count / denom if denom else None,
        "outcome_counts": dict(sorted(counts.items())),
    }


def analyze(
    spec_path: str | Path,
    evidence_path: str | Path,
    positioning_path: str | Path,
    *,
    profile: str = DEFAULT_PROFILE,
) -> dict[str, Any]:
    frozen = _load_json(spec_path)
    if frozen.get("status") != "AVAILABLE":
        raise ValueError("frozen discriminator spec is not AVAILABLE")
    evidence = _load(evidence_path)
    by_time, by_strike = _load_positioning(positioning_path)

    report: dict[str, Any] = {
        "status": "AVAILABLE",
        "methodology_version": "PCR_RESEARCH_METHODOLOGY_V2",
        "profile": profile,
        "spec_source": str(spec_path),
        "evidence_source": str(evidence_path),
        "positioning_source": str(positioning_path),
        "leakage_guard": {
            "current_holdout_validation_input_used": False,
            "feature_identity_source": "EXPLICIT_FROZEN_PROFILE",
            "cut_point_source": "100_SESSION_TRAIN_SPEC_ONLY",
            "positioning_rule": "FROZEN_T0_ATM_EXACT_SAME_STRIKE_T0_TO_TPLUS5",
            "panel_any_confirmation_allowed": False,
            "moving_atm_substitution_allowed": False,
        },
        "methodology": [
            "Stage-2 events are first entries from the existing frozen bidirectional definition.",
            "Confidence feature identity is explicit in the selected profile and cannot be selected by the current holdout's labels.",
            "Quartile cut points are read only from the frozen 100-session TRAIN discriminator.",
            "The T0 ATM strike is frozen exactly once; only that same strike can confirm from T0 through T0+5m.",
            "If the frozen strike is absent at a later timestamp, it is marked unavailable and no substitute strike is used.",
            "T0 CE/PE instrument keys are carried downstream so premium research follows the exact same contract.",
        ],
        "directions": {},
    }

    for direction in ("BEARISH", "BULLISH"):
        specs = _frozen_specs(frozen, direction, profile)
        enriched: list[dict[str, Any]] = []
        for event in _events(evidence, direction):
            score_rows: list[dict[str, Any]] = []
            scores: list[int] = []
            complete = True
            for fs in specs:
                value = event.get(fs["feature"])
                if not isinstance(value, (int, float)):
                    complete = False
                    score_rows.append({"feature": fs["feature"], "value": None, "bucket": None, "favorable_score": None})
                    continue
                idx = _bucket_index(float(value), fs["train_cut_points"])
                score = _favorable_score(idx, fs["expected_monotonic"])
                scores.append(score)
                score_rows.append({
                    "feature": fs["feature"],
                    "value": float(value),
                    "bucket": f"Q{idx + 1}",
                    "favorable_score": score,
                })
            tier = _tier(scores) if complete and len(scores) == len(specs) else "UNAVAILABLE"
            confidence_score = sum(scores) if tier != "UNAVAILABLE" else None

            session = str(event["session_date"])
            t0 = _dt(event["event_time"])
            atm = _t0_atm(by_time.get((session, t0), []))
            first_offset, confirmation_status, timeline = _confirmation_timeline(
                by_strike, session=session, t0=t0, t0_atm=atm, direction=direction
            )
            strike_key = atm.get("strike_key") if atm else None
            enriched.append({
                "session_date": session,
                "timestamp": t0.isoformat(),
                "direction": direction,
                "outcome": str(event["label"]),
                "confidence_profile": profile,
                "confidence_tier": tier,
                "confidence_score": confidence_score,
                "severity_features": score_rows,
                "t0_atm_available": atm is not None,
                "t0_atm_strike": str(strike_key) if strike_key is not None else None,
                "t0_ce_instrument_key": atm.get("ce_instrument_key") if atm else None,
                "t0_pe_instrument_key": atm.get("pe_instrument_key") if atm else None,
                "confirmation_status": confirmation_status,
                "first_confirmation_offset_minutes": first_offset,
                "confirmation_offset_group": _offset_group(first_offset),
                "positioning_timeline": timeline,
            })

        report["directions"][direction.lower()] = {
            "direction": direction,
            "target_positioning": TARGET_COMBINED[direction],
            "frozen_severity_features": specs,
            "stage_2_event_count": len(enriched),
            "t0_atm_available_count": sum(bool(x["t0_atm_available"]) for x in enriched),
            "confirmed_within_5m_count": sum(x["confirmation_status"] == "CONFIRMED" for x in enriched),
            "confirmation_status_counts": dict(sorted(Counter(x["confirmation_status"] for x in enriched).items())),
            "by_confidence_tier": {
                tier: _summary([x for x in enriched if x["confidence_tier"] == tier], direction)
                for tier in ("LOW", "MEDIUM", "HIGH", "VERY_HIGH", "UNAVAILABLE")
            },
            "events": enriched,
        }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Leakage-guarded frozen PCR methodology v2")
    parser.add_argument("--spec", required=True, help="Frozen 100-session discriminator JSON")
    parser.add_argument("--evidence", required=True, help="Current block historical evidence CSV")
    parser.add_argument("--positioning", required=True, help="Historical positioning sidecar CSV")
    parser.add_argument("--profile", choices=sorted(PROFILES), default=DEFAULT_PROFILE)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = analyze(args.spec, args.evidence, args.positioning, profile=args.profile)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "methodology_version": result["methodology_version"],
        "profile": result["profile"],
        "leakage_guard": result["leakage_guard"],
        "bearish": {k: result["directions"]["bearish"][k] for k in ("stage_2_event_count", "t0_atm_available_count", "confirmed_within_5m_count", "confirmation_status_counts")},
        "bullish": {k: result["directions"]["bullish"][k] for k in ("stage_2_event_count", "t0_atm_available_count", "confirmed_within_5m_count", "confirmation_status_counts")},
        "output": str(out),
    }, indent=2))


if __name__ == "__main__":
    main()
