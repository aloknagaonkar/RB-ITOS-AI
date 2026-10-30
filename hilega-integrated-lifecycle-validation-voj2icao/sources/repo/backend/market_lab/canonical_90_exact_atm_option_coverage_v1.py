from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

MODEL = "CANONICAL_90_EXACT_ATM_OPTION_COVERAGE_GATE_V1"

DEFAULT_DECISION_ROOT = Path(
    "data/historical-evidence/canonical-decision-audit-v1"
)
DEFAULT_EVIDENCE_ROOT = Path("data/historical-evidence")
DEFAULT_OUTPUT = Path(
    "data/historical-evidence/canonical-90-exact-atm-option-coverage-v1.json"
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


def _block_from_name(path: Path, prefix: str) -> str:
    name = path.stem
    suffix = name.removeprefix(prefix + "-")
    return suffix.upper().replace("-", "_")


def _nonempty_files(root: Path, pattern: str) -> list[Path]:
    return [
        p for p in sorted(root.glob(pattern))
        if p.is_file() and p.stat().st_size > 0
    ]


def load_trade_eligible_events(decision_root: str | Path) -> list[dict[str, Any]]:
    root = Path(decision_root)
    events: list[dict[str, Any]] = []
    for p in sorted(root.glob("2026-*.json")):
        doc = json.loads(p.read_text(encoding="utf-8"))
        for event in doc.get("events", []):
            if event.get("final_decision") == "TRADE_ELIGIBLE":
                events.append(dict(event))
    return events


def build_session_file_map(
    files: list[Path],
    *,
    prefix: str,
) -> dict[str, tuple[str, Path]]:
    mapping: dict[str, tuple[str, Path]] = {}
    duplicates: dict[str, list[str]] = defaultdict(list)

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
                    duplicates[d].extend([str(mapping[d][1]), str(p)])
                else:
                    mapping[d] = (block, p)

    if duplicates:
        sample = {k: sorted(set(v)) for k, v in list(duplicates.items())[:5]}
        raise ValueError(f"Duplicate session ownership across files: {sample}")

    return mapping


def _required_positioning_columns(fieldnames: list[str] | None) -> None:
    required = {
        "session_date",
        "timestamp",
        "moving_atm",
        "strike",
        "strike_offset",
        "ce_instrument_key",
        "pe_instrument_key",
    }
    missing = required - set(fieldnames or [])
    if missing:
        raise ValueError(f"Positioning CSV missing columns: {sorted(missing)}")


def resolve_exact_atm_contracts(
    events: list[dict[str, Any]],
    positioning_map: dict[str, tuple[str, Path]],
) -> list[dict[str, Any]]:
    by_file: dict[Path, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        d = event["session_date"]
        owner = positioning_map.get(d)
        if owner is None:
            event["_coverage_issue"] = "POSITIONING_SESSION_MISSING"
            continue
        event["_block"], p = owner
        by_file[p].append(event)

    resolved: list[dict[str, Any]] = []

    for p, file_events in by_file.items():
        needs = {
            (e["session_date"], e["c2_expected_timestamp"]): e
            for e in file_events
        }
        matches: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)

        with p.open(newline="", encoding="utf-8-sig") as f:
            rd = csv.DictReader(f)
            _required_positioning_columns(rd.fieldnames)
            for row in rd:
                key = (
                    str(row.get("session_date") or ""),
                    str(row.get("timestamp") or ""),
                )
                if key not in needs:
                    continue
                try:
                    offset = int(float(str(row.get("strike_offset") or "")))
                except ValueError:
                    continue
                if offset == 0:
                    matches[key].append(row)

        for event in file_events:
            key = (event["session_date"], event["c2_expected_timestamp"])
            rows = matches.get(key, [])
            out = dict(event)
            out["block"] = event.get("_block")
            out["positioning_file"] = str(p)

            if not rows:
                out["coverage_status"] = "MISSING_EXACT_ATM_POSITIONING"
                resolved.append(out)
                continue
            if len(rows) != 1:
                out["coverage_status"] = "AMBIGUOUS_EXACT_ATM_POSITIONING"
                out["positioning_match_count"] = len(rows)
                resolved.append(out)
                continue

            row = rows[0]
            moving_atm = _float(row.get("moving_atm"))
            strike = _float(row.get("strike"))

            if moving_atm is None or strike is None or strike != moving_atm:
                out["coverage_status"] = "INCONSISTENT_EXACT_ATM_POSITIONING"
                out["moving_atm"] = moving_atm
                out["strike"] = strike
                resolved.append(out)
                continue

            side = "CE" if event["direction"] == "BULLISH" else "PE"
            key_name = "ce_instrument_key" if side == "CE" else "pe_instrument_key"
            instrument_key = str(row.get(key_name) or "").strip()

            if not instrument_key:
                out["coverage_status"] = "MISSING_EXACT_ATM_INSTRUMENT"
                out["option_side"] = side
                out["moving_atm"] = moving_atm
                out["strike"] = strike
                resolved.append(out)
                continue

            entry_dt = _dt(event["c2_expected_timestamp"]) + timedelta(minutes=1)
            out.update({
                "coverage_status": "CONTRACT_RESOLVED",
                "option_side": side,
                "moving_atm": moving_atm,
                "strike": strike,
                "instrument_key": instrument_key,
                "entry_timestamp": _iso_minute(entry_dt),
                "path_end_timestamp": _iso_minute(entry_dt + timedelta(minutes=15)),
            })
            resolved.append(out)

    # Include events that had no positioning owner.
    owned_ids = {r["event_id"] for r in resolved}
    for e in events:
        if e["event_id"] in owned_ids:
            continue
        out = dict(e)
        out["coverage_status"] = e.get("_coverage_issue", "POSITIONING_SESSION_MISSING")
        resolved.append(out)

    resolved.sort(key=lambda e: (e["session_date"], e["c1_timestamp"], e["event_id"]))
    return resolved


def attach_exact_option_coverage(
    rows: list[dict[str, Any]],
    option_map: dict[str, tuple[str, Path]],
) -> list[dict[str, Any]]:
    needed_by_file: dict[Path, list[dict[str, Any]]] = defaultdict(list)

    for row in rows:
        if row.get("coverage_status") != "CONTRACT_RESOLVED":
            continue
        owner = option_map.get(row["session_date"])
        if owner is None:
            row["coverage_status"] = "OPTION_OHLC_SESSION_MISSING"
            continue
        block, p = owner
        if row.get("block") and block != row["block"]:
            row["coverage_status"] = "BLOCK_MISMATCH"
            row["option_ohlc_block"] = block
            row["option_ohlc_file"] = str(p)
            continue
        row["option_ohlc_block"] = block
        row["option_ohlc_file"] = str(p)
        needed_by_file[p].append(row)

    for p, file_rows in needed_by_file.items():
        # Multiple eligible events can reuse the same exact option contract in
        # the same session. Build a UNION of timestamps needed for reading the
        # source file, but evaluate each event against its own 16-minute window.
        keys: dict[tuple[str, str], set[str]] = defaultdict(set)
        for row in file_rows:
            entry = _dt(row["entry_timestamp"])
            expected = {
                _iso_minute(entry + timedelta(minutes=i))
                for i in range(16)  # entry bar plus exact +1 ... +15 bars
            }
            keys[(row["session_date"], row["instrument_key"])].update(expected)

        seen: dict[tuple[str, str], dict[str, dict[str, str]]] = defaultdict(dict)

        with p.open(newline="", encoding="utf-8-sig") as f:
            rd = csv.DictReader(f)
            required = {
                "session_date","instrument_key","timestamp",
                "open","high","low","close","strike","side",
            }
            missing = required - set(rd.fieldnames or [])
            if missing:
                raise ValueError(f"Option OHLC CSV missing columns: {sorted(missing)}")

            for r in rd:
                key = (
                    str(r.get("session_date") or ""),
                    str(r.get("instrument_key") or ""),
                )
                expected = keys.get(key)
                if not expected:
                    continue
                t = str(r.get("timestamp") or "")
                if t in expected:
                    seen[key][t] = r

        for row in file_rows:
            key = (row["session_date"], row["instrument_key"])
            entry = row["entry_timestamp"]
            entry_dt = _dt(entry)
            expected = sorted(
                _iso_minute(entry_dt + timedelta(minutes=i))
                for i in range(16)
            )
            actual = seen.get(key, {})

            if entry not in actual:
                row["coverage_status"] = "MISSING_ENTRY_MINUTE"
                row["missing_timestamps"] = [entry]
                continue

            entry_row = actual[entry]
            entry_open = _float(entry_row.get("open"))
            if entry_open is None or entry_open <= 0:
                row["coverage_status"] = "INVALID_ENTRY_OPEN"
                row["entry_open"] = entry_open
                continue

            side = str(entry_row.get("side") or "").upper()
            strike = _float(entry_row.get("strike"))
            if side != row["option_side"] or strike != row["strike"]:
                row["coverage_status"] = "OPTION_IDENTITY_MISMATCH"
                row["ohlc_side"] = side
                row["ohlc_strike"] = strike
                continue

            missing_ts = [t for t in expected if t not in actual]
            if missing_ts:
                # NSE option minute bars for the regular session end with the
                # 15:29 bar. If every missing timestamp is 15:30 or later on
                # the same session date, this is deterministic session-end
                # censoring rather than a data gap.
                missing_dt = [_dt(t) for t in missing_ts]
                session_end_censored = all(
                    t.date().isoformat() == row["session_date"]
                    and (t.hour, t.minute) >= (15, 30)
                    for t in missing_dt
                )
                row["coverage_status"] = (
                    "SESSION_END_CENSORED"
                    if session_end_censored
                    else "INCOMPLETE_15M_PATH"
                )
                row["entry_open"] = entry_open
                row["path_rows_available"] = sum(
                    1 for t in expected if t in actual
                )
                row["missing_timestamps"] = missing_ts
                continue

            row["coverage_status"] = "READY"
            row["entry_open"] = entry_open
            row["path_rows_available"] = len(actual)
            row["missing_timestamps"] = []

    return rows


def run(
    *,
    decision_root: str | Path = DEFAULT_DECISION_ROOT,
    evidence_root: str | Path = DEFAULT_EVIDENCE_ROOT,
    output: str | Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    evidence = Path(evidence_root)
    events = load_trade_eligible_events(decision_root)

    positioning_files = _nonempty_files(evidence, "positioning-*.csv")
    option_files = _nonempty_files(evidence, "option-ohlc-*.csv")

    positioning_map = build_session_file_map(
        positioning_files, prefix="positioning"
    )
    option_map = build_session_file_map(
        option_files, prefix="option-ohlc"
    )

    rows = resolve_exact_atm_contracts(events, positioning_map)
    rows = attach_exact_option_coverage(rows, option_map)

    counts = Counter(r["coverage_status"] for r in rows)
    by_direction = {
        direction: dict(Counter(
            r["coverage_status"] for r in rows
            if r.get("direction") == direction
        ))
        for direction in ("BULLISH", "BEARISH")
    }

    result = {
        "model": MODEL,
        "candidate_count": len(events),
        "coverage_counts": dict(counts),
        "ready_count": counts.get("READY", 0),
        "not_ready_count": len(events) - counts.get("READY", 0),
        "by_direction": by_direction,
        "rules": {
            "candidate_source": "TRADE_ELIGIBLE only",
            "contract": "exact C2 moving ATM",
            "bullish_side": "CE",
            "bearish_side": "PE",
            "nearest_strike_fallback": False,
            "nearest_time_fallback": False,
            "entry": "exact next-minute OPEN after C2",
            "path_requirement": "entry minute through entry+15 minutes inclusive",
            "session_end_censoring": "missing timestamps only at 15:30 or later are classified SESSION_END_CENSORED",
        },
        "rows": rows,
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
        "candidate_count": result["candidate_count"],
        "coverage_counts": result["coverage_counts"],
        "ready_count": result["ready_count"],
        "not_ready_count": result["not_ready_count"],
        "by_direction": result["by_direction"],
        "output": args.output,
    }, indent=2))


if __name__ == "__main__":
    main()
