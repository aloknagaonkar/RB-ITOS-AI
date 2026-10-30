from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

MODEL = "CANONICAL_90_NINE_LEG_OPTION_COVERAGE_V1"

DEFAULT_DECISION_ROOT = Path(
    "data/historical-evidence/canonical-decision-audit-v1"
)
DEFAULT_EVIDENCE_ROOT = Path("data/historical-evidence")
DEFAULT_OUTPUT = Path(
    "data/historical-evidence/canonical-90-nine-leg-option-coverage-v1.json"
)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _iso_minute(value: datetime) -> str:
    return value.replace(second=0, microsecond=0).isoformat()


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _nonempty_files(root: Path, pattern: str) -> list[Path]:
    return [
        p for p in sorted(root.glob(pattern))
        if p.is_file() and p.stat().st_size > 0
    ]


def _block_from_name(path: Path, prefix: str) -> str:
    suffix = path.stem.removeprefix(prefix + "-")
    return suffix.upper().replace("-", "_")


def load_trade_eligible_events(decision_root: str | Path) -> list[dict[str, Any]]:
    root = Path(decision_root)
    events: list[dict[str, Any]] = []
    for p in sorted(root.glob("2026-*.json")):
        doc = json.loads(p.read_text(encoding="utf-8"))
        for event in doc.get("events", []):
            if event.get("final_decision") == "TRADE_ELIGIBLE":
                events.append(dict(event))
    events.sort(key=lambda x: (x["session_date"], x["c1_timestamp"], x["event_id"]))
    return events


def build_session_file_map(
    files: list[Path],
    *,
    prefix: str,
) -> dict[str, tuple[str, Path]]:
    mapping: dict[str, tuple[str, Path]] = {}
    duplicate: dict[str, list[str]] = defaultdict(list)

    for p in files:
        block = _block_from_name(p, prefix)
        seen: set[str] = set()
        with p.open(newline="", encoding="utf-8-sig") as f:
            rd = csv.DictReader(f)
            if "session_date" not in (rd.fieldnames or []):
                continue
            for row in rd:
                d = str(row.get("session_date") or "").strip()
                if not d or d in seen:
                    continue
                seen.add(d)
                if d in mapping and mapping[d][1] != p:
                    duplicate[d].extend([str(mapping[d][1]), str(p)])
                else:
                    mapping[d] = (block, p)

    if duplicate:
        sample = {k: sorted(set(v)) for k, v in list(duplicate.items())[:5]}
        raise ValueError(f"duplicate session ownership: {sample}")

    return mapping


def leg_spec(direction: str) -> list[tuple[str, int, str]]:
    d = str(direction).upper()

    if d == "BULLISH":
        return [
            ("ITM4", -4, "CE"),
            ("ITM3", -3, "CE"),
            ("ITM2", -2, "CE"),
            ("ITM1", -1, "CE"),
            ("ATM",   0, "CE"),
            ("OTM1",  1, "CE"),
            ("OTM2",  2, "CE"),
            ("OTM3",  3, "CE"),
            ("OTM4",  4, "CE"),
        ]

    if d == "BEARISH":
        return [
            ("ITM4",  4, "PE"),
            ("ITM3",  3, "PE"),
            ("ITM2",  2, "PE"),
            ("ITM1",  1, "PE"),
            ("ATM",   0, "PE"),
            ("OTM1", -1, "PE"),
            ("OTM2", -2, "PE"),
            ("OTM3", -3, "PE"),
            ("OTM4", -4, "PE"),
        ]

    raise ValueError(f"unsupported direction: {direction}")


def resolve_legs(
    events: list[dict[str, Any]],
    positioning_map: dict[str, tuple[str, Path]],
) -> list[dict[str, Any]]:
    by_file: dict[Path, list[dict[str, Any]]] = defaultdict(list)

    for event in events:
        owner = positioning_map.get(event["session_date"])
        if owner is None:
            for label, offset, side in leg_spec(event["direction"]):
                by_file[Path("__MISSING__")].append({
                    **event,
                    "leg": label,
                    "strike_offset": offset,
                    "option_side": side,
                    "coverage_status": "POSITIONING_SESSION_MISSING",
                })
            continue

        block, p = owner
        for label, offset, side in leg_spec(event["direction"]):
            by_file[p].append({
                **event,
                "block": block,
                "leg": label,
                "strike_offset": offset,
                "option_side": side,
            })

    out: list[dict[str, Any]] = []

    for p, legs in by_file.items():
        if str(p) == "__MISSING__":
            out.extend(legs)
            continue

        needed = {
            (x["session_date"], x["c2_expected_timestamp"], int(x["strike_offset"]))
            for x in legs
        }
        matches: dict[tuple[str, str, int], list[dict[str, str]]] = defaultdict(list)

        with p.open(newline="", encoding="utf-8-sig") as f:
            rd = csv.DictReader(f)
            required = {
                "session_date","timestamp","moving_atm","strike","strike_offset",
                "ce_instrument_key","pe_instrument_key",
            }
            missing = required - set(rd.fieldnames or [])
            if missing:
                raise ValueError(f"{p}: missing positioning columns {sorted(missing)}")

            for row in rd:
                try:
                    offset = int(float(str(row.get("strike_offset") or "")))
                except ValueError:
                    continue

                key = (
                    str(row.get("session_date") or ""),
                    str(row.get("timestamp") or ""),
                    offset,
                )
                if key in needed:
                    matches[key].append(row)

        for leg in legs:
            key = (
                leg["session_date"],
                leg["c2_expected_timestamp"],
                int(leg["strike_offset"]),
            )
            rows = matches.get(key, [])
            result = dict(leg)
            result["positioning_file"] = str(p)

            if not rows:
                result["coverage_status"] = "MISSING_EXACT_STRIKE_POSITIONING"
                out.append(result)
                continue

            if len(rows) != 1:
                result["coverage_status"] = "AMBIGUOUS_EXACT_STRIKE_POSITIONING"
                result["positioning_match_count"] = len(rows)
                out.append(result)
                continue

            row = rows[0]
            moving_atm = _float(row.get("moving_atm"))
            strike = _float(row.get("strike"))
            actual_offset = int(float(row["strike_offset"]))

            key_name = (
                "ce_instrument_key"
                if result["option_side"] == "CE"
                else "pe_instrument_key"
            )
            instrument = str(row.get(key_name) or "").strip()

            if moving_atm is None or strike is None or actual_offset != result["strike_offset"]:
                result["coverage_status"] = "INCONSISTENT_EXACT_STRIKE_POSITIONING"
                out.append(result)
                continue

            if not instrument:
                result["coverage_status"] = "MISSING_EXACT_STRIKE_INSTRUMENT"
                result["moving_atm"] = moving_atm
                result["strike"] = strike
                out.append(result)
                continue

            entry_dt = _dt(result["c2_expected_timestamp"]) + timedelta(minutes=1)
            result.update({
                "coverage_status": "CONTRACT_RESOLVED",
                "moving_atm": moving_atm,
                "strike": strike,
                "instrument_key": instrument,
                "entry_timestamp": _iso_minute(entry_dt),
                "path_end_timestamp": _iso_minute(entry_dt + timedelta(minutes=15)),
            })
            out.append(result)

    out.sort(
        key=lambda x: (
            x["session_date"],
            x["c1_timestamp"],
            x["event_id"],
            x["leg"],
        )
    )
    return out


def attach_ohlc_coverage(
    legs: list[dict[str, Any]],
    option_map: dict[str, tuple[str, Path]],
) -> list[dict[str, Any]]:
    by_file: dict[Path, list[dict[str, Any]]] = defaultdict(list)

    for leg in legs:
        if leg.get("coverage_status") != "CONTRACT_RESOLVED":
            continue

        owner = option_map.get(leg["session_date"])
        if owner is None:
            leg["coverage_status"] = "OPTION_OHLC_SESSION_MISSING"
            continue

        block, p = owner
        if block != leg.get("block"):
            leg["coverage_status"] = "BLOCK_MISMATCH"
            leg["option_ohlc_block"] = block
            leg["option_ohlc_file"] = str(p)
            continue

        leg["option_ohlc_block"] = block
        leg["option_ohlc_file"] = str(p)
        by_file[p].append(leg)

    for p, file_legs in by_file.items():
        need: dict[tuple[str, str], set[str]] = defaultdict(set)

        for leg in file_legs:
            start = _dt(leg["entry_timestamp"])
            for i in range(16):
                need[(leg["session_date"], leg["instrument_key"])].add(
                    _iso_minute(start + timedelta(minutes=i))
                )

        seen: dict[tuple[str, str], dict[str, dict[str, str]]] = defaultdict(dict)

        with p.open(newline="", encoding="utf-8-sig") as f:
            rd = csv.DictReader(f)
            required = {
                "session_date","instrument_key","strike","side","timestamp",
                "open","high","low","close",
            }
            missing = required - set(rd.fieldnames or [])
            if missing:
                raise ValueError(f"{p}: missing option columns {sorted(missing)}")

            for row in rd:
                key = (
                    str(row.get("session_date") or ""),
                    str(row.get("instrument_key") or ""),
                )
                wanted = need.get(key)
                if not wanted:
                    continue
                ts = str(row.get("timestamp") or "")
                if ts in wanted:
                    seen[key][ts] = row

        for leg in file_legs:
            key = (leg["session_date"], leg["instrument_key"])
            start = _dt(leg["entry_timestamp"])
            expected = [
                _iso_minute(start + timedelta(minutes=i))
                for i in range(16)
            ]
            actual = seen.get(key, {})
            entry_ts = expected[0]

            if entry_ts not in actual:
                leg["coverage_status"] = "MISSING_ENTRY_MINUTE"
                leg["missing_timestamps"] = [entry_ts]
                continue

            entry_row = actual[entry_ts]
            entry_open = _float(entry_row.get("open"))
            actual_side = str(entry_row.get("side") or "").upper()
            actual_strike = _float(entry_row.get("strike"))

            if entry_open is None or entry_open <= 0:
                leg["coverage_status"] = "INVALID_ENTRY_OPEN"
                leg["entry_open"] = entry_open
                continue

            if actual_side != leg["option_side"] or actual_strike != leg["strike"]:
                leg["coverage_status"] = "OPTION_IDENTITY_MISMATCH"
                leg["ohlc_side"] = actual_side
                leg["ohlc_strike"] = actual_strike
                continue

            missing_ts = [t for t in expected if t not in actual]
            if missing_ts:
                missing_dt = [_dt(t) for t in missing_ts]
                censored = all(
                    t.date().isoformat() == leg["session_date"]
                    and (t.hour, t.minute) >= (15, 30)
                    for t in missing_dt
                )
                leg["coverage_status"] = (
                    "SESSION_END_CENSORED"
                    if censored
                    else "INCOMPLETE_15M_PATH"
                )
                leg["entry_open"] = entry_open
                leg["path_rows_available"] = sum(t in actual for t in expected)
                leg["missing_timestamps"] = missing_ts
                continue

            leg["coverage_status"] = "READY"
            leg["entry_open"] = entry_open
            leg["path_rows_available"] = 16
            leg["missing_timestamps"] = []

    return legs


def run(
    *,
    decision_root: str | Path = DEFAULT_DECISION_ROOT,
    evidence_root: str | Path = DEFAULT_EVIDENCE_ROOT,
    output: str | Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    evidence = Path(evidence_root)
    events = load_trade_eligible_events(decision_root)

    positioning_map = build_session_file_map(
        _nonempty_files(evidence, "positioning-*.csv"),
        prefix="positioning",
    )
    option_map = build_session_file_map(
        _nonempty_files(evidence, "option-ohlc-*.csv"),
        prefix="option-ohlc",
    )

    legs = resolve_legs(events, positioning_map)
    legs = attach_ohlc_coverage(legs, option_map)

    labels = ("ITM4","ITM3","ITM2","ITM1","ATM","OTM1","OTM2","OTM3","OTM4")
    counts = Counter(x["coverage_status"] for x in legs)

    by_leg = {
        label: dict(Counter(
            x["coverage_status"] for x in legs if x["leg"] == label
        ))
        for label in labels
    }

    by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for leg in legs:
        by_event[str(leg["event_id"])].append(leg)

    complete = sum(
        len(v) == 9
        and {x["leg"] for x in v} == set(labels)
        and all(x["coverage_status"] == "READY" for x in v)
        for v in by_event.values()
    )

    censored_only = sum(
        len(v) == 9
        and all(x["coverage_status"] in {"READY","SESSION_END_CENSORED"} for x in v)
        and any(x["coverage_status"] == "SESSION_END_CENSORED" for x in v)
        for v in by_event.values()
    )

    result = {
        "model": MODEL,
        "signal_count": len(events),
        "expected_leg_count": len(events) * 9,
        "actual_leg_count": len(legs),
        "coverage_counts": dict(counts),
        "ready_leg_count": counts.get("READY", 0),
        "not_ready_leg_count": len(legs) - counts.get("READY", 0),
        "complete_nine_leg_signal_count": complete,
        "session_end_censored_signal_count": censored_only,
        "by_leg": by_leg,
        "rules": {
            "candidate_source": "TRADE_ELIGIBLE only",
            "bullish": "ITM4..ITM1 = offsets -4..-1 CE; ATM 0 CE; OTM1..OTM4 = +1..+4 CE",
            "bearish": "ITM4..ITM1 = offsets +4..+1 PE; ATM 0 PE; OTM1..OTM4 = -1..-4 PE",
            "entry": "exact next-minute OPEN after C2",
            "nearest_strike_fallback": False,
            "nearest_time_fallback": False,
            "path_requirement": "entry minute through entry+15 minutes inclusive",
        },
        "legs": legs,
    }

    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--decision-root", default=str(DEFAULT_DECISION_ROOT))
    ap.add_argument("--evidence-root", default=str(DEFAULT_EVIDENCE_ROOT))
    ap.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = ap.parse_args()

    result = run(
        decision_root=args.decision_root,
        evidence_root=args.evidence_root,
        output=args.output,
    )

    print(json.dumps({
        "model": result["model"],
        "signal_count": result["signal_count"],
        "expected_leg_count": result["expected_leg_count"],
        "actual_leg_count": result["actual_leg_count"],
        "coverage_counts": result["coverage_counts"],
        "ready_leg_count": result["ready_leg_count"],
        "not_ready_leg_count": result["not_ready_leg_count"],
        "complete_nine_leg_signal_count": result["complete_nine_leg_signal_count"],
        "session_end_censored_signal_count": result["session_end_censored_signal_count"],
        "by_leg": result["by_leg"],
        "output": args.output,
    }, indent=2))


if __name__ == "__main__":
    main()
