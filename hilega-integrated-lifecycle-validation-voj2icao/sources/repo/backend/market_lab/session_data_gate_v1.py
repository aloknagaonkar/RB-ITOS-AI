from __future__ import annotations

# This file is a replacement for backend/market_lab/session_data_gate_v1.py
# It preserves the original gate behavior while correcting positioning OI field
# names to the actual cache schema:
#   ce_open_interest
#   pe_open_interest

import argparse
import csv
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, date
from pathlib import Path
from typing import Any

DEFAULT_FUTURES_CSV = Path(
    "data/historical-evidence/midpoint-v2-nifty-futures-vwap-v1-development.csv"
)

ALLOWED_BUCKETS = ("train", "oos-a", "oos-b", "oos-c", "oos-d")


@dataclass
class Check:
    name: str
    status: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionDataGateResult:
    session_date: str
    status: str
    checks: list[Check]
    repair_required: list[str]
    positioning_file: str | None = None
    option_ohlc_file: str | None = None
    futures_csv: str | None = None

    def to_dict(self) -> dict:
        return {
            "session_date": self.session_date,
            "status": self.status,
            "repair_required": self.repair_required,
            "positioning_file": self.positioning_file,
            "option_ohlc_file": self.option_ohlc_file,
            "futures_csv": self.futures_csv,
            "checks": [asdict(x) for x in self.checks],
        }


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def _candidate_files(data_root: Path, prefix: str, session_date: str) -> list[Path]:
    candidates: list[Path] = []
    for bucket in ALLOWED_BUCKETS:
        directory = data_root / f"{prefix}-{bucket}"
        if not directory.exists():
            continue

        exact = sorted(directory.glob(f"*__{session_date}__{session_date}__*.json"))
        candidates.extend(exact)

        for path in sorted(directory.glob(f"*{session_date}*.json")):
            if path in candidates:
                continue
            try:
                payload = _load_json(path)
            except Exception:
                continue
            if str(payload.get("session_date")) == session_date:
                candidates.append(path)
    return candidates


def _select_file(data_root: Path, prefix: str, session_date: str) -> Path | None:
    candidates = _candidate_files(data_root, prefix, session_date)
    return candidates[0] if candidates else None


def _parse_rows(payload: dict) -> list[dict]:
    rows = payload.get("rows")
    return rows if isinstance(rows, list) else []


def _timestamp_stats(rows: list[dict], session_date: str) -> dict:
    timestamps = []
    for row in rows:
        raw = row.get("timestamp")
        if not raw:
            continue
        try:
            ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except Exception:
            continue
        if ts.date().isoformat() == session_date:
            timestamps.append(ts)

    timestamps.sort()
    return {
        "timestamp_count": len(timestamps),
        "first_timestamp": timestamps[0].isoformat() if timestamps else None,
        "last_timestamp": timestamps[-1].isoformat() if timestamps else None,
    }


def _check_positioning(path: Path | None, session_date: str) -> Check:
    if path is None:
        return Check("POSITIONING", "FAIL", {"reason": "MISSING"})

    try:
        payload = _load_json(path)
    except Exception as exc:
        return Check("POSITIONING", "FAIL", {"reason": "UNREADABLE", "error": str(exc)})

    rows = _parse_rows(payload)
    stats = _timestamp_stats(rows, session_date)

    ce_rows = [r for r in rows if r.get("ce_instrument_key")]
    pe_rows = [r for r in rows if r.get("pe_instrument_key")]

    # Correct cache schema:
    #   ce_open_interest
    #   pe_open_interest
    oi_rows = [
        r for r in rows
        if r.get("ce_open_interest") is not None
        and r.get("pe_open_interest") is not None
    ]

    reasons = []
    if payload.get("status") not in (None, "AVAILABLE"):
        reasons.append(f"STATUS_{payload.get('status')}")
    if str(payload.get("session_date")) != session_date:
        reasons.append("SESSION_DATE_MISMATCH")
    if not rows:
        reasons.append("NO_ROWS")
    if not ce_rows or not pe_rows:
        reasons.append("CE_PE_INSTRUMENTS_MISSING")
    if not oi_rows:
        reasons.append("OPEN_INTEREST_MISSING")

    return Check(
        "POSITIONING",
        "PASS" if not reasons else "FAIL",
        {
            "file": str(path),
            "row_count": len(rows),
            "ce_rows": len(ce_rows),
            "pe_rows": len(pe_rows),
            "rows_with_both_open_interest": len(oi_rows),
            "oi_fields": ["ce_open_interest", "pe_open_interest"],
            **stats,
            "reasons": reasons,
        },
    )


def _check_option_ohlc(path: Path | None, session_date: str) -> Check:
    if path is None:
        return Check("OPTION_OHLC", "FAIL", {"reason": "MISSING"})

    try:
        payload = _load_json(path)
    except Exception as exc:
        return Check("OPTION_OHLC", "FAIL", {"reason": "UNREADABLE", "error": str(exc)})

    rows = _parse_rows(payload)
    reasons = []

    if payload.get("status") not in (None, "AVAILABLE"):
        reasons.append(f"STATUS_{payload.get('status')}")
    if str(payload.get("session_date")) != session_date:
        reasons.append("SESSION_DATE_MISMATCH")
    if not rows:
        reasons.append("NO_ROWS")

    instruments = {str(r.get("instrument_key")) for r in rows if r.get("instrument_key")}
    sides = {str(r.get("side")).upper() for r in rows if r.get("side")}
    strikes = {r.get("strike") for r in rows if r.get("strike") is not None}

    bad_ohlc = 0
    timestamps = []
    unique_keys = set()
    duplicate_key_rows = 0

    for row in rows:
        try:
            o, h, l, c = map(float, (row["open"], row["high"], row["low"], row["close"]))
            if h < max(o, c) or l > min(o, c) or h < l:
                bad_ohlc += 1
        except Exception:
            bad_ohlc += 1

        raw = row.get("timestamp")
        if raw:
            try:
                ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                if ts.date().isoformat() == session_date:
                    timestamps.append(ts)
                key = (row.get("instrument_key"), ts.isoformat())
                if key in unique_keys:
                    duplicate_key_rows += 1
                unique_keys.add(key)
            except Exception:
                pass

    timestamps.sort()

    if "CE" not in sides or "PE" not in sides:
        reasons.append("CE_OR_PE_SIDE_MISSING")
    if not instruments:
        reasons.append("NO_INSTRUMENTS")
    if not strikes:
        reasons.append("NO_STRIKES")
    if bad_ohlc:
        reasons.append("INVALID_OHLC")
    if duplicate_key_rows:
        reasons.append("DUPLICATE_INSTRUMENT_TIMESTAMP")

    return Check(
        "OPTION_OHLC",
        "PASS" if not reasons else "FAIL",
        {
            "file": str(path),
            "row_count": len(rows),
            "instrument_count": len(instruments),
            "strike_count": len(strikes),
            "sides": sorted(sides),
            "first_timestamp": timestamps[0].isoformat() if timestamps else None,
            "last_timestamp": timestamps[-1].isoformat() if timestamps else None,
            "invalid_ohlc_rows": bad_ohlc,
            "duplicate_instrument_timestamp_rows": duplicate_key_rows,
            "reasons": reasons,
        },
    )


def _check_futures(path: Path, session_date: str) -> Check:
    if not path.exists():
        return Check("FUTURES", "FAIL", {"reason": "CSV_MISSING", "file": str(path)})

    rows = []
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("session_date") == session_date:
                rows.append(row)

    reasons = []
    timestamps = []
    seen = set()
    dup = 0
    invalid = 0

    for row in rows:
        try:
            ts = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
            timestamps.append(ts)
            if row["timestamp"] in seen:
                dup += 1
            seen.add(row["timestamp"])

            o, h, l, c = map(float, (row["open"], row["high"], row["low"], row["close"]))
            volume = float(row["volume"])
            vwap = float(row["session_vwap"])
            if h < max(o, c) or l > min(o, c) or h < l or volume < 0 or vwap <= 0:
                invalid += 1
        except Exception:
            invalid += 1

    timestamps.sort()

    if not rows:
        reasons.append("MISSING")
    if rows and len(rows) < 300:
        reasons.append("TOO_FEW_1M_ROWS")
    if timestamps:
        if timestamps[0].strftime("%H:%M") > "09:15":
            reasons.append("STARTS_AFTER_09_15")
        if timestamps[-1].strftime("%H:%M") < "15:29":
            reasons.append("ENDS_BEFORE_15_29")
    if dup:
        reasons.append("DUPLICATE_TIMESTAMPS")
    if invalid:
        reasons.append("INVALID_OHLCV_OR_VWAP")

    instruments = sorted({r.get("instrument_key") for r in rows if r.get("instrument_key")})
    expiries = sorted({r.get("expiry") for r in rows if r.get("expiry")})
    sources = sorted({r.get("contract_source") for r in rows if r.get("contract_source")})

    if len(instruments) > 1:
        reasons.append("MULTIPLE_FUTURES_CONTRACTS")
    if len(expiries) > 1:
        reasons.append("MULTIPLE_FUTURES_EXPIRIES")

    return Check(
        "FUTURES",
        "PASS" if not reasons else "FAIL",
        {
            "file": str(path),
            "row_count": len(rows),
            "instrument_keys": instruments,
            "expiries": expiries,
            "contract_sources": sources,
            "first_timestamp": timestamps[0].isoformat() if timestamps else None,
            "last_timestamp": timestamps[-1].isoformat() if timestamps else None,
            "duplicate_timestamps": dup,
            "invalid_rows": invalid,
            "reasons": reasons,
        },
    )


def _check_0920_baseline(positioning: Check, session_date: str) -> Check:
    if positioning.status != "PASS":
        return Check("SESSION_BASELINE_09_20", "FAIL", {"reason": "POSITIONING_NOT_VALID"})

    path = Path(positioning.details["file"])
    payload = _load_json(path)
    rows = _parse_rows(payload)

    matches = []
    usable = []

    for row in rows:
        raw = row.get("timestamp")
        if not raw:
            continue
        try:
            ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except Exception:
            continue

        if ts.date().isoformat() == session_date and ts.strftime("%H:%M") == "09:20":
            matches.append(row)
            if (
                row.get("ce_open_interest") is not None
                and row.get("pe_open_interest") is not None
            ):
                usable.append(row)

    return Check(
        "SESSION_BASELINE_09_20",
        "PASS" if usable else "FAIL",
        {
            "matching_rows": len(matches),
            "usable_open_interest_rows": len(usable),
            "oi_fields": ["ce_open_interest", "pe_open_interest"],
            "reason": None if usable else "GENUINE_09_20_BASELINE_UNAVAILABLE",
        },
    )


def validate_session(
    session_date: str,
    *,
    data_root: str | Path = "data",
    futures_csv: str | Path = DEFAULT_FUTURES_CSV,
) -> SessionDataGateResult:
    date.fromisoformat(session_date)

    root = Path(data_root)
    pos_file = _select_file(root, "historical-positioning-cache", session_date)
    opt_file = _select_file(root, "historical-option-ohlc-cache", session_date)

    pos = _check_positioning(pos_file, session_date)
    opt = _check_option_ohlc(opt_file, session_date)
    fut = _check_futures(Path(futures_csv), session_date)
    baseline = _check_0920_baseline(pos, session_date)

    checks = [pos, opt, fut, baseline]
    repair = []
    if pos.status != "PASS":
        repair.append("POSITIONING")
    if opt.status != "PASS":
        repair.append("OPTION_OHLC")
    if fut.status != "PASS":
        repair.append("FUTURES")
    if baseline.status != "PASS" and "POSITIONING" not in repair:
        repair.append("SESSION_BASELINE_09_20")

    return SessionDataGateResult(
        session_date=session_date,
        status="PASS" if not repair else "FAIL",
        checks=checks,
        repair_required=repair,
        positioning_file=str(pos_file) if pos_file else None,
        option_ohlc_file=str(opt_file) if opt_file else None,
        futures_csv=str(futures_csv),
    )


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m market_lab.session_data_gate_v1")
    p.add_argument("--session-date", required=True)
    p.add_argument("--data-root", default="data")
    p.add_argument("--futures-csv", default=str(DEFAULT_FUTURES_CSV))
    args = p.parse_args()

    result = validate_session(
        args.session_date,
        data_root=args.data_root,
        futures_csv=args.futures_csv,
    )
    print(json.dumps(result.to_dict(), indent=2))
    raise SystemExit(0 if result.status == "PASS" else 2)


if __name__ == "__main__":
    main()
