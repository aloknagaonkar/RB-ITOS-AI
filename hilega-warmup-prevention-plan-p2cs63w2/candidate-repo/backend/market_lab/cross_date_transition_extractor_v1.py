from __future__ import annotations

import argparse
import csv
import glob
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable, Optional


MODEL = "CROSS_DATE_TRANSITION_EXTRACTOR_V1"


def _sign(value: Optional[float]) -> str:
    if value is None:
        return "NA"
    if value > 0:
        return "POS"
    if value < 0:
        return "NEG"
    return "ZERO"


def _horizon_state(imbalance: Optional[float], pcr_change: Optional[float]) -> str:
    """
    Descriptive research label only.

    BULLISH: option OI imbalance > 0 AND PCR change > 0
    BEARISH: option OI imbalance < 0 AND PCR change < 0
    MIXED:   available values disagree or contain zero
    NA:      either value unavailable
    """
    if imbalance is None or pcr_change is None:
        return "NA"
    if imbalance > 0 and pcr_change > 0:
        return "BULLISH"
    if imbalance < 0 and pcr_change < 0:
        return "BEARISH"
    return "MIXED"


def _three_horizon_state(s5: str, s10: str, s15: str) -> str:
    states = (s5, s10, s15)
    if "NA" in states:
        return "INCOMPLETE"
    if all(s == "BULLISH" for s in states):
        return "BULLISH_ALL_3"
    if all(s == "BEARISH" for s in states):
        return "BEARISH_ALL_3"
    return "MIXED"


def _agreement_count(states: Iterable[str], target: str) -> int:
    return sum(1 for s in states if s == target)


@dataclass(frozen=True)
class TransitionRow:
    session_date: str
    timestamp: str
    spot: Optional[float]
    moving_atm: Optional[float]

    imbalance_5m: Optional[float]
    pcr_change_5m: Optional[float]
    state_5m: str

    imbalance_10m: Optional[float]
    pcr_change_10m: Optional[float]
    state_10m: str

    imbalance_15m: Optional[float]
    pcr_change_15m: Optional[float]
    state_15m: str

    bullish_horizon_count: int
    bearish_horizon_count: int
    three_horizon_state: str

    pcr_current: Optional[float]
    session_imbalance: Optional[float]
    session_imbalance_sign: str
    session_pcr_baseline_0920: Optional[float]
    session_pcr_current: Optional[float]
    session_pcr_change_0920_to_now: Optional[float]
    session_pcr_change_sign: str

    futures_oi_direction: str
    futures_oi_status: str
    vwap_side: str

    fallback_used: bool
    evaluation_label: Optional[str]


@dataclass(frozen=True)
class PersistenceRun:
    session_date: str
    direction: str
    start_timestamp: str
    end_timestamp: str
    candles: int


def build_transition_row(session_date: str, row: dict[str, Any]) -> TransitionRow:
    s5 = _horizon_state(row.get("imbalance_5m"), row.get("pcr_change_5m"))
    s10 = _horizon_state(row.get("imbalance_10m"), row.get("pcr_change_10m"))
    s15 = _horizon_state(row.get("imbalance_15m"), row.get("pcr_change_15m"))
    states = (s5, s10, s15)

    return TransitionRow(
        session_date=session_date,
        timestamp=str(row.get("timestamp", "")),
        spot=row.get("spot"),
        moving_atm=row.get("moving_atm"),

        imbalance_5m=row.get("imbalance_5m"),
        pcr_change_5m=row.get("pcr_change_5m"),
        state_5m=s5,

        imbalance_10m=row.get("imbalance_10m"),
        pcr_change_10m=row.get("pcr_change_10m"),
        state_10m=s10,

        imbalance_15m=row.get("imbalance_15m"),
        pcr_change_15m=row.get("pcr_change_15m"),
        state_15m=s15,

        bullish_horizon_count=_agreement_count(states, "BULLISH"),
        bearish_horizon_count=_agreement_count(states, "BEARISH"),
        three_horizon_state=_three_horizon_state(s5, s10, s15),

        pcr_current=row.get("pcr_current"),
        session_imbalance=row.get("session_imbalance"),
        session_imbalance_sign=_sign(row.get("session_imbalance")),
        session_pcr_baseline_0920=row.get("session_pcr_baseline_0920"),
        session_pcr_current=row.get("session_pcr_current"),
        session_pcr_change_0920_to_now=row.get("session_pcr_change_0920_to_now"),
        session_pcr_change_sign=_sign(row.get("session_pcr_change_0920_to_now")),

        futures_oi_direction=str(row.get("futures_oi_direction") or "NA"),
        futures_oi_status=str(row.get("futures_oi_status") or "NA"),
        vwap_side=str(row.get("vwap_side") or "NA"),

        fallback_used=bool(row.get("fallback_used", False)),
        evaluation_label=row.get("evaluation_label"),
    )


def extract_rows(payload: dict[str, Any]) -> list[TransitionRow]:
    session_date = str(payload.get("session_date", ""))
    return [build_transition_row(session_date, row) for row in payload.get("rows", [])]


def extract_runs(rows: list[TransitionRow]) -> list[PersistenceRun]:
    """
    Emit every consecutive run of exact 3-horizon alignment.
    No minimum persistence threshold is applied.
    """
    runs: list[PersistenceRun] = []
    current_direction: Optional[str] = None
    start_timestamp: Optional[str] = None
    end_timestamp: Optional[str] = None
    candles = 0
    current_session: Optional[str] = None

    def flush() -> None:
        nonlocal current_direction, start_timestamp, end_timestamp, candles, current_session
        if current_direction and start_timestamp and end_timestamp and current_session:
            runs.append(PersistenceRun(
                session_date=current_session,
                direction=current_direction,
                start_timestamp=start_timestamp,
                end_timestamp=end_timestamp,
                candles=candles,
            ))
        current_direction = None
        start_timestamp = None
        end_timestamp = None
        candles = 0
        current_session = None

    for row in rows:
        if row.three_horizon_state == "BULLISH_ALL_3":
            direction = "BULLISH"
        elif row.three_horizon_state == "BEARISH_ALL_3":
            direction = "BEARISH"
        else:
            direction = None

        if direction is None:
            flush()
            continue

        if current_direction == direction and current_session == row.session_date:
            end_timestamp = row.timestamp
            candles += 1
        else:
            flush()
            current_direction = direction
            current_session = row.session_date
            start_timestamp = row.timestamp
            end_timestamp = row.timestamp
            candles = 1

    flush()
    return runs


def summarize(rows: list[TransitionRow], runs: list[PersistenceRun]) -> dict[str, Any]:
    sessions = sorted({r.session_date for r in rows})
    by_session: dict[str, Any] = {}

    for session in sessions:
        sr = [r for r in rows if r.session_date == session]
        session_runs = [r for r in runs if r.session_date == session]

        bullish_all3 = sum(r.three_horizon_state == "BULLISH_ALL_3" for r in sr)
        bearish_all3 = sum(r.three_horizon_state == "BEARISH_ALL_3" for r in sr)
        mixed = sum(r.three_horizon_state == "MIXED" for r in sr)
        incomplete = sum(r.three_horizon_state == "INCOMPLETE" for r in sr)

        by_session[session] = {
            "candles": len(sr),
            "bullish_all_3_candles": bullish_all3,
            "bearish_all_3_candles": bearish_all3,
            "mixed_candles": mixed,
            "incomplete_candles": incomplete,
            "bullish_all_3_with_futures_bullish": sum(
                r.three_horizon_state == "BULLISH_ALL_3" and r.futures_oi_direction == "BULLISH"
                for r in sr
            ),
            "bearish_all_3_with_futures_bearish": sum(
                r.three_horizon_state == "BEARISH_ALL_3" and r.futures_oi_direction == "BEARISH"
                for r in sr
            ),
            "bullish_all_3_with_vwap_above": sum(
                r.three_horizon_state == "BULLISH_ALL_3" and r.vwap_side == "ABOVE"
                for r in sr
            ),
            "bearish_all_3_with_vwap_below": sum(
                r.three_horizon_state == "BEARISH_ALL_3" and r.vwap_side == "BELOW"
                for r in sr
            ),
            "bullish_run_lengths": [r.candles for r in session_runs if r.direction == "BULLISH"],
            "bearish_run_lengths": [r.candles for r in session_runs if r.direction == "BEARISH"],
            "fallback_used_candles": sum(r.fallback_used for r in sr),
        }

    return {
        "status": "PASS",
        "model": MODEL,
        "sessions": sessions,
        "session_count": len(sessions),
        "row_count": len(rows),
        "run_count": len(runs),
        "by_session": by_session,
    }


def _load_payload(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if payload.get("status") != "PASS":
        raise ValueError(f"{path}: audit status is not PASS")
    if not isinstance(payload.get("rows"), list):
        raise ValueError(f"{path}: rows array missing")
    return payload


def _write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not records:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(records[0].keys()))
        writer.writeheader()
        writer.writerows(records)


def resolve_inputs(explicit: list[str], patterns: list[str]) -> list[Path]:
    resolved: list[Path] = [Path(x) for x in explicit]
    for pattern in patterns:
        resolved.extend(Path(p) for p in glob.glob(pattern))
    unique = sorted({p.resolve() for p in resolved})
    if not unique:
        raise ValueError("No audit JSON inputs resolved")
    return unique


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Research-only cross-date OI/PCR transition extractor."
    )
    parser.add_argument("--audit-json", action="append", default=[],
                        help="Audit JSON input. Repeat for multiple dates.")
    parser.add_argument("--audit-glob", action="append", default=[],
                        help="Glob resolving multiple audit JSON files.")
    parser.add_argument("--rows-csv", required=True)
    parser.add_argument("--runs-csv", required=True)
    parser.add_argument("--summary-json", required=True)
    args = parser.parse_args()

    paths = resolve_inputs(args.audit_json, args.audit_glob)

    all_rows: list[TransitionRow] = []
    for path in paths:
        payload = _load_payload(path)
        all_rows.extend(extract_rows(payload))

    # Stable chronological order within each date.
    all_rows.sort(key=lambda r: (r.session_date, r.timestamp))
    runs = extract_runs(all_rows)
    summary = summarize(all_rows, runs)

    _write_csv(Path(args.rows_csv), [asdict(r) for r in all_rows])
    _write_csv(Path(args.runs_csv), [asdict(r) for r in runs])

    summary_path = Path(args.summary_json)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(json.dumps({
        "status": "PASS",
        "model": MODEL,
        "inputs": [str(p) for p in paths],
        "sessions": summary["session_count"],
        "rows": summary["row_count"],
        "runs": summary["run_count"],
        "rows_csv": str(args.rows_csv),
        "runs_csv": str(args.runs_csv),
        "summary_json": str(args.summary_json),
    }, indent=2))


if __name__ == "__main__":
    main()
