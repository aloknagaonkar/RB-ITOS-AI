"""Stage-2 success-vs-false-warning descriptive research.

Joins frozen Stage-2 reversal events back to the historical evidence row at T0 and
compares information that was available at event time. This module intentionally
learns no thresholds and emits no trade signal.

Strike-level premium/OI positioning is NOT present in the current historical
evidence CSV schema, so this v1 report measures the PCR/panel/OI context first and
reports that limitation explicitly. A later historical positioning evidence layer
can join on the same (session_date, timestamp) event identity without changing the
frozen Stage-2 definition.
"""

from __future__ import annotations

import csv
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field

STAGE_2 = "STAGE_2_5M_15M_BEARISH_30M_RISING"
TARGET_SUCCESS = "TRUE_BEARISH_REVERSAL"
TARGET_FALSE = "FALSE_WARNING"

FEATURES = (
    "fixed_pcr",
    "moving_pcr",
    "full_pcr",
    "fixed_moving_pcr_spread",
    "fixed_pcr_change_1m",
    "fixed_pcr_change_5m",
    "fixed_pcr_change_15m",
    "fixed_pcr_change_30m",
    "moving_pcr_change_1m",
    "moving_pcr_change_5m",
    "moving_pcr_change_15m",
    "moving_pcr_change_30m",
    "full_pcr_change_1m",
    "full_pcr_change_5m",
    "full_pcr_change_15m",
    "full_pcr_change_30m",
    "fixed_call_oi_change_pct",
    "fixed_put_oi_change_pct",
    "moving_call_oi_change_pct",
    "moving_put_oi_change_pct",
    "full_call_oi_change_pct",
    "full_put_oi_change_pct",
    "atm_divergence_points",
)


class ResearchModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Distribution(ResearchModel):
    count: int
    mean: float | None = None
    median: float | None = None
    q25: float | None = None
    q75: float | None = None


class FeatureComparison(ResearchModel):
    feature: str
    success: Distribution
    false_warning: Distribution
    median_difference_success_minus_false: float | None = None
    standardized_median_difference: float | None = None
    block_direction_consistency_count: int = 0
    block_available_count: int = 0


class BlockSummary(ResearchModel):
    block: str
    evidence_source: str
    reversal_source: str
    evidence_row_count: int
    stage_2_event_count: int
    joined_event_count: int
    target_success_count: int
    target_false_warning_count: int
    other_outcome_counts: dict[str, int]


class Stage2DiscriminatorReport(ResearchModel):
    status: Literal["AVAILABLE", "UNAVAILABLE"]
    stage: str = STAGE_2
    target_success_label: str = TARGET_SUCCESS
    target_false_label: str = TARGET_FALSE
    block_count: int
    total_evidence_rows: int
    total_stage_2_events: int
    total_joined_events: int
    total_success_events: int
    total_false_warning_events: int
    blocks: list[BlockSummary]
    features: list[FeatureComparison]
    methodology: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


def _number(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _quantile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * p
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _distribution(values: Iterable[float]) -> Distribution:
    data = list(values)
    if not data:
        return Distribution(count=0)
    return Distribution(
        count=len(data),
        mean=statistics.fmean(data),
        median=statistics.median(data),
        q25=_quantile(data, 0.25),
        q75=_quantile(data, 0.75),
    )


def _load_evidence(path: str | Path) -> tuple[int, dict[tuple[str, str], dict[str, str]]]:
    source = Path(path)
    with source.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"session_date", "timestamp", *FEATURES}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"evidence CSV missing required fields: {sorted(missing)}")
        rows: dict[tuple[str, str], dict[str, str]] = {}
        count = 0
        for row in reader:
            count += 1
            timestamp = datetime.fromisoformat(row["timestamp"]).isoformat()
            key = (row["session_date"], timestamp)
            if key in rows:
                raise ValueError(f"duplicate evidence identity: {key}")
            rows[key] = row
    return count, rows


def _load_stage2_events(path: str | Path) -> list[dict]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if payload.get("status") != "AVAILABLE":
        raise ValueError(f"reversal report is not AVAILABLE: {source}")
    stage = next((item for item in payload.get("stages", []) if item.get("stage") == STAGE_2), None)
    if stage is None:
        raise ValueError(f"Stage 2 missing from reversal report: {source}")
    return list(stage.get("events", []))


def _event_key(event: dict) -> tuple[str, str]:
    return event["session_date"], datetime.fromisoformat(event["event_time"]).isoformat()


def analyze_stage2_discriminator(
    blocks: Iterable[tuple[str, str | Path, str | Path]],
) -> Stage2DiscriminatorReport:
    block_specs = list(blocks)
    if not block_specs:
        raise ValueError("at least one block is required")
    if len({name for name, _, _ in block_specs}) != len(block_specs):
        raise ValueError("block names must be unique")

    block_summaries: list[BlockSummary] = []
    combined_values: dict[str, dict[str, list[float]]] = {
        feature: {TARGET_SUCCESS: [], TARGET_FALSE: []} for feature in FEATURES
    }
    block_medians: dict[str, list[float]] = defaultdict(list)
    total_rows = total_events = total_joined = total_success = total_false = 0

    for name, evidence_path, reversal_path in block_specs:
        evidence_count, evidence = _load_evidence(evidence_path)
        events = _load_stage2_events(reversal_path)
        total_rows += evidence_count
        total_events += len(events)
        joined = 0
        success_count = 0
        false_count = 0
        other = Counter()
        local_values: dict[str, dict[str, list[float]]] = {
            feature: {TARGET_SUCCESS: [], TARGET_FALSE: []} for feature in FEATURES
        }

        for event in events:
            row = evidence.get(_event_key(event))
            if row is None:
                continue
            joined += 1
            label = event.get("response_label")
            if label == TARGET_SUCCESS:
                success_count += 1
            elif label == TARGET_FALSE:
                false_count += 1
            else:
                other[str(label)] += 1
                continue
            for feature in FEATURES:
                value = _number(row.get(feature))
                if value is None:
                    continue
                local_values[feature][label].append(value)
                combined_values[feature][label].append(value)

        total_joined += joined
        total_success += success_count
        total_false += false_count
        block_summaries.append(BlockSummary(
            block=name,
            evidence_source=str(evidence_path),
            reversal_source=str(reversal_path),
            evidence_row_count=evidence_count,
            stage_2_event_count=len(events),
            joined_event_count=joined,
            target_success_count=success_count,
            target_false_warning_count=false_count,
            other_outcome_counts=dict(sorted(other.items())),
        ))

        for feature in FEATURES:
            s = _distribution(local_values[feature][TARGET_SUCCESS])
            f = _distribution(local_values[feature][TARGET_FALSE])
            if s.median is not None and f.median is not None:
                block_medians[feature].append(s.median - f.median)

    comparisons: list[FeatureComparison] = []
    for feature in FEATURES:
        s = _distribution(combined_values[feature][TARGET_SUCCESS])
        f = _distribution(combined_values[feature][TARGET_FALSE])
        median_difference = None
        standardized = None
        if s.median is not None and f.median is not None:
            median_difference = s.median - f.median
            iqr_s = (s.q75 - s.q25) if s.q25 is not None and s.q75 is not None else 0.0
            iqr_f = (f.q75 - f.q25) if f.q25 is not None and f.q75 is not None else 0.0
            pooled_iqr = (iqr_s + iqr_f) / 2
            if pooled_iqr > 0:
                standardized = median_difference / pooled_iqr
        directions = block_medians.get(feature, [])
        if median_difference is None or median_difference == 0:
            consistency = sum(value == 0 for value in directions)
        else:
            sign = 1 if median_difference > 0 else -1
            consistency = sum((1 if value > 0 else -1 if value < 0 else 0) == sign for value in directions)
        comparisons.append(FeatureComparison(
            feature=feature,
            success=s,
            false_warning=f,
            median_difference_success_minus_false=median_difference,
            standardized_median_difference=standardized,
            block_direction_consistency_count=consistency,
            block_available_count=len(directions),
        ))

    comparisons.sort(key=lambda item: (
        item.standardized_median_difference is not None,
        abs(item.standardized_median_difference or 0.0),
        item.block_direction_consistency_count,
    ), reverse=True)

    status = "AVAILABLE" if total_success and total_false else "UNAVAILABLE"
    return Stage2DiscriminatorReport(
        status=status,
        block_count=len(block_specs),
        total_evidence_rows=total_rows,
        total_stage_2_events=total_events,
        total_joined_events=total_joined,
        total_success_events=total_success,
        total_false_warning_events=total_false,
        blocks=block_summaries,
        features=comparisons,
        methodology=[
            "Stage 2 remains frozen: Moving PCR 5m and 15m falling while 30m is rising.",
            "Only first-entry Stage-2 events from the existing reversal reports are analyzed; no minute-state re-counting occurs.",
            "Each event is joined to the exact same-session evidence row at T0; no interpolation or nearest-time matching is used.",
            "Primary contrast is TRUE_BEARISH_REVERSAL versus FALSE_WARNING using only features already available at T0.",
            "No discriminator threshold is learned in this report; feature ranking is descriptive only.",
            "Block-direction consistency shows whether the sign of the median difference agrees with the combined result across blocks.",
        ],
        limitations=[
            "Current historical evidence CSV does not contain per-strike option premium/close plus OI history, so same-strike CE/PE positioning confirmation is not yet included in this v1 discriminator.",
            "The next positioning layer should be produced from reconstructed option candles and joined to these same frozen Stage-2 event timestamps without changing the Stage-2 definition.",
            "Outcome labels are research labels from the existing reversal analyzer and are not trade signals or option-P&L outcomes.",
        ],
    )


def write_stage2_discriminator_json(report: Stage2DiscriminatorReport, path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
