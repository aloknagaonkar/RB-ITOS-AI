from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from pathlib import Path
from typing import Any

MODEL = "NIFTY_OI_STRENGTH_BUCKET_MOVEMENT_PROBABILITY_V1"

DEFAULT_CHECKPOINT_CSV = Path(
    "data/historical-evidence/"
    "nifty-oi-movement-magnitude-attribution-checkpoints-v1.csv"
)
DEFAULT_OUTPUT_JSON = Path(
    "data/historical-evidence/nifty-oi-strength-bucket-movement-probability-v1.json"
)
DEFAULT_OUTPUT_CSV = Path(
    "data/historical-evidence/nifty-oi-strength-bucket-movement-probability-v1.csv"
)

FORWARD_HORIZONS = (5, 10)
OI_LOOKBACKS = (5, 10, 15)
MOVE_THRESHOLDS = (10, 20, 30, 40, 50)

# Non-overlapping directional OI imbalance buckets.
# lower inclusive, upper exclusive; final bucket has no upper bound.
OI_BUCKETS = (
    (0, 1_000_000, "0-1M"),
    (1_000_000, 2_000_000, "1-2M"),
    (2_000_000, 3_000_000, "2-3M"),
    (3_000_000, 5_000_000, "3-5M"),
    (5_000_000, 7_500_000, "5-7.5M"),
    (7_500_000, 10_000_000, "7.5-10M"),
    (10_000_000, 15_000_000, "10-15M"),
    (15_000_000, None, "15M+"),
)


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
    return xs[lo] * (1 - frac) + xs[hi] * frac


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


def _in_bucket(value: float, lo: int, hi: int | None) -> bool:
    if value < lo:
        return False
    if hi is None:
        return True
    return value < hi


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

                    # This study focuses only on aligned directional OI strength.
                    if directional_imbalance < 0:
                        continue

                    usable.append((directional_imbalance, float(excursion)))

                for lo, hi, label in OI_BUCKETS:
                    bucket_excursions = [
                        excursion
                        for directional_imbalance, excursion in usable
                        if _in_bucket(directional_imbalance, lo, hi)
                    ]

                    bucket_count = len(bucket_excursions)

                    for move in MOVE_THRESHOLDS:
                        hits = [x for x in bucket_excursions if x >= move]

                        out.append({
                            "direction": direction,
                            "oi_lookback_minutes": lb,
                            "forward_horizon_minutes": fh,
                            "oi_bucket": label,
                            "oi_bucket_lower": lo,
                            "oi_bucket_upper": hi,
                            "nifty_move_threshold_points": move,
                            "eligible_checkpoint_count": bucket_count,
                            "movement_hit_count": len(hits),
                            "movement_hit_rate_pct": (
                                100.0 * len(hits) / bucket_count
                                if bucket_count else None
                            ),
                            "median_forward_excursion_points": (
                                statistics.median(bucket_excursions)
                                if bucket_excursions else None
                            ),
                            "p75_forward_excursion_points": (
                                _percentile(bucket_excursions, 0.75)
                                if bucket_excursions else None
                            ),
                            "p90_forward_excursion_points": (
                                _percentile(bucket_excursions, 0.90)
                                if bucket_excursions else None
                            ),
                            "max_forward_excursion_points": (
                                max(bucket_excursions)
                                if bucket_excursions else None
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
        "role": "DESCRIPTIVE_NON_OVERLAPPING_OI_BUCKET_TO_NIFTY_MOVEMENT_PROBABILITY",
        "checkpoint_count": len(checkpoints),
        "forward_horizons_minutes": list(FORWARD_HORIZONS),
        "oi_lookbacks_minutes": list(OI_LOOKBACKS),
        "move_thresholds_points": list(MOVE_THRESHOLDS),
        "oi_buckets": [
            {
                "label": label,
                "lower_inclusive": lo,
                "upper_exclusive": hi,
            }
            for lo, hi, label in OI_BUCKETS
        ],
        "directional_imbalance_definition": {
            "raw": "PE delta OI - CE delta OI",
            "bullish": "raw imbalance",
            "bearish": "-raw imbalance",
            "aligned_only": True,
            "negative_directional_imbalance_excluded": True,
        },
        "important_interpretation": (
            "Buckets are non-overlapping. This avoids cumulative >= threshold "
            "blurring and is descriptive only on the exposed canonical population."
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
    return result["rows"]


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
        "preview": _preview(result),
        "output_json": args.output_json,
        "output_csv": args.output_csv,
    }, indent=2))


if __name__ == "__main__":
    main()
