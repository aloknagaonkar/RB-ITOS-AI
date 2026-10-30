"""Compare PCR deep-analysis reports across TRAIN, OOS-A and OOS-B.

This module does not learn or tune thresholds. It compares already-computed
PCR deep-analysis reports using the same fixed definitions in every block.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field

FORWARD_FIELD = "forward_change_15m"

# Candidate definitions frozen from the training exploration. The comparison
# code does not alter these definitions based on OOS results.
CANDIDATES = (
    ("moving", "level_plus_turn", "PCR_LT_0_70_AND_5M_RISING", "BULLISH"),
    ("moving", "level_plus_turn", "PCR_GT_1_25_AND_5M_FALLING", "BEARISH"),
    ("moving", "early_flip_candidates", "BEARISH_5M_15M_FLIP_WHILE_30M_RISING", "BEARISH"),
)


class CompareModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class BlockCandidateStats(CompareModel):
    block: str
    source: str
    row_count: int
    session_count: int
    forward_count_15m: int
    forward_session_count_15m: int
    mean_15m: float | None = None
    median_15m: float | None = None
    bullish_pct_15m: float | None = None
    bearish_pct_15m: float | None = None
    directional_hit_pct_15m: float | None = None
    direction_supported: bool | None = None


class CandidateComparison(CompareModel):
    panel: str
    family: str
    condition: str
    expected_direction: str
    blocks: list[BlockCandidateStats]
    all_blocks_direction_supported: bool
    all_blocks_positive_sample: bool
    consistent_direction_count: int
    validation_status: str


class PCRDeepComparisonReport(CompareModel):
    status: str
    training_source: str
    oos_a_source: str
    oos_b_source: str
    total_row_count: int
    total_session_count: int
    methodology: list[str] = Field(default_factory=list)
    candidates: list[CandidateComparison]


def _load(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _find_panel(report: dict, panel: str) -> dict:
    for item in report.get("panels", []):
        if item.get("panel") == panel:
            return item
    raise ValueError(f"panel not found: {panel}")


def _find_condition(report: dict, panel: str, family: str, condition: str) -> dict:
    panel_obj = _find_panel(report, panel)
    for item in panel_obj.get(family, []):
        if item.get("condition") == condition:
            return item
    raise ValueError(f"condition not found: {panel}.{family}.{condition}")


def _direction_supported(mean: float | None, median: float | None, direction: str) -> bool | None:
    if mean is None or median is None:
        return None
    if direction == "BULLISH":
        return mean > 0 and median > 0
    if direction == "BEARISH":
        return mean < 0 and median < 0
    raise ValueError(f"unsupported direction: {direction}")


def _block_stats(block: str, report: dict, panel: str, family: str, condition: str, direction: str) -> BlockCandidateStats:
    item = _find_condition(report, panel, family, condition)
    forward = item.get("forwards", {}).get(FORWARD_FIELD, {})
    bullish = forward.get("bullish_pct")
    bearish = forward.get("bearish_pct")
    mean = forward.get("mean")
    median = forward.get("median")
    directional_hit = bullish if direction == "BULLISH" else bearish
    return BlockCandidateStats(
        block=block,
        source=str(report.get("source", "")),
        row_count=int(item.get("row_count", 0)),
        session_count=int(item.get("session_count", 0)),
        forward_count_15m=int(forward.get("count", 0)),
        forward_session_count_15m=int(forward.get("session_count", 0)),
        mean_15m=mean,
        median_15m=median,
        bullish_pct_15m=bullish,
        bearish_pct_15m=bearish,
        directional_hit_pct_15m=directional_hit,
        direction_supported=_direction_supported(mean, median, direction),
    )


def compare_reports(training: dict, oos_a: dict, oos_b: dict) -> PCRDeepComparisonReport:
    blocks = (("TRAIN", training), ("OOS_A", oos_a), ("OOS_B", oos_b))
    candidates: list[CandidateComparison] = []
    for panel, family, condition, direction in CANDIDATES:
        stats = [_block_stats(name, report, panel, family, condition, direction) for name, report in blocks]
        support_count = sum(item.direction_supported is True for item in stats)
        positive_sample = all(item.forward_count_15m > 0 and item.forward_session_count_15m > 0 for item in stats)
        all_supported = support_count == len(stats)
        if all_supported and positive_sample:
            validation_status = "CONSISTENT"
        elif support_count >= 2 and positive_sample:
            validation_status = "MIXED"
        else:
            validation_status = "WEAK_OR_UNAVAILABLE"
        candidates.append(CandidateComparison(
            panel=panel,
            family=family,
            condition=condition,
            expected_direction=direction,
            blocks=stats,
            all_blocks_direction_supported=all_supported,
            all_blocks_positive_sample=positive_sample,
            consistent_direction_count=support_count,
            validation_status=validation_status,
        ))

    return PCRDeepComparisonReport(
        status="AVAILABLE",
        training_source=str(training.get("source", "")),
        oos_a_source=str(oos_a.get("source", "")),
        oos_b_source=str(oos_b.get("source", "")),
        total_row_count=sum(int(report.get("row_count", 0)) for _, report in blocks),
        total_session_count=sum(int(report.get("session_count", 0)) for _, report in blocks),
        methodology=[
            "Candidate definitions are frozen from the training study and are not retuned on OOS-A or OOS-B.",
            "Validation compares the same condition across TRAIN, OOS-A and OOS-B.",
            "Primary comparison horizon is +15m for this v1 comparison report.",
            "Direction support requires both mean and median +15m move to have the expected sign.",
            "CONSISTENT means all three blocks support the expected direction with non-empty samples; MIXED means two of three do.",
            "This remains descriptive research and emits no BUY/SELL signal.",
        ],
        candidates=candidates,
    )


def compare_pcr_deep_json(training_path: str | Path, oos_a_path: str | Path, oos_b_path: str | Path) -> PCRDeepComparisonReport:
    return compare_reports(_load(training_path), _load(oos_a_path), _load(oos_b_path))


def write_pcr_deep_comparison_json(report: PCRDeepComparisonReport, path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
