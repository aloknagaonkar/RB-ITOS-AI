from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

MODEL = "NIFTY_OI_MOVEMENT_MAGNITUDE_ATTRIBUTION_V1"

DEFAULT_ENRICHMENT_ROOT = Path(
    "data/historical-evidence/historical-oi-enrichment"
)
DEFAULT_CANONICAL_COVERAGE = Path(
    "data/historical-evidence/historical-oi-enrichment/canonical-90-coverage-v1.json"
)
DEFAULT_OUTPUT_JSON = Path(
    "data/historical-evidence/nifty-oi-movement-magnitude-attribution-v1.json"
)
DEFAULT_OUTPUT_CSV = Path(
    "data/historical-evidence/nifty-oi-movement-magnitude-attribution-v1.csv"
)
DEFAULT_CHECKPOINT_CSV = Path(
    "data/historical-evidence/nifty-oi-movement-magnitude-attribution-checkpoints-v1.csv"
)

FORWARD_HORIZONS = (5, 10, 15)
OI_LOOKBACKS = (5, 10, 15)
MOVE_THRESHOLDS = tuple(range(10, 101, 10))


def _f(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return xs[lo]
    frac = pos - lo
    return xs[lo] * (1.0 - frac) + xs[hi] * frac


def _stats(values: Iterable[float]) -> dict[str, Any]:
    xs = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    if not xs:
        return {
            "n": 0,
            "min": None,
            "p10": None,
            "p25": None,
            "median": None,
            "p75": None,
            "p90": None,
            "max": None,
            "mean": None,
        }
    return {
        "n": len(xs),
        "min": min(xs),
        "p10": _percentile(xs, 0.10),
        "p25": _percentile(xs, 0.25),
        "median": statistics.median(xs),
        "p75": _percentile(xs, 0.75),
        "p90": _percentile(xs, 0.90),
        "max": max(xs),
        "mean": statistics.fmean(xs),
    }


def _extract_rows(doc: Any) -> list[dict[str, Any]]:
    if isinstance(doc, list):
        return [dict(x) for x in doc if isinstance(x, dict)]
    if isinstance(doc, dict):
        for key in ("rows", "checkpoints", "data"):
            value = doc.get(key)
            if isinstance(value, list):
                return [dict(x) for x in value if isinstance(x, dict)]
    raise ValueError("Unable to locate enriched rows list")


def load_canonical_dates(
    coverage_path: str | Path = DEFAULT_CANONICAL_COVERAGE,
) -> list[str] | None:
    p = Path(coverage_path)
    if not p.exists() or p.stat().st_size == 0:
        return None

    doc = json.loads(p.read_text(encoding="utf-8"))

    dates: set[str] = set()

    if isinstance(doc, dict):
        for key in ("sessions", "results", "dates"):
            value = doc.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        dates.add(item)
                    elif isinstance(item, dict):
                        d = (
                            item.get("session_date")
                            or item.get("date")
                        )
                        if d:
                            status = str(item.get("status") or "").upper()
                            if not status or status in {
                                "COMPLETE", "SKIPPED_COMPLETE", "PASS", "READY"
                            }:
                                dates.add(str(d))
        # Some reports are keyed by date.
        for k, v in doc.items():
            if (
                isinstance(k, str)
                and len(k) == 10
                and k[4:5] == "-"
                and k[7:8] == "-"
            ):
                if not isinstance(v, dict):
                    dates.add(k)
                else:
                    status = str(v.get("status") or "").upper()
                    if not status or status in {
                        "COMPLETE", "SKIPPED_COMPLETE", "PASS", "READY"
                    }:
                        dates.add(k)

    return sorted(dates) or None


def discover_enriched_files(
    enrichment_root: str | Path,
    canonical_dates: list[str] | None,
) -> list[tuple[str, Path]]:
    root = Path(enrichment_root)
    found: list[tuple[str, Path]] = []

    if canonical_dates:
        for d in canonical_dates:
            candidates = [
                root / d / "enriched.json",
                root / d / f"{d}.json",
            ]
            p = next((x for x in candidates if x.exists() and x.stat().st_size > 0), None)
            if p is None:
                raise FileNotFoundError(f"missing enriched JSON for canonical date {d}")
            found.append((d, p))
        return found

    for p in sorted(root.glob("2026-*/enriched.json")):
        if p.is_file() and p.stat().st_size > 0:
            found.append((p.parent.name, p))

    if not found:
        raise FileNotFoundError(f"no enriched JSON files found under {root}")

    return found


def load_checkpoints(
    enrichment_root: str | Path = DEFAULT_ENRICHMENT_ROOT,
    canonical_coverage: str | Path = DEFAULT_CANONICAL_COVERAGE,
) -> list[dict[str, Any]]:
    canonical_dates = load_canonical_dates(canonical_coverage)
    files = discover_enriched_files(enrichment_root, canonical_dates)

    all_rows: list[dict[str, Any]] = []

    for session_date, p in files:
        doc = json.loads(p.read_text(encoding="utf-8"))
        rows = _extract_rows(doc)

        session_rows: list[dict[str, Any]] = []
        for raw in rows:
            timestamp = str(raw.get("timestamp") or raw.get("checkpoint_timestamp") or "")
            spot = _f(raw.get("spot"))
            if not timestamp or spot is None:
                continue

            row = dict(raw)
            row["session_date"] = str(raw.get("session_date") or session_date)
            row["timestamp"] = timestamp
            row["spot"] = spot
            session_rows.append(row)

        session_rows.sort(key=lambda r: r["timestamp"])

        # Enforce uniqueness and exact 5-minute chronology from the source artifact.
        seen: set[str] = set()
        for row in session_rows:
            if row["timestamp"] in seen:
                raise ValueError(
                    f"duplicate checkpoint {session_date} {row['timestamp']}"
                )
            seen.add(row["timestamp"])
            all_rows.append(row)

    all_rows.sort(key=lambda r: (r["session_date"], r["timestamp"]))
    return all_rows


def _field(row: dict[str, Any], stem: str, horizon: int) -> float | None:
    candidates = [
        f"{stem}_{horizon}m",
        f"{stem}_{horizon}",
    ]
    for key in candidates:
        if key in row:
            value = _f(row.get(key))
            if value is not None:
                return value
    return None


def build_checkpoint_dataset(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_session[str(row["session_date"])].append(row)

    output: list[dict[str, Any]] = []

    for session_date, session_rows in sorted(by_session.items()):
        session_rows.sort(key=lambda r: r["timestamp"])

        for i, row in enumerate(session_rows):
            record: dict[str, Any] = {
                "session_date": session_date,
                "timestamp": row["timestamp"],
                "spot": float(row["spot"]),
                "moving_atm": _f(row.get("moving_atm")),
                "pcr_current": _f(
                    row.get("pcr_current")
                    if "pcr_current" in row
                    else row.get("moving_pcr")
                ),
            }

            for lb in OI_LOOKBACKS:
                record[f"ce_delta_{lb}m"] = _field(row, "ce_delta", lb)
                record[f"pe_delta_{lb}m"] = _field(row, "pe_delta", lb)
                record[f"imbalance_{lb}m"] = _field(row, "imbalance", lb)
                record[f"pcr_change_{lb}m"] = _field(row, "pcr_change", lb)

            for fh in FORWARD_HORIZONS:
                steps = fh // 5
                future_rows = session_rows[i + 1:i + steps + 1]

                if len(future_rows) != steps:
                    record[f"bull_excursion_{fh}m"] = None
                    record[f"bear_excursion_{fh}m"] = None
                    record[f"net_change_{fh}m"] = None
                    continue

                # Exact 5m checkpoint sequence only. We intentionally do not
                # interpolate or use nearest timestamps.
                base = float(row["spot"])
                future_spots = [float(x["spot"]) for x in future_rows]

                record[f"bull_excursion_{fh}m"] = max(
                    [0.0] + [x - base for x in future_spots]
                )
                record[f"bear_excursion_{fh}m"] = max(
                    [0.0] + [base - x for x in future_spots]
                )
                record[f"net_change_{fh}m"] = future_spots[-1] - base

            output.append(record)

    return output


def _reliability(
    checkpoints: list[dict[str, Any]],
    *,
    direction: str,
    forward_horizon: int,
    move_threshold: int,
    oi_lookback: int,
    floor: float | None,
) -> dict[str, Any]:
    if floor is None:
        return {
            "eligible_checkpoint_count": 0,
            "movement_hit_count": 0,
            "movement_hit_rate_pct": None,
        }

    directional_values: list[tuple[float, float | None]] = []
    excursion_key = (
        f"bull_excursion_{forward_horizon}m"
        if direction == "BULLISH"
        else f"bear_excursion_{forward_horizon}m"
    )

    for row in checkpoints:
        imbalance = row.get(f"imbalance_{oi_lookback}m")
        excursion = row.get(excursion_key)
        if imbalance is None or excursion is None:
            continue
        directional_imbalance = (
            float(imbalance)
            if direction == "BULLISH"
            else -float(imbalance)
        )
        directional_values.append((directional_imbalance, float(excursion)))

    eligible = [
        exc
        for directional_imbalance, exc in directional_values
        if directional_imbalance >= floor
    ]
    hits = [x for x in eligible if x >= move_threshold]

    return {
        "eligible_checkpoint_count": len(eligible),
        "movement_hit_count": len(hits),
        "movement_hit_rate_pct": (
            100.0 * len(hits) / len(eligible)
            if eligible else None
        ),
    }


def analyze(checkpoints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for direction in ("BULLISH", "BEARISH"):
        for fh in FORWARD_HORIZONS:
            excursion_key = (
                f"bull_excursion_{fh}m"
                if direction == "BULLISH"
                else f"bear_excursion_{fh}m"
            )

            for move in MOVE_THRESHOLDS:
                movement_rows = [
                    r for r in checkpoints
                    if r.get(excursion_key) is not None
                    and float(r[excursion_key]) >= move
                ]

                for lb in OI_LOOKBACKS:
                    raw_imbalance = [
                        float(r[f"imbalance_{lb}m"])
                        for r in movement_rows
                        if r.get(f"imbalance_{lb}m") is not None
                    ]
                    directional_imbalance = [
                        x if direction == "BULLISH" else -x
                        for x in raw_imbalance
                    ]

                    ce_vals = [
                        float(r[f"ce_delta_{lb}m"])
                        for r in movement_rows
                        if r.get(f"ce_delta_{lb}m") is not None
                    ]
                    pe_vals = [
                        float(r[f"pe_delta_{lb}m"])
                        for r in movement_rows
                        if r.get(f"pe_delta_{lb}m") is not None
                    ]
                    pcr_vals = [
                        float(r[f"pcr_change_{lb}m"])
                        for r in movement_rows
                        if r.get(f"pcr_change_{lb}m") is not None
                    ]
                    directional_pcr = [
                        x if direction == "BULLISH" else -x
                        for x in pcr_vals
                    ]

                    directional_stats = _stats(directional_imbalance)
                    robust_floor = directional_stats["p10"]

                    aligned_count = sum(x > 0 for x in directional_imbalance)
                    aligned_rate = (
                        100.0 * aligned_count / len(directional_imbalance)
                        if directional_imbalance else None
                    )

                    reliability = _reliability(
                        checkpoints,
                        direction=direction,
                        forward_horizon=fh,
                        move_threshold=move,
                        oi_lookback=lb,
                        floor=robust_floor,
                    )

                    rows.append({
                        "direction": direction,
                        "forward_horizon_minutes": fh,
                        "nifty_move_threshold_points": move,
                        "oi_lookback_minutes": lb,
                        "movement_sample_count": len(movement_rows),
                        "oi_sample_count": len(directional_imbalance),
                        "directional_imbalance_aligned_count": aligned_count,
                        "directional_imbalance_aligned_rate_pct": aligned_rate,
                        "observed_min_directional_imbalance": directional_stats["min"],
                        "robust_min_p10_directional_imbalance": directional_stats["p10"],
                        "p25_directional_imbalance": directional_stats["p25"],
                        "median_directional_imbalance": directional_stats["median"],
                        "p75_directional_imbalance": directional_stats["p75"],
                        "p90_directional_imbalance": directional_stats["p90"],
                        "max_directional_imbalance": directional_stats["max"],
                        "mean_directional_imbalance": directional_stats["mean"],
                        "ce_delta_min": _stats(ce_vals)["min"],
                        "ce_delta_p10": _stats(ce_vals)["p10"],
                        "ce_delta_median": _stats(ce_vals)["median"],
                        "pe_delta_min": _stats(pe_vals)["min"],
                        "pe_delta_p10": _stats(pe_vals)["p10"],
                        "pe_delta_median": _stats(pe_vals)["median"],
                        "directional_pcr_change_p10": _stats(directional_pcr)["p10"],
                        "directional_pcr_change_median": _stats(directional_pcr)["median"],
                        **reliability,
                    })

    return rows


def write_csv(rows: list[dict[str, Any]], path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys()) if rows else []
    with p.open("w", newline="", encoding="utf-8") as f:
        if not fields:
            return
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def write_checkpoint_csv(rows: list[dict[str, Any]], path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "session_date","timestamp","spot","moving_atm","pcr_current",
        "ce_delta_5m","pe_delta_5m","imbalance_5m","pcr_change_5m",
        "ce_delta_10m","pe_delta_10m","imbalance_10m","pcr_change_10m",
        "ce_delta_15m","pe_delta_15m","imbalance_15m","pcr_change_15m",
        "bull_excursion_5m","bear_excursion_5m","net_change_5m",
        "bull_excursion_10m","bear_excursion_10m","net_change_10m",
        "bull_excursion_15m","bear_excursion_15m","net_change_15m",
    ]
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def run(
    *,
    enrichment_root: str | Path = DEFAULT_ENRICHMENT_ROOT,
    canonical_coverage: str | Path = DEFAULT_CANONICAL_COVERAGE,
    output_json: str | Path = DEFAULT_OUTPUT_JSON,
    output_csv: str | Path = DEFAULT_OUTPUT_CSV,
    checkpoint_csv: str | Path = DEFAULT_CHECKPOINT_CSV,
) -> dict[str, Any]:
    source_rows = load_checkpoints(enrichment_root, canonical_coverage)
    checkpoints = build_checkpoint_dataset(source_rows)
    attribution = analyze(checkpoints)

    session_dates = sorted({r["session_date"] for r in checkpoints})

    result = {
        "status": "PASS",
        "model": MODEL,
        "role": "DESCRIPTIVE_CAUSAL_OI_TO_NIFTY_MOVEMENT_MAGNITUDE_ATTRIBUTION",
        "session_count": len(session_dates),
        "session_dates": session_dates,
        "checkpoint_count": len(checkpoints),
        "forward_horizons_minutes": list(FORWARD_HORIZONS),
        "oi_lookbacks_minutes": list(OI_LOOKBACKS),
        "move_thresholds_points": list(MOVE_THRESHOLDS),
        "movement_definition": {
            "source": "exact enriched NIFTY spot checkpoints",
            "bullish_excursion": (
                "maximum positive spot change among exact future 5m checkpoints "
                "inside the selected forward horizon"
            ),
            "bearish_excursion": (
                "maximum negative spot change magnitude among exact future 5m "
                "checkpoints inside the selected forward horizon"
            ),
            "intrabar_1m_high_low_used": False,
            "nearest_time_fallback": False,
            "interpolation": False,
        },
        "oi_definition": {
            "basket": "moving ATM ±5 same physical strikes",
            "lookbacks": [5, 10, 15],
            "imbalance": "PE delta OI - CE delta OI",
            "bullish_directional_imbalance": "raw imbalance",
            "bearish_directional_imbalance": "-raw imbalance",
            "robust_minimum": "10th percentile among checkpoints that achieved the move",
            "observed_minimum": "literal minimum among checkpoints that achieved the move",
        },
        "important_interpretation": (
            "No OI level is treated as a proven requirement. Observed minima and "
            "P10 floors are descriptive characteristics of the exposed historical "
            "population, and movement can occur with non-aligned OI."
        ),
        "attribution_rows": attribution,
        "governance": {
            "population_is_fresh_oos": False,
            "population_previously_exposed": True,
            "entry_logic_changed": False,
            "exit_logic_used": False,
            "stop_loss_used": False,
            "pnl_used": False,
            "result_is_strategy_validation": False,
        },
    }

    out = Path(output_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    write_csv(attribution, output_csv)
    write_checkpoint_csv(checkpoints, checkpoint_csv)

    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--enrichment-root", default=str(DEFAULT_ENRICHMENT_ROOT))
    ap.add_argument("--canonical-coverage", default=str(DEFAULT_CANONICAL_COVERAGE))
    ap.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    ap.add_argument("--output-csv", default=str(DEFAULT_OUTPUT_CSV))
    ap.add_argument("--checkpoint-csv", default=str(DEFAULT_CHECKPOINT_CSV))
    args = ap.parse_args()

    result = run(
        enrichment_root=args.enrichment_root,
        canonical_coverage=args.canonical_coverage,
        output_json=args.output_json,
        output_csv=args.output_csv,
        checkpoint_csv=args.checkpoint_csv,
    )

    # Compact console matrix focused on the robust P10 "minimum-like" number.
    preview = [
        r for r in result["attribution_rows"]
        if r["nifty_move_threshold_points"] <= 50
    ]

    print(json.dumps({
        "status": result["status"],
        "model": result["model"],
        "session_count": result["session_count"],
        "checkpoint_count": result["checkpoint_count"],
        "movement_definition": result["movement_definition"],
        "preview_first_50_points": preview,
        "output_json": args.output_json,
        "output_csv": args.output_csv,
        "checkpoint_csv": args.checkpoint_csv,
    }, indent=2))


if __name__ == "__main__":
    main()
