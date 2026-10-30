from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path

TARGET_DATE = "2026-07-21"
REQUIRED_COLUMNS = [
    "session_date","expiry","instrument_key","trading_symbol","contract_source",
    "timestamp","open","high","low","close","volume","open_interest",
    "typical_price","session_cumulative_volume","session_vwap",
]

class July21CoverageRepairError(RuntimeError):
    pass

def read_csv(path: str | Path):
    p = Path(path)
    if not p.exists():
        raise July21CoverageRepairError(f"CSV not found: {p}")
    with p.open(newline="") as h:
        r = csv.DictReader(h)
        return list(r.fieldnames or []), list(r)

def validate_patch(path: str | Path):
    fields, rows = read_csv(path)
    missing = [c for c in REQUIRED_COLUMNS if c not in fields]
    if missing:
        raise July21CoverageRepairError(f"Patch CSV missing required columns: {missing}")
    if not rows:
        raise July21CoverageRepairError("Patch CSV contains no rows")
    dates = {r["session_date"] for r in rows}
    if dates != {TARGET_DATE}:
        raise July21CoverageRepairError(f"Patch must contain only {TARGET_DATE}; found {sorted(dates)}")

    seen = set()
    parsed = []
    for r in rows:
        ts = r["timestamp"]
        if ts in seen:
            raise July21CoverageRepairError(f"Duplicate timestamp in patch: {ts}")
        seen.add(ts)
        dt = datetime.fromisoformat(ts.replace("Z","+00:00"))
        if dt.date().isoformat() != TARGET_DATE:
            raise July21CoverageRepairError(f"Timestamp date mismatch: {ts}")
        parsed.append(dt)
        if not r["instrument_key"]:
            raise July21CoverageRepairError("instrument_key is empty")
        if r["contract_source"] != "EXPIRED_FUTURE_API":
            raise July21CoverageRepairError(
                f"Expected EXPIRED_FUTURE_API, found {r['contract_source']}"
            )
        for name in ("open","high","low","close","volume","typical_price","session_cumulative_volume","session_vwap"):
            try:
                float(r[name])
            except Exception as e:
                raise July21CoverageRepairError(f"Invalid {name} at {ts}: {r[name]!r}") from e

    parsed.sort()
    if parsed[0].strftime("%H:%M") > "09:15":
        raise July21CoverageRepairError(f"Patch starts too late: {parsed[0].isoformat()}")
    if parsed[-1].strftime("%H:%M") < "15:29":
        raise July21CoverageRepairError(f"Patch ends too early: {parsed[-1].isoformat()}")
    if len(rows) < 300:
        raise July21CoverageRepairError(f"Patch has suspiciously few rows: {len(rows)}")

    instruments = {r["instrument_key"] for r in rows}
    expiries = {r["expiry"] for r in rows}
    if len(instruments) != 1 or len(expiries) != 1:
        raise July21CoverageRepairError(
            f"Multiple futures contracts/expiries: instruments={sorted(instruments)}, expiries={sorted(expiries)}"
        )
    return rows

def merge_patch(*, base_csv: str | Path, patch_csv: str | Path, output_csv: str | Path):
    base_fields, base_rows = read_csv(base_csv)
    missing = [c for c in REQUIRED_COLUMNS if c not in base_fields]
    if missing:
        raise July21CoverageRepairError(f"Base CSV missing required columns: {missing}")
    patch_rows = validate_patch(patch_csv)

    before = sum(1 for r in base_rows if r["session_date"] == TARGET_DATE)
    merged = [r for r in base_rows if r["session_date"] != TARGET_DATE] + patch_rows
    merged.sort(key=lambda r: (r["session_date"], datetime.fromisoformat(r["timestamp"].replace("Z","+00:00"))))

    seen = set()
    for r in merged:
        key = (r["session_date"], r["timestamp"])
        if key in seen:
            raise July21CoverageRepairError(f"Duplicate session/timestamp after merge: {key}")
        seen.add(key)

    out = Path(output_csv)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as h:
        w = csv.DictWriter(h, fieldnames=base_fields)
        w.writeheader()
        w.writerows(merged)

    return {
        "target_date": TARGET_DATE,
        "base_target_rows_before": before,
        "patch_rows": len(patch_rows),
        "rows_after": len(merged),
        "output": str(out),
        "instrument_key": patch_rows[0]["instrument_key"],
        "expiry": patch_rows[0]["expiry"],
        "contract_source": patch_rows[0]["contract_source"],
        "first_timestamp": patch_rows[0]["timestamp"],
        "last_timestamp": patch_rows[-1]["timestamp"],
    }

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base-csv", default="data/historical-evidence/midpoint-v2-nifty-futures-vwap-v1-development.csv")
    p.add_argument("--patch-csv", required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()
    import json
    print(json.dumps({"status":"PASS", **merge_patch(base_csv=a.base_csv, patch_csv=a.patch_csv, output_csv=a.output)}, indent=2))

if __name__ == "__main__":
    main()
