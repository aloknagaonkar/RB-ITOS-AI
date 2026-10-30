from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from pathlib import Path
from typing import Any

MODEL = "NIFTY_OI_STRENGTH_MOVEMENT_PROBABILITY_V1"

DEFAULT_CHECKPOINT_CSV = Path(
    "data/historical-evidence/"
    "nifty-oi-movement-magnitude-attribution-checkpoints-v1.csv"
)
DEFAULT_OUTPUT_JSON = Path(
    "data/historical-evidence/nifty-oi-strength-movement-probability-v1.json"
)
DEFAULT_OUTPUT_CSV = Path(
    "data/historical-evidence/nifty-oi-strength-movement-probability-v1.csv"
)

# User explicitly requested only 5m and 10m forward movement analysis.
FORWARD_HORIZONS = (5, 10)

# Historical OI context remains 5m / 10m / 15m because all are known at T.
OI_LOOKBACKS = (5, 10, 15)

# Absolute directional imbalance thresholds, expressed in contracts/units
# exactly as stored in the enriched OI source.
OI_STRENGTH_THRESHOLDS = (
    1_000_000,
    2_000_000,
    3_000_000,
    5_000_000,
    7_500_000,
    10_000_000,
    15_000_000,
)

MOVE_THRESHOLDS = tuple(range(10, 101, 10))


def _f(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def load_checkpoints(path: str | Path = DEFAULT_CHECKPOINT_CSV) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        raise FileNotFoundError(p)

    rows: list[dict[str, Any]] = []
    with p.open(newline="", encoding="utf-8-sig") as f:
        rd = csv.DictReader(f)
        required = {
            "session_date", "timestamp", "spot",
            "imbalance_5m", "imbalance_10m", "imbalance_15m",
            "bull_excursion_5m", "bear_excursion_5m",
            "bull_excursion_10m", "bear_excursion_10m",
        }
        missing = required - set(rd.fieldnames or [])
        if missing:
            raise ValueError(f"{p}: missing columns {sorted(missing)}")

        for raw in rd:
            row: dict[str, Any] = dict(raw)
            for lb in OI_LOOKBACKS:
                row[f"imbalance_{lb}m"] = _f(raw.get(f"imbalance_{lb}m"))
            for fh in FORWARD_HORIZONS:
                row[f"bull_excursion_{fh}m"] = _f(raw.get(f"bull_excursion_{fh}m"))
                row[f"bear_excursion_{fh}m"] = _f(raw.get(f"bear_excursion_{fh}m"))
            rows.append(row)

    return rows


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
    return xs[lo] * (1 - frac) + xs[hi] * frac


def analyze(checkpoints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    for direction in ("BULLISH", "BEARISH"):
        for lb in OI_LOOKBACKS:
            imbalance_key = f"imbalance_{lb}m"

            for fh in FORWARD_HORIZONS:
                excursion_key = (
                    f"bull_excursion_{fh}m"
                    if direction == "BULLISH"
                    else f"bear_excursion_{fh}m"
                )

                usable: list[tuple[float, float]] = []
                for row in checkpoints:
                    imbalance = row.get(imbalance_key)
                    excursion = row.get(excursion_key)
                    if imbalance is None or excursion is None:
                        continue

                    directional_imbalance = (
                        float(imbalance)
                        if direction == "BULLISH"
                        else -float(imbalance)
                    )
                    usable.append((directional_imbalance, float(excursion)))

                for oi_floor in OI_STRENGTH_THRESHOLDS:
                    eligible = [
                        excursion
                        for directional_imbalance, excursion in usable
                        if directional_imbalance >= oi_floor
                    ]

                    for move in MOVE_THRESHOLDS:
                        hits = [x for x in eligible if x >= move]

                        out.append({
                            "direction": direction,
                            "oi_lookback_minutes": lb,
                            "forward_horizon_minutes": fh,
                            "oi_directional_imbalance_floor": oi_floor,
                            "oi_directional_imbalance_floor_millions": oi_floor / 1_000_000.0,
                            "nifty_move_threshold_points": move,
                            "eligible_checkpoint_count": len(eligible),
                            "movement_hit_count": len(hits),
                            "movement_hit_rate_pct": (
                                100.0 * len(hits) / len(eligible)
                                if eligible else None
                            ),
                            "median_forward_excursion_points": (
                                statistics.median(eligible) if eligible else None
                            ),
                            "p75_forward_excursion_points": (
                                _percentile(eligible, 0.75) if eligible else None
                            ),
                            "p90_forward_excursion_points": (
                                _percentile(eligible, 0.90) if eligible else None
                            ),
                            "max_forward_excursion_points": (
                                max(eligible) if eligible else None
                            ),
                        })

    return out


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


def run(
    *,
    checkpoint_csv: str | Path = DEFAULT_CHECKPOINT_CSV,
    output_json: str | Path = DEFAULT_OUTPUT_JSON,
    output_csv: str | Path = DEFAULT_OUTPUT_CSV,
) -> dict[str, Any]:
    checkpoints = load_checkpoints(checkpoint_csv)
    rows = analyze(checkpoints)

    result = {
        "status": "PASS",
        "model": MODEL,
        "role": "DESCRIPTIVE_OI_STRENGTH_TO_FORWARD_NIFTY_MOVEMENT_PROBABILITY",
        "checkpoint_count": len(checkpoints),
        "forward_horizons_minutes": list(FORWARD_HORIZONS),
        "oi_lookbacks_minutes": list(OI_LOOKBACKS),
        "oi_strength_thresholds": list(OI_STRENGTH_THRESHOLDS),
        "move_thresholds_points": list(MOVE_THRESHOLDS),
        "directional_imbalance_definition": {
            "raw": "PE delta OI - CE delta OI",
            "bullish": "raw imbalance",
            "bearish": "-raw imbalance",
            "eligibility": "directional imbalance >= selected OI floor",
        },
        "important_interpretation": (
            "This measures conditional historical frequency, not a proven causal "
            "requirement or validated trading threshold."
        ),
        "rows": rows,
        "governance": {
            "forward_15m_excluded": True,
            "stop_loss_used": False,
            "option_pnl_used": False,
            "strategy_entry_logic_changed": False,
            "population_is_fresh_oos": False,
            "result_is_strategy_validation": False,
        },
    }

    out = Path(output_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    write_csv(rows, output_csv)
    return result


def _preview(result: dict[str, Any]) -> list[dict[str, Any]]:
    # Compact console preview through 50 points only.
    return [
        r for r in result["rows"]
        if r["nifty_move_threshold_points"] <= 50
    ]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint-csv", default=str(DEFAULT_CHECKPOINT_CSV))
    ap.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    ap.add_argument("--output-csv", default=str(DEFAULT_OUTPUT_CSV))
    args = ap.parse_args()

    result = run(
        checkpoint_csv=args.checkpoint_csv,
        output_json=args.output_json,
        output_csv=args.output_csv,
    )

    print(json.dumps({
        "status": result["status"],
        "model": result["model"],
        "checkpoint_count": result["checkpoint_count"],
        "forward_horizons_minutes": result["forward_horizons_minutes"],
        "oi_lookbacks_minutes": result["oi_lookbacks_minutes"],
        "preview_10_to_50_points": _preview(result),
        "output_json": args.output_json,
        "output_csv": args.output_csv,
    }, indent=2))


if __name__ == "__main__":
    main()
