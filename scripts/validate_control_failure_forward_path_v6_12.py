from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

MODEL = "CONTROL_FAILURE_FORWARD_PATH_EXIT_OPPORTUNITY_V6_12"
PRIMARY_VARIANT = "A"
RANK_CUTS = (0.05, 0.10, 0.20)
HORIZONS = (5, 10, 15, 20, 30)


def _f(v: Any) -> float | None:
    if v in (None, "", "None"):
        return None
    try:
        return float(v)
    except Exception:
        return None


def median(xs: list[float]) -> float | None:
    return float(statistics.median(xs)) if xs else None


def mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def direction_sign(direction: str) -> int:
    if direction == "BULLISH":
        return 1
    if direction == "BEARISH":
        return -1
    raise ValueError(direction)


def load_spot_index(positioning_path: Path) -> dict[datetime, float]:
    doc = json.loads(positioning_path.read_text(encoding="utf-8"))
    sessions = doc.get("sessions") or []
    if len(sessions) != 1:
        raise ValueError(f"{positioning_path}: expected one session, got {len(sessions)}")
    s = sessions[0]
    if s.get("status") != "AVAILABLE":
        raise ValueError(f"{positioning_path}: session not AVAILABLE")
    idx: dict[datetime, float] = {}
    for r in s.get("rows") or []:
        if r.get("timestamp") is None or r.get("spot") is None:
            continue
        t = datetime.fromisoformat(str(r["timestamp"]))
        spot = float(r["spot"])
        if t in idx and idx[t] != spot:
            raise ValueError(f"ambiguous spot at {t.isoformat()}")
        idx[t] = spot
    return idx


def exact_directional_path(
    spot_idx: dict[datetime, float], trigger: datetime, direction: str, minutes: int = 30
) -> list[float]:
    if trigger not in spot_idx:
        raise ValueError(f"missing exact trigger spot {trigger.isoformat()}")
    s0 = spot_idx[trigger]
    sign = direction_sign(direction)
    path: list[float] = []
    for m in range(1, minutes + 1):
        t = trigger + timedelta(minutes=m)
        if t not in spot_idx:
            raise ValueError(f"missing exact forward minute {t.isoformat()}")
        path.append(sign * (spot_idx[t] - s0))
    return path


def first_extreme_minute(path: list[float], mode: str) -> int:
    if not path:
        raise ValueError("empty path")
    target = max(path) if mode == "max" else min(path)
    return path.index(target) + 1


def path_metrics(path: list[float]) -> dict[str, float | int | bool]:
    if len(path) < 30:
        raise ValueError("V6.12 requires exact full 30-minute path")
    mfe = max(path[:30])
    mae = min(path[:30])
    t_mfe = first_extreme_minute(path[:30], "max")
    t_mae = first_extreme_minute(path[:30], "min")
    adverse_before_mfe = min([0.0] + path[:t_mfe])
    favorable_before_mae = max([0.0] + path[:t_mae])
    out: dict[str, float | int | bool] = {
        "mfe_30m_path": mfe,
        "mae_30m_path": mae,
        "time_to_mfe_min": t_mfe,
        "time_to_mae_min": t_mae,
        "mfe_before_mae": t_mfe < t_mae,
        "mae_before_mfe": t_mae < t_mfe,
        "adverse_before_mfe": adverse_before_mfe,
        "favorable_before_mae": favorable_before_mae,
        "move_15m_path": path[14],
        "move_30m_path": path[29],
        "giveback_mfe_to_15m": mfe - path[14],
        "giveback_mfe_to_30m": mfe - path[29],
    }
    for h in HORIZONS:
        seg = path[:h]
        out[f"mfe_{h}m_path"] = max(seg)
        out[f"mae_{h}m_path"] = min(seg)
    return out


def assign_fold_rank_percentiles(rows: list[dict[str, Any]], variant: str = PRIMARY_VARIANT) -> None:
    by_session: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        if r.get("variant") != variant or _f(r.get("score")) is None:
            continue
        by_session.setdefault(str(r["session_date"]), []).append(r)
    for xs in by_session.values():
        xs.sort(key=lambda r: float(r["score"]), reverse=True)
        n = len(xs)
        for i, r in enumerate(xs, start=1):
            r["fold_rank"] = i
            r["fold_rows"] = n
            r["fold_rank_fraction"] = i / n
            r["in_top5_fold"] = i <= max(1, math.ceil(n * 0.05))
            r["in_top10_fold"] = i <= max(1, math.ceil(n * 0.10))
            r["in_top20_fold"] = i <= max(1, math.ceil(n * 0.20))


def summarize(rows: list[dict[str, Any]], label: str) -> dict[str, Any]:
    def vals(key: str) -> list[float]:
        return [float(v) for r in rows if (v := _f(r.get(key))) is not None]

    out: dict[str, Any] = {"group": label, "events": len(rows), "sessions": len({r["session_date"] for r in rows})}
    for key in (
        "mfe_30m_path", "mae_30m_path", "time_to_mfe_min", "time_to_mae_min",
        "adverse_before_mfe", "giveback_mfe_to_15m", "giveback_mfe_to_30m",
        "move_15m_path", "move_30m_path",
    ):
        x = vals(key)
        out[f"median_{key}"] = median(x)
        out[f"mean_{key}"] = mean(x)
    if rows:
        out["mfe_before_mae_pct"] = 100.0 * sum(bool(r.get("mfe_before_mae")) for r in rows) / len(rows)
        out["mae_before_mfe_pct"] = 100.0 * sum(bool(r.get("mae_before_mfe")) for r in rows) / len(rows)
    else:
        out["mfe_before_mae_pct"] = None
        out["mae_before_mfe_pct"] = None
    for h in HORIZONS:
        x = vals(f"mfe_{h}m_path")
        y = vals(f"mae_{h}m_path")
        out[f"median_mfe_{h}m"] = median(x)
        out[f"median_mae_{h}m"] = median(y)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--scored",
        default="data/historical-evidence/control-failure-forward-outcome-v6-11/forward-outcome-scored-candidates-v6-11.csv",
    )
    ap.add_argument("--positioning-root", default="data/historical-evidence/historical-oi-build")
    ap.add_argument("--output-dir", default="data/historical-evidence/control-failure-forward-path-v6-12")
    args = ap.parse_args()

    scored_path = Path(args.scored)
    if not scored_path.exists():
        raise FileNotFoundError(scored_path)
    rows: list[dict[str, Any]] = [dict(r) for r in load_csv(scored_path)]
    primary = [r for r in rows if r.get("variant") == PRIMARY_VARIANT and _f(r.get("score")) is not None]
    assign_fold_rank_percentiles(primary, PRIMARY_VARIANT)

    spot_cache: dict[str, dict[datetime, float]] = {}
    enriched: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for r in primary:
        ds = str(r["session_date"])
        try:
            if ds not in spot_cache:
                p = Path(args.positioning_root) / ds / "positioning.json"
                spot_cache[ds] = load_spot_index(p)
            trigger = datetime.fromisoformat(str(r["trigger_time"]))
            path = exact_directional_path(spot_cache[ds], trigger, str(r["direction"]), 30)
            rr = dict(r)
            rr.update(path_metrics(path))
            rr["path_complete_30m"] = True
            enriched.append(rr)
        except Exception as exc:
            errors.append({
                "session_date": ds,
                "variant": r.get("variant"),
                "direction": r.get("direction"),
                "trigger_time": r.get("trigger_time"),
                "score": r.get("score"),
                "error": str(exc),
            })

    groups: list[tuple[str, list[dict[str, Any]]]] = [("ALL_PRIMARY_A", enriched)]
    for cut in (5, 10, 20):
        groups.append((f"TOP{cut}_FOLD", [r for r in enriched if bool(r.get(f"in_top{cut}_fold"))]))
    # Bottom half is descriptive comparator, still determined only by the fold's causal score ranking.
    groups.append(("BOTTOM50_FOLD", [r for r in enriched if _f(r.get("fold_rank_fraction")) is not None and float(r["fold_rank_fraction"]) > 0.50]))
    summaries = [summarize(xs, label) for label, xs in groups]

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "forward-path-candidates-v6-12.csv", enriched)
    write_csv(out / "forward-path-summary-v6-12.csv", summaries)
    write_csv(out / "forward-path-errors-v6-12.csv", errors)
    (out / "forward-path-summary-v6-12.json").write_text(json.dumps({
        "model": MODEL,
        "primary_variant": PRIMARY_VARIANT,
        "source": str(scored_path),
        "selection": "fold-local fixed score ranks learned chronologically in V6.11",
        "exact_full_30m_path_required": True,
        "input_primary_rows": len(primary),
        "complete_path_rows": len(enriched),
        "errors": len(errors),
        "summary": summaries,
    }, indent=2, allow_nan=False) + "\n", encoding="utf-8")

    print(f"model={MODEL} primary_variant=A input_rows={len(primary)} complete_30m_paths={len(enriched)} errors={len(errors)}")
    print("\n=== FORWARD PATH / EXIT OPPORTUNITY ===")
    for s in summaries:
        print(
            f"{s['group']}: events={s['events']} sessions={s['sessions']} "
            f"MFE30={s['median_mfe_30m_path']} MAE30={s['median_mae_30m_path']} "
            f"tMFE={s['median_time_to_mfe_min']} tMAE={s['median_time_to_mae_min']} "
            f"adv_before_MFE={s['median_adverse_before_mfe']} "
            f"MFE_before_MAE={s['mfe_before_mae_pct']}% "
            f"giveback15={s['median_giveback_mfe_to_15m']} giveback30={s['median_giveback_mfe_to_30m']} "
            f"med15={s['median_move_15m_path']} med30={s['median_move_30m_path']}"
        )
    print("\nNo exit rule is selected by V6.12; this is path attribution only.")
    print(f"DETAIL_CSV: {out/'forward-path-candidates-v6-12.csv'}")
    print(f"SUMMARY_CSV: {out/'forward-path-summary-v6-12.csv'}")
    print(f"ERRORS_CSV: {out/'forward-path-errors-v6-12.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
