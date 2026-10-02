#!/usr/bin/env python3
"""OI/price pressure-failure transition research V4.

Combines:
- V3 fixed ATM +/-2 strike-breadth summary
- LIVE_SHADOW NORMALIZED_FEATURES spot checkpoints

Purpose: study whether a bearish OI impulse first fades and then fails to move
price lower, before ATM/strike breadth turns bullish.

Research-only. It does not modify strategy, paper trading, or live execution.

Checkpoint/candle semantics:
  checkpoint 2026-09-21 10:40 represents the completed 5m candle
  2026-09-21 10:35 -> 2026-09-21 10:40.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

MODEL = "OI_PRICE_FAILURE_TRANSITION_V4"


class TransitionStudyError(RuntimeError):
    pass


def _num(v: Any) -> float | None:
    if v in (None, ""):
        return None
    try:
        out = float(v)
    except (TypeError, ValueError) as exc:
        raise TransitionStudyError(f"INVALID_NUMERIC_{v}") from exc
    if not math.isfinite(out):
        raise TransitionStudyError(f"NONFINITE_NUMERIC_{v}")
    return out


def _fmt_m(v: float | None) -> str:
    return "—" if v is None else f"{v / 1_000_000:+.3f}M"


def _fmt_pts(v: float | None) -> str:
    return "—" if v is None else f"{v:+.2f}"


def load_breadth(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise TransitionStudyError(f"BREADTH_INPUT_NOT_FOUND_{path}")
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise TransitionStudyError("BREADTH_INPUT_EMPTY")
    required = {
        "time", "phase", "fixed_atm", "bullish_count", "bearish_count",
        "atm_state", "aggregate_imbalance", "aggregate_imbalance_velocity",
    }
    missing = required - set(rows[0])
    if missing:
        raise TransitionStudyError("BREADTH_COLUMNS_MISSING_" + "_".join(sorted(missing)))
    return rows


def load_spot_from_step_audit(path: Path, session_date: str) -> dict[str, dict[str, Any]]:
    if not path.exists():
        raise TransitionStudyError(f"STEP_AUDIT_NOT_FOUND_{path}")
    latest: dict[str, dict[str, Any]] = {}
    for line in path.open(encoding="utf-8"):
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("stage") != "NORMALIZED_FEATURES":
            continue
        cp = str(rec.get("checkpoint") or "")
        if not cp.startswith(session_date):
            continue
        seq = int(rec.get("sequence") or 0)
        old = latest.get(cp)
        if old is None or seq >= int(old.get("sequence") or 0):
            latest[cp] = rec

    out: dict[str, dict[str, Any]] = {}
    for cp, rec in sorted(latest.items()):
        payload = rec.get("payload") or {}
        spot = payload.get("spot")
        if spot is None:
            continue
        dt = datetime.fromisoformat(cp)
        out[dt.strftime("%H:%M")] = {
            "checkpoint": cp,
            "checkpoint_dt": dt,
            "spot": float(spot),
            "moving_atm": payload.get("moving_atm"),
            "all3_state": payload.get("all3_state"),
        }
    if not out:
        raise TransitionStudyError(f"NO_NORMALIZED_FEATURES_{session_date}")
    return out


def _oi_direction(imbalance: float | None) -> str:
    if imbalance is None:
        return "INCOMPLETE"
    if imbalance > 0:
        return "BULLISH"
    if imbalance < 0:
        return "BEARISH"
    return "MIXED"


def _price_direction(delta: float | None) -> str:
    if delta is None:
        return "INCOMPLETE"
    if delta > 0:
        return "UP"
    if delta < 0:
        return "DOWN"
    return "FLAT"


def _response(oi_direction: str, price_direction: str) -> str:
    if "INCOMPLETE" in (oi_direction, price_direction):
        return "INCOMPLETE"
    if oi_direction == "BEARISH":
        if price_direction == "DOWN":
            return "BEARISH_CONFIRMED_RESPONSE"
        if price_direction == "UP":
            return "FAILED_BEARISH_RESPONSE"
        return "WEAK_BEARISH_RESPONSE"
    if oi_direction == "BULLISH":
        if price_direction == "UP":
            return "BULLISH_CONFIRMED_RESPONSE"
        if price_direction == "DOWN":
            return "FAILED_BULLISH_RESPONSE"
        return "WEAK_BULLISH_RESPONSE"
    return "MIXED_RESPONSE"


def _phase_label(row: dict[str, Any]) -> str:
    imb = row["aggregate_imbalance"]
    vel = row["aggregate_imbalance_velocity"]
    prev_vel = row["previous_imbalance_velocity"]
    bull = row["bullish_count"]
    bear = row["bearish_count"]
    atm = row["atm_state"]
    response = row["oi_price_response"]

    if imb is None:
        return "INCOMPLETE"
    if imb > 0 and bull >= 4 and atm == "BULLISH":
        return "BROAD_BULLISH_CONFIRMATION"
    if imb <= 0 and vel is not None and vel > 0 and bull >= 2 and atm == "BULLISH":
        return "EARLY_BULL_TRANSITION"
    if response == "FAILED_BEARISH_RESPONSE":
        return "PRICE_OI_DIVERGENCE"
    if imb < 0 and vel is not None and vel > 0:
        if prev_vel is not None and prev_vel < 0:
            return "BEARISH_FADING_REVERSAL"
        return "BEARISH_FADING"
    if imb < 0 and vel is not None and vel < 0:
        return "BEARISH_ACCELERATING"
    if imb < 0:
        return "BEARISH"
    if imb > 0:
        return "BULLISH"
    return "MIXED"


def analyze(
    breadth_rows: list[dict[str, Any]],
    spot_by_time: dict[str, dict[str, Any]],
    *,
    session_date: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    prev_spot: float | None = None
    prev_velocity: float | None = None

    for raw in breadth_rows:
        t = str(raw["time"])
        spot_rec = spot_by_time.get(t)
        if spot_rec is None:
            raise TransitionStudyError(f"EXACT_SPOT_CHECKPOINT_MISSING_{session_date}_{t}")
        cp_dt: datetime = spot_rec["checkpoint_dt"]
        candle_start = cp_dt - timedelta(minutes=5)

        spot = float(spot_rec["spot"])
        spot_delta = None if prev_spot is None else spot - prev_spot
        imbalance = _num(raw.get("aggregate_imbalance"))
        velocity = _num(raw.get("aggregate_imbalance_velocity"))
        acceleration = None if velocity is None or prev_velocity is None else velocity - prev_velocity
        oi_dir = _oi_direction(imbalance)
        price_dir = _price_direction(spot_delta)

        row: dict[str, Any] = {
            "model": MODEL,
            "session_date": session_date,
            "candle_start": candle_start.isoformat(),
            "candle_end": cp_dt.isoformat(),
            "checkpoint": spot_rec["checkpoint"],
            "time": t,
            "phase": str(raw["phase"]),
            "spot": spot,
            "spot_change_5m": spot_delta,
            "price_direction": price_dir,
            "fixed_atm": _num(raw.get("fixed_atm")),
            "moving_atm": _num(spot_rec.get("moving_atm")),
            "bullish_count": int(float(raw["bullish_count"])),
            "bearish_count": int(float(raw["bearish_count"])),
            "atm_state": str(raw["atm_state"]),
            "aggregate_imbalance": imbalance,
            "aggregate_imbalance_velocity": velocity,
            "previous_imbalance_velocity": prev_velocity,
            "aggregate_imbalance_acceleration": acceleration,
            "oi_direction": oi_dir,
            "all3_state": spot_rec.get("all3_state"),
        }
        row["oi_price_response"] = _response(oi_dir, price_dir)
        row["transition_phase"] = _phase_label(row)
        out.append(row)

        prev_spot = spot
        if velocity is not None:
            prev_velocity = velocity

    return out


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise TransitionStudyError("NO_OUTPUT_ROWS")
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def print_summary(rows: list[dict[str, Any]], focus_times: set[str]) -> None:
    print(f"model={MODEL}")
    print("CANDLE_DATE_TIME                  SPOT     ΔSPOT  OI_IMB     OI_VEL     OI_ACCEL   BULL/BEAR ATM      RESPONSE                    TRANSITION")
    print("-" * 175)
    for r in rows:
        marker = "*" if r["time"] in focus_times else " "
        candle = f"{r['candle_start'][:16]} -> {r['candle_end'][:16]}"
        print(
            f"{marker}{candle:34} "
            f"{r['spot']:8.2f} {_fmt_pts(r['spot_change_5m']):>7} "
            f"{_fmt_m(r['aggregate_imbalance']):>10} "
            f"{_fmt_m(r['aggregate_imbalance_velocity']):>10} "
            f"{_fmt_m(r['aggregate_imbalance_acceleration']):>10} "
            f"{r['bullish_count']}/{r['bearish_count']:<3} "
            f"{r['atm_state'][:8]:8} "
            f"{r['oi_price_response'][:27]:27} "
            f"{r['transition_phase']}"
        )

    print("\n=== FOCUS CANDLES ===")
    for r in rows:
        if r["time"] not in focus_times:
            continue
        print(
            f"{r['session_date']} checkpoint={r['time']} candle={r['candle_start']} -> {r['candle_end']} "
            f"spot={r['spot']:.2f} Δ5m={_fmt_pts(r['spot_change_5m'])} "
            f"imbalance={_fmt_m(r['aggregate_imbalance'])} velocity={_fmt_m(r['aggregate_imbalance_velocity'])} "
            f"acceleration={_fmt_m(r['aggregate_imbalance_acceleration'])} breadth={r['bullish_count']}/{r['bullish_count'] + r['bearish_count']} "
            f"ATM={r['atm_state']} response={r['oi_price_response']} phase={r['transition_phase']}"
        )


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--date", required=True)
    p.add_argument("--breadth-input", type=Path, required=True)
    p.add_argument(
        "--step-audit",
        type=Path,
        default=Path("data/live-observation/shadow-v1/step-audit.jsonl"),
    )
    p.add_argument("--focus-times", nargs="+", default=["10:35", "10:40"])
    p.add_argument("--output", type=Path)
    args = p.parse_args()

    breadth = load_breadth(args.breadth_input)
    spots = load_spot_from_step_audit(args.step_audit, args.date)
    rows = analyze(breadth, spots, session_date=args.date)

    out = args.output or args.breadth_input.parent / f"{args.date}-oi-price-failure-transition-v4.csv"
    write_csv(out, rows)
    print_summary(rows, set(args.focus_times))
    print(f"OUTPUT_CSV: {out}")
    print("NOTE: checkpoint T is the completed 5m candle ending at T; candle_start=T-5m.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
