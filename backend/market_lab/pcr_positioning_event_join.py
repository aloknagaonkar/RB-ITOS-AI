"""Join frozen bidirectional PCR Stage-2 events to historical strike positioning.

Research-only.  This module does not emit trade signals.  It measures whether
same-strike positioning confirms a PCR transition at T0 or within the next
five minutes, and compares confirmation frequency/timing by outcome label.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

DIRECTIONS = {
    "BEARISH": (-1, -1, 1),
    "BULLISH": (1, 1, -1),
}
TARGET_COMBINED = {
    "BEARISH": "STRONG_BEARISH",
    "BULLISH": "STRONG_BULLISH",
}
OFFSETS = tuple(range(0, 6))


def _float(v: Any) -> float | None:
    if v in (None, ""):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _dt(v: Any) -> datetime:
    s = str(v)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def _sign(v: float | None) -> int | None:
    if v is None:
        return None
    if v > 0:
        return 1
    if v < 0:
        return -1
    return 0


def _load_evidence(path: str | Path) -> list[dict[str, Any]]:
    required = {
        "session_date", "timestamp", "spot",
        "moving_pcr_change_5m", "moving_pcr_change_15m", "moving_pcr_change_30m",
        "forward_change_5m", "forward_change_15m", "forward_change_30m",
    }
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        missing = required.difference(r.fieldnames or [])
        if missing:
            raise ValueError("evidence CSV missing columns: " + ", ".join(sorted(missing)))
        for raw in r:
            row = dict(raw)
            row["dt"] = _dt(raw["timestamp"])
            for key in required.difference({"session_date", "timestamp"}):
                row[key] = _float(raw.get(key))
            rows.append(row)
    return rows


def _load_positioning(path: str | Path) -> dict[tuple[str, datetime], list[dict[str, Any]]]:
    required = {
        "session_date", "timestamp", "strike", "strike_offset",
        "combined_5m", "ce_5m_state", "pe_5m_state",
    }
    by_time: dict[tuple[str, datetime], list[dict[str, Any]]] = defaultdict(list)
    with Path(path).open("r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        missing = required.difference(r.fieldnames or [])
        if missing:
            raise ValueError("positioning CSV missing columns: " + ", ".join(sorted(missing)))
        for raw in r:
            row = dict(raw)
            row["dt"] = _dt(raw["timestamp"])
            row["strike"] = _float(raw.get("strike"))
            try:
                row["strike_offset"] = int(raw.get("strike_offset", ""))
            except ValueError:
                row["strike_offset"] = None
            by_time[(str(raw["session_date"]), row["dt"])].append(row)
    return by_time


def _stage2_events(rows: list[dict[str, Any]], direction: str) -> list[dict[str, Any]]:
    expected = DIRECTIONS[direction]
    by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_session[str(row["session_date"])].append(row)
    events: list[dict[str, Any]] = []
    for session in sorted(by_session):
        was_in = False
        for row in sorted(by_session[session], key=lambda x: x["dt"]):
            signs = (
                _sign(row.get("moving_pcr_change_5m")),
                _sign(row.get("moving_pcr_change_15m")),
                _sign(row.get("moving_pcr_change_30m")),
            )
            is_in = signs == expected
            if is_in and not was_in:
                events.append(row)
            was_in = is_in
    return events


def _prior15(by_time: dict[datetime, dict[str, Any]], event_dt: datetime) -> float | None:
    now = by_time.get(event_dt)
    before = by_time.get(event_dt - timedelta(minutes=15))
    if not now or not before:
        return None
    a, b = now.get("spot"), before.get("spot")
    if not isinstance(a, float) or not isinstance(b, float):
        return None
    return a - b


def _response_label(direction: str, prior15: float | None, f5: float | None, f15: float | None, f30: float | None) -> str:
    if prior15 is None or f15 is None:
        return "UNAVAILABLE"
    bullish = direction == "BULLISH"
    prior_opposite = prior15 < 0 if bullish else prior15 > 0
    favorable15 = f15 > 0 if bullish else f15 < 0
    favorable30 = None if f30 is None else (f30 > 0 if bullish else f30 < 0)
    favorable5 = None if f5 is None else (f5 > 0 if bullish else f5 < 0)
    prefix = direction
    if prior_opposite:
        if favorable15 and favorable30 is True:
            return f"TRUE_{prefix}_REVERSAL"
        if favorable15 and favorable30 is False:
            return f"{prefix}_PULLBACK"
        if favorable5 is True and not favorable15:
            return f"SHORT_{prefix}_REVERSAL"
        return f"FALSE_{prefix}_WARNING"
    if favorable15:
        return f"{prefix}_CONTINUATION"
    return f"FALSE_{prefix}_WARNING"


def _confirmation_at(rows: list[dict[str, Any]], direction: str) -> tuple[bool, list[float], list[int]]:
    target = TARGET_COMBINED[direction]
    strikes: list[float] = []
    offsets: list[int] = []
    for row in rows:
        if row.get("combined_5m") == target:
            strike = row.get("strike")
            off = row.get("strike_offset")
            if isinstance(strike, float):
                strikes.append(strike)
            if isinstance(off, int):
                offsets.append(off)
    return bool(strikes), strikes, offsets


def analyze(evidence_csv: str | Path, positioning_csv: str | Path) -> dict[str, Any]:
    evidence = _load_evidence(evidence_csv)
    positioning = _load_positioning(positioning_csv)
    evidence_by_session: dict[str, dict[datetime, dict[str, Any]]] = defaultdict(dict)
    for row in evidence:
        evidence_by_session[str(row["session_date"])][row["dt"]] = row

    report: dict[str, Any] = {
        "status": "AVAILABLE",
        "evidence_source": str(evidence_csv),
        "positioning_source": str(positioning_csv),
        "methodology": [
            "Stage-2 events are first entries into the frozen bidirectional PCR state.",
            "Positioning confirmation is STRONG_BULLISH/STRONG_BEARISH on the 5m exact-baseline sidecar.",
            "Confirmation is scanned at T0 through T0+5m; no interpolation or nearest timestamp matching.",
            "Any strike in the Moving-ATM +/-5 panel can confirm; strike offsets are retained for later refinement.",
            "Outcome labels are descriptive research labels, not option trade outcomes.",
        ],
        "directions": {},
    }

    for direction in ("BEARISH", "BULLISH"):
        events = _stage2_events(evidence, direction)
        event_rows: list[dict[str, Any]] = []
        outcome_totals: Counter[str] = Counter()
        outcome_confirmed: Counter[str] = Counter()
        first_offset_counts: Counter[str] = Counter()
        offset_any_counts = {str(o): 0 for o in OFFSETS}

        for event in events:
            session = str(event["session_date"])
            event_dt: datetime = event["dt"]
            prior = _prior15(evidence_by_session[session], event_dt)
            label = _response_label(
                direction,
                prior,
                event.get("forward_change_5m"),
                event.get("forward_change_15m"),
                event.get("forward_change_30m"),
            )
            outcome_totals[label] += 1
            first_offset: int | None = None
            first_strikes: list[float] = []
            first_offsets: list[int] = []
            timeline: list[dict[str, Any]] = []
            for offset in OFFSETS:
                ts = event_dt + timedelta(minutes=offset)
                rows_here = positioning.get((session, ts), [])
                confirmed, strikes, strike_offsets = _confirmation_at(rows_here, direction)
                if confirmed:
                    offset_any_counts[str(offset)] += 1
                    if first_offset is None:
                        first_offset = offset
                        first_strikes = strikes
                        first_offsets = strike_offsets
                timeline.append({
                    "offset_minutes": offset,
                    "timestamp": ts.isoformat(),
                    "confirmed": confirmed,
                    "confirming_strikes": strikes,
                    "confirming_strike_offsets": strike_offsets,
                })
            if first_offset is not None:
                outcome_confirmed[label] += 1
                first_offset_counts[str(first_offset)] += 1
            event_rows.append({
                "session_date": session,
                "timestamp": event_dt.isoformat(),
                "direction": direction,
                "outcome": label,
                "first_confirmation_offset_minutes": first_offset,
                "first_confirmation_strikes": first_strikes,
                "first_confirmation_strike_offsets": first_offsets,
                "timeline": timeline,
            })

        confirmed_total = sum(first_offset_counts.values())
        outcome_stats = {}
        for label in sorted(outcome_totals):
            total = outcome_totals[label]
            confirmed = outcome_confirmed[label]
            outcome_stats[label] = {
                "event_count": total,
                "confirmed_within_5m_count": confirmed,
                "confirmed_within_5m_pct": (100.0 * confirmed / total) if total else None,
            }
        report["directions"][direction.lower()] = {
            "direction": direction,
            "target_positioning": TARGET_COMBINED[direction],
            "stage_2_event_count": len(events),
            "confirmed_within_5m_count": confirmed_total,
            "confirmed_within_5m_pct": (100.0 * confirmed_total / len(events)) if events else None,
            "first_confirmation_offset_counts": dict(sorted(first_offset_counts.items(), key=lambda kv: int(kv[0]))),
            "confirmation_present_at_offset_counts": offset_any_counts,
            "outcomes": outcome_stats,
            "events": event_rows,
        }
    return report


def main() -> None:
    p = argparse.ArgumentParser(description="Join Stage-2 PCR events to historical positioning timeline")
    p.add_argument("--evidence", required=True)
    p.add_argument("--positioning", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    result = analyze(args.evidence, args.positioning)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    compact = {
        "status": result["status"],
        "bearish": {k: result["directions"]["bearish"][k] for k in ("stage_2_event_count", "confirmed_within_5m_count", "confirmed_within_5m_pct", "first_confirmation_offset_counts")},
        "bullish": {k: result["directions"]["bullish"][k] for k in ("stage_2_event_count", "confirmed_within_5m_count", "confirmed_within_5m_pct", "first_confirmation_offset_counts")},
        "output": str(out),
    }
    print(json.dumps(compact, indent=2))


if __name__ == "__main__":
    main()
