#!/usr/bin/env python3
"""Strike-level OI breadth / transition research V3.

Consumes the V2 fixed physical-strike per-strike CSV (normally ATM +/-2) and
measures how directional breadth evolves before/after an event boundary.

Research-only. No strategy, paper-order, or live-execution logic is modified.

Metrics per strike/checkpoint:
- CE rolling delta / PE rolling delta
- imbalance = PE rolling delta - CE rolling delta
- CE delta acceleration = CE_delta(T) - CE_delta(T-5m)
- PE delta acceleration = PE_delta(T) - PE_delta(T-5m)
- imbalance velocity = imbalance(T) - imbalance(T-5m)
- strike state: BULLISH / BEARISH / MIXED / INCOMPLETE

Breadth per checkpoint:
- bullish/bearish/mixed/incomplete strike count
- bullish/bearish breadth percentage
- ATM state
- ATM +/-1 and ATM +/-2 state counts
- aggregate strike imbalance and aggregate imbalance velocity

Directional semantics intentionally match the current OI research rule at the
single-strike level:
  BULLISH iff imbalance > 0
  BEARISH iff imbalance < 0
  MIXED iff imbalance == 0
This V3 is descriptive research; it does not create a trading rule.
"""
from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

MODEL = "STRIKE_BREADTH_TRANSITION_V3"


class BreadthStudyError(RuntimeError):
    pass


def _num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise BreadthStudyError(f"INVALID_NUMERIC_VALUE_{value}") from exc
    if not math.isfinite(out):
        raise BreadthStudyError(f"NONFINITE_VALUE_{value}")
    return out


def _state(imbalance: float | None) -> str:
    if imbalance is None:
        return "INCOMPLETE"
    if imbalance > 0:
        return "BULLISH"
    if imbalance < 0:
        return "BEARISH"
    return "MIXED"


def _fmt_m(value: float | None) -> str:
    return "—" if value is None else f"{value / 1_000_000:+.3f}M"


def _fmt_pct(value: float | None) -> str:
    return "—" if value is None else f"{value:+.1f}%"


def load_per_strike_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise BreadthStudyError(f"INPUT_NOT_FOUND_{path}")
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise BreadthStudyError("INPUT_EMPTY")

    required = {"time", "phase", "fixed_atm", "strike", "side", "rolling_delta", "oi"}
    missing = required - set(rows[0])
    if missing:
        raise BreadthStudyError("INPUT_COLUMNS_MISSING_" + "_".join(sorted(missing)))
    return rows


def analyze(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    grouped: dict[tuple[str, float], dict[str, dict[str, Any]]] = defaultdict(dict)
    meta_by_time: dict[str, dict[str, Any]] = {}

    for row in rows:
        t = str(row["time"])
        strike = float(row["strike"])
        side = str(row["side"]).upper()
        if side not in {"CE", "PE"}:
            raise BreadthStudyError(f"INVALID_SIDE_{side}")
        if side in grouped[(t, strike)]:
            raise BreadthStudyError(f"DUPLICATE_SIDE_{t}_{strike}_{side}")
        grouped[(t, strike)][side] = row
        meta_by_time[t] = row

    times = sorted(meta_by_time)
    strikes = sorted({strike for _, strike in grouped})
    if not strikes:
        raise BreadthStudyError("NO_STRIKES")

    fixed_atm_values = {float(meta_by_time[t]["fixed_atm"]) for t in times}
    if len(fixed_atm_values) != 1:
        raise BreadthStudyError("FIXED_ATM_NOT_CONSTANT")
    fixed_atm = next(iter(fixed_atm_values))

    detail: list[dict[str, Any]] = []
    summary: list[dict[str, Any]] = []
    prev_by_strike: dict[float, dict[str, float | None]] = {}

    for t in times:
        states: list[str] = []
        aggregate_imbalance = 0.0
        aggregate_velocity = 0.0
        aggregate_velocity_complete = True
        atm_state = "INCOMPLETE"
        near1_states: list[str] = []
        near2_states: list[str] = []

        for strike in strikes:
            pair = grouped.get((t, strike), {})
            ce = pair.get("CE")
            pe = pair.get("PE")
            if ce is None or pe is None:
                raise BreadthStudyError(f"PAIR_INCOMPLETE_{t}_{strike}")

            ce_delta = _num(ce.get("rolling_delta"))
            pe_delta = _num(pe.get("rolling_delta"))
            imbalance = None if ce_delta is None or pe_delta is None else pe_delta - ce_delta
            state = _state(imbalance)

            prev = prev_by_strike.get(strike)
            ce_accel = None if prev is None or ce_delta is None or prev["ce_delta"] is None else ce_delta - float(prev["ce_delta"])
            pe_accel = None if prev is None or pe_delta is None or prev["pe_delta"] is None else pe_delta - float(prev["pe_delta"])
            imb_velocity = None if prev is None or imbalance is None or prev["imbalance"] is None else imbalance - float(prev["imbalance"])

            detail.append({
                "model": MODEL,
                "time": t,
                "phase": str(ce["phase"]),
                "fixed_atm": fixed_atm,
                "strike": strike,
                "distance_from_atm": int(round((strike - fixed_atm) / 50.0)),
                "ce_oi": int(float(ce["oi"])),
                "pe_oi": int(float(pe["oi"])),
                "ce_delta": ce_delta,
                "pe_delta": pe_delta,
                "imbalance": imbalance,
                "state": state,
                "ce_delta_acceleration": ce_accel,
                "pe_delta_acceleration": pe_accel,
                "imbalance_velocity": imb_velocity,
            })

            prev_by_strike[strike] = {"ce_delta": ce_delta, "pe_delta": pe_delta, "imbalance": imbalance}
            states.append(state)
            if imbalance is not None:
                aggregate_imbalance += imbalance
            if imb_velocity is None:
                aggregate_velocity_complete = False
            else:
                aggregate_velocity += imb_velocity

            distance = int(round((strike - fixed_atm) / 50.0))
            if distance == 0:
                atm_state = state
            if abs(distance) <= 1:
                near1_states.append(state)
            if abs(distance) <= 2:
                near2_states.append(state)

        total = len(states)
        bullish = states.count("BULLISH")
        bearish = states.count("BEARISH")
        mixed = states.count("MIXED")
        incomplete = states.count("INCOMPLETE")

        summary.append({
            "model": MODEL,
            "time": t,
            "phase": str(meta_by_time[t]["phase"]),
            "fixed_atm": fixed_atm,
            "strike_count": total,
            "bullish_count": bullish,
            "bearish_count": bearish,
            "mixed_count": mixed,
            "incomplete_count": incomplete,
            "bullish_breadth_pct": bullish / total * 100.0 if total else None,
            "bearish_breadth_pct": bearish / total * 100.0 if total else None,
            "atm_state": atm_state,
            "atm_pm1_bullish_count": near1_states.count("BULLISH"),
            "atm_pm1_bearish_count": near1_states.count("BEARISH"),
            "atm_pm2_bullish_count": near2_states.count("BULLISH"),
            "atm_pm2_bearish_count": near2_states.count("BEARISH"),
            "aggregate_imbalance": aggregate_imbalance,
            "aggregate_imbalance_velocity": aggregate_velocity if aggregate_velocity_complete else None,
        })

    return summary, detail


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise BreadthStudyError("NO_OUTPUT_ROWS")
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def print_summary(rows: list[dict[str, Any]]) -> None:
    print(f"model={MODEL}")
    print("TIME  PHASE               BULL BEAR MIX  BULL%  ATM       ATM±1(B/B) ATM±2(B/B)   IMBALANCE  IMB_VELOCITY")
    for r in rows:
        print(
            f"{r['time']:5} {r['phase'][:18]:18} "
            f"{r['bullish_count']:>4} {r['bearish_count']:>4} {r['mixed_count']:>3} "
            f"{_fmt_pct(r['bullish_breadth_pct']):>6} "
            f"{r['atm_state'][:8]:8} "
            f"{r['atm_pm1_bullish_count']}/{r['atm_pm1_bearish_count']:^7} "
            f"{r['atm_pm2_bullish_count']}/{r['atm_pm2_bearish_count']:^7} "
            f"{_fmt_m(r['aggregate_imbalance']):>11} "
            f"{_fmt_m(r['aggregate_imbalance_velocity']):>12}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path)
    parser.add_argument("--detail-output", type=Path)
    args = parser.parse_args()

    rows = load_per_strike_csv(args.input)
    summary, detail = analyze(rows)

    stem = args.input.stem.replace("-per-strike-v2", "")
    base_dir = args.input.parent
    summary_out = args.summary_output or base_dir / f"{stem}-strike-breadth-summary-v3.csv"
    detail_out = args.detail_output or base_dir / f"{stem}-strike-transition-detail-v3.csv"

    write_csv(summary_out, summary)
    write_csv(detail_out, detail)
    print_summary(summary)
    print(f"SUMMARY_CSV: {summary_out}")
    print(f"DETAIL_CSV: {detail_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
