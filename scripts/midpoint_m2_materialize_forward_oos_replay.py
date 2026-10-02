#!/usr/bin/env python3
import csv
import importlib.util
import json
from collections import defaultdict
from pathlib import Path

U = Path("data/historical-evidence/midpoint-forward-sep2026-underlying.csv")
F = Path("data/historical-evidence/midpoint-forward-sep2026-futures-vwap.csv")
V57 = Path("scripts/midpoint_v57_full_historical_be_lifecycle_replay.py")
OUT = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "midpoint-ui-replay-v1"
)

def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def norm_ts(value):
    ts = str(value).strip().replace(" ", "T", 1)
    if len(ts) == 16:
        ts += ":00"
    if "+" not in ts[10:] and not ts.endswith("Z"):
        ts += "+05:30"
    return ts

def trusted(ts):
    return "09:15" <= ts[11:16] <= "15:14"

def load_underlying():
    data = defaultdict(dict)

    with U.open(newline="") as fh:
        for row in csv.DictReader(fh):
            ts = norm_ts(row["timestamp"])
            if not trusted(ts):
                continue

            data[row["session_date"]][ts] = {
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row.get("volume") or 0),
            }

    return data

def load_futures():
    data = defaultdict(dict)

    with F.open(newline="") as fh:
        for row in csv.DictReader(fh):
            ts = norm_ts(row["timestamp"])
            if not trusted(ts):
                continue

            close = float(row["close"])
            vwap = float(row.get("session_vwap") or row["vwap"])

            data[row["session_date"]][ts] = {
                "close": close,
                "vwap": vwap,
                "diff": close - vwap,
                "volume": float(row.get("volume") or 0),
            }

    return data

def write_jsonl(path, rows):
    with path.open("w") as fh:
        for row in rows:
            fh.write(
                json.dumps(
                    row,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )

def main():
    v57 = load_module(V57, "v57_forward_oos")
    underlying = load_underlying()
    futures = load_futures()

    days = sorted(set(underlying) & set(futures))

    if len(days) != 12:
        raise SystemExit(
            f"STOP: expected 12 common sessions, got {len(days)}"
        )

    for day in days:
        u_day = underlying[day]
        f_day = futures[day]

        overlap = sorted(set(u_day) & set(f_day))

        if len(overlap) != 360:
            raise SystemExit(
                f"STOP {day}: overlap={len(overlap)} expected=360"
            )

        audit_rows, open_active, active_family = v57.replay_session(
            day,
            u_day,
            f_day,
        )

        minutes = []

        for ts in overlap:
            u = u_day[ts]
            f = f_day[ts]

            minutes.append({
                "session_date": day,
                "timestamp": ts,
                "underlying_open": u["open"],
                "underlying_high": u["high"],
                "underlying_low": u["low"],
                "underlying_close": u["close"],
                "futures_close": f["close"],
                "futures_vwap": f["vwap"],
                "data_status": "BOTH",
            })

        out_dir = OUT / day
        out_dir.mkdir(parents=True, exist_ok=True)

        write_jsonl(out_dir / "audit.jsonl", audit_rows)
        write_jsonl(out_dir / "minutes.jsonl", minutes)

        metadata = {
            "session_date": day,
            "block": "FORWARD_OOS_2026-09",
            "event_count": len(audit_rows),
            "minute_count": len(minutes),
            "first_minute": minutes[0]["timestamp"],
            "last_minute": minutes[-1]["timestamp"],
            "open_active": bool(open_active),
            "active_family": active_family,
            "source": "FORWARD_OOS_REPLAY",
            "minute_source":
                "HISTORICAL_UNDERLYING_PLUS_FUTURES_VWAP",
            "research_scope": "FORWARD_OOS",
            "parity_population_member": False,
        }

        (out_dir / "metadata.json").write_text(
            json.dumps(metadata, indent=2) + "\n"
        )

        reentries = sum(
            row.get("event_type") == "POST_CAP20_REENTRY_TRIGGERED"
            for row in audit_rows
        )

        reentry_checks = sum(
            row.get("event_type") == "POST_RESCUE_REENTRY_CHECK"
            for row in audit_rows
        )

        print(
            day,
            "events=", len(audit_rows),
            "minutes=", len(minutes),
            "reentries=", reentries,
            "reentry_checks=", reentry_checks,
        )

if __name__ == "__main__":
    main()
