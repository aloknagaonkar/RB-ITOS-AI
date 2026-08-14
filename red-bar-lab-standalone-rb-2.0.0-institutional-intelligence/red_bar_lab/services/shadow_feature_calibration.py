from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from itertools import combinations
from typing import Iterable, Mapping

import pandas as pd

from red_bar_lab.intelligence.directional_features import latest_directional_features
from red_bar_lab.intelligence.directional_regime import classify_directional_regime
from red_bar_lab.intelligence.directional_transition import (
    evaluate_shadow_directional_transition,
)
from red_bar_lab.services.shadow_directional_outcome import evaluate_shadow_outcome


NUMERIC_FEATURES = (
    "confidence",
    "ema_fast_slope_atr",
    "ema_slow_slope_atr",
    "ema_fast_acceleration_atr",
    "ema_spread_atr",
    "adx",
    "adx_slope",
    "dmi_gap",
    "directional_dmi_gap",
    "displacement_atr",
    "directional_displacement_atr",
    "range_atr",
    "compression_ratio",
    "volume_ratio",
)

CATEGORICAL_FEATURES = (
    "direction",
    "regime",
    "transition_type",
    "time_bucket",
    "breakout",
    "breakdown",
    "bullish_structure",
    "bearish_structure",
)


def _decision_rank(value: object) -> int:
    return {
        "NO_TRANSITION": 0,
        "WATCH": 1,
        "TRANSITION_FORMING": 2,
        "SHADOW_SIGNAL": 3,
        "STRONG_SHADOW_SIGNAL": 4,
    }.get(str(value or ""), 0)


def _safe_mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _accuracy(rows: Iterable[Mapping[str, object]], field: str = "direction_correct_30m") -> float | None:
    values = [bool(row[field]) for row in rows if row.get(field) is not None]
    if not values:
        return None
    return round(sum(values) / len(values) * 100.0, 2)


def _time_bucket(timestamp: object) -> str:
    value = pd.Timestamp(timestamp)
    minutes = value.hour * 60 + value.minute
    if minutes < 10 * 60 + 30:
        return "OPEN_0915_1029"
    if minutes < 12 * 60:
        return "MORNING_1030_1159"
    if minutes < 13 * 60 + 30:
        return "MIDDAY_1200_1329"
    return "AFTERNOON_1330_CLOSE"


def build_calibration_rows(
    frames_by_date: Mapping[date, pd.DataFrame],
    *,
    minimum_decision: str = "STRONG_SHADOW_SIGNAL",
    minimum_history: int = 35,
) -> list[dict[str, object]]:
    """Walk-forward feature/outcome rows for calibration only."""
    threshold = _decision_rank(minimum_decision)
    output: list[dict[str, object]] = []

    for trading_date in sorted(frames_by_date):
        frame = frames_by_date[trading_date].copy()
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
        frame = (
            frame.dropna(subset=["timestamp", "open", "high", "low", "close", "volume"])
            .sort_values("timestamp")
            .drop_duplicates("timestamp", keep="last")
            .reset_index(drop=True)
        )
        if len(frame) < minimum_history:
            continue

        for end in range(minimum_history, len(frame)):
            visible = frame.iloc[: end + 1].copy()
            features = latest_directional_features(visible)
            regime = classify_directional_regime(features)
            transition = evaluate_shadow_directional_transition(features, regime=regime)
            transition_record = transition.as_record()

            if transition_record.get("direction") not in {"BULLISH", "BEARISH"}:
                continue
            if _decision_rank(transition_record.get("decision")) < threshold:
                continue

            feature_record = features.as_dict()
            timestamp = pd.Timestamp(feature_record["timestamp"])
            direction = str(transition_record["direction"])
            dmi_gap = float(feature_record["plus_di"]) - float(feature_record["minus_di"])
            displacement = float(feature_record["displacement_atr"])

            record = {
                **transition_record,
                **feature_record,
                "timestamp": timestamp.isoformat(),
                "candle_timestamp": timestamp.isoformat(),
                "trading_date": trading_date.isoformat(),
                "time_bucket": _time_bucket(timestamp),
                "dmi_gap": abs(dmi_gap),
                "directional_dmi_gap": dmi_gap if direction == "BULLISH" else -dmi_gap,
                "directional_displacement_atr": (
                    displacement if direction == "BULLISH" else -displacement
                ),
                "execution_allowed": False,
                "source": "SHADOW_DIRECTIONAL_FEATURE_CALIBRATION",
            }
            outcome = evaluate_shadow_outcome(frame, record).as_record()
            record.update(outcome)
            record["execution_allowed"] = False
            output.append(record)

    return output


def summarize_group(
    rows: Iterable[Mapping[str, object]],
    *,
    group_name: str,
    group_value: object,
    baseline_accuracy: float | None,
) -> dict[str, object]:
    items = list(rows)
    resolved = [row for row in items if row.get("direction_correct_30m") is not None]
    accuracy = _accuracy(resolved)
    mfe = [
        float(row["maximum_favorable_excursion"])
        for row in resolved
        if row.get("maximum_favorable_excursion") is not None
    ]
    mae = [
        float(row["maximum_adverse_excursion"])
        for row in resolved
        if row.get("maximum_adverse_excursion") is not None
    ]
    avg_mfe = _safe_mean(mfe)
    avg_mae = _safe_mean(mae)
    return {
        "feature": group_name,
        "segment": str(group_value),
        "samples": len(items),
        "resolved_30m": len(resolved),
        "accuracy_30m": accuracy,
        "lift_vs_baseline": (
            round(accuracy - baseline_accuracy, 2)
            if accuracy is not None and baseline_accuracy is not None
            else None
        ),
        "average_mfe": avg_mfe,
        "average_mae": avg_mae,
        "mfe_mae_ratio": (
            round(avg_mfe / avg_mae, 3)
            if avg_mfe is not None and avg_mae not in {None, 0}
            else None
        ),
        "execution_allowed": False,
    }


def analyze_categorical(
    rows: Iterable[Mapping[str, object]],
    field: str,
) -> list[dict[str, object]]:
    items = list(rows)
    baseline = _accuracy(items)
    grouped: dict[str, list[Mapping[str, object]]] = {}
    for row in items:
        grouped.setdefault(str(row.get(field) or "UNKNOWN"), []).append(row)
    return [
        summarize_group(
            group,
            group_name=field,
            group_value=value,
            baseline_accuracy=baseline,
        )
        for value, group in sorted(grouped.items())
    ]


def analyze_numeric_quantiles(
    rows: Iterable[Mapping[str, object]],
    field: str,
    *,
    bins: int = 4,
) -> list[dict[str, object]]:
    items = [dict(row) for row in rows if row.get(field) is not None]
    if not items:
        return []
    frame = pd.DataFrame(items)
    frame[field] = pd.to_numeric(frame[field], errors="coerce")
    frame = frame.dropna(subset=[field])
    if frame.empty or frame[field].nunique() < 2:
        return []

    requested_bins = min(int(bins), int(frame[field].nunique()))
    try:
        labels = pd.qcut(frame[field], q=requested_bins, duplicates="drop")
    except ValueError:
        return []
    frame["_segment"] = labels.astype(str)
    baseline = _accuracy(frame.to_dict("records"))

    output = []
    for segment, group in frame.groupby("_segment", observed=True):
        output.append(
            summarize_group(
                group.to_dict("records"),
                group_name=field,
                group_value=segment,
                baseline_accuracy=baseline,
            )
        )
    return output


def analyze_evidence(
    rows: Iterable[Mapping[str, object]],
    *,
    minimum_samples: int = 10,
) -> list[dict[str, object]]:
    items = list(rows)
    baseline = _accuracy(items)
    grouped: dict[str, list[Mapping[str, object]]] = {}
    for row in items:
        evidence = row.get("evidence") or []
        if isinstance(evidence, str):
            evidence = [evidence]
        for tag in evidence:
            grouped.setdefault(str(tag), []).append(row)
    output = [
        summarize_group(
            group,
            group_name="evidence",
            group_value=tag,
            baseline_accuracy=baseline,
        )
        for tag, group in grouped.items()
        if len(group) >= minimum_samples
    ]
    return sorted(
        output,
        key=lambda row: (
            -(float(row.get("lift_vs_baseline") or -999)),
            -int(row.get("samples") or 0),
        ),
    )


def analyze_evidence_pairs(
    rows: Iterable[Mapping[str, object]],
    *,
    minimum_samples: int = 10,
) -> list[dict[str, object]]:
    items = list(rows)
    baseline = _accuracy(items)
    grouped: dict[str, list[Mapping[str, object]]] = {}
    for row in items:
        evidence = row.get("evidence") or []
        if isinstance(evidence, str):
            evidence = [evidence]
        tags = sorted({str(tag) for tag in evidence})
        for left, right in combinations(tags, 2):
            grouped.setdefault(f"{left} + {right}", []).append(row)
    output = [
        summarize_group(
            group,
            group_name="evidence_pair",
            group_value=pair,
            baseline_accuracy=baseline,
        )
        for pair, group in grouped.items()
        if len(group) >= minimum_samples
    ]
    return sorted(
        output,
        key=lambda row: (
            -(float(row.get("lift_vs_baseline") or -999)),
            -int(row.get("samples") or 0),
        ),
    )


@dataclass(frozen=True)
class CalibrationRecommendation:
    priority: int
    feature: str
    segment: str
    samples: int
    accuracy_30m: float
    lift_vs_baseline: float
    mfe_mae_ratio: float | None
    recommendation: str

    def as_record(self) -> dict[str, object]:
        return {
            **self.__dict__,
            "execution_allowed": False,
        }


def build_recommendations(
    analyses: Iterable[Mapping[str, object]],
    *,
    minimum_samples: int = 20,
    minimum_lift: float = 5.0,
    minimum_accuracy: float = 55.0,
) -> list[dict[str, object]]:
    candidates: list[CalibrationRecommendation] = []
    for row in analyses:
        samples = int(row.get("samples") or 0)
        accuracy = row.get("accuracy_30m")
        lift = row.get("lift_vs_baseline")
        ratio = row.get("mfe_mae_ratio")
        if (
            samples < minimum_samples
            or accuracy is None
            or lift is None
            or float(accuracy) < minimum_accuracy
            or float(lift) < minimum_lift
        ):
            continue
        feature = str(row.get("feature") or "")
        segment = str(row.get("segment") or "")
        candidates.append(
            CalibrationRecommendation(
                priority=0,
                feature=feature,
                segment=segment,
                samples=samples,
                accuracy_30m=float(accuracy),
                lift_vs_baseline=float(lift),
                mfe_mae_ratio=float(ratio) if ratio is not None else None,
                recommendation=(
                    f"Research candidate: require or up-weight {feature} segment "
                    f"{segment}; validate out-of-sample before changing engine weights."
                ),
            )
        )

    candidates.sort(
        key=lambda item: (
            -item.lift_vs_baseline,
            -item.accuracy_30m,
            -item.samples,
        )
    )
    return [
        CalibrationRecommendation(
            priority=index,
            feature=item.feature,
            segment=item.segment,
            samples=item.samples,
            accuracy_30m=item.accuracy_30m,
            lift_vs_baseline=item.lift_vs_baseline,
            mfe_mae_ratio=item.mfe_mae_ratio,
            recommendation=item.recommendation,
        ).as_record()
        for index, item in enumerate(candidates[:20], start=1)
    ]


class ShadowFeatureCalibrationService:
    def analyze(
        self,
        rows: Iterable[Mapping[str, object]],
        *,
        minimum_segment_samples: int = 10,
    ) -> dict[str, object]:
        items = list(rows)
        baseline = {
            "samples": len(items),
            "resolved_30m": sum(
                row.get("direction_correct_30m") is not None for row in items
            ),
            "accuracy_30m": _accuracy(items),
            "average_mfe": _safe_mean([
                float(row["maximum_favorable_excursion"])
                for row in items
                if row.get("maximum_favorable_excursion") is not None
            ]),
            "average_mae": _safe_mean([
                float(row["maximum_adverse_excursion"])
                for row in items
                if row.get("maximum_adverse_excursion") is not None
            ]),
            "execution_allowed": False,
        }

        numeric = []
        for field in NUMERIC_FEATURES:
            numeric.extend(analyze_numeric_quantiles(items, field))

        categorical = []
        for field in CATEGORICAL_FEATURES:
            categorical.extend(analyze_categorical(items, field))

        evidence = analyze_evidence(
            items,
            minimum_samples=minimum_segment_samples,
        )
        evidence_pairs = analyze_evidence_pairs(
            items,
            minimum_samples=minimum_segment_samples,
        )

        all_segments = numeric + categorical + evidence + evidence_pairs
        recommendations = build_recommendations(
            all_segments,
            minimum_samples=max(20, minimum_segment_samples),
        )

        strongest = sorted(
            [
                row for row in all_segments
                if int(row.get("samples") or 0) >= minimum_segment_samples
                and row.get("accuracy_30m") is not None
            ],
            key=lambda row: (
                -(float(row.get("lift_vs_baseline") or -999)),
                -int(row.get("samples") or 0),
            ),
        )[:25]

        weakest = sorted(
            [
                row for row in all_segments
                if int(row.get("samples") or 0) >= minimum_segment_samples
                and row.get("accuracy_30m") is not None
            ],
            key=lambda row: (
                float(row.get("lift_vs_baseline") or 999),
                -int(row.get("samples") or 0),
            ),
        )[:25]

        return {
            "baseline": baseline,
            "numeric_segments": numeric,
            "categorical_segments": categorical,
            "evidence_segments": evidence,
            "evidence_pair_segments": evidence_pairs,
            "strongest_segments": strongest,
            "weakest_segments": weakest,
            "recommendations": recommendations,
            "rows": items,
            "execution_allowed": False,
        }
