from __future__ import annotations

import argparse
import csv
import json
import statistics
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

MODEL = "CONTROL_FAILURE_INTRABAR_ATTRIBUTION_V6_5"
DEFAULT_TARGETS = [
    ("2026-05-18", "BULLISH", "2026-05-18T10:00:00+05:30"),
    ("2026-06-24", "BULLISH", "2026-06-24T09:55:00+05:30"),
    ("2026-06-29", "BEARISH", "2026-06-29T10:35:00+05:30"),
    ("2026-07-07", "BEARISH", "2026-07-07T12:05:00+05:30"),
    # Weaker comparison case from V6.4.
    ("2026-05-25", "BULLISH", "2026-05-25T09:45:00+05:30"),
]


def _f(v: Any) -> float | None:
    if v in (None, ""):
        return None
    return float(v)


def _state(imbalance: float) -> str:
    if imbalance > 0:
        return "BULLISH"
    if imbalance < 0:
        return "BEARISH"
    return "MIXED"


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def load_session(path: Path) -> dict[str, Any]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    sessions = doc.get("sessions") or []
    if len(sessions) != 1:
        raise ValueError(f"{path}: expected one session, found {len(sessions)}")
    s = sessions[0]
    if s.get("status") != "AVAILABLE":
        raise ValueError(f"{path}: session status={s.get('status')!r}, expected AVAILABLE")
    return s


def index_rows(session: dict[str, Any]) -> dict[datetime, dict[float, dict[str, Any]]]:
    out: dict[datetime, dict[float, dict[str, Any]]] = {}
    for r in session.get("rows") or []:
        t = datetime.fromisoformat(str(r["timestamp"]))
        strike = float(r["strike"])
        out.setdefault(t, {})
        if strike in out[t]:
            raise ValueError(f"duplicate strike={strike} at {t.isoformat()}")
        out[t][strike] = r
    return out


def atm_spot(group: dict[float, dict[str, Any]], ts: datetime) -> tuple[float, float]:
    atms = {float(r["moving_atm"]) for r in group.values() if r.get("moving_atm") is not None}
    spots = {float(r["spot"]) for r in group.values() if r.get("spot") is not None}
    if len(atms) != 1 or len(spots) != 1:
        raise ValueError(f"ambiguous ATM/spot at {ts.isoformat()}")
    return next(iter(atms)), next(iter(spots))


def leg_oi(group: dict[float, dict[str, Any]], strike: float, side: str, ts: datetime) -> float:
    r = group.get(strike)
    if r is None:
        raise ValueError(f"missing exact strike={strike} at {ts.isoformat()}")
    key = "ce_open_interest" if side == "CE" else "pe_open_interest"
    v = _f(r.get(key))
    if v is None:
        raise ValueError(f"missing {key} strike={strike} at {ts.isoformat()}")
    return v


def round_minute(ts: datetime) -> datetime:
    return ts.replace(second=0, microsecond=0)


@dataclass(frozen=True)
class MinuteRow:
    session_date: str
    known_direction: str
    move_start_time: str
    signal_checkpoint: str
    selected_wings: int
    signal_atm: float
    minute_checkpoint: str
    minute_from_candle_start: int
    minute_from_move_start: float
    spot: float
    spot_delta_1m: float | None
    ce_delta_1m: float | None
    pe_delta_1m: float | None
    imbalance_1m: float | None
    imbalance_velocity_1m: float | None
    imbalance_acceleration_1m: float | None
    bullish_strikes: int
    bearish_strikes: int
    mixed_strikes: int
    atm_state: str
    failed_bearish_response: bool
    failed_bullish_response: bool
    bearish_decay: bool
    bullish_decay: bool
    direction_failure: bool
    direction_decay: bool
    cumulative_spot_from_candle_start: float | None
    cumulative_ce_delta_from_candle_start: float | None
    cumulative_pe_delta_from_candle_start: float | None
    cumulative_imbalance_from_candle_start: float | None


def build_intrabar_rows(
    session: dict[str, Any],
    known_direction: str,
    move_start: str,
    signal_checkpoint: str,
    selected_wings: int,
) -> list[MinuteRow]:
    idx = index_rows(session)
    cp = datetime.fromisoformat(signal_checkpoint)
    candle_start = cp - timedelta(minutes=5)
    move_dt = datetime.fromisoformat(move_start) if "T" in move_start else datetime.fromisoformat(
        f"{cp.date().isoformat()}T{move_start}:00{cp.strftime('%z')[:3]}:{cp.strftime('%z')[3:]}"
    )

    signal_group = idx.get(cp)
    if signal_group is None:
        raise ValueError(f"missing signal checkpoint {cp.isoformat()}")
    signal_atm, _ = atm_spot(signal_group, cp)
    interval = float(session.get("strike_interval") or 50.0)
    strikes = [signal_atm + i * interval for i in range(-selected_wings, selected_wings + 1)]

    # Baseline is exact minute at candle start. Minute checkpoints are +1..+5.
    base_group = idx.get(candle_start)
    if base_group is None:
        raise ValueError(f"missing candle-start minute {candle_start.isoformat()}")
    _, base_spot = atm_spot(base_group, candle_start)
    base_ce = sum(leg_oi(base_group, s, "CE", candle_start) for s in strikes)
    base_pe = sum(leg_oi(base_group, s, "PE", candle_start) for s in strikes)

    prelim: list[dict[str, Any]] = []
    prev_imb: float | None = None
    prev_vel: float | None = None
    prev_spot: float | None = None

    for i in range(1, 6):
        t = candle_start + timedelta(minutes=i)
        prev = t - timedelta(minutes=1)
        cur_group = idx.get(t)
        prev_group = idx.get(prev)
        if cur_group is None or prev_group is None:
            raise ValueError(f"missing exact 1m row at {t.isoformat()} or {prev.isoformat()}")
        _, spot = atm_spot(cur_group, t)

        ce_d = pe_d = 0.0
        bull = bear = mixed = 0
        atm_state = "MIXED"
        for strike in strikes:
            ce = leg_oi(cur_group, strike, "CE", t) - leg_oi(prev_group, strike, "CE", prev)
            pe = leg_oi(cur_group, strike, "PE", t) - leg_oi(prev_group, strike, "PE", prev)
            ce_d += ce
            pe_d += pe
            st = _state(pe - ce)
            if st == "BULLISH":
                bull += 1
            elif st == "BEARISH":
                bear += 1
            else:
                mixed += 1
            if strike == signal_atm:
                atm_state = st

        imb = pe_d - ce_d
        vel = None if prev_imb is None else imb - prev_imb
        accel = None if vel is None or prev_vel is None else vel - prev_vel
        spot_d = None if prev_spot is None else spot - prev_spot
        # For first intrabar minute, spot change is still exact t vs t-1.
        if spot_d is None:
            _, prev_spot_exact = atm_spot(prev_group, prev)
            spot_d = spot - prev_spot_exact

        failed_bear = imb < 0 and spot_d > 0
        failed_bull = imb > 0 and spot_d < 0
        bearish_decay = imb < 0 and vel is not None and vel > 0 and accel is not None and accel > 0
        bullish_decay = imb > 0 and vel is not None and vel < 0 and accel is not None and accel < 0

        cur_ce = sum(leg_oi(cur_group, s, "CE", t) for s in strikes)
        cur_pe = sum(leg_oi(cur_group, s, "PE", t) for s in strikes)
        cum_ce = cur_ce - base_ce
        cum_pe = cur_pe - base_pe

        prelim.append({
            "t": t,
            "spot": spot,
            "spot_d": spot_d,
            "ce_d": ce_d,
            "pe_d": pe_d,
            "imb": imb,
            "vel": vel,
            "accel": accel,
            "bull": bull,
            "bear": bear,
            "mixed": mixed,
            "atm_state": atm_state,
            "failed_bear": failed_bear,
            "failed_bull": failed_bull,
            "bearish_decay": bearish_decay,
            "bullish_decay": bullish_decay,
            "cum_ce": cum_ce,
            "cum_pe": cum_pe,
            "cum_imb": cum_pe - cum_ce,
            "cum_spot": spot - base_spot,
        })
        prev_imb = imb
        prev_vel = vel
        prev_spot = spot

    out: list[MinuteRow] = []
    for r in prelim:
        t = r["t"]
        direction_failure = r["failed_bear"] if known_direction == "BULLISH" else r["failed_bull"]
        direction_decay = r["bearish_decay"] if known_direction == "BULLISH" else r["bullish_decay"]
        out.append(MinuteRow(
            session_date=str(session.get("session_date") or cp.date().isoformat()),
            known_direction=known_direction,
            move_start_time=move_dt.isoformat(),
            signal_checkpoint=cp.isoformat(),
            selected_wings=selected_wings,
            signal_atm=signal_atm,
            minute_checkpoint=t.isoformat(),
            minute_from_candle_start=int((t - candle_start).total_seconds() // 60),
            minute_from_move_start=(t - move_dt).total_seconds() / 60.0,
            spot=r["spot"],
            spot_delta_1m=r["spot_d"],
            ce_delta_1m=r["ce_d"],
            pe_delta_1m=r["pe_d"],
            imbalance_1m=r["imb"],
            imbalance_velocity_1m=r["vel"],
            imbalance_acceleration_1m=r["accel"],
            bullish_strikes=r["bull"],
            bearish_strikes=r["bear"],
            mixed_strikes=r["mixed"],
            atm_state=r["atm_state"],
            failed_bearish_response=r["failed_bear"],
            failed_bullish_response=r["failed_bull"],
            bearish_decay=r["bearish_decay"],
            bullish_decay=r["bullish_decay"],
            direction_failure=direction_failure,
            direction_decay=direction_decay,
            cumulative_spot_from_candle_start=r["cum_spot"],
            cumulative_ce_delta_from_candle_start=r["cum_ce"],
            cumulative_pe_delta_from_candle_start=r["cum_pe"],
            cumulative_imbalance_from_candle_start=r["cum_imb"],
        ))
    return out


def first_minute(rows: list[MinuteRow], attr: str) -> MinuteRow | None:
    for r in rows:
        if bool(getattr(r, attr)):
            return r
    return None


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in fields})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--positioning-root", default="data/historical-evidence/historical-oi-build")
    ap.add_argument("--v6-4-detail", default="data/historical-evidence/control-failure-component-timestamp-v6-4/component-timestamp-detail-v6-4.csv")
    ap.add_argument("--output-dir", default="data/historical-evidence/control-failure-intrabar-v6-5")
    ap.add_argument("--all-matched", action="store_true", help="Analyze all V6.4 matched ±15m events instead of the default 5 research targets")
    args = ap.parse_args()

    detail_path = Path(args.v6_4_detail)
    if not detail_path.exists():
        raise FileNotFoundError(detail_path)
    v64 = load_csv(detail_path)
    index = {(r["session_date"], r["known_direction"], r["signal_checkpoint"]): r for r in v64}

    if args.all_matched:
        targets = list(index)
    else:
        targets = DEFAULT_TARGETS

    minute_rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for ds, direction, cp in targets:
        meta = index.get((ds, direction, cp))
        if meta is None:
            raise RuntimeError(f"V6.4 target not found: {(ds, direction, cp)}")
        wings = int(meta["selected_wings"])
        positioning = Path(args.positioning_root) / ds / "positioning.json"
        session = load_session(positioning)
        rows = build_intrabar_rows(session, direction, meta["move_start_time"], cp, wings)
        minute_rows.extend(asdict(r) for r in rows)

        fail = first_minute(rows, "direction_failure")
        decay = first_minute(rows, "direction_decay")
        earliest_candidates = [r for r in (fail, decay) if r is not None]
        earliest = min(earliest_candidates, key=lambda r: r.minute_checkpoint) if earliest_candidates else None
        summaries.append({
            "session_date": ds,
            "known_direction": direction,
            "move_start_time": meta["move_start_time"],
            "signal_checkpoint": cp,
            "selected_wings": wings,
            "component_order_5m": meta.get("component_order"),
            "move_15m": _f(meta.get("move_15m")),
            "move_30m": _f(meta.get("move_30m")),
            "first_direction_failure_minute": fail.minute_checkpoint if fail else None,
            "first_direction_failure_ll_minutes": fail.minute_from_move_start if fail else None,
            "first_direction_decay_minute": decay.minute_checkpoint if decay else None,
            "first_direction_decay_ll_minutes": decay.minute_from_move_start if decay else None,
            "earliest_intrabar_component": (
                "FAILURE" if earliest is fail else "DECAY" if earliest is decay else None
            ),
            "earliest_intrabar_component_minute": earliest.minute_checkpoint if earliest else None,
            "earliest_intrabar_component_ll_minutes": earliest.minute_from_move_start if earliest else None,
            "signal_ll_minutes": float(meta.get("signal_lead_lag_minutes") or 0.0),
            "intrabar_lead_gain_minutes": (
                float(meta.get("signal_lead_lag_minutes") or 0.0) - earliest.minute_from_move_start
                if earliest else None
            ),
        })

    out = Path(args.output_dir)
    minute_fields = list(minute_rows[0].keys()) if minute_rows else []
    summary_fields = list(summaries[0].keys()) if summaries else []
    write_csv(out / "intrabar-minute-detail-v6-5.csv", minute_rows, minute_fields)
    write_csv(out / "intrabar-event-summary-v6-5.csv", summaries, summary_fields)

    json_doc = {
        "model": MODEL,
        "evaluation_only": True,
        "signal_logic_changed": False,
        "expiry_aware_baskets_changed": False,
        "minute_semantics": "Each minute checkpoint compares exact same signal-ATM physical basket at T vs T-1m; signal ATM is frozen for the critical 5m candle.",
        "default_targets": [list(x) for x in DEFAULT_TARGETS],
        "event_summaries": summaries,
    }
    (out / "intrabar-summary-v6-5.json").write_text(json.dumps(json_doc, indent=2, allow_nan=False) + "\n", encoding="utf-8")

    print(f"model={MODEL} targets={len(summaries)} minute_rows={len(minute_rows)}")
    print("\n=== INTRABAR 1-MINUTE ATTRIBUTION ===")
    by_key: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for r in minute_rows:
        by_key.setdefault((r["session_date"], r["known_direction"], r["signal_checkpoint"]), []).append(r)
    for s in summaries:
        key = (s["session_date"], s["known_direction"], s["signal_checkpoint"])
        print(
            f"\n{s['session_date']} {s['known_direction']} move={s['move_start_time']} "
            f"signal={s['signal_checkpoint']} wings=±{s['selected_wings']} "
            f"5m_order={s['component_order_5m']} +15={s['move_15m']} +30={s['move_30m']}"
        )
        print("MINUTE  LL  SPOTΔ1m  IMB1m     VEL1m     ACC1m     B/B  ATM      FAIL DECAY  CUM_SPOT CUM_IMB")
        for r in by_key.get(key, []):
            fmtm = lambda v: "—" if v is None else f"{float(v)/1_000_000:+.3f}M"
            print(
                f"{r['minute_checkpoint'][11:16]:>5} {r['minute_from_move_start']:+4.0f} "
                f"{r['spot_delta_1m']:+8.2f} {fmtm(r['imbalance_1m']):>9} "
                f"{fmtm(r['imbalance_velocity_1m']):>9} {fmtm(r['imbalance_acceleration_1m']):>9} "
                f"{r['bullish_strikes']}/{r['bearish_strikes']:<2} {r['atm_state']:<8} "
                f"{'Y' if r['direction_failure'] else '-':>4} {'Y' if r['direction_decay'] else '-':>5} "
                f"{r['cumulative_spot_from_candle_start']:+8.2f} {fmtm(r['cumulative_imbalance_from_candle_start']):>9}"
            )
        print(
            f"FIRST_FAILURE={s['first_direction_failure_minute']}({s['first_direction_failure_ll_minutes']}) "
            f"FIRST_DECAY={s['first_direction_decay_minute']}({s['first_direction_decay_ll_minutes']}) "
            f"EARLIEST={s['earliest_intrabar_component']} {s['earliest_intrabar_component_minute']} "
            f"({s['earliest_intrabar_component_ll_minutes']}) lead_gain={s['intrabar_lead_gain_minutes']}m"
        )

    gains = [s["intrabar_lead_gain_minutes"] for s in summaries if s["intrabar_lead_gain_minutes"] is not None]
    if gains:
        print("\n=== SUMMARY ===")
        print(f"events_with_intrabar_component={len(gains)}/{len(summaries)} median_lead_gain={statistics.median(gains)}m")
    print(f"DETAIL_CSV: {out / 'intrabar-minute-detail-v6-5.csv'}")
    print(f"SUMMARY_CSV: {out / 'intrabar-event-summary-v6-5.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
