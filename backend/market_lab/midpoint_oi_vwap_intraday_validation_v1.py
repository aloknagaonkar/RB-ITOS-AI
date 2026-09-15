from __future__ import annotations

"""
Today-only intraday research adapter.

Purpose
-------
Pull current-day NIFTY spot, NIFTY futures and expiry-day options through
Upstox's intraday 1-minute candle endpoint, reconstruct synchronized 5-minute
OI states, compute prospective futures VWAP, emit Arm A signals, and emit a
midpoint-aligned diagnostic Arm C candidate set.

This module is intentionally isolated from frozen V1/V2 artifacts. It does
not place orders, does not mutate lab.db, and does not modify historical
development/OOS files.

Important
---------
Arm C in this module is marked INTRADAY_DIAGNOSTIC_ONLY. It uses the frozen
opening-midpoint structure and T+3 feature thresholds loaded from the existing
MIDPOINT_STABLE_FEATURE_STATE_MACHINE_V3_2 artifact, but it does not claim to
replace the canonical historical structural-reconstruction pipeline.
"""

import argparse
import csv
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median
from typing import Any
from urllib.parse import quote

import httpx

RESEARCH_VERSION = "MIDPOINT_OI_VWAP_INTRADAY_VALIDATION_V1"
UNDERLYING = "NSE_INDEX|Nifty 50"
ROUND_TRIP_COST_PCT_POINTS = 0.5
HORIZONS = (1, 3, 5, 10, 15)


def parse_ts(v: str) -> datetime:
    return datetime.fromisoformat(v.replace("Z", "+00:00"))


def pct(a: float, b: float) -> float:
    return ((b / a) - 1.0) * 100.0


def round_atm(spot: float, step: int = 50) -> float:
    return float(round(spot / step) * step)


def floor_5m(ts: datetime) -> datetime:
    return ts.replace(minute=(ts.minute // 5) * 5, second=0, microsecond=0)


def completed_5m_checkpoints(rows: list[dict[str, Any]]) -> list[datetime]:
    out = []
    for r in rows:
        ts = parse_ts(r["timestamp"])
        if ts.minute % 5 == 0 and ts.second == 0:
            out.append(ts)
    return out


def state(price_now: float | None, price_prev: float | None,
          oi_now: float | None, oi_prev: float | None,
          price_threshold_pct: float, oi_threshold_pct: float) -> str:
    if None in (price_now, price_prev, oi_now, oi_prev):
        return "UNAVAILABLE"
    if not price_prev or not oi_prev:
        return "UNAVAILABLE"
    dp = pct(float(price_prev), float(price_now))
    doi = pct(float(oi_prev), float(oi_now))
    if abs(dp) < price_threshold_pct or abs(doi) < oi_threshold_pct:
        return "NEUTRAL"
    if dp > 0 and doi > 0:
        return "LONG_BUILDUP"
    if dp < 0 and doi > 0:
        return "SHORT_BUILDUP"
    if dp < 0 and doi < 0:
        return "LONG_UNWINDING"
    if dp > 0 and doi < 0:
        return "SHORT_COVERING"
    return "NEUTRAL"


def oi_direction(ce: str, pe: str) -> str:
    if ce == "LONG_BUILDUP" and pe == "SHORT_BUILDUP":
        return "BULLISH"
    if ce == "SHORT_BUILDUP" and pe == "LONG_BUILDUP":
        return "BEARISH"
    return "NEUTRAL"


def confluence_direction(ce: str, pe: str, fut_close: float | None,
                         fut_vwap: float | None) -> str:
    if fut_close is None or fut_vwap is None:
        return "NEUTRAL"
    d = oi_direction(ce, pe)
    if d == "BULLISH" and fut_close > fut_vwap:
        return d
    if d == "BEARISH" and fut_close < fut_vwap:
        return d
    return "NEUTRAL"


def metric_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "positive_count": 0, "win_rate_pct": None,
                "mean_pct": None, "median_pct": None, "sum_pct_points": None,
                "profit_factor": None}
    winners = [x for x in values if x > 0]
    losers = [x for x in values if x <= 0]
    gp, gl = sum(winners), abs(sum(losers))
    return {
        "count": len(values),
        "positive_count": len(winners),
        "win_rate_pct": 100 * len(winners) / len(values),
        "mean_pct": mean(values),
        "median_pct": median(values),
        "sum_pct_points": sum(values),
        "profit_factor": gp / gl if gl else None,
    }


def client() -> httpx.Client:
    token = os.getenv("UPSTOX_ACCESS_TOKEN")
    if not token:
        raise SystemExit("UPSTOX_ACCESS_TOKEN missing; source .env first")
    return httpx.Client(
        base_url="https://api.upstox.com",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        timeout=30,
    )


def intraday(client_: httpx.Client, instrument: str) -> list[dict[str, Any]]:
    encoded = quote(instrument, safe="")
    r = client_.get(f"/v3/historical-candle/intraday/{encoded}/minutes/1")
    r.raise_for_status()
    raw = r.json().get("data", {}).get("candles", [])
    rows = []
    for v in raw:
        if not isinstance(v, list) or len(v) < 6:
            continue
        rows.append({
            "timestamp": v[0],
            "open": float(v[1]),
            "high": float(v[2]),
            "low": float(v[3]),
            "close": float(v[4]),
            "volume": int(v[5]) if v[5] is not None else None,
            "oi": int(v[6]) if len(v) >= 7 and v[6] is not None else None,
        })
    rows.sort(key=lambda x: parse_ts(x["timestamp"]))
    return rows


def option_chain(client_: httpx.Client, expiry: str) -> list[dict[str, Any]]:
    r = client_.get("/v2/option/chain", params={
        "instrument_key": UNDERLYING, "expiry_date": expiry
    })
    r.raise_for_status()
    return r.json().get("data") or []


def current_future(client_: httpx.Client, session_date: str) -> dict[str, Any]:
    r = client_.get("/v2/instruments/search", params={
        "query": "NIFTY", "exchanges": "NSE", "segments": "FUT",
        "instrument_types": "FUT", "records": 30, "page_number": 1,
    })
    r.raise_for_status()
    candidates = []
    for row in r.json().get("data") or []:
        if str(row.get("instrument_type") or "").upper() != "FUT":
            continue
        name = str(row.get("name") or "").upper()
        sym = str(row.get("trading_symbol") or "").upper()
        underlying = str(row.get("underlying_symbol") or "").upper()
        if not (underlying == "NIFTY" or sym.startswith("NIFTY FUT")
                or name in {"NIFTY", "NIFTY 50"}):
            continue
        expiry = str(row.get("expiry") or "")[:10]
        if expiry and expiry >= session_date:
            candidates.append((expiry, row))
    if not candidates:
        raise RuntimeError("No current NIFTY futures contract found")
    return sorted(candidates, key=lambda x: x[0])[0][1]


def chain_map(chain: list[dict[str, Any]]) -> dict[float, dict[str, str | None]]:
    out = {}
    for r in chain:
        strike = float(r["strike_price"])
        ce = r.get("call_options") or {}
        pe = r.get("put_options") or {}
        out[strike] = {
            "CE": ce.get("instrument_key") or (ce.get("market_data") or {}).get("instrument_key"),
            "PE": pe.get("instrument_key") or (pe.get("market_data") or {}).get("instrument_key"),
        }
    return out


def add_vwap(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cpv = 0.0
    cv = 0
    out = []
    for r in rows:
        vol = r["volume"]
        typical = (r["high"] + r["low"] + r["close"]) / 3.0
        if vol is not None and vol >= 0:
            cpv += typical * vol
            cv += vol
        x = dict(r)
        x["session_vwap"] = cpv / cv if cv else None
        out.append(x)
    return out


def idx(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {parse_ts(r["timestamp"]).isoformat(): r for r in rows}


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    fields = []
    seen = set()
    for r in rows:
        for k in r:
            if k not in seen:
                seen.add(k); fields.append(k)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader(); w.writerows(rows)


def first_reference(spot: list[dict[str, Any]], colour: str) -> dict[str, Any] | None:
    # Opening 09:15–09:19 is intentionally ignored.
    for r in spot:
        ts = parse_ts(r["timestamp"])
        if (ts.hour, ts.minute) < (9, 20):
            continue
        if colour == "RED" and r["close"] < r["open"]:
            return r
        if colour == "GREEN" and r["close"] > r["open"]:
            return r
    return None


def midpoint_events(spot: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Minimal prospective opening-midpoint event reconstruction.

    It freezes the first RED and GREEN references after 09:19, requires
    close-only midpoint and boundary crossings, and emits T0/T+3 rows.
    """
    events = []
    for colour in ("RED", "GREEN"):
        ref = first_reference(spot, colour)
        if not ref:
            continue
        hi, lo = ref["high"], ref["low"]
        mid = (hi + lo) / 2.0
        ref_ts = parse_ts(ref["timestamp"])
        midpoint_seen = False
        boundary_ts = None
        direction = None
        for r in spot:
            ts = parse_ts(r["timestamp"])
            if ts <= ref_ts:
                continue
            c = r["close"]
            if colour == "RED":
                if c < mid:
                    midpoint_seen = True
                if midpoint_seen and c < lo:
                    boundary_ts, direction = ts, "BEARISH"
                    break
            else:
                if c > mid:
                    midpoint_seen = True
                if midpoint_seen and c > hi:
                    boundary_ts, direction = ts, "BULLISH"
                    break
        if boundary_ts is None:
            continue
        events.append({
            "reference_colour": colour,
            "reference_timestamp": ref_ts.isoformat(),
            "reference_high": hi,
            "reference_low": lo,
            "reference_midpoint": mid,
            "direction": direction,
            "boundary_break_timestamp": boundary_ts.isoformat(),
            "t3_timestamp": (boundary_ts + timedelta(minutes=3)).isoformat(),
        })
    return events


def t3_features(event: dict[str, Any], spot_idx: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    t0 = parse_ts(event["boundary_break_timestamp"])
    direction = event["direction"]
    boundary = event["reference_high"] if direction == "BULLISH" else event["reference_low"]
    closes = []
    for i in range(4):
        r = spot_idx.get((t0 + timedelta(minutes=i)).isoformat())
        if not r:
            return None
        closes.append(float(r["close"]))
    sign = 1.0 if direction == "BULLISH" else -1.0
    progress = [sign * (c - boundary) for c in closes]
    acceptance = 100.0 * sum(x > 0 for x in progress) / len(progress)
    consecutive = 0
    for x in reversed(progress):
        if x > 0:
            consecutive += 1
        else:
            break
    t3 = t0 + timedelta(minutes=3)
    prev5 = spot_idx.get((t3 - timedelta(minutes=5)).isoformat())
    momentum5 = None if not prev5 else sign * (closes[-1] - float(prev5["close"]))
    best = max(progress)
    return {
        "acceptance_pct": acceptance,
        "momentum_5m_directional": momentum5,
        "progress_points": progress[-1],
        "giveback_from_best_checkpoint_points": best - progress[-1],
        "consecutive_closes": float(consecutive),
        "velocity": progress[-1] / 3.0,
    }


def passes_frozen_rules(direction: str, features: dict[str, Any],
                        frozen_doc: dict[str, Any]) -> tuple[bool, dict[str, bool]]:
    rules = ((frozen_doc.get("t3_train_only_rules") or {}).get(direction) or {}).get("features") or {}
    checks = {}
    for name, spec in rules.items():
        if str(spec.get("status")) != "ACTIVE":
            continue
        value = features.get(name)
        threshold = spec.get("threshold")
        polarity = spec.get("polarity")
        if value is None or threshold is None:
            checks[name] = False
        elif polarity == "HIGHER_IS_BETTER":
            checks[name] = float(value) >= float(threshold)
        elif polarity == "LOWER_IS_BETTER":
            checks[name] = float(value) <= float(threshold)
    return bool(checks) and all(checks.values()), checks


def economics(signal_ts: datetime, instrument: str,
              option_idx: dict[str, dict[str, Any]]) -> dict[str, Any]:
    entry_ts = signal_ts + timedelta(minutes=1)
    entry = option_idx.get(entry_ts.isoformat())
    if not entry:
        return {"entry_available": False, "issue": "NEXT_MINUTE_OPEN_UNAVAILABLE"}
    ep = float(entry["open"])
    net = {}
    for h in HORIZONS:
        r = option_idx.get((entry_ts + timedelta(minutes=h)).isoformat())
        net[f"{h}m"] = None if not r else pct(ep, float(r["close"])) - ROUND_TRIP_COST_PCT_POINTS
    path = [option_idx.get((entry_ts + timedelta(minutes=i)).isoformat()) for i in range(15)]
    full = all(x is not None for x in path)
    highs = [float(x["high"]) for x in path if x]
    lows = [float(x["low"]) for x in path if x]
    return {
        "entry_available": True,
        "entry_timestamp": entry_ts.isoformat(),
        "entry_price": ep,
        "net_returns_pct": net,
        "complete_15m_path": full,
        "mfe_pct_15m": pct(ep, max(highs)) if highs else None,
        "mae_pct_15m": pct(ep, min(lows)) if lows else None,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out = {"trade_count": len(rows), "direction_counts": dict(Counter(r["direction"] for r in rows))}
    for h in HORIZONS:
        vals = [r["net_returns_pct"][f"{h}m"] for r in rows
                if r.get("entry_available") and r.get("net_returns_pct", {}).get(f"{h}m") is not None]
        out[f"net_{h}m"] = metric_summary(vals)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session-date", required=True)
    ap.add_argument("--expiry", required=True)
    ap.add_argument("--frozen-state",
                    default="data/historical-evidence/midpoint-stable-feature-state-machine-v3-2-development.json")
    ap.add_argument("--output-dir",
                    default="data/historical-evidence/intraday-validation")
    ap.add_argument("--price-threshold-pct", type=float, default=None)
    ap.add_argument("--oi-threshold-pct", type=float, default=None)
    args = ap.parse_args()

    # Read canonical positioning defaults from the repository when available.
    price_threshold = args.price_threshold_pct
    oi_threshold = args.oi_threshold_pct
    if price_threshold is None or oi_threshold is None:
        try:
            from .historical_positioning import PositioningConfig
            cfg = PositioningConfig()
            if price_threshold is None:
                price_threshold = float(getattr(cfg, "price_threshold_pct"))
            if oi_threshold is None:
                oi_threshold = float(getattr(cfg, "oi_threshold_pct"))
        except Exception as exc:
            raise SystemExit(
                "Unable to read canonical PositioningConfig defaults. "
                "Pass --price-threshold-pct and --oi-threshold-pct explicitly. "
                f"Reason: {exc}"
            )

    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    frozen = json.loads(Path(args.frozen_state).read_text())

    with client() as c:
        spot = intraday(c, UNDERLYING)
        chain = option_chain(c, args.expiry)
        cmap = chain_map(chain)
        fut_contract = current_future(c, args.session_date)
        fut_key = str(fut_contract["instrument_key"])
        futures = add_vwap(intraday(c, fut_key))

        # Restrict to requested session only.
        spot = [r for r in spot if parse_ts(r["timestamp"]).date().isoformat() == args.session_date]
        futures = [r for r in futures if parse_ts(r["timestamp"]).date().isoformat() == args.session_date]
        if not spot or not futures:
            raise SystemExit("No current-session spot/futures intraday candles")

        # Fetch every strike that can be exact moving ATM during observed period.
        needed_strikes = sorted({round_atm(float(r["close"])) for r in spot})
        option_series: dict[str, list[dict[str, Any]]] = {}
        contract_meta: dict[tuple[float, str], str] = {}
        issues = Counter()
        for strike in needed_strikes:
            sides = cmap.get(strike)
            if not sides:
                issues[f"MISSING_CHAIN_STRIKE_{strike}"] += 1
                continue
            for side in ("CE", "PE"):
                key = sides.get(side)
                if not key:
                    issues[f"MISSING_{side}_KEY_{strike}"] += 1
                    continue
                contract_meta[(strike, side)] = str(key)
                try:
                    option_series[str(key)] = [
                        r for r in intraday(c, str(key))
                        if parse_ts(r["timestamp"]).date().isoformat() == args.session_date
                    ]
                except Exception:
                    issues[f"OPTION_INTRADAY_FETCH_FAILED_{side}_{strike}"] += 1

    spot_idx = idx(spot)
    fut_idx = idx(futures)
    option_idx = {k: idx(v) for k, v in option_series.items()}

    # 5-minute exact-ATM positioning checkpoints.
    checkpoints = []
    for ts in completed_5m_checkpoints(spot):
        if (ts.hour, ts.minute) < (9, 20):
            continue
        srow = spot_idx.get(ts.isoformat())
        prev_spot = spot_idx.get((ts - timedelta(minutes=5)).isoformat())
        frow = fut_idx.get(ts.isoformat())
        if not srow or not prev_spot or not frow:
            continue
        strike = round_atm(float(srow["close"]))
        row = {
            "session_date": args.session_date,
            "timestamp": ts.isoformat(),
            "spot": float(srow["close"]),
            "moving_atm": strike,
            "futures_close": float(frow["close"]),
            "futures_vwap": frow["session_vwap"],
        }
        for side, prefix in (("CE", "ce"), ("PE", "pe")):
            key = contract_meta.get((strike, side))
            series = option_idx.get(key or "", {})
            now = series.get(ts.isoformat())
            prev = series.get((ts - timedelta(minutes=5)).isoformat())
            row[f"{prefix}_instrument_key"] = key
            row[f"{prefix}_premium"] = None if not now else now["close"]
            row[f"{prefix}_oi"] = None if not now else now["oi"]
            row[f"{prefix}_5m_state"] = state(
                None if not now else now["close"],
                None if not prev else prev["close"],
                None if not now else now["oi"],
                None if not prev else prev["oi"],
                price_threshold, oi_threshold,
            )
        row["direction"] = confluence_direction(
            row["ce_5m_state"], row["pe_5m_state"],
            row["futures_close"], row["futures_vwap"]
        )
        checkpoints.append(row)

    # Arm A: transition into synchronized 5m confluence.
    arm_a = []
    prev_dir = "NEUTRAL"
    for r in checkpoints:
        d = r["direction"]
        if d in {"BULLISH", "BEARISH"} and d != prev_dir:
            side = "CE" if d == "BULLISH" else "PE"
            key = r[f"{side.lower()}_instrument_key"]
            if key and key in option_idx:
                base = {
                    "arm": "ARM_A_OI_VWAP_5MIN",
                    "session_date": args.session_date,
                    "signal_timestamp": r["timestamp"],
                    "direction": d,
                    "option_side": side,
                    "instrument_key": key,
                    "strike": r["moving_atm"],
                    "ce_state": r["ce_5m_state"],
                    "pe_state": r["pe_5m_state"],
                    "futures_close": r["futures_close"],
                    "futures_vwap": r["futures_vwap"],
                }
                base.update(economics(parse_ts(r["timestamp"]), key, option_idx[key]))
                arm_a.append(base)
        prev_dir = d

    # Arm C diagnostic: frozen midpoint T+3 confirmation + latest completed 5m confluence.
    mid_events = midpoint_events(spot)
    arm_c = []
    midpoint_diag = []
    cp_idx = {parse_ts(r["timestamp"]).isoformat(): r for r in checkpoints}
    for ev in mid_events:
        features = t3_features(ev, spot_idx)
        if features is None:
            midpoint_diag.append({**ev, "status": "T3_DATA_INCOMPLETE"})
            continue
        confirmed, checks = passes_frozen_rules(ev["direction"], features, frozen)
        diag = {**ev, "features": features, "feature_checks": checks,
                "t3_confirmed": confirmed}
        midpoint_diag.append(diag)
        if not confirmed:
            continue
        t3 = parse_ts(ev["t3_timestamp"])
        cp = floor_5m(t3)
        p = cp_idx.get(cp.isoformat())
        if not p or p["direction"] != ev["direction"]:
            continue
        strike = round_atm(float(spot_idx[t3.isoformat()]["close"]))
        side = "CE" if ev["direction"] == "BULLISH" else "PE"
        key = contract_meta.get((strike, side))
        if not key or key not in option_idx:
            issues["MISSING_EXACT_ATM_AT_MIDPOINT_CONFIRMATION"] += 1
            continue
        base = {
            "arm": "ARM_C_MIDPOINT_PLUS_OI_VWAP",
            "session_date": args.session_date,
            "signal_timestamp": t3.isoformat(),
            "midpoint_confirmation_timestamp": t3.isoformat(),
            "oi_vwap_checkpoint_timestamp": cp.isoformat(),
            "direction": ev["direction"],
            "option_side": side,
            "instrument_key": key,
            "strike": strike,
            "ce_state": p["ce_5m_state"],
            "pe_state": p["pe_5m_state"],
            "futures_close": p["futures_close"],
            "futures_vwap": p["futures_vwap"],
            "midpoint_features": features,
        }
        base.update(economics(t3, key, option_idx[key]))
        arm_c.append(base)

    raw_option_rows = []
    for key, rows in option_series.items():
        for r in rows:
            raw_option_rows.append({"instrument_key": key, **r})

    write_csv(outdir / f"underlying-{args.session_date}.csv", spot)
    write_csv(outdir / f"futures-vwap-{args.session_date}.csv", futures)
    write_csv(outdir / f"positioning-5min-{args.session_date}.csv", checkpoints)
    write_csv(outdir / f"option-ohlc-{args.session_date}.csv", raw_option_rows)

    doc = {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "research_status": "INTRADAY_DIAGNOSTIC_ONLY_NOT_PROMOTION_EVIDENCE",
        "session_date": args.session_date,
        "expiry": args.expiry,
        "coverage": {
            "spot_first": spot[0]["timestamp"],
            "spot_last": spot[-1]["timestamp"],
            "spot_count": len(spot),
            "futures_first": futures[0]["timestamp"],
            "futures_last": futures[-1]["timestamp"],
            "futures_count": len(futures),
            "option_contract_count": len(option_series),
            "moving_atm_strikes": needed_strikes,
        },
        "positioning_config": {
            "price_threshold_pct": price_threshold,
            "oi_threshold_pct": oi_threshold,
            "source": "repository PositioningConfig defaults unless explicitly overridden",
        },
        "rules": {
            "arm_a": "synchronized completed 5m CE/PE OI direction plus futures close/VWAP; signal only on direction transition",
            "arm_c": "opening midpoint T+3 diagnostic confirmation plus latest completed 5m Arm-A confluence",
            "exact_atm_at_signal": True,
            "entry": "next-minute OPEN",
            "nearest_time_fallback": False,
            "nearest_strike_fallback": False,
            "round_trip_cost_pct_points": ROUND_TRIP_COST_PCT_POINTS,
            "paper_or_live_order_emission_allowed": False,
        },
        "issues": dict(issues),
        "midpoint_diagnostics": midpoint_diag,
        "arm_a": {"summary": summarize(arm_a), "trades": arm_a},
        "arm_c": {"summary": summarize(arm_c), "trades": arm_c},
        "comparison": {
            "arm_a_trade_count": len(arm_a),
            "arm_c_trade_count": len(arm_c),
            "arm_c_survival_pct_of_arm_a": 100 * len(arm_c) / len(arm_a) if arm_a else None,
        },
    }
    out = outdir / f"midpoint-oi-vwap-intraday-validation-{args.session_date}.json"
    out.write_text(json.dumps(doc, indent=2, allow_nan=False))
    print(json.dumps({
        "output": str(out),
        "coverage": doc["coverage"],
        "comparison": doc["comparison"],
        "arm_a": doc["arm_a"]["summary"],
        "arm_c": doc["arm_c"]["summary"],
        "issues": doc["issues"],
    }, indent=2))


if __name__ == "__main__":
    main()
