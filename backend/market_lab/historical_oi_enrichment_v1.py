from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

MODEL = "HISTORICAL_OI_ENRICHMENT_V1"


def _f(v):
    if v in (None, ""):
        return None
    return float(v)


def _timestamp_key(v: str) -> str:
    return datetime.fromisoformat(v).isoformat()


def _load_canonical(path: Path, session_date: str) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = [dict(r) for r in csv.DictReader(f) if r.get("session_date") == session_date]
    if not rows:
        raise ValueError(f"No canonical rows for {session_date}")
    return rows


def _load_built(path: Path, session_date: str) -> dict[str, Any]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    sessions = doc.get("sessions") or []
    matches = [x for x in sessions if str(x.get("session_date")) == session_date]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one built session for {session_date}, found {len(matches)}")
    session = matches[0]
    if session.get("status") != "AVAILABLE":
        raise ValueError(f"Built session is not AVAILABLE: {session.get('status')}")
    return session


def _index_rows(rows: list[dict[str, Any]]):
    by_ts: dict[str, dict[float, dict[str, Any]]] = defaultdict(dict)
    for r in rows:
        ts = _timestamp_key(str(r["timestamp"]))
        strike = float(r["strike"])
        if strike in by_ts[ts]:
            raise ValueError(f"Duplicate built row {ts} strike {strike}")
        by_ts[ts][strike] = r
    return by_ts


def _sum_basket(at: dict[float, dict[str, Any]], strikes: list[float]):
    ce = 0.0
    pe = 0.0
    missing_ce = []
    missing_pe = []
    for strike in strikes:
        r = at.get(strike)
        if not r:
            missing_ce.append(strike)
            missing_pe.append(strike)
            continue
        c = _f(r.get("ce_open_interest"))
        p = _f(r.get("pe_open_interest"))
        if c is None:
            missing_ce.append(strike)
        else:
            ce += c
        if p is None:
            missing_pe.append(strike)
        else:
            pe += p
    return {
        "complete": not missing_ce and not missing_pe,
        "ce": None if missing_ce else ce,
        "pe": None if missing_pe else pe,
        "missing_ce": missing_ce,
        "missing_pe": missing_pe,
    }


def _pct(delta, base):
    if delta is None or base in (None, 0):
        return None
    return delta / base * 100.0


def _pcr(pe, ce):
    if pe is None or ce in (None, 0):
        return None
    return pe / ce


def _strike_interval(session: dict[str, Any]) -> float:
    value = session.get("strike_interval")
    if value is not None:
        return float(value)
    vals = sorted({float(r["strike"]) for r in session.get("rows", [])})
    diffs = [b-a for a,b in zip(vals, vals[1:]) if b>a]
    if not diffs:
        raise ValueError("Cannot infer strike interval")
    return min(diffs)


def enrich_session(
    canonical_rows: list[dict[str, Any]],
    built_session: dict[str, Any],
    session_date: str,
) -> dict[str, Any]:
    built_rows = built_session.get("rows") or []
    by_ts = _index_rows(built_rows)
    interval = _strike_interval(built_session)

    canonical_by_time = {str(r.get("time")): r for r in canonical_rows}
    anchor = canonical_by_time.get("09:20")
    if anchor is None:
        raise ValueError("Canonical session has no exact 09:20 row")

    fixed_atm = _f(anchor.get("fixed_atm"))
    anchor_ts = str(anchor.get("timestamp") or "")
    if fixed_atm is None:
        built_anchor = by_ts.get(_timestamp_key(anchor_ts), {})
        atms = {float(r["moving_atm"]) for r in built_anchor.values() if r.get("moving_atm") is not None}
        if len(atms) == 1:
            fixed_atm = next(iter(atms))
    if fixed_atm is None:
        raise ValueError("Exact 09:20 fixed ATM unavailable")

    fixed_strikes = [fixed_atm + i*interval for i in range(-5, 6)]
    baseline_rows = by_ts.get(_timestamp_key(anchor_ts))
    if baseline_rows is None:
        raise ValueError("Built source has no exact 09:20 timestamp")

    fixed_base = _sum_basket(baseline_rows, fixed_strikes)

    enriched = []
    counts = defaultdict(int)

    for src in canonical_rows:
        out = dict(src)
        ts_raw = str(src.get("timestamp") or "")
        ts = _timestamp_key(ts_raw)
        current = by_ts.get(ts)

        out["enrichment_model"] = MODEL
        out["enrichment_provenance"] = "DOWNLOADED_ENRICHMENT"
        out["fixed_atm"] = fixed_atm
        out["fixed_strikes"] = ",".join(str(int(x) if x.is_integer() else x) for x in fixed_strikes)

        if current is None:
            out["enrichment_status"] = "SOURCE_MISSING"
            out["enrichment_issue"] = "exact_timestamp_missing"
            counts["SOURCE_MISSING"] += 1
            enriched.append(out)
            continue

        fixed_now = _sum_basket(current, fixed_strikes)
        out["fixed_complete"] = bool(fixed_base["complete"] and fixed_now["complete"])
        out["fixed_missing_ce"] = ",".join(map(str, fixed_now["missing_ce"]))
        out["fixed_missing_pe"] = ",".join(map(str, fixed_now["missing_pe"]))
        out["fixed_ce_oi_baseline_0920"] = fixed_base["ce"]
        out["fixed_pe_oi_baseline_0920"] = fixed_base["pe"]
        out["fixed_ce_oi"] = fixed_now["ce"]
        out["fixed_pe_oi"] = fixed_now["pe"]

        ce_delta = None if fixed_now["ce"] is None or fixed_base["ce"] is None else fixed_now["ce"] - fixed_base["ce"]
        pe_delta = None if fixed_now["pe"] is None or fixed_base["pe"] is None else fixed_now["pe"] - fixed_base["pe"]
        out["f_ce_delta"] = ce_delta
        out["f_pe_delta"] = pe_delta
        out["f_ce_pct"] = _pct(ce_delta, fixed_base["ce"])
        out["f_pe_pct"] = _pct(pe_delta, fixed_base["pe"])
        out["f_imbalance"] = None if ce_delta is None or pe_delta is None else pe_delta - ce_delta
        out["f_pcr_baseline"] = _pcr(fixed_base["pe"], fixed_base["ce"])
        out["f_pcr"] = _pcr(fixed_now["pe"], fixed_now["ce"])
        out["f_pcr_change"] = (
            None if out["f_pcr"] is None or out["f_pcr_baseline"] is None
            else out["f_pcr"] - out["f_pcr_baseline"]
        )

        moving_atm = _f(src.get("moving_atm"))
        moving_strikes = [] if moving_atm is None else [moving_atm + i*interval for i in range(-5,6)]
        moving_now = _sum_basket(current, moving_strikes) if moving_strikes else {"complete":False,"ce":None,"pe":None}

        horizons = {}
        for minutes in (5,10,15):
            prev_dt = datetime.fromisoformat(ts_raw)
            prev_dt = prev_dt.replace(second=0, microsecond=0)
            from datetime import timedelta
            prev_ts = (prev_dt - timedelta(minutes=minutes)).isoformat()
            prev = by_ts.get(prev_ts)
            if prev is None or not moving_strikes:
                horizons[f"{minutes}m"] = {"status":"SOURCE_MISSING","reason":"exact_prior_timestamp_missing"}
                continue
            prior = _sum_basket(prev, moving_strikes)
            if not moving_now.get("complete") or not prior.get("complete"):
                horizons[f"{minutes}m"] = {"status":"SOURCE_MISSING","reason":"exact_same_strike_basket_incomplete"}
                continue
            ce_d = moving_now["ce"] - prior["ce"]
            pe_d = moving_now["pe"] - prior["pe"]
            cur_pcr = _pcr(moving_now["pe"], moving_now["ce"])
            prior_pcr = _pcr(prior["pe"], prior["ce"])
            horizons[f"{minutes}m"] = {
                "status":"AVAILABLE",
                "current_ce_oi":moving_now["ce"],
                "current_pe_oi":moving_now["pe"],
                "prior_ce_oi":prior["ce"],
                "prior_pe_oi":prior["pe"],
                "ce_delta":ce_d,
                "pe_delta":pe_d,
                "imbalance":pe_d-ce_d,
                "current_pcr":cur_pcr,
                "prior_pcr":prior_pcr,
                "pcr_change":None if cur_pcr is None or prior_pcr is None else cur_pcr-prior_pcr,
            }

        out["moving_horizons"] = horizons
        h5 = horizons.get("5m") or {}
        if h5.get("status") == "AVAILABLE":
            out["m_ce_oi"] = h5["current_ce_oi"]
            out["m_pe_oi"] = h5["current_pe_oi"]
            out["m_ce_delta"] = h5["ce_delta"]
            out["m_pe_delta"] = h5["pe_delta"]
            out["m_pcr_previous"] = h5["prior_pcr"]
            out["m_pcr"] = h5["current_pcr"]
            out["m_pcr_change"] = h5["pcr_change"]
            out["m_ce_pct"] = _pct(h5["ce_delta"], h5["prior_ce_oi"])
            out["m_pe_pct"] = _pct(h5["pe_delta"], h5["prior_pe_oi"])
            out["m_activity"] = abs(h5["ce_delta"]) + abs(h5["pe_delta"])
            out["m_common_strikes"] = len(moving_strikes)

        if out["fixed_complete"]:
            out["enrichment_status"] = "AVAILABLE"
            out["enrichment_issue"] = None
            counts["AVAILABLE"] += 1
        else:
            out["enrichment_status"] = "SOURCE_MISSING"
            out["enrichment_issue"] = "fixed_basket_incomplete"
            counts["SOURCE_MISSING"] += 1

        enriched.append(out)

    return {
        "model": MODEL,
        "session_date": session_date,
        "source_provenance": "HISTORICAL_CANDLE_RECONSTRUCTION",
        "fixed_atm": fixed_atm,
        "fixed_strikes": fixed_strikes,
        "row_count": len(enriched),
        "status_counts": dict(counts),
        "rows": enriched,
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    flat = []
    for r in rows:
        x = dict(r)
        if isinstance(x.get("moving_horizons"), dict):
            x["moving_horizons"] = json.dumps(x["moving_horizons"], sort_keys=True)
        flat.append(x)
    keys = []
    for r in flat:
        for k in r:
            if k not in keys:
                keys.append(k)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(flat)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session-date", required=True)
    ap.add_argument(
        "--canonical",
        default="data/historical-evidence/oi-pattern-library-90d-historical-only-v1.csv",
    )
    ap.add_argument("--built-positioning")
    ap.add_argument("--output-dir", default="data/historical-evidence/historical-oi-enrichment")
    args = ap.parse_args()

    built = Path(args.built_positioning) if args.built_positioning else Path(
        f"data/historical-evidence/historical-oi-build/{args.session_date}/positioning.json"
    )
    canonical = Path(args.canonical)
    if not built.exists():
        raise SystemExit(
            f"Built positioning source missing: {built}. "
            "Use the existing Historical OI Download/Build panel first with the exact expiry."
        )

    canonical_rows = _load_canonical(canonical, args.session_date)
    built_session = _load_built(built, args.session_date)
    doc = enrich_session(canonical_rows, built_session, args.session_date)

    outdir = Path(args.output_dir) / args.session_date
    outdir.mkdir(parents=True, exist_ok=True)
    json_path = outdir / "enriched.json"
    csv_path = outdir / "enriched.csv"
    json_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    write_csv(csv_path, doc["rows"])

    print(json.dumps({
        "status":"COMPLETE",
        "model":MODEL,
        "session_date":args.session_date,
        "row_count":doc["row_count"],
        "status_counts":doc["status_counts"],
        "fixed_atm":doc["fixed_atm"],
        "json":str(json_path),
        "csv":str(csv_path),
    }, indent=2))


if __name__ == "__main__":
    main()
