"""Descriptive cross-session analysis for historical PCR evidence datasets.

The analyzer is intentionally observational. It summarizes how evidence features
co-occur with later NIFTY point changes and does not emit trade signals,
recommendations, or inferred/missing values.
"""

from __future__ import annotations

import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field

FORWARD_FIELDS = (
    "forward_change_5m",
    "forward_change_10m",
    "forward_change_15m",
    "forward_change_30m",
)

LEVEL_FEATURES = (
    "fixed_pcr",
    "moving_pcr",
    "full_pcr",
)

SIGNED_FEATURES = (
    "fixed_pcr_change_5m",
    "fixed_pcr_change_15m",
    "fixed_pcr_change_30m",
    "moving_pcr_change_5m",
    "moving_pcr_change_15m",
    "moving_pcr_change_30m",
    "full_pcr_change_5m",
    "full_pcr_change_15m",
    "full_pcr_change_30m",
    "fixed_moving_pcr_spread",
    "atm_divergence_points",
    "fixed_oi_imbalance_pct",
    "moving_oi_imbalance_pct",
    "full_oi_imbalance_pct",
)

LEVEL_BUCKET_LABELS = ("VERY_LOW", "LOW", "MID", "HIGH", "VERY_HIGH")
SIGNED_BUCKET_LABELS = (
    "STRONG_FALLING",
    "FALLING",
    "MIDDLE",
    "RISING",
    "STRONG_RISING",
)


class HistoricalAnalysisModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ForwardStats(HistoricalAnalysisModel):
    count: int
    session_count: int
    mean: float | None = None
    median: float | None = None
    mean_absolute: float | None = None
    stdev: float | None = None
    positive_pct: float | None = None
    negative_pct: float | None = None
    zero_pct: float | None = None
    positive_session_pct: float | None = None
    negative_session_pct: float | None = None
    flat_session_pct: float | None = None


class FeatureBucket(HistoricalAnalysisModel):
    label: str
    lower_bound: float | None = None
    upper_bound: float | None = None
    row_count: int
    session_count: int
    forwards: dict[str, ForwardStats]


class FeatureAnalysis(HistoricalAnalysisModel):
    feature: str
    kind: str
    available_row_count: int
    session_count: int
    thresholds: list[float]
    correlations: dict[str, float | None]
    buckets: list[FeatureBucket]


class HistoricalAnalysisReport(HistoricalAnalysisModel):
    status: str
    source: str
    row_count: int
    session_count: int
    first_session_date: str | None = None
    last_session_date: str | None = None
    methodology: list[str] = Field(default_factory=list)
    feature_analyses: list[FeatureAnalysis]


def _to_float(value: str | float | int | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return None
    return converted if math.isfinite(converted) else None


def load_evidence_csv(path: str | Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"session_date", "timestamp", *FORWARD_FIELDS}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"historical evidence CSV missing columns: {', '.join(sorted(missing))}")
        for raw in reader:
            row: dict[str, object] = dict(raw)
            # Keep identifiers as text. Convert all known numeric evidence fields.
            for key in set(LEVEL_FEATURES) | set(SIGNED_FEATURES) | set(FORWARD_FIELDS) | {
                "fixed_call_oi_change_pct", "fixed_put_oi_change_pct",
                "moving_call_oi_change_pct", "moving_put_oi_change_pct",
                "full_call_oi_change_pct", "full_put_oi_change_pct",
            }:
                if key in row:
                    row[key] = _to_float(raw.get(key))
            pairs = {
                "fixed_oi_imbalance_pct": ("fixed_put_oi_change_pct", "fixed_call_oi_change_pct"),
                "moving_oi_imbalance_pct": ("moving_put_oi_change_pct", "moving_call_oi_change_pct"),
                "full_oi_imbalance_pct": ("full_put_oi_change_pct", "full_call_oi_change_pct"),
            }
            for target, (put_key, call_key) in pairs.items():
                put_value = row.get(put_key)
                call_value = row.get(call_key)
                row[target] = (
                    float(put_value) - float(call_value)
                    if isinstance(put_value, float) and isinstance(call_value, float)
                    else None
                )
            rows.append(row)
    return rows


def _quantile(values: list[float], probability: float) -> float:
    """Linear-interpolated quantile, deterministic and dependency-free."""
    ordered = sorted(values)
    if not ordered:
        raise ValueError("quantile requires values")
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * probability
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    weight = index - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _thresholds(values: list[float]) -> list[float]:
    return [_quantile(values, probability) for probability in (0.2, 0.4, 0.6, 0.8)]


def _bucket_index(value: float, thresholds: list[float]) -> int:
    for index, threshold in enumerate(thresholds):
        if value <= threshold:
            return index
    return 4


def _pct(part: int, whole: int) -> float | None:
    return (part * 100.0 / whole) if whole else None


def _forward_stats(rows: Iterable[dict[str, object]], forward_field: str) -> ForwardStats:
    values: list[tuple[str, float]] = []
    for row in rows:
        value = row.get(forward_field)
        session = row.get("session_date")
        if isinstance(value, (int, float)) and not isinstance(value, bool) and isinstance(session, str):
            values.append((session, float(value)))
    if not values:
        return ForwardStats(count=0, session_count=0)

    numeric = [value for _, value in values]
    by_session: dict[str, list[float]] = defaultdict(list)
    for session, value in values:
        by_session[session].append(value)
    session_means = [statistics.fmean(items) for items in by_session.values()]

    return ForwardStats(
        count=len(numeric),
        session_count=len(by_session),
        mean=statistics.fmean(numeric),
        median=statistics.median(numeric),
        mean_absolute=statistics.fmean(abs(value) for value in numeric),
        stdev=statistics.stdev(numeric) if len(numeric) > 1 else 0.0,
        positive_pct=_pct(sum(value > 0 for value in numeric), len(numeric)),
        negative_pct=_pct(sum(value < 0 for value in numeric), len(numeric)),
        zero_pct=_pct(sum(value == 0 for value in numeric), len(numeric)),
        positive_session_pct=_pct(sum(value > 0 for value in session_means), len(session_means)),
        negative_session_pct=_pct(sum(value < 0 for value in session_means), len(session_means)),
        flat_session_pct=_pct(sum(value == 0 for value in session_means), len(session_means)),
    )


def _pearson(rows: Iterable[dict[str, object]], feature: str, forward_field: str) -> float | None:
    pairs: list[tuple[float, float]] = []
    for row in rows:
        x = row.get(feature)
        y = row.get(forward_field)
        if (
            isinstance(x, (int, float)) and not isinstance(x, bool)
            and isinstance(y, (int, float)) and not isinstance(y, bool)
        ):
            pairs.append((float(x), float(y)))
    if len(pairs) < 2:
        return None
    xs = [pair[0] for pair in pairs]
    ys = [pair[1] for pair in pairs]
    mean_x = statistics.fmean(xs)
    mean_y = statistics.fmean(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in pairs)
    denominator = math.sqrt(
        sum((x - mean_x) ** 2 for x in xs) * sum((y - mean_y) ** 2 for y in ys)
    )
    return numerator / denominator if denominator else None


def analyze_feature(rows: list[dict[str, object]], feature: str, kind: str) -> FeatureAnalysis:
    available_rows = [
        row for row in rows
        if isinstance(row.get(feature), (int, float)) and not isinstance(row.get(feature), bool)
    ]
    values = [float(row[feature]) for row in available_rows]
    sessions = {str(row["session_date"]) for row in available_rows if row.get("session_date")}
    if not values:
        return FeatureAnalysis(
            feature=feature,
            kind=kind,
            available_row_count=0,
            session_count=0,
            thresholds=[],
            correlations={field: None for field in FORWARD_FIELDS},
            buckets=[],
        )

    thresholds = _thresholds(values)
    labels = LEVEL_BUCKET_LABELS if kind == "level" else SIGNED_BUCKET_LABELS
    grouped: list[list[dict[str, object]]] = [[] for _ in range(5)]
    for row in available_rows:
        grouped[_bucket_index(float(row[feature]), thresholds)].append(row)

    buckets: list[FeatureBucket] = []
    for index, bucket_rows in enumerate(grouped):
        lower = None if index == 0 else thresholds[index - 1]
        upper = None if index == 4 else thresholds[index]
        buckets.append(FeatureBucket(
            label=labels[index],
            lower_bound=lower,
            upper_bound=upper,
            row_count=len(bucket_rows),
            session_count=len({str(row["session_date"]) for row in bucket_rows}),
            forwards={field: _forward_stats(bucket_rows, field) for field in FORWARD_FIELDS},
        ))

    return FeatureAnalysis(
        feature=feature,
        kind=kind,
        available_row_count=len(available_rows),
        session_count=len(sessions),
        thresholds=thresholds,
        correlations={field: _pearson(available_rows, feature, field) for field in FORWARD_FIELDS},
        buckets=buckets,
    )


def build_historical_analysis_report(
    rows: list[dict[str, object]],
    source: str,
) -> HistoricalAnalysisReport:
    sessions = sorted({str(row["session_date"]) for row in rows if row.get("session_date")})
    analyses = [analyze_feature(rows, feature, "level") for feature in LEVEL_FEATURES]
    analyses.extend(analyze_feature(rows, feature, "signed") for feature in SIGNED_FEATURES)
    return HistoricalAnalysisReport(
        status="AVAILABLE" if rows else "UNAVAILABLE",
        source=source,
        row_count=len(rows),
        session_count=len(sessions),
        first_session_date=sessions[0] if sessions else None,
        last_session_date=sessions[-1] if sessions else None,
        methodology=[
            "Observational descriptive analysis only; no BUY/SELL classification.",
            "Five feature buckets use dataset-derived 20/40/60/80 percentile thresholds.",
            "Forward outcomes use only values already present in the evidence dataset.",
            "Session counts and session-mean direction percentages are reported because minute rows are not independent observations.",
            "OI imbalance is Put OI change % minus Call OI change % for the same panel.",
        ],
        feature_analyses=analyses,
    )


def analyze_historical_evidence_csv(path: str | Path) -> HistoricalAnalysisReport:
    rows = load_evidence_csv(path)
    return build_historical_analysis_report(rows, str(path))


def write_historical_analysis_json(report: HistoricalAnalysisReport, path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
