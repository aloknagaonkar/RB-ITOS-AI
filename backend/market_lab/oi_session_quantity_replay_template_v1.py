from __future__ import annotations

"""
OI_SESSION_QUANTITY_REPLAY_TEMPLATE_V1

Generic research utility to inspect OI quantity + percentage for ANY historical
session and ANY requested checkpoint times.

Supports:
- moving ATM
- fixed morning ATM
- ATM only (band 0)
- ATM ±N bands, e.g. ±2, ±5
- exact T vs T-5m same-physical-strike comparison
- multiple dates in one run
- JSON + optional flat CSV output

Research only. No trading decision is emitted.
"""

import argparse
import csv
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

VERSION = "OI_SESSION_QUANTITY_REPLAY_TEMPLATE_V1"


def num(v: Any):
    if v in ("", None):
        return None
    try:
        return float(v)
    except Exception:
        return None


def parse_ts(v: Any):
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return None


def pct(cur, prev):
    if cur is None or prev in (None, 0):
        return None
    return (cur - prev) / prev * 100.0


def read_csv(path):
    with Path(path).open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def detect(rows):
    keys = set().union(*(r.keys() for r in rows))
    def first(*names):
        return next((n for n in names if n in keys), None)

    c = {
        "timestamp": first("timestamp", "datetime", "provider_timestamp", "time"),
        "session_date": first("session_date", "date"),
        "strike": first("strike", "strike_price"),
        "offset": first("strike_offset", "offset"),
        "atm": first("moving_atm", "atm", "atm_strike"),
        "ce_oi": first("ce_oi", "call_oi", "ce_open_interest", "call_open_interest"),
        "pe_oi": first("pe_oi", "put_oi", "pe_open_interest", "put_open_interest"),
    }
    missing = [k for k in ("timestamp","strike","offset","atm","ce_oi","pe_oi") if c[k] is None]
    if missing:
        raise RuntimeError("Missing positioning columns: " + ", ".join(missing))
    return c


def build_snapshots(rows, c):
    out = {}
    dates = set()
    for r in rows:
        t = parse_ts(r.get(c["timestamp"]))
        if not t:
            continue
        out.setdefault(t, []).append(r)
        dates.add(t.date().isoformat())
    return out, dates


def atm_from_rows(rows, c):
    atm_rows = [r for r in rows if num(r.get(c["offset"])) == 0]
    if not atm_rows:
        return None
    return num(atm_rows[0].get(c["atm"]))


def find_exact_snapshot(snaps, date_s, hhmm):
    hh, mm = [int(x) for x in hhmm.split(":")]
    for t, rows in snaps.items():
        if t.date().isoformat() == date_s and t.hour == hh and t.minute == mm:
            return t, rows
    return None, None


def fixed_atm(snaps, c, date_s, fixed_time):
    _, rows = find_exact_snapshot(snaps, date_s, fixed_time)
    return atm_from_rows(rows, c) if rows else None


def aggregate(cur, prev, c, center, width, strike_step):
    wanted = {center + i * strike_step for i in range(-width, width + 1)}
    cm = {num(r[c["strike"]]): r for r in cur}
    pm = {num(r[c["strike"]]): r for r in prev}
    common = sorted(wanted & set(cm) & set(pm))
    if not common:
        return None

    ce_prev = sum(num(pm[s][c["ce_oi"]]) or 0 for s in common)
    ce_cur  = sum(num(cm[s][c["ce_oi"]]) or 0 for s in common)
    pe_prev = sum(num(pm[s][c["pe_oi"]]) or 0 for s in common)
    pe_cur  = sum(num(cm[s][c["pe_oi"]]) or 0 for s in common)

    ce_delta = ce_cur - ce_prev
    pe_delta = pe_cur - pe_prev

    return {
        "center_atm": center,
        "band_width": width,
        "strike_count": len(common),
        "common_strikes": [int(x) for x in common],

        "ce_oi_previous": ce_prev,
        "ce_oi_current": ce_cur,
        "ce_change_abs_signed": ce_delta,
        "ce_change_abs_magnitude": abs(ce_delta),
        "ce_change_pct_5m": pct(ce_cur, ce_prev),

        "pe_oi_previous": pe_prev,
        "pe_oi_current": pe_cur,
        "pe_change_abs_signed": pe_delta,
        "pe_change_abs_magnitude": abs(pe_delta),
        "pe_change_pct_5m": pct(pe_cur, pe_prev),

        "total_oi_previous": ce_prev + pe_prev,
        "total_oi_current": ce_cur + pe_cur,
        "total_abs_activity": abs(ce_delta) + abs(pe_delta),

        "pcr_previous": pe_prev / ce_prev if ce_prev else None,
        "pcr_current": pe_cur / ce_cur if ce_cur else None,
    }


def parse_session_specs(specs):
    """
    Format:
      YYYY-MM-DD|09:20,09:25,09:30
    """
    out = []
    for spec in specs or []:
        if "|" not in spec:
            raise RuntimeError(
                f"Invalid --session '{spec}'. Expected YYYY-MM-DD|HH:MM,HH:MM"
            )
        date_s, times_s = spec.split("|", 1)
        times = [x.strip() for x in times_s.split(",") if x.strip()]
        out.append({"date": date_s.strip(), "times": times})
    return out


def load_request(request_json, session_specs):
    req = []
    if request_json:
        obj = json.loads(Path(request_json).read_text(encoding="utf-8"))
        req.extend(obj.get("sessions", []))
    req.extend(parse_session_specs(session_specs))
    if not req:
        raise RuntimeError("Provide --request-json or at least one --session")
    return req


def flatten(result):
    rows = []
    for session in result["sessions"]:
        for cp in session["checkpoints"]:
            if cp.get("status") != "AVAILABLE":
                rows.append({
                    "session_date": session["session_date"],
                    "block": session.get("block"),
                    "checkpoint": cp.get("checkpoint"),
                    "status": cp.get("status"),
                })
                continue
            for mode_name, mode in cp["bands"].items():
                if mode is None:
                    continue
                rows.append({
                    "session_date": session["session_date"],
                    "block": session.get("block"),
                    "checkpoint": cp["checkpoint"],
                    "timestamp": cp["timestamp"],
                    "previous_timestamp": cp["previous_timestamp"],
                    "moving_atm": cp.get("moving_atm"),
                    "fixed_atm": cp.get("fixed_atm"),
                    "mode": mode_name,
                    **{k:v for k,v in mode.items() if k != "common_strikes"},
                    "common_strikes": ";".join(str(x) for x in mode["common_strikes"]),
                })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--positioning", action="append", required=True,
                    help="BLOCK|path.csv; repeat for TRAIN/OOS blocks")
    ap.add_argument("--request-json")
    ap.add_argument("--session", action="append",
                    help="YYYY-MM-DD|HH:MM,HH:MM,... ; repeatable")
    ap.add_argument("--fixed-atm-time", default="09:20")
    ap.add_argument("--bands", default="0,2,5",
                    help="Comma-separated half-widths. 0 means ATM only.")
    ap.add_argument("--strike-step", type=float, default=50.0)
    ap.add_argument("--output", required=True)
    ap.add_argument("--csv-output")
    a = ap.parse_args()

    bands = sorted({int(x.strip()) for x in a.bands.split(",") if x.strip()})
    if any(x < 0 for x in bands):
        raise RuntimeError("Band widths must be >= 0")

    sources = {}
    date_to_block = {}
    for spec in a.positioning:
        block, path = spec.split("|", 1)
        rows = read_csv(path)
        c = detect(rows)
        snaps, dates = build_snapshots(rows, c)
        sources[block] = {"columns": c, "snapshots": snaps, "path": path}
        for d in dates:
            if d in date_to_block and date_to_block[d] != block:
                raise RuntimeError(f"Session {d} exists in multiple blocks")
            date_to_block[d] = block

    requests = load_request(a.request_json, a.session)

    result = {
        "research_version": VERSION,
        "config": {
            "fixed_atm_time": a.fixed_atm_time,
            "bands": bands,
            "strike_step": a.strike_step,
            "change_horizon_minutes": 5,
        },
        "sessions": [],
        "integrity": {
            "same_physical_strikes_current_vs_previous": True,
            "moving_atm_supported": True,
            "fixed_atm_supported": True,
            "arbitrary_dates_supported": True,
            "arbitrary_checkpoint_times_supported": True,
            "strategy_rule_changed": False,
            "paper_or_live_order_emission_allowed": False,
        },
    }

    for req in requests:
        date_s = req["date"]
        times = req.get("times", [])
        block = date_to_block.get(date_s)

        session_out = {
            "session_date": date_s,
            "block": block,
            "source_available": block is not None,
            "fixed_atm_time": a.fixed_atm_time,
            "fixed_atm": None,
            "checkpoints": [],
        }

        if block is None:
            session_out["issue"] = "SESSION_NOT_FOUND_IN_POSITIONING_INPUTS"
            result["sessions"].append(session_out)
            continue

        src = sources[block]
        c = src["columns"]
        snaps = src["snapshots"]
        f_atm = fixed_atm(snaps, c, date_s, a.fixed_atm_time)
        session_out["fixed_atm"] = f_atm

        for hhmm in times:
            t, cur = find_exact_snapshot(snaps, date_s, hhmm)
            if not t or not cur:
                session_out["checkpoints"].append({
                    "checkpoint": hhmm,
                    "status": "CURRENT_CHECKPOINT_MISSING",
                })
                continue

            prev_t = t - timedelta(minutes=5)
            prev = snaps.get(prev_t, [])
            if not prev:
                session_out["checkpoints"].append({
                    "checkpoint": hhmm,
                    "status": "PREVIOUS_5M_CHECKPOINT_MISSING",
                    "timestamp": t.isoformat(),
                })
                continue

            m_atm = atm_from_rows(cur, c)
            cp = {
                "checkpoint": hhmm,
                "status": "AVAILABLE",
                "timestamp": t.isoformat(),
                "previous_timestamp": prev_t.isoformat(),
                "moving_atm": m_atm,
                "fixed_atm": f_atm,
                "bands": {},
            }

            for width in bands:
                if m_atm is not None:
                    cp["bands"][f"moving_pm{width}"] = aggregate(
                        cur, prev, c, m_atm, width, a.strike_step
                    )
                if f_atm is not None:
                    cp["bands"][f"fixed_pm{width}"] = aggregate(
                        cur, prev, c, f_atm, width, a.strike_step
                    )

            session_out["checkpoints"].append(cp)

        result["sessions"].append(session_out)

    outp = Path(a.output)
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8")

    if a.csv_output:
        flat = flatten(result)
        cp = Path(a.csv_output)
        cp.parent.mkdir(parents=True, exist_ok=True)
        if flat:
            fields = []
            for r in flat:
                for k in r:
                    if k not in fields:
                        fields.append(k)
            with cp.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fields)
                w.writeheader()
                w.writerows(flat)

    summary = {
        "research_version": VERSION,
        "requested_sessions": len(requests),
        "available_sessions": sum(1 for s in result["sessions"] if s["source_available"]),
        "requested_checkpoints": sum(len(s.get("times", [])) for s in requests),
        "available_checkpoints": sum(
            1 for s in result["sessions"]
            for cp in s["checkpoints"] if cp.get("status") == "AVAILABLE"
        ),
        "bands": bands,
        "fixed_atm_time": a.fixed_atm_time,
        "output": a.output,
        "csv_output": a.csv_output,
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
