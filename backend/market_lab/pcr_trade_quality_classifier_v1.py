"""Leakage-guarded PCR Trade Quality Classifier v1.

Purpose
-------
Train a transparent, direction-specific logistic classifier that decides whether
an already-qualified PCR Methodology V2 candidate should be TRADE_ALLOWED or
NO_TRADE.  Training is restricted to the declared development blocks
TRAIN/OOS_A/OOS_B/OOS_C/OOS_D.  OOS_E/F/G/H are never valid training inputs.

The label is the already frozen realized option policy outcome:
  * TARGET_FIRST (+5%)
  * STOP_FIRST / AMBIGUOUS_SAME_BAR (-10%)
  * NEITHER_WITHIN_15M -> +15m close return
then a fixed 0.50 percentage-point round-trip cost is subtracted.
A positive net realized return is the positive class.

Only features known at or before entry are used.  All forward_change_* fields
are explicitly prohibited.

Research only.  No live order placement.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any, Iterable

MODEL_VERSION = "PCR_TRADE_QUALITY_CLASSIFIER_V1"
METHODOLOGY_VERSION = "PCR_RESEARCH_METHODOLOGY_V2"
CONFIDENCE_PROFILE = "FROZEN_D5_D15"
CONTRACT_RULE = "EXACT_T0_ATM_INSTRUMENT_NO_SUBSTITUTION"
ENTRY_RULE = "NEXT_MINUTE_OPEN"
FROZEN_POLICY = "TARGET_5_STOP_10_TIME_EXIT_15M"
ROUND_TRIP_COST_PCT_POINTS = 0.50
ALLOWED_DEVELOPMENT_BLOCKS = {"TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D"}
THRESHOLD_GRID = (0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80)
MIN_OOF_ALLOWED = 12

# All values below are available by confirmation/entry time.  Spot momentum is
# derived from exact historical spot timestamps ending at T0, never future rows.
FEATURE_NAMES = (
    "confidence_score",
    "confirmation_offset_minutes",
    "minute_of_session",
    "spot_momentum_1m",
    "spot_momentum_5m",
    "spot_momentum_15m",
    "fixed_pcr",
    "fixed_moving_pcr_spread",
    "fixed_pcr_change_1m",
    "fixed_pcr_change_5m",
    "fixed_pcr_change_15m",
    "moving_pcr_change_5m",
    "full_pcr_change_5m",
    "fixed_call_oi_change_pct",
    "fixed_put_oi_change_pct",
    "moving_call_oi_change_pct",
    "moving_put_oi_change_pct",
    "ce_5m_premium_change_pct",
    "ce_5m_oi_change_pct",
    "pe_5m_premium_change_pct",
    "pe_5m_oi_change_pct",
)

PROHIBITED_PREFIXES = ("forward_change_",)


def _dt(value: Any) -> datetime:
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def _num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _load_evidence(path: str | Path) -> tuple[
    dict[tuple[str, datetime], dict[str, str]],
    dict[str, dict[datetime, dict[str, str]]],
]:
    exact: dict[tuple[str, datetime], dict[str, str]] = {}
    by_session: dict[str, dict[datetime, dict[str, str]]] = defaultdict(dict)
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        if {"session_date", "timestamp", "spot"}.difference(fields):
            raise ValueError("evidence CSV missing session_date/timestamp/spot")
        for bad in fields:
            if any(bad.startswith(prefix) for prefix in PROHIBITED_PREFIXES):
                # Presence is fine; use is not.  Kept as explicit guard metadata.
                continue
        for row in reader:
            session = str(row["session_date"])
            ts = _dt(row["timestamp"])
            exact[(session, ts)] = row
            by_session[session][ts] = row
    return exact, by_session


def _load_positioning(path: str | Path) -> dict[tuple[str, datetime, str], dict[str, str]]:
    idx: dict[tuple[str, datetime, str], dict[str, str]] = {}
    required = {
        "session_date", "timestamp", "strike",
        "ce_5m_premium_change_pct", "ce_5m_oi_change_pct",
        "pe_5m_premium_change_pct", "pe_5m_oi_change_pct",
    }
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError("positioning CSV missing columns: " + ", ".join(sorted(missing)))
        for row in reader:
            key = (str(row["session_date"]), _dt(row["timestamp"]), _strike_text(row["strike"]))
            idx[key] = row
    return idx


def _strike_text(value: Any) -> str:
    x = _num(value)
    if x is None:
        return str(value)
    return f"{x:.10f}".rstrip("0").rstrip(".")


def _spot_momentum(by_session: dict[str, dict[datetime, dict[str, str]]], session: str, t0: datetime, minutes: int) -> float | None:
    current = by_session.get(session, {}).get(t0)
    previous = by_session.get(session, {}).get(t0 - timedelta(minutes=minutes))
    a = _num(current.get("spot")) if current else None
    b = _num(previous.get("spot")) if previous else None
    return a - b if a is not None and b is not None else None


def _minute_of_session(ts: datetime) -> float:
    # Indian cash market session starts 09:15 local.  Historical timestamps in
    # this project are already exchange-local offset-aware/naive consistently.
    return float((ts.hour * 60 + ts.minute) - (9 * 60 + 15))


def _validate_methodology(doc: dict[str, Any]) -> None:
    if doc.get("status") != "AVAILABLE" or doc.get("methodology_version") != METHODOLOGY_VERSION:
        raise ValueError("methodology must be AVAILABLE PCR_RESEARCH_METHODOLOGY_V2")
    if doc.get("profile") != CONFIDENCE_PROFILE:
        raise ValueError("classifier v1 requires FROZEN_D5_D15 profile")
    guard = doc.get("leakage_guard", {})
    required = {
        "current_holdout_validation_input_used": False,
        "panel_any_confirmation_allowed": False,
        "moving_atm_substitution_allowed": False,
    }
    for key, expected in required.items():
        if guard.get(key) is not expected:
            raise ValueError(f"methodology leakage guard failed: {key}")


def _validate_backtest(doc: dict[str, Any]) -> None:
    if doc.get("status") != "AVAILABLE" or doc.get("methodology_version") != METHODOLOGY_VERSION:
        raise ValueError("backtest must be AVAILABLE PCR_RESEARCH_METHODOLOGY_V2")
    if doc.get("confidence_profile") != CONFIDENCE_PROFILE:
        raise ValueError("backtest profile must be FROZEN_D5_D15")
    if doc.get("entry_rule") != ENTRY_RULE or doc.get("contract_selection_rule") != CONTRACT_RULE:
        raise ValueError("backtest entry/contract rules are not frozen V2 rules")


def _realized_return(trade: dict[str, Any]) -> float | None:
    result = trade.get("target_stop", {}).get("TARGET_5_STOP_10", {}).get("result")
    if result == "TARGET_FIRST":
        gross = 5.0
    elif result in {"STOP_FIRST", "AMBIGUOUS_SAME_BAR"}:
        gross = -10.0
    elif result == "NEITHER_WITHIN_15M":
        gross = _num(trade.get("returns_pct", {}).get("15m"))
    else:
        return None
    if gross is None:
        return None
    return gross - ROUND_TRIP_COST_PCT_POINTS


def _event_key(direction: str, event: dict[str, Any]) -> tuple[str, str, str]:
    return direction, str(event["session_date"]), str(event["timestamp"])


def _trade_key(trade: dict[str, Any]) -> tuple[str, str, str]:
    return str(trade["direction"]), str(trade["session_date"]), str(trade["stage2_timestamp"])


def build_block_rows(
    block_name: str,
    methodology_path: str | Path,
    backtest_path: str | Path,
    evidence_path: str | Path,
    positioning_path: str | Path,
) -> list[dict[str, Any]]:
    methodology = _load_json(methodology_path)
    backtest = _load_json(backtest_path)
    _validate_methodology(methodology)
    _validate_backtest(backtest)
    evidence_exact, evidence_by_session = _load_evidence(evidence_path)
    positioning = _load_positioning(positioning_path)

    events: dict[tuple[str, str, str], dict[str, Any]] = {}
    for dkey in ("bearish", "bullish"):
        direction = dkey.upper()
        for event in methodology.get("directions", {}).get(dkey, {}).get("events", []):
            events[_event_key(direction, event)] = event

    rows: list[dict[str, Any]] = []
    for trade in backtest.get("trades", []):
        key = _trade_key(trade)
        event = events.get(key)
        if event is None:
            continue
        if event.get("confidence_tier") not in {"HIGH", "VERY_HIGH"}:
            continue
        net_return = _realized_return(trade)
        if net_return is None:
            continue
        session = str(trade["session_date"])
        t0 = _dt(trade["stage2_timestamp"])
        confirmation_ts = _dt(trade["confirmation_timestamp"])
        evidence = evidence_exact.get((session, t0))
        if evidence is None:
            continue
        strike = _strike_text(trade.get("frozen_t0_atm_strike"))
        pos = positioning.get((session, confirmation_ts, strike))
        if pos is None:
            continue

        features: dict[str, float | None] = {
            "confidence_score": _num(event.get("confidence_score")),
            "confirmation_offset_minutes": _num(trade.get("confirmation_offset_minutes")),
            "minute_of_session": _minute_of_session(t0),
            "spot_momentum_1m": _spot_momentum(evidence_by_session, session, t0, 1),
            "spot_momentum_5m": _spot_momentum(evidence_by_session, session, t0, 5),
            "spot_momentum_15m": _spot_momentum(evidence_by_session, session, t0, 15),
            "fixed_pcr": _num(evidence.get("fixed_pcr")),
            "fixed_moving_pcr_spread": _num(evidence.get("fixed_moving_pcr_spread")),
            "fixed_pcr_change_1m": _num(evidence.get("fixed_pcr_change_1m")),
            "fixed_pcr_change_5m": _num(evidence.get("fixed_pcr_change_5m")),
            "fixed_pcr_change_15m": _num(evidence.get("fixed_pcr_change_15m")),
            "moving_pcr_change_5m": _num(evidence.get("moving_pcr_change_5m")),
            "full_pcr_change_5m": _num(evidence.get("full_pcr_change_5m")),
            "fixed_call_oi_change_pct": _num(evidence.get("fixed_call_oi_change_pct")),
            "fixed_put_oi_change_pct": _num(evidence.get("fixed_put_oi_change_pct")),
            "moving_call_oi_change_pct": _num(evidence.get("moving_call_oi_change_pct")),
            "moving_put_oi_change_pct": _num(evidence.get("moving_put_oi_change_pct")),
            "ce_5m_premium_change_pct": _num(pos.get("ce_5m_premium_change_pct")),
            "ce_5m_oi_change_pct": _num(pos.get("ce_5m_oi_change_pct")),
            "pe_5m_premium_change_pct": _num(pos.get("pe_5m_premium_change_pct")),
            "pe_5m_oi_change_pct": _num(pos.get("pe_5m_oi_change_pct")),
        }
        rows.append({
            "block": block_name,
            "direction": str(trade["direction"]),
            "session_date": session,
            "stage2_timestamp": trade["stage2_timestamp"],
            "confirmation_timestamp": trade["confirmation_timestamp"],
            "features": features,
            "net_realized_return_pct": net_return,
            "positive_label": 1 if net_return > 0 else 0,
        })
    return rows


def _median_impute(rows: list[dict[str, Any]], features: Iterable[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for name in features:
        vals = [r["features"].get(name) for r in rows]
        clean = [float(v) for v in vals if v is not None and math.isfinite(float(v))]
        out[name] = float(median(clean)) if clean else 0.0
    return out


def _scaler(rows: list[dict[str, Any]], medians: dict[str, float]) -> tuple[dict[str, float], dict[str, float]]:
    means: dict[str, float] = {}
    stds: dict[str, float] = {}
    for name in FEATURE_NAMES:
        vals = [float(r["features"].get(name) if r["features"].get(name) is not None else medians[name]) for r in rows]
        m = sum(vals) / len(vals) if vals else 0.0
        variance = sum((x - m) ** 2 for x in vals) / len(vals) if vals else 0.0
        s = math.sqrt(variance)
        means[name] = m
        stds[name] = s if s > 1e-12 else 1.0
    return means, stds


def _vector(row: dict[str, Any], medians: dict[str, float], means: dict[str, float], stds: dict[str, float]) -> list[float]:
    return [
        ((float(row["features"].get(name)) if row["features"].get(name) is not None else medians[name]) - means[name]) / stds[name]
        for name in FEATURE_NAMES
    ]


def _sigmoid(z: float) -> float:
    if z >= 0:
        ez = math.exp(-z)
        return 1.0 / (1.0 + ez)
    ez = math.exp(z)
    return ez / (1.0 + ez)


def _fit(rows: list[dict[str, Any]], *, epochs: int = 1800, lr: float = 0.04, l2: float = 0.08) -> dict[str, Any]:
    if len(rows) < 8:
        raise ValueError("not enough rows to fit quality classifier")
    labels = [int(r["positive_label"]) for r in rows]
    if len(set(labels)) < 2:
        raise ValueError("quality classifier needs both positive and negative labels")
    medians = _median_impute(rows, FEATURE_NAMES)
    means, stds = _scaler(rows, medians)
    xs = [_vector(r, medians, means, stds) for r in rows]
    ys = [float(x) for x in labels]
    weights = [0.0] * len(FEATURE_NAMES)
    bias = math.log((sum(ys) + 0.5) / (len(ys) - sum(ys) + 0.5))

    for _ in range(epochs):
        gw = [0.0] * len(weights)
        gb = 0.0
        for x, y in zip(xs, ys):
            p = _sigmoid(bias + sum(w * v for w, v in zip(weights, x)))
            err = p - y
            gb += err
            for j, v in enumerate(x):
                gw[j] += err * v
        n = float(len(xs))
        bias -= lr * (gb / n)
        for j in range(len(weights)):
            grad = gw[j] / n + l2 * weights[j]
            weights[j] -= lr * grad

    return {
        "feature_names": list(FEATURE_NAMES),
        "medians": medians,
        "means": means,
        "stds": stds,
        "weights": {name: weights[i] for i, name in enumerate(FEATURE_NAMES)},
        "bias": bias,
        "training_count": len(rows),
        "positive_count": sum(labels),
        "negative_count": len(labels) - sum(labels),
    }


def _predict(model: dict[str, Any], row: dict[str, Any]) -> float:
    x = _vector(row, model["medians"], model["means"], model["stds"])
    weights = [float(model["weights"][name]) for name in FEATURE_NAMES]
    return _sigmoid(float(model["bias"]) + sum(w * v for w, v in zip(weights, x)))


def _profit_factor(returns: list[float]) -> float | None:
    profit = sum(x for x in returns if x > 0)
    loss = -sum(x for x in returns if x < 0)
    if loss == 0:
        return None
    return profit / loss


def _threshold_metrics(scored: list[tuple[float, dict[str, Any]]], threshold: float) -> dict[str, Any]:
    selected = [r for p, r in scored if p >= threshold]
    returns = [float(r["net_realized_return_pct"]) for r in selected]
    return {
        "threshold": threshold,
        "allowed_count": len(selected),
        "positive_count": sum(x > 0 for x in returns),
        "positive_pct": 100.0 * sum(x > 0 for x in returns) / len(returns) if returns else None,
        "mean_net_return_pct": sum(returns) / len(returns) if returns else None,
        "sum_net_return_pct_points": sum(returns),
        "profit_factor": _profit_factor(returns),
    }


def _choose_threshold(scored: list[tuple[float, dict[str, Any]]]) -> tuple[float, list[dict[str, Any]]]:
    metrics = [_threshold_metrics(scored, t) for t in THRESHOLD_GRID]
    eligible = [
        m for m in metrics
        if m["allowed_count"] >= MIN_OOF_ALLOWED
        and m["mean_net_return_pct"] is not None
        and m["mean_net_return_pct"] > 0
        and m["profit_factor"] is not None
        and m["profit_factor"] > 1.0
    ]
    pool = eligible or [m for m in metrics if m["allowed_count"] >= MIN_OOF_ALLOWED]
    if not pool:
        pool = [m for m in metrics if m["allowed_count"] > 0]
    if not pool:
        return 0.80, metrics
    best = max(pool, key=lambda m: (m["mean_net_return_pct"], m["profit_factor"] or 0.0, m["allowed_count"]))
    return float(best["threshold"]), metrics


def _oof(direction_rows: list[dict[str, Any]]) -> list[tuple[float, dict[str, Any]]]:
    blocks = sorted(set(r["block"] for r in direction_rows))
    scored: list[tuple[float, dict[str, Any]]] = []
    for holdout in blocks:
        train = [r for r in direction_rows if r["block"] != holdout]
        test = [r for r in direction_rows if r["block"] == holdout]
        if not train or not test:
            continue
        try:
            model = _fit(train)
        except ValueError:
            continue
        scored.extend((_predict(model, r), r) for r in test)
    return scored


def train(blocks: list[tuple[str, str, str, str, str]]) -> dict[str, Any]:
    if not blocks:
        raise ValueError("at least one development block is required")
    names = [name for name, *_ in blocks]
    invalid = [name for name in names if name not in ALLOWED_DEVELOPMENT_BLOCKS]
    if invalid:
        raise ValueError("training blocks must be development-only; invalid: " + ", ".join(invalid))
    if len(set(names)) != len(names):
        raise ValueError("duplicate development block names")

    all_rows: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for name, methodology, backtest, evidence, positioning in blocks:
        rows = build_block_rows(name, methodology, backtest, evidence, positioning)
        counts[name] = len(rows)
        all_rows.extend(rows)

    directions: dict[str, Any] = {}
    for direction in ("BEARISH", "BULLISH"):
        rows = [r for r in all_rows if r["direction"] == direction]
        if len(rows) < 20:
            raise ValueError(f"not enough {direction} development rows ({len(rows)})")
        oof_scored = _oof(rows)
        threshold, threshold_table = _choose_threshold(oof_scored)
        final_model = _fit(rows)
        oof_selected = _threshold_metrics(oof_scored, threshold)
        directions[direction.lower()] = {
            "direction": direction,
            "decision_threshold": threshold,
            "model": final_model,
            "oof": {
                "prediction_count": len(oof_scored),
                "selected_threshold_metrics": oof_selected,
                "threshold_grid_metrics": threshold_table,
            },
        }

    return {
        "status": "AVAILABLE",
        "model_version": MODEL_VERSION,
        "model_status": "FROZEN_AFTER_DEVELOPMENT_FOR_UNTOUCHED_OOS_H",
        "methodology_version": METHODOLOGY_VERSION,
        "confidence_profile": CONFIDENCE_PROFILE,
        "entry_rule": ENTRY_RULE,
        "contract_selection_rule": CONTRACT_RULE,
        "label_policy": FROZEN_POLICY,
        "round_trip_cost_pct_points": ROUND_TRIP_COST_PCT_POINTS,
        "development_blocks": names,
        "development_row_counts": counts,
        "feature_names": list(FEATURE_NAMES),
        "leakage_guard": {
            "allowed_training_blocks": sorted(ALLOWED_DEVELOPMENT_BLOCKS),
            "holdout_blocks_e_f_g_h_allowed_for_training": False,
            "future_return_features_used": False,
            "prohibited_feature_prefixes": list(PROHIBITED_PREFIXES),
            "feature_time_boundary": "AT_OR_BEFORE_ENTRY_ONLY",
            "threshold_calibration": "LEAVE_ONE_DEVELOPMENT_BLOCK_OUT_ONLY",
        },
        "decision_semantics": {
            "probability_ge_direction_threshold": "TRADE_ALLOWED",
            "probability_below_direction_threshold": "NO_TRADE",
        },
        "directions": directions,
    }


def _parse_block(value: str) -> tuple[str, str, str, str, str]:
    parts = value.split("|")
    if len(parts) != 5:
        raise argparse.ArgumentTypeError("--block must be NAME|METHODOLOGY_JSON|BACKTEST_JSON|EVIDENCE_CSV|POSITIONING_CSV")
    return tuple(parts)  # type: ignore[return-value]


def main() -> None:
    parser = argparse.ArgumentParser(description="Train leakage-guarded PCR Trade Quality Classifier v1")
    parser.add_argument(
        "--block", action="append", required=True, type=_parse_block,
        help="Development block: NAME|METHODOLOGY_JSON|BACKTEST_JSON|EVIDENCE_CSV|POSITIONING_CSV",
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = train(args.block)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "model_version": result["model_version"],
        "model_status": result["model_status"],
        "development_blocks": result["development_blocks"],
        "development_row_counts": result["development_row_counts"],
        "leakage_guard": result["leakage_guard"],
        "bearish": {
            "threshold": result["directions"]["bearish"]["decision_threshold"],
            "oof": result["directions"]["bearish"]["oof"]["selected_threshold_metrics"],
        },
        "bullish": {
            "threshold": result["directions"]["bullish"]["decision_threshold"],
            "oof": result["directions"]["bullish"]["oof"]["selected_threshold_metrics"],
        },
        "output": str(out),
    }, indent=2))


if __name__ == "__main__":
    main()
