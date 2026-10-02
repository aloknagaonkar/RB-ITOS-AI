#!/usr/bin/env python3
"""Fixed physical-strike OI event study V2.

Research-only diagnostic for a known event boundary.

For the baseline checkpoint, freeze the exact ATM and construct two physical
strike baskets (default ATM +/-2 and ATM +/-5).  For every requested checkpoint,
read the exact completed 1-minute option candle immediately before the checkpoint
(e.g. 10:40 uses 10:39) for the SAME physical CE/PE contracts.

Outputs:
  1. basket summary CSV
  2. per-strike CSV

No nearest timestamp/strike fallback, no interpolation, no partial baskets.
No strategy, paper-order, or live-execution logic is changed.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterable

from dotenv import load_dotenv

from market_lab.domain import IST
from market_lab.live_fixed_session_anchor_recovery_v1 import (
    AnchorRecoveryError,
    UpstoxIntradayAnchorSourceV1,
)

MODEL = "FIXED_EVENT_OI_BASKET_COMPARISON_V2"


class EventStudyError(RuntimeError):
    pass


@dataclass(frozen=True)
class Leg:
    strike: float
    side: str
    instrument_key: str


def _checkpoint_dt(session_date: date, hhmm: str) -> datetime:
    try:
        hh, mm = map(int, hhmm.split(":"))
        return datetime.combine(session_date, time(hh, mm), tzinfo=IST)
    except Exception as exc:
        raise EventStudyError(f"INVALID_TIME_{hhmm}") from exc


def _fmt_m(v: float | int | None) -> str:
    if v is None:
        return "—"
    return f"{float(v)/1_000_000:+.3f}M"


def _fmt_pct(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:+.3f}%"


def _pcr(pe: int | float, ce: int | float) -> float | None:
    return None if ce == 0 else float(pe) / float(ce)


def _pct(delta: int | float, base: int | float) -> float | None:
    return None if base == 0 else float(delta) / float(base) * 100.0


def _valid_oi(v: Any, *, label: str) -> int:
    if type(v) not in (int, float) or not math.isfinite(v) or v < 0 or int(v) != v:
        raise EventStudyError(f"INVALID_OI_{label}")
    return int(v)


def _side(raw: Any) -> str:
    value = str(raw or "").upper()
    return {"CALL": "CE", "PUT": "PE"}.get(value, value)


def contract_index(rows: Iterable[dict[str, Any]], underlying: str, expiry: date) -> dict[tuple[float, str], str]:
    out: dict[tuple[float, str], str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("underlying_key") not in (None, underlying):
            continue
        if row.get("expiry") not in (None, expiry.isoformat()):
            continue
        side = _side(row.get("instrument_type") or row.get("option_type"))
        if side not in {"CE", "PE"}:
            continue
        try:
            strike = float(row["strike_price"])
        except Exception:
            continue
        key = str(row.get("instrument_key") or "").strip()
        if not key:
            continue
        ident = (strike, side)
        if ident in out and out[ident] != key:
            raise EventStudyError(f"DUPLICATE_CONTRACT_{strike}_{side}")
        out[ident] = key
    return out


def load_baseline_from_step_audit(path: Path, session_date: str, baseline_time: str) -> dict[str, Any]:
    target = f"{session_date}T{baseline_time}:00"
    best: dict[str, Any] | None = None
    for line in path.open(encoding="utf-8"):
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("stage") != "NORMALIZED_FEATURES":
            continue
        cp = str(rec.get("checkpoint") or "")
        if not cp.startswith(target):
            continue
        if best is None or int(rec.get("sequence") or 0) >= int(best.get("sequence") or 0):
            best = rec
    if best is None:
        raise EventStudyError(f"BASELINE_NORMALIZED_FEATURES_NOT_FOUND_{session_date}_{baseline_time}")
    payload = best.get("payload") or {}
    atm = payload.get("moving_atm")
    spot = payload.get("spot")
    if atm is None or spot is None:
        raise EventStudyError("BASELINE_ATM_OR_SPOT_MISSING")
    return {
        "checkpoint": str(best.get("checkpoint")),
        "sequence": int(best.get("sequence") or 0),
        "spot": float(spot),
        "atm": float(atm),
    }


def build_legs(*, idx: dict[tuple[float, str], str], atm: float, wings: int, strike_interval: float) -> list[Leg]:
    legs: list[Leg] = []
    for offset in range(-wings, wings + 1):
        strike = float(atm + offset * strike_interval)
        for side in ("CE", "PE"):
            key = idx.get((strike, side))
            if not key:
                label = int(strike) if strike.is_integer() else strike
                raise EventStudyError(f"EXACT_CONTRACT_MISSING_{label}_{side}")
            legs.append(Leg(strike, side, key))
    expected = (2 * wings + 1) * 2
    if len(legs) != expected:
        raise EventStudyError(f"BASKET_INCOMPLETE_{len(legs)}_OF_{expected}")
    return legs


def index_intraday_rows(rows: Iterable[Any], *, instrument_key: str) -> dict[datetime, int]:
    out: dict[datetime, int] = {}
    duplicate: set[datetime] = set()
    for row in rows:
        if not isinstance(row, list) or len(row) <= 6:
            continue
        try:
            ts = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00")).astimezone(IST)
        except Exception:
            continue
        oi = _valid_oi(row[6], label=f"{instrument_key}_{ts.isoformat()}")
        if ts in out:
            duplicate.add(ts)
        out[ts] = oi
    if duplicate:
        first = sorted(duplicate)[0]
        raise EventStudyError(f"DUPLICATE_MINUTE_{instrument_key}_{first.isoformat()}")
    return out


def fetch_oi_series(source: Any, legs: list[Leg]) -> dict[str, dict[datetime, int]]:
    series: dict[str, dict[datetime, int]] = {}
    for leg in legs:
        if leg.instrument_key in series:
            continue
        rows = source.intraday_1m(leg.instrument_key)
        series[leg.instrument_key] = index_intraday_rows(rows, instrument_key=leg.instrument_key)
    return series


def analyze_fixed_basket(
    *,
    session_date: date,
    checkpoints: list[str],
    baseline_time: str,
    event_time: str,
    atm: float,
    wings: int,
    strike_interval: float,
    legs: list[Leg],
    oi_series: dict[str, dict[datetime, int]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    per_strike: list[dict[str, Any]] = []
    summary: list[dict[str, Any]] = []
    baseline_by_leg: dict[tuple[float, str], int] = {}
    prev_by_leg: dict[tuple[float, str], int] = {}

    ordered = [_checkpoint_dt(session_date, t) for t in checkpoints]
    baseline_dt = _checkpoint_dt(session_date, baseline_time)
    event_dt = _checkpoint_dt(session_date, event_time)
    if baseline_dt not in ordered:
        raise EventStudyError("BASELINE_NOT_IN_CHECKPOINTS")

    # Pre-load exact checkpoint snapshots, using the immediately prior completed 1m candle.
    snapshot: dict[datetime, dict[tuple[float, str], int]] = {}
    for cp in ordered:
        source_minute = cp - timedelta(minutes=1)
        values: dict[tuple[float, str], int] = {}
        for leg in legs:
            series = oi_series.get(leg.instrument_key) or {}
            if source_minute not in series:
                label = int(leg.strike) if leg.strike.is_integer() else leg.strike
                raise EventStudyError(
                    f"EXACT_MINUTE_MISSING_{cp.strftime('%H:%M')}_{label}_{leg.side}_{source_minute.isoformat()}"
                )
            values[(leg.strike, leg.side)] = series[source_minute]
        snapshot[cp] = values

    baseline_by_leg = dict(snapshot[baseline_dt])

    for cp in ordered:
        values = snapshot[cp]
        ce = sum(v for (strike, side), v in values.items() if side == "CE")
        pe = sum(v for (strike, side), v in values.items() if side == "PE")
        base_ce = sum(v for (strike, side), v in baseline_by_leg.items() if side == "CE")
        base_pe = sum(v for (strike, side), v in baseline_by_leg.items() if side == "PE")
        prev_values = snapshot.get(cp - timedelta(minutes=5))
        if prev_values is not None:
            prev_ce = sum(v for (strike, side), v in prev_values.items() if side == "CE")
            prev_pe = sum(v for (strike, side), v in prev_values.items() if side == "PE")
            ce_roll = ce - prev_ce
            pe_roll = pe - prev_pe
            prev_pcr = _pcr(prev_pe, prev_ce)
            cur_pcr = _pcr(pe, ce)
            pcr_roll = None if prev_pcr is None or cur_pcr is None else cur_pcr - prev_pcr
        else:
            prev_ce = prev_pe = ce_roll = pe_roll = pcr_roll = None
            cur_pcr = _pcr(pe, ce)

        ce_base_delta = ce - base_ce
        pe_base_delta = pe - base_pe
        base_pcr = _pcr(base_pe, base_ce)
        cur_pcr = _pcr(pe, ce)
        pcr_from_base = None if base_pcr is None or cur_pcr is None else cur_pcr - base_pcr
        roll_imbalance = None if ce_roll is None or pe_roll is None else pe_roll - ce_roll
        base_imbalance = pe_base_delta - ce_base_delta
        total_oi = ce + pe
        norm_roll = None if roll_imbalance is None or total_oi == 0 else roll_imbalance / total_oi * 100.0
        norm_base = None if total_oi == 0 else base_imbalance / total_oi * 100.0

        phase = "PRE_HISTORY"
        if cp == baseline_dt:
            phase = "PRE_EVENT_BASELINE"
        elif cp == event_dt:
            phase = "EVENT"
        elif cp > event_dt:
            phase = "POST_EVENT"
        elif cp > baseline_dt:
            phase = "BETWEEN_BASELINE_EVENT"

        summary.append({
            "model": MODEL,
            "checkpoint": cp.isoformat(),
            "time": cp.strftime("%H:%M"),
            "source_minute": (cp - timedelta(minutes=1)).isoformat(),
            "phase": phase,
            "wings": wings,
            "fixed_atm": atm,
            "strike_interval": strike_interval,
            "strike_count": 2 * wings + 1,
            "ce_oi": ce,
            "pe_oi": pe,
            "total_oi": total_oi,
            "rolling_ce_delta": ce_roll,
            "rolling_pe_delta": pe_roll,
            "rolling_imbalance": roll_imbalance,
            "rolling_normalized_imbalance_pct": norm_roll,
            "current_pcr": cur_pcr,
            "rolling_pcr_change": pcr_roll,
            "baseline_ce_oi": base_ce,
            "baseline_pe_oi": base_pe,
            "ce_delta_from_baseline": ce_base_delta,
            "pe_delta_from_baseline": pe_base_delta,
            "ce_delta_from_baseline_pct": _pct(ce_base_delta, base_ce),
            "pe_delta_from_baseline_pct": _pct(pe_base_delta, base_pe),
            "imbalance_from_baseline": base_imbalance,
            "normalized_imbalance_from_baseline_pct": norm_base,
            "baseline_pcr": base_pcr,
            "pcr_change_from_baseline": pcr_from_base,
        })

        for leg in legs:
            key = (leg.strike, leg.side)
            oi = values[key]
            base_oi = baseline_by_leg[key]
            prev_oi = prev_values[key] if prev_values is not None else None
            per_strike.append({
                "model": MODEL,
                "checkpoint": cp.isoformat(),
                "time": cp.strftime("%H:%M"),
                "source_minute": (cp - timedelta(minutes=1)).isoformat(),
                "phase": phase,
                "wings": wings,
                "fixed_atm": atm,
                "strike": leg.strike,
                "side": leg.side,
                "instrument_key": leg.instrument_key,
                "oi": oi,
                "rolling_delta": None if prev_oi is None else oi - prev_oi,
                "rolling_delta_pct": None if prev_oi in (None, 0) else (oi - prev_oi) / prev_oi * 100.0,
                "baseline_oi": base_oi,
                "delta_from_baseline": oi - base_oi,
                "delta_from_baseline_pct": _pct(oi - base_oi, base_oi),
            })

    return summary, per_strike


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise EventStudyError(f"NO_ROWS_FOR_{path}")
    fields = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def print_summary(rows: list[dict[str, Any]], *, title: str) -> None:
    print()
    print(f"=== {title} ===")
    print("TIME   PHASE               CE_OI      PE_OI      R_CEΔ      R_PEΔ      R_IMB      BASE_CEΔ   BASE_PEΔ   BASE_IMB   PCR      PCRΔ_R    PCRΔ_BASE")
    print("-" * 165)
    for r in rows:
        pcr = "—" if r["current_pcr"] is None else f'{r["current_pcr"]:.4f}'
        pcr_r = "—" if r["rolling_pcr_change"] is None else f'{r["rolling_pcr_change"]:+.4f}'
        pcr_b = "—" if r["pcr_change_from_baseline"] is None else f'{r["pcr_change_from_baseline"]:+.4f}'
        print(
            f'{r["time"]:5} {r["phase"]:19} '
            f'{_fmt_m(r["ce_oi"]):>10} {_fmt_m(r["pe_oi"]):>10} '
            f'{_fmt_m(r["rolling_ce_delta"]):>10} {_fmt_m(r["rolling_pe_delta"]):>10} {_fmt_m(r["rolling_imbalance"]):>10} '
            f'{_fmt_m(r["ce_delta_from_baseline"]):>10} {_fmt_m(r["pe_delta_from_baseline"]):>10} {_fmt_m(r["imbalance_from_baseline"]):>10} '
            f'{pcr:>7} {pcr_r:>10} {pcr_b:>11}'
        )


def parse_checkpoints(session_date: date, start: str, end: str) -> list[str]:
    cur = _checkpoint_dt(session_date, start)
    last = _checkpoint_dt(session_date, end)
    if cur > last:
        raise EventStudyError("FROM_TIME_AFTER_TO_TIME")
    out = []
    while cur <= last:
        out.append(cur.strftime("%H:%M"))
        cur += timedelta(minutes=5)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", required=True, help="Session date YYYY-MM-DD; V2 current-day Upstox intraday source only")
    ap.add_argument("--expiry", required=True, help="Exact option expiry YYYY-MM-DD")
    ap.add_argument("--underlying", default="NSE_INDEX|Nifty 50")
    ap.add_argument("--step-audit", default="data/live-observation/shadow-v1/step-audit.jsonl")
    ap.add_argument("--from-time", default="10:10")
    ap.add_argument("--to-time", default="11:05")
    ap.add_argument("--baseline-time", default="10:35")
    ap.add_argument("--event-time", default="10:40")
    ap.add_argument("--strike-interval", type=float, default=50.0)
    ap.add_argument("--wings", type=int, nargs="+", default=[2, 5], help="Physical basket wings to compare, default: 2 5")
    ap.add_argument("--output-dir", default="data/live-observation/analysis")
    args = ap.parse_args()

    session_date = date.fromisoformat(args.date)
    expiry = date.fromisoformat(args.expiry)
    if session_date != datetime.now(IST).date():
        raise SystemExit("V2_UPSTOX_INTRADAY_SOURCE_IS_CURRENT_DAY_ONLY")
    if any(w < 0 for w in args.wings):
        raise SystemExit("WINGS_MUST_BE_NONNEGATIVE")

    baseline = load_baseline_from_step_audit(Path(args.step_audit), args.date, args.baseline_time)
    atm = float(baseline["atm"])
    checkpoints = parse_checkpoints(session_date, args.from_time, args.to_time)

    load_dotenv(".env")
    token = os.getenv("UPSTOX_ACCESS_TOKEN", "")
    if not token:
        raise SystemExit("UPSTOX_ACCESS_TOKEN is not set")

    print(f"model={MODEL}")
    print(f"session={args.date} expiry={args.expiry} window={args.from_time}-{args.to_time}")
    print(f"baseline={args.baseline_time} event={args.event_time} baseline_spot={baseline['spot']:.2f} fixed_atm={atm:.0f}")
    print(f"wings={','.join(map(str,args.wings))} exact_physical_strikes=true nearest_fallback=false interpolation=false")
    print("checkpoint semantics: checkpoint T uses exact completed 1m OI candle at T-1 minute")

    source = UpstoxIntradayAnchorSourceV1(token)
    try:
        idx = contract_index(source.option_contracts(args.underlying, expiry), args.underlying, expiry)
        max_wings = max(args.wings)
        all_legs = build_legs(idx=idx, atm=atm, wings=max_wings, strike_interval=args.strike_interval)
        oi_series = fetch_oi_series(source, all_legs)

        out_dir = Path(args.output_dir)
        for wings in args.wings:
            selected_strikes = {float(atm + i * args.strike_interval) for i in range(-wings, wings + 1)}
            legs = [leg for leg in all_legs if leg.strike in selected_strikes]
            summary, per_strike = analyze_fixed_basket(
                session_date=session_date,
                checkpoints=checkpoints,
                baseline_time=args.baseline_time,
                event_time=args.event_time,
                atm=atm,
                wings=wings,
                strike_interval=args.strike_interval,
                legs=legs,
                oi_series=oi_series,
            )
            print_summary(summary, title=f"FIXED ATM +/-{wings} ({2*wings+1} STRIKES)")
            summary_path = out_dir / f"{args.date}-fixed-event-oi-pm{wings}-summary-v2.csv"
            strike_path = out_dir / f"{args.date}-fixed-event-oi-pm{wings}-per-strike-v2.csv"
            write_csv(summary, summary_path)
            write_csv(per_strike, strike_path)
            print(f"SUMMARY_CSV: {summary_path}")
            print(f"PER_STRIKE_CSV: {strike_path}")
    except (AnchorRecoveryError, EventStudyError) as exc:
        raise SystemExit(f"FAIL_CLOSED: {exc}") from exc
    finally:
        source.close()


if __name__ == "__main__":
    main()
