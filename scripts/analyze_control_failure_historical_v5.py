from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

MODEL = "CONTROL_FAILURE_HISTORICAL_V5"
TZ = "+05:30"


def _f(v: Any) -> float | None:
    if v in (None, ""):
        return None
    return float(v)


def _state(imb: float) -> str:
    if imb > 0:
        return "BULLISH"
    if imb < 0:
        return "BEARISH"
    return "MIXED"


def _pct(n: int, d: int) -> float:
    return 0.0 if d == 0 else n / d * 100.0


def _directional_points(direction: str, start: float, end: float | None) -> float | None:
    if end is None:
        return None
    raw = end - start
    return raw if direction == "BULLISH" else -raw


def discover_positioning_files(root: Path, dates: list[str] | None, last_n: int | None) -> list[Path]:
    paths = sorted(root.glob("*/positioning.json"))
    if dates:
        wanted = set(dates)
        paths = [p for p in paths if p.parent.name in wanted]
    if last_n is not None:
        paths = paths[-last_n:]
    return paths


def load_session(path: Path) -> dict[str, Any]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    sessions = doc.get("sessions") or []
    if len(sessions) != 1:
        raise ValueError(f"{path}: expected exactly one session, found {len(sessions)}")
    s = sessions[0]
    if s.get("status") != "AVAILABLE":
        raise ValueError(f"{path}: session status is {s.get('status')!r}, expected AVAILABLE")
    return s


def _index_rows(session: dict[str, Any]) -> dict[datetime, dict[float, dict[str, Any]]]:
    out: dict[datetime, dict[float, dict[str, Any]]] = {}
    for r in session.get("rows") or []:
        ts = datetime.fromisoformat(str(r["timestamp"]))
        strike = float(r["strike"])
        out.setdefault(ts, {})
        if strike in out[ts]:
            raise ValueError(f"duplicate strike={strike} at {ts.isoformat()}")
        out[ts][strike] = r
    return out


def _exact_checkpoint_times(index: dict[datetime, dict[float, dict[str, Any]]]) -> list[datetime]:
    return [
        t for t in sorted(index)
        if t.minute % 5 == 0 and t.second == 0 and t.microsecond == 0
        and (t.hour > 9 or (t.hour == 9 and t.minute >= 20))
        and (t.hour < 15 or (t.hour == 15 and t.minute <= 25))
    ]


def _atm_spot(group: dict[float, dict[str, Any]], ts: datetime) -> tuple[float, float]:
    atms = {float(r["moving_atm"]) for r in group.values() if r.get("moving_atm") is not None}
    spots = {float(r["spot"]) for r in group.values() if r.get("spot") is not None}
    if len(atms) != 1 or len(spots) != 1:
        raise ValueError(f"ambiguous ATM/spot at {ts.isoformat()}: atms={sorted(atms)}, spots={sorted(spots)}")
    return next(iter(atms)), next(iter(spots))


def _leg_oi(group: dict[float, dict[str, Any]], strike: float, side: str, ts: datetime) -> float:
    r = group.get(strike)
    if r is None:
        raise ValueError(f"missing exact strike={strike} at {ts.isoformat()}")
    key = "ce_open_interest" if side == "CE" else "pe_open_interest"
    v = _f(r.get(key))
    if v is None:
        raise ValueError(f"missing {key} strike={strike} at {ts.isoformat()}")
    return v


@dataclass(frozen=True)
class CandleRow:
    session_date: str
    checkpoint: str
    candle_start: str
    candle_end: str
    spot: float
    spot_delta_5m: float | None
    moving_atm: float
    strikes: str
    ce_delta_total: float | None
    pe_delta_total: float | None
    imbalance: float | None
    imbalance_velocity: float | None
    imbalance_acceleration: float | None
    bullish_strikes: int
    bearish_strikes: int
    mixed_strikes: int
    bullish_breadth_pct: float
    atm_state: str
    oi_state: str
    failed_bearish_response: bool
    failed_bullish_response: bool
    bearish_decay: bool
    bullish_decay: bool


def build_candles(session: dict[str, Any], wings: int = 2) -> list[CandleRow]:
    session_date = str(session.get("session_date") or "")
    interval = float(session.get("strike_interval") or 50.0)
    idx = _index_rows(session)
    times = _exact_checkpoint_times(idx)
    prelim: list[dict[str, Any]] = []

    for t in times:
        prev = t - timedelta(minutes=5)
        cur_group = idx.get(t)
        prev_group = idx.get(prev)
        if cur_group is None:
            continue
        atm, spot = _atm_spot(cur_group, t)
        if prev_group is None:
            prelim.append({"t": t, "spot": spot, "atm": atm, "strikes": [atm + i * interval for i in range(-wings, wings + 1)], "complete": False})
            continue
        strikes = [atm + i * interval for i in range(-wings, wings + 1)]
        ce_total = pe_total = 0.0
        bull = bear = mixed = 0
        atm_state = "MIXED"
        for strike in strikes:
            ce_d = _leg_oi(cur_group, strike, "CE", t) - _leg_oi(prev_group, strike, "CE", prev)
            pe_d = _leg_oi(cur_group, strike, "PE", t) - _leg_oi(prev_group, strike, "PE", prev)
            ce_total += ce_d
            pe_total += pe_d
            imb = pe_d - ce_d
            st = _state(imb)
            if st == "BULLISH": bull += 1
            elif st == "BEARISH": bear += 1
            else: mixed += 1
            if strike == atm:
                atm_state = st
        prelim.append({
            "t": t, "spot": spot, "atm": atm, "strikes": strikes, "complete": True,
            "ce_delta_total": ce_total, "pe_delta_total": pe_total, "imbalance": pe_total - ce_total,
            "bull": bull, "bear": bear, "mixed": mixed, "atm_state": atm_state,
        })

    by_t = {r["t"]: r for r in prelim}
    out: list[CandleRow] = []
    for r in prelim:
        t = r["t"]
        prev_r = by_t.get(t - timedelta(minutes=5))
        prev2_r = by_t.get(t - timedelta(minutes=10))
        spot_delta = None if prev_r is None else r["spot"] - prev_r["spot"]
        imb = r.get("imbalance") if r.get("complete") else None
        velocity = None
        acceleration = None
        if imb is not None and prev_r and prev_r.get("imbalance") is not None:
            velocity = imb - prev_r["imbalance"]
        if velocity is not None and prev_r and prev2_r and prev_r.get("imbalance") is not None and prev2_r.get("imbalance") is not None:
            prev_velocity = prev_r["imbalance"] - prev2_r["imbalance"]
            acceleration = velocity - prev_velocity
        oi_state = "INCOMPLETE" if imb is None else _state(imb)
        failed_bear = bool(imb is not None and imb < 0 and spot_delta is not None and spot_delta > 0)
        failed_bull = bool(imb is not None and imb > 0 and spot_delta is not None and spot_delta < 0)
        bearish_decay = bool(imb is not None and imb < 0 and velocity is not None and velocity > 0 and acceleration is not None and acceleration > 0)
        bullish_decay = bool(imb is not None and imb > 0 and velocity is not None and velocity < 0 and acceleration is not None and acceleration < 0)
        strikes = r.get("strikes") or []
        out.append(CandleRow(
            session_date=session_date,
            checkpoint=t.isoformat(),
            candle_start=(t - timedelta(minutes=5)).isoformat(),
            candle_end=t.isoformat(),
            spot=r["spot"],
            spot_delta_5m=spot_delta,
            moving_atm=r["atm"],
            strikes=",".join(str(int(s) if float(s).is_integer() else s) for s in strikes),
            ce_delta_total=r.get("ce_delta_total"),
            pe_delta_total=r.get("pe_delta_total"),
            imbalance=imb,
            imbalance_velocity=velocity,
            imbalance_acceleration=acceleration,
            bullish_strikes=int(r.get("bull", 0)),
            bearish_strikes=int(r.get("bear", 0)),
            mixed_strikes=int(r.get("mixed", 0)),
            bullish_breadth_pct=_pct(int(r.get("bull", 0)), (2 * wings + 1)) if r.get("complete") else 0.0,
            atm_state=r.get("atm_state", "INCOMPLETE") if r.get("complete") else "INCOMPLETE",
            oi_state=oi_state,
            failed_bearish_response=failed_bear,
            failed_bullish_response=failed_bull,
            bearish_decay=bearish_decay,
            bullish_decay=bullish_decay,
        ))
    return out


@dataclass(frozen=True)
class EventRow:
    session_date: str
    direction: str
    detected_checkpoint: str
    detection_candle_start: str
    detection_candle_end: str
    component_order: str
    failure_checkpoint: str
    decay_checkpoint: str
    spot_at_detection: float
    imbalance: float | None
    imbalance_velocity: float | None
    imbalance_acceleration: float | None
    bullish_strikes: int
    bearish_strikes: int
    atm_state: str
    move_5m: float | None
    move_10m: float | None
    move_15m: float | None
    move_30m: float | None
    mfe_30m: float | None
    mae_30m: float | None
    atm_confirm_minutes: float | None
    breadth_2of5_confirm_minutes: float | None
    breadth_4of5_confirm_minutes: float | None


def _at(rows: dict[datetime, CandleRow], t: datetime) -> CandleRow | None:
    return rows.get(t)


def detect_events(candles: list[CandleRow], window_candles: int = 2) -> list[EventRow]:
    by_t = {datetime.fromisoformat(r.checkpoint): r for r in candles}
    times = sorted(by_t)
    events: list[EventRow] = []
    last_detection: dict[str, datetime | None] = {"BULLISH": None, "BEARISH": None}

    for t in times:
        recent_times = [t - timedelta(minutes=5 * i) for i in range(window_candles)]
        recent = [by_t[x] for x in reversed(recent_times) if x in by_t]
        if len(recent) < window_candles:
            continue
        for direction in ("BULLISH", "BEARISH"):
            if direction == "BULLISH":
                failures = [r for r in recent if r.failed_bearish_response]
                decays = [r for r in recent if r.bearish_decay]
            else:
                failures = [r for r in recent if r.failed_bullish_response]
                decays = [r for r in recent if r.bullish_decay]
            if not failures or not decays:
                continue
            detect_t = t
            last = last_detection[direction]
            if last is not None and detect_t - last <= timedelta(minutes=5):
                continue
            failure = failures[-1]
            decay = decays[-1]
            ft = datetime.fromisoformat(failure.checkpoint)
            dt = datetime.fromisoformat(decay.checkpoint)
            order = "SAME_CANDLE" if ft == dt else ("DECAY_THEN_FAILURE" if dt < ft else "FAILURE_THEN_DECAY")
            det = by_t[detect_t]

            def future(minutes: int) -> float | None:
                rr = _at(by_t, detect_t + timedelta(minutes=minutes))
                return _directional_points(direction, det.spot, None if rr is None else rr.spot)

            fwd_rows = [_at(by_t, detect_t + timedelta(minutes=m)) for m in (5, 10, 15, 20, 25, 30)]
            fwd_pts = [_directional_points(direction, det.spot, r.spot if r else None) for r in fwd_rows]
            valid = [x for x in fwd_pts if x is not None]
            mfe = max(valid) if valid else None
            mae = min(valid) if valid else None

            atm_confirm = breadth2 = breadth4 = None
            for mins in range(0, 31, 5):
                rr = _at(by_t, detect_t + timedelta(minutes=mins))
                if rr is None:
                    continue
                if direction == "BULLISH":
                    if atm_confirm is None and rr.atm_state == "BULLISH": atm_confirm = float(mins)
                    if breadth2 is None and rr.bullish_strikes >= 2: breadth2 = float(mins)
                    if breadth4 is None and rr.bullish_strikes >= 4: breadth4 = float(mins)
                else:
                    if atm_confirm is None and rr.atm_state == "BEARISH": atm_confirm = float(mins)
                    if breadth2 is None and rr.bearish_strikes >= 2: breadth2 = float(mins)
                    if breadth4 is None and rr.bearish_strikes >= 4: breadth4 = float(mins)

            events.append(EventRow(
                session_date=det.session_date,
                direction=direction,
                detected_checkpoint=det.checkpoint,
                detection_candle_start=det.candle_start,
                detection_candle_end=det.candle_end,
                component_order=order,
                failure_checkpoint=failure.checkpoint,
                decay_checkpoint=decay.checkpoint,
                spot_at_detection=det.spot,
                imbalance=det.imbalance,
                imbalance_velocity=det.imbalance_velocity,
                imbalance_acceleration=det.imbalance_acceleration,
                bullish_strikes=det.bullish_strikes,
                bearish_strikes=det.bearish_strikes,
                atm_state=det.atm_state,
                move_5m=future(5),
                move_10m=future(10),
                move_15m=future(15),
                move_30m=future(30),
                mfe_30m=mfe,
                mae_30m=mae,
                atm_confirm_minutes=atm_confirm,
                breadth_2of5_confirm_minutes=breadth2,
                breadth_4of5_confirm_minutes=breadth4,
            ))
            last_detection[direction] = detect_t
    return events


def _mean(vals: Iterable[float | None]) -> float | None:
    xs = [float(v) for v in vals if v is not None]
    return None if not xs else sum(xs) / len(xs)


def summarize(events: list[EventRow], sessions: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {"model": MODEL, "session_count": len(sessions), "sessions": sessions, "event_count": len(events), "by_direction": {}}
    for d in ("BULLISH", "BEARISH"):
        es = [e for e in events if e.direction == d]
        out["by_direction"][d] = {
            "events": len(es),
            "avg_move_5m": _mean(e.move_5m for e in es),
            "avg_move_10m": _mean(e.move_10m for e in es),
            "avg_move_15m": _mean(e.move_15m for e in es),
            "avg_move_30m": _mean(e.move_30m for e in es),
            "avg_mfe_30m": _mean(e.mfe_30m for e in es),
            "avg_mae_30m": _mean(e.mae_30m for e in es),
            "hit_ge_10pts_15m_pct": _pct(sum((e.move_15m or -1e99) >= 10 for e in es), sum(e.move_15m is not None for e in es)),
            "hit_ge_20pts_30m_pct": _pct(sum((e.move_30m or -1e99) >= 20 for e in es), sum(e.move_30m is not None for e in es)),
            "orders": {
                "DECAY_THEN_FAILURE": sum(e.component_order == "DECAY_THEN_FAILURE" for e in es),
                "FAILURE_THEN_DECAY": sum(e.component_order == "FAILURE_THEN_DECAY" for e in es),
                "SAME_CANDLE": sum(e.component_order == "SAME_CANDLE" for e in es),
            },
        }
    return out


def write_csv(path: Path, rows: list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    dicts = [asdict(r) for r in rows]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(dicts[0].keys()))
        w.writeheader(); w.writerows(dicts)


def main() -> None:
    ap = argparse.ArgumentParser(description="Historical two-candle OI control-failure attribution research")
    ap.add_argument("--build-root", default="data/historical-evidence/historical-oi-build")
    ap.add_argument("--dates", nargs="*")
    ap.add_argument("--last-n", type=int)
    ap.add_argument("--wings", type=int, default=2)
    ap.add_argument("--output-dir", default="data/historical-evidence/control-failure-v5")
    args = ap.parse_args()

    paths = discover_positioning_files(Path(args.build_root), args.dates, args.last_n)
    if not paths:
        raise SystemExit(f"No positioning.json files found under {args.build_root}")

    all_candles: list[CandleRow] = []
    all_events: list[EventRow] = []
    sessions: list[str] = []
    failures: list[dict[str, str]] = []
    for p in paths:
        try:
            s = load_session(p)
            date = str(s.get("session_date") or p.parent.name)
            candles = build_candles(s, wings=args.wings)
            events = detect_events(candles)
            sessions.append(date)
            all_candles.extend(candles)
            all_events.extend(events)
            print(f"{date}: candles={len(candles)} events={len(events)}")
        except Exception as exc:
            failures.append({"path": str(p), "error": str(exc)})
            print(f"{p.parent.name}: INCOMPLETE {exc}")

    outdir = Path(args.output_dir)
    write_csv(outdir / "control-failure-candles-v5.csv", all_candles)
    write_csv(outdir / "control-failure-events-v5.csv", all_events)
    summary = summarize(all_events, sessions)
    summary["failures"] = failures
    (outdir / "control-failure-summary-v5.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print(f"model={MODEL} successful_sessions={len(sessions)} failed_sessions={len(failures)} events={len(all_events)}")
    for d, s in summary["by_direction"].items():
        print(
            f"{d}: events={s['events']} avg+5={s['avg_move_5m']} avg+10={s['avg_move_10m']} "
            f"avg+15={s['avg_move_15m']} avg+30={s['avg_move_30m']} MFE30={s['avg_mfe_30m']} MAE30={s['avg_mae_30m']} "
            f"orders={s['orders']}"
        )
    print(f"EVENTS_CSV: {outdir / 'control-failure-events-v5.csv'}")
    print(f"CANDLES_CSV: {outdir / 'control-failure-candles-v5.csv'}")
    print(f"SUMMARY_JSON: {outdir / 'control-failure-summary-v5.json'}")


if __name__ == "__main__":
    main()
