from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from validate_control_failure_intrabar_v6_5 import (
    atm_spot,
    build_intrabar_rows,
    index_rows,
    load_session,
)

MODEL = "CONTROL_FAILURE_FULL_DAY_INTRABAR_FALSE_POSITIVE_V6_7"
VARIANTS = ("A", "B", "C", "D", "E")


def _f(v: Any) -> float | None:
    if v in (None, ""):
        return None
    return float(v)


def directional(direction: str, raw: float | None) -> float | None:
    if raw is None:
        return None
    return raw if direction == "BULLISH" else -raw


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys()) if rows else []
    with path.open("w", newline="", encoding="utf-8") as fh:
        if not fields:
            return
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def load_move_starts(path: Path) -> dict[str, str]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("research_version") != "TREND_DAY_MOVE_START_OI_REPLAY_V1":
        raise ValueError(f"Unexpected replay version: {doc.get('research_version')}")
    out: dict[str, str] = {}
    for r in doc.get("rows") or []:
        ds = str(r.get("session_date") or "")
        ms = r.get("move_start_time")
        if ds and ms:
            out.setdefault(ds, str(ms))
    return out


def resolve_move_dt(ds: str, move_start: str, reference: datetime) -> datetime:
    if "T" in move_start:
        return datetime.fromisoformat(move_start)
    off = reference.strftime("%z")
    off = f"{off[:3]}:{off[3:]}" if off else ""
    return datetime.fromisoformat(f"{ds}T{move_start}:00{off}")


def trigger_minute(rows, variant: str) -> int | None:
    """Return 1-based minute inside the 5m candle when a frozen variant first becomes causally true."""
    fails = [bool(r.direction_failure) for r in rows]
    fail_idx = [i for i, v in enumerate(fails) if v]
    if not fail_idx:
        return None
    first = fail_idx[0]

    if variant == "A":
        return first + 1
    if len(fail_idx) < 2:
        return None
    second = fail_idx[1]
    if variant == "B":
        return second + 1
    if variant == "C":
        return second + 1 if first <= 1 else None

    # D/E require direction-normalized net continuation over the two minutes
    # immediately after first failure. Those two minutes must actually exist.
    if first + 2 >= len(rows):
        return None
    next2 = 0.0
    for j in (first + 1, first + 2):
        v = directional(rows[j].known_direction, rows[j].spot_delta_1m)
        if v is None:
            return None
        next2 += v
    if next2 <= 0:
        return None
    causal_idx = max(second, first + 2)
    if variant == "D":
        return causal_idx + 1
    if variant == "E":
        return causal_idx + 1 if first <= 1 else None
    raise ValueError(variant)


def candidate_checkpoints(idx: dict[datetime, dict[float, dict[str, Any]]]) -> list[datetime]:
    times = sorted(idx)
    present = set(times)
    out = []
    for t in times:
        # Frozen non-overlapping 5m clock checkpoints; exact five 1m steps required.
        if t.minute % 5 != 0:
            continue
        if all(t - timedelta(minutes=i) in present for i in range(0, 6)):
            out.append(t)
    return out


def spot_at(idx, ts: datetime) -> float | None:
    group = idx.get(ts)
    if group is None:
        return None
    try:
        return atm_spot(group, ts)[1]
    except Exception:
        return None


def forward_metrics(idx, trigger: datetime, direction: str) -> dict[str, float | None]:
    s0 = spot_at(idx, trigger)
    if s0 is None:
        return {f"move_{m}m": None for m in (5, 10, 15, 30)} | {"mfe_30m": None, "mae_30m": None}
    result: dict[str, float | None] = {}
    for m in (5, 10, 15, 30):
        sx = spot_at(idx, trigger + timedelta(minutes=m))
        result[f"move_{m}m"] = directional(direction, None if sx is None else sx - s0)
    path: list[float] = []
    for m in range(1, 31):
        sx = spot_at(idx, trigger + timedelta(minutes=m))
        if sx is not None:
            dv = directional(direction, sx - s0)
            if dv is not None:
                path.append(dv)
    result["mfe_30m"] = max(path) if path else None
    result["mae_30m"] = min(path) if path else None
    return result


def median(xs: list[float]) -> float | None:
    return float(statistics.median(xs)) if xs else None


def mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def summarize(cands: list[dict[str, Any]], variant: str, direction: str, session_count: int) -> dict[str, Any]:
    xs = [r for r in cands if r["variant"] == variant and r["direction"] == direction]
    def vals(k: str) -> list[float]:
        return [float(r[k]) for r in xs if r.get(k) is not None]
    def hit(k: str) -> float | None:
        ys = vals(k)
        return 100.0 * sum(v > 0 for v in ys) / len(ys) if ys else None
    near_same = [r for r in xs if r.get("near_known_move_start_same_direction")]
    return {
        "variant": variant,
        "direction": direction,
        "events": len(xs),
        "sessions_with_signal": len({r["session_date"] for r in xs}),
        "signals_per_session": len(xs) / session_count if session_count else None,
        "near_known_move_start_same_direction": len(near_same),
        "near_known_move_start_rate_pct": 100.0 * len(near_same) / len(xs) if xs else None,
        "median_5m": median(vals("move_5m")),
        "median_10m": median(vals("move_10m")),
        "median_15m": median(vals("move_15m")),
        "median_30m": median(vals("move_30m")),
        "mean_5m": mean(vals("move_5m")),
        "mean_10m": mean(vals("move_10m")),
        "mean_15m": mean(vals("move_15m")),
        "mean_30m": mean(vals("move_30m")),
        "hit_5m_pct": hit("move_5m"),
        "hit_10m_pct": hit("move_10m"),
        "hit_15m_pct": hit("move_15m"),
        "hit_30m_pct": hit("move_30m"),
        "median_mfe_30m": median(vals("mfe_30m")),
        "median_mae_30m": median(vals("mae_30m")),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inventory", default="data/historical-evidence/control-failure-expiry-aware-v6-2/expiry-aware-inventory-v6-2.csv")
    ap.add_argument("--positioning-root", default="data/historical-evidence/historical-oi-build")
    ap.add_argument("--move-start-replay", default="data/historical-evidence/trend-day-move-start-oi-replay-v1.json")
    ap.add_argument("--output-dir", default="data/historical-evidence/control-failure-full-day-intrabar-v6-7")
    args = ap.parse_args()

    inventory_path = Path(args.inventory)
    replay_path = Path(args.move_start_replay)
    if not inventory_path.exists():
        raise FileNotFoundError(inventory_path)
    if not replay_path.exists():
        raise FileNotFoundError(replay_path)

    inventory = load_csv(inventory_path)
    available = [r for r in inventory if r.get("status") == "AVAILABLE" and r.get("selected_wings") not in (None, "")]
    unavailable = [r for r in inventory if r not in available]
    move_starts = load_move_starts(replay_path)

    candidates: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    scanned_candles = 0

    for inv in available:
        ds = inv["session_date"]
        wings = int(inv["selected_wings"])
        known_direction = inv.get("known_direction")
        p = Path(args.positioning_root) / ds / "positioning.json"
        try:
            session = load_session(p)
            idx = index_rows(session)
        except Exception as exc:
            errors.append({"session_date": ds, "checkpoint": None, "error": f"SESSION:{type(exc).__name__}:{exc}"})
            continue

        cps = candidate_checkpoints(idx)
        scanned_candles += len(cps)
        for cp in cps:
            for direction in ("BULLISH", "BEARISH"):
                try:
                    # move_start is only a timestamp anchor required by the V6.5 helper;
                    # it is NOT used to construct failures/decays here.
                    rows = build_intrabar_rows(session, direction, cp.isoformat(), cp.isoformat(), wings)
                except Exception as exc:
                    errors.append({"session_date": ds, "checkpoint": cp.isoformat(), "direction": direction, "error": f"CANDLE:{type(exc).__name__}:{exc}"})
                    continue

                fail_count = sum(bool(r.direction_failure) for r in rows)
                if fail_count == 0:
                    continue
                first_fail = next(i + 1 for i, r in enumerate(rows) if r.direction_failure)
                max_consec = 0
                cur = 0
                for r in rows:
                    if r.direction_failure:
                        cur += 1
                        max_consec = max(max_consec, cur)
                    else:
                        cur = 0
                decay_count = sum(bool(r.direction_decay) for r in rows)

                for variant in VARIANTS:
                    tm = trigger_minute(rows, variant)
                    if tm is None:
                        continue
                    trigger = cp - timedelta(minutes=5) + timedelta(minutes=tm)
                    metrics = forward_metrics(idx, trigger, direction)
                    ms = move_starts.get(ds)
                    near = False
                    ll = None
                    if ms and known_direction == direction:
                        move_dt = resolve_move_dt(ds, ms, trigger)
                        ll = (trigger - move_dt).total_seconds() / 60.0
                        near = abs(ll) <= 15.0
                    candidates.append({
                        "session_date": ds,
                        "known_session_direction": known_direction,
                        "direction": direction,
                        "selected_wings": wings,
                        "five_minute_checkpoint": cp.isoformat(),
                        "variant": variant,
                        "trigger_minute_from_candle_start": tm,
                        "trigger_time": trigger.isoformat(),
                        "failure_count_5m": fail_count,
                        "max_consecutive_failure_count": max_consec,
                        "first_failure_minute": first_fail,
                        "decay_count_5m": decay_count,
                        "known_move_start": ms,
                        "lead_lag_to_known_move_start": ll,
                        "near_known_move_start_same_direction": near,
                        **metrics,
                    })

    summaries = [summarize(candidates, v, d, len(available)) for v in VARIANTS for d in ("BULLISH", "BEARISH")]
    out = Path(args.output_dir)
    write_csv(out / "full-day-intrabar-candidates-v6-7.csv", candidates)
    write_csv(out / "full-day-intrabar-summary-v6-7.csv", summaries)
    write_csv(out / "full-day-intrabar-errors-v6-7.csv", errors)

    doc = {
        "model": MODEL,
        "research_only": True,
        "threshold_optimization_performed": False,
        "available_sessions": len(available),
        "unavailable_sessions": len(unavailable),
        "available_dates": [r["session_date"] for r in available],
        "unavailable_dates": [r["session_date"] for r in unavailable],
        "scanned_5m_candles": scanned_candles,
        "candidate_rows": len(candidates),
        "variants": {
            "A": ">=1 direction-control failure; trigger at first failure minute",
            "B": ">=2 direction-control failures; trigger at second failure minute",
            "C": ">=2 failures AND first failure <= minute 2; trigger at second failure minute",
            "D": ">=2 failures AND direction-normalized next-2m continuation after first failure > 0; trigger only once both second failure and 2m continuation are observable",
            "E": "D plus first failure <= minute 2",
        },
        "proximity_definition": "Candidate direction must equal frozen session direction and causal trigger must be within +/-15m of retrospective move start.",
        "summary": summaries,
        "errors": errors,
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "full-day-intrabar-summary-v6-7.json").write_text(json.dumps(doc, indent=2, allow_nan=False) + "\n", encoding="utf-8")

    print(f"model={MODEL} available_sessions={len(available)} unavailable_sessions={len(unavailable)} scanned_5m_candles={scanned_candles} candidate_rows={len(candidates)} errors={len(errors)}")
    if unavailable:
        print("UNAVAILABLE_DATES=" + " ".join(r["session_date"] for r in unavailable))
    print("\n=== FROZEN FULL-DAY VARIANT SUMMARY ===")
    for r in summaries:
        print(
            f"{r['variant']} {r['direction']}: events={r['events']} sessions={r['sessions_with_signal']} "
            f"sig/session={r['signals_per_session']:.2f} near_move={r['near_known_move_start_same_direction']} "
            f"near_rate={r['near_known_move_start_rate_pct']}% med5={r['median_5m']} med10={r['median_10m']} "
            f"med15={r['median_15m']} med30={r['median_30m']} hit15={r['hit_15m_pct']}% hit30={r['hit_30m_pct']}% "
            f"MFE30={r['median_mfe_30m']} MAE30={r['median_mae_30m']}"
        )
    print(f"CANDIDATES_CSV: {out / 'full-day-intrabar-candidates-v6-7.csv'}")
    print(f"SUMMARY_CSV: {out / 'full-day-intrabar-summary-v6-7.csv'}")
    print(f"ERRORS_CSV: {out / 'full-day-intrabar-errors-v6-7.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
