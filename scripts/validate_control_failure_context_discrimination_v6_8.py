from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from validate_control_failure_intrabar_v6_5 import atm_spot, index_rows, leg_oi, load_session

MODEL = "CONTROL_FAILURE_CONTEXT_DISCRIMINATION_V6_8"
HORIZONS = (5, 10, 15)
NUMERIC_FEATURES = (
    "spot_trend_5m", "spot_trend_10m", "spot_trend_15m",
    "pcr_current", "pcr_change_5m", "pcr_change_10m", "pcr_change_15m",
    "imbalance_5m", "imbalance_10m", "imbalance_15m",
    "imbalance_velocity_5m", "imbalance_acceleration_5m",
    "ce_delta_5m", "pe_delta_5m", "ce_delta_10m", "pe_delta_10m", "ce_delta_15m", "pe_delta_15m",
    "bullish_breadth_1m_pct", "breadth_change_1m_pct",
    "minutes_since_open",
    "failure_count_5m", "max_consecutive_failure_count", "first_failure_minute", "decay_count_5m",
)


def _f(v: Any) -> float | None:
    if v in (None, ""):
        return None
    return float(v)


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)


def pcr(pe: float, ce: float) -> float | None:
    return None if ce == 0 else pe / ce


def state(v: float) -> str:
    return "BULLISH" if v > 0 else "BEARISH" if v < 0 else "MIXED"


def directional_support(direction: str, atm_state: str) -> bool:
    return atm_state == direction


def time_bucket(ts: datetime) -> str:
    m = ts.hour * 60 + ts.minute
    if m < 10 * 60 + 30:
        return "OPEN_0915_1029"
    if m < 12 * 60:
        return "MORNING_1030_1159"
    if m < 14 * 60:
        return "MIDDAY_1200_1359"
    return "LATE_1400_CLOSE"


def minutes_since_open(ts: datetime) -> int:
    return ts.hour * 60 + ts.minute - (9 * 60 + 15)


def exact_totals(idx, ts: datetime, strikes: list[float]) -> tuple[float, float, float]:
    group = idx.get(ts)
    if group is None:
        raise ValueError(f"missing exact timestamp={ts.isoformat()}")
    _, spot = atm_spot(group, ts)
    ce = sum(leg_oi(group, s, "CE", ts) for s in strikes)
    pe = sum(leg_oi(group, s, "PE", ts) for s in strikes)
    return ce, pe, spot


def one_minute_breadth(idx, ts: datetime, strikes: list[float], atm: float) -> tuple[int, int, int, str]:
    cur = idx.get(ts); prev = idx.get(ts - timedelta(minutes=1))
    if cur is None or prev is None:
        raise ValueError(f"missing exact 1m context around {ts.isoformat()}")
    bull = bear = mixed = 0
    atm_state = "MIXED"
    for s in strikes:
        ce_d = leg_oi(cur, s, "CE", ts) - leg_oi(prev, s, "CE", ts - timedelta(minutes=1))
        pe_d = leg_oi(cur, s, "PE", ts) - leg_oi(prev, s, "PE", ts - timedelta(minutes=1))
        st = state(pe_d - ce_d)
        bull += st == "BULLISH"; bear += st == "BEARISH"; mixed += st == "MIXED"
        if s == atm:
            atm_state = st
    return int(bull), int(bear), int(mixed), atm_state


def build_pretrigger_context(session: dict[str, Any], trigger: datetime, wings: int) -> dict[str, Any]:
    """Build context strictly at trigger-1m or earlier; no trigger-minute data is used."""
    idx = index_rows(session)
    ctx = trigger - timedelta(minutes=1)
    group = idx.get(ctx)
    if group is None:
        raise ValueError(f"missing pre-trigger context timestamp={ctx.isoformat()}")
    atm, spot = atm_spot(group, ctx)
    interval = float(session.get("strike_interval") or 50.0)
    strikes = [atm + i * interval for i in range(-wings, wings + 1)]

    ce0, pe0, _ = exact_totals(idx, ctx, strikes)
    out: dict[str, Any] = {
        "context_time": ctx.isoformat(),
        "context_atm": atm,
        "context_spot": spot,
        "pcr_current": pcr(pe0, ce0),
        "time_bucket": time_bucket(ctx),
        "minutes_since_open": minutes_since_open(ctx),
    }

    for h in HORIZONS:
        prev_t = ctx - timedelta(minutes=h)
        cep, pep, sp = exact_totals(idx, prev_t, strikes)
        ce_d = ce0 - cep; pe_d = pe0 - pep
        out[f"spot_trend_{h}m"] = spot - sp
        out[f"ce_delta_{h}m"] = ce_d
        out[f"pe_delta_{h}m"] = pe_d
        out[f"imbalance_{h}m"] = pe_d - ce_d
        pp = pcr(pep, cep)
        out[f"pcr_prior_{h}m"] = pp
        out[f"pcr_change_{h}m"] = None if out["pcr_current"] is None or pp is None else out["pcr_current"] - pp

    # 5m imbalance velocity / acceleration, all on the same exact physical strikes.
    def imb5(end: datetime) -> float:
        ce_e, pe_e, _ = exact_totals(idx, end, strikes)
        ce_s, pe_s, _ = exact_totals(idx, end - timedelta(minutes=5), strikes)
        return (pe_e - pe_s) - (ce_e - ce_s)

    i0 = imb5(ctx); i1 = imb5(ctx - timedelta(minutes=5)); i2 = imb5(ctx - timedelta(minutes=10))
    v0 = i0 - i1; v1 = i1 - i2
    out["imbalance_velocity_5m"] = v0
    out["imbalance_acceleration_5m"] = v0 - v1

    bull, bear, mixed, atm_state = one_minute_breadth(idx, ctx, strikes, atm)
    pbull, _, _, _ = one_minute_breadth(idx, ctx - timedelta(minutes=1), strikes, atm)
    denom = len(strikes)
    out.update({
        "bullish_strikes_1m": bull,
        "bearish_strikes_1m": bear,
        "mixed_strikes_1m": mixed,
        "bullish_breadth_1m_pct": 100.0 * bull / denom,
        "breadth_change_1m_pct": 100.0 * (bull - pbull) / denom,
        "atm_state_1m": atm_state,
    })
    return out


def median(xs: list[float]) -> float | None:
    return float(statistics.median(xs)) if xs else None


def mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def compare_numeric(rows: list[dict[str, Any]], variant: str, direction: str, feature: str) -> dict[str, Any]:
    base = [r for r in rows if r["variant"] == variant and r["direction"] == direction]
    near = [_f(r.get(feature)) for r in base if r["population"] == "NEAR_MOVE"]
    far = [_f(r.get(feature)) for r in base if r["population"] == "NON_MOVE"]
    near = [x for x in near if x is not None]; far = [x for x in far if x is not None]
    mn, mf = median(near), median(far)
    # Scale-free descriptive separation: median difference divided by pooled MAD.
    pooled = near + far
    medp = median(pooled)
    mad = median([abs(x - medp) for x in pooled]) if medp is not None else None
    sep = None if mn is None or mf is None or mad in (None, 0) else (mn - mf) / mad
    return {
        "variant": variant, "direction": direction, "feature": feature,
        "near_n": len(near), "non_move_n": len(far),
        "near_median": mn, "non_move_median": mf,
        "median_difference": None if mn is None or mf is None else mn - mf,
        "near_mean": mean(near), "non_move_mean": mean(far),
        "robust_separation_mad_units": sep,
    }


def categorical_summary(rows: list[dict[str, Any]], variant: str, direction: str, feature: str) -> list[dict[str, Any]]:
    base = [r for r in rows if r["variant"] == variant and r["direction"] == direction]
    out = []
    for pop in ("NEAR_MOVE", "NON_MOVE"):
        xs = [str(r.get(feature)) for r in base if r["population"] == pop and r.get(feature) not in (None, "")]
        c = Counter(xs)
        for value, n in sorted(c.items()):
            out.append({"variant": variant, "direction": direction, "population": pop, "feature": feature, "value": value, "count": n, "rate_pct": 100.0*n/len(xs) if xs else None})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", default="data/historical-evidence/control-failure-full-day-intrabar-v6-7/full-day-intrabar-candidates-v6-7.csv")
    ap.add_argument("--inventory", default="data/historical-evidence/control-failure-expiry-aware-v6-2/expiry-aware-inventory-v6-2.csv")
    ap.add_argument("--positioning-root", default="data/historical-evidence/historical-oi-build")
    ap.add_argument("--output-dir", default="data/historical-evidence/control-failure-context-discrimination-v6-8")
    args = ap.parse_args()

    cpath = Path(args.candidates); ipath = Path(args.inventory)
    if not cpath.exists(): raise FileNotFoundError(cpath)
    if not ipath.exists(): raise FileNotFoundError(ipath)
    candidates = load_csv(cpath); inventory = load_csv(ipath)
    inv_by_date = {r["session_date"]: r for r in inventory}
    session_cache: dict[str, dict[str, Any]] = {}
    enriched: list[dict[str, Any]] = []; errors: list[dict[str, Any]] = []

    for c in candidates:
        ds = c["session_date"]
        try:
            inv = inv_by_date[ds]
            wings = int(inv["selected_wings"])
            if ds not in session_cache:
                session_cache[ds] = load_session(Path(args.positioning_root) / ds / "positioning.json")
            trigger = datetime.fromisoformat(c["trigger_time"])
            ctx = build_pretrigger_context(session_cache[ds], trigger, wings)
            known_dir = c.get("known_session_direction")
            near = str(c.get("near_known_move_start_same_direction", "")).lower() == "true"
            population = "NEAR_MOVE" if near else "NON_MOVE"
            # Same-direction near-move is already frozen by V6.7. Everything else is negative-control population.
            row: dict[str, Any] = dict(c)
            row.update(ctx)
            row["population"] = population
            row["context_atm_supports_candidate"] = directional_support(c["direction"], ctx["atm_state_1m"])
            row["context_oi_5m_supports_candidate"] = state(ctx["imbalance_5m"]) == c["direction"]
            row["context_spot_5m_supports_candidate"] = (ctx["spot_trend_5m"] > 0 if c["direction"] == "BULLISH" else ctx["spot_trend_5m"] < 0)
            row["expiry_sessions_left"] = inv.get("sessions_to_expiry") or inv.get("sessions_left")
            enriched.append(row)
        except Exception as exc:
            errors.append({"session_date": ds, "variant": c.get("variant"), "direction": c.get("direction"), "trigger_time": c.get("trigger_time"), "error": f"{type(exc).__name__}:{exc}"})

    variants = sorted({r["variant"] for r in enriched})
    comparisons = [compare_numeric(enriched, v, d, f) for v in variants for d in ("BULLISH", "BEARISH") for f in NUMERIC_FEATURES]
    categorical: list[dict[str, Any]] = []
    for v in variants:
        for d in ("BULLISH", "BEARISH"):
            for f in ("time_bucket", "atm_state_1m", "context_atm_supports_candidate", "context_oi_5m_supports_candidate", "context_spot_5m_supports_candidate", "selected_wings"):
                categorical.extend(categorical_summary(enriched, v, d, f))

    # Rank only by absolute robust separation for discovery; this is descriptive, not a selected rule.
    ranked = sorted([r for r in comparisons if r["robust_separation_mad_units"] is not None], key=lambda r: abs(float(r["robust_separation_mad_units"])), reverse=True)

    out = Path(args.output_dir); out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "context-enriched-candidates-v6-8.csv", enriched)
    write_csv(out / "context-numeric-comparison-v6-8.csv", comparisons)
    write_csv(out / "context-categorical-comparison-v6-8.csv", categorical)
    write_csv(out / "context-errors-v6-8.csv", errors)
    doc = {
        "model": MODEL, "research_only": True, "threshold_optimization_performed": False,
        "pretrigger_context_definition": "All contextual features are computed at trigger_time - 1 minute or earlier using exact timestamps and exact physical strikes.",
        "population_definition": {"NEAR_MOVE": "V6.7 same-direction candidate within +/-15m of retrospective move start", "NON_MOVE": "all other full-day candidates"},
        "candidate_rows": len(candidates), "enriched_rows": len(enriched), "errors": errors,
        "top_descriptive_numeric_separations": ranked[:30],
    }
    (out / "context-discrimination-summary-v6-8.json").write_text(json.dumps(doc, indent=2, allow_nan=False) + "\n", encoding="utf-8")

    print(f"model={MODEL} input_candidates={len(candidates)} enriched={len(enriched)} errors={len(errors)} sessions={len(session_cache)}")
    print("\n=== PRE-TRIGGER CONTEXT DISCRIMINATION: TOP DESCRIPTIVE SEPARATIONS ===")
    for r in ranked[:24]:
        print(f"{r['variant']} {r['direction']} {r['feature']}: near_n={r['near_n']} non_n={r['non_move_n']} near_med={r['near_median']} non_med={r['non_move_median']} diff={r['median_difference']} robust_sep={r['robust_separation_mad_units']}")
    print("\nNo threshold or live rule is selected by V6.8; this is context discovery only.")
    print(f"ENRICHED_CSV: {out / 'context-enriched-candidates-v6-8.csv'}")
    print(f"NUMERIC_CSV: {out / 'context-numeric-comparison-v6-8.csv'}")
    print(f"CATEGORICAL_CSV: {out / 'context-categorical-comparison-v6-8.csv'}")
    print(f"ERRORS_CSV: {out / 'context-errors-v6-8.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
