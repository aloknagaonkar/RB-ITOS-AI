"""Five-block / 100-session comparison for frozen PCR Stage-2 reversal research.

This module does not discover or retune PCR conditions. It compares the same
Stage-2 definition across TRAIN and OOS-A/B/C/D, then aggregates event-level
lead/lag and response-label evidence across all five independent blocks.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

STAGE_2 = "STAGE_2_5M_15M_BEARISH_30M_RISING"
BLOCK_ORDER = ("TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D")


class CompareModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class BlockStage2(CompareModel):
    block: str
    source: str
    row_count: int
    session_count: int
    event_count: int
    event_session_count: int
    prior_uptrend_event_count: int
    pcr_led_price_count: int
    pcr_led_price_pct: float | None = None
    mean_lead_minutes: float | None = None
    median_lead_minutes: float | None = None
    mean_forward_15m: float | None = None
    median_forward_15m: float | None = None
    bearish_pct_15m: float | None = None
    response_counts: dict[str, int]
    bearish_direction_supported: bool
    lead_supported: bool


class CombinedStage2(CompareModel):
    total_row_count: int
    total_session_count: int
    event_count: int
    event_session_count_sum: int
    prior_uptrend_event_count: int
    pcr_led_price_count: int
    pcr_led_price_pct: float | None = None
    mean_lead_minutes: float | None = None
    median_lead_minutes: float | None = None
    mean_forward_15m: float | None = None
    median_forward_15m: float | None = None
    bearish_pct_15m: float | None = None
    response_counts: dict[str, int]


class PCRReversal100Report(CompareModel):
    status: str
    stage: str
    block_count: int
    total_row_count: int
    total_session_count: int
    methodology: list[str] = Field(default_factory=list)
    blocks: list[BlockStage2]
    combined: CombinedStage2
    bearish_direction_block_count: int
    lead_support_block_count: int
    robustness_status: str


def _load(path: str | Path) -> dict:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if data.get("status") != "AVAILABLE":
        raise ValueError(f"reversal report is not AVAILABLE: {path}")
    return data


def _stage2(data: dict, path: str | Path) -> dict:
    for stage in data.get("stages", []):
        if stage.get("stage") == STAGE_2:
            return stage
    raise ValueError(f"Stage 2 missing from reversal report: {path}")


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def compare_reversal_reports(paths: dict[str, str | Path]) -> PCRReversal100Report:
    if tuple(paths) != BLOCK_ORDER:
        raise ValueError(f"blocks must be supplied in order: {', '.join(BLOCK_ORDER)}")

    blocks: list[BlockStage2] = []
    all_events: list[dict] = []
    total_rows = 0
    total_sessions = 0
    combined_responses: dict[str, int] = {}

    for block in BLOCK_ORDER:
        path = paths[block]
        data = _load(path)
        s2 = _stage2(data, path)
        events = list(s2.get("events", []))
        all_events.extend(events)
        total_rows += int(data.get("row_count", 0))
        total_sessions += int(data.get("session_count", 0))
        for label, count in (s2.get("response_counts") or {}).items():
            combined_responses[label] = combined_responses.get(label, 0) + int(count)

        mean15 = s2.get("mean_forward_15m")
        median15 = s2.get("median_forward_15m")
        lead_pct = s2.get("pcr_led_price_pct")
        mean_lead = s2.get("mean_lead_minutes")
        bearish_supported = (
            isinstance(mean15, (int, float)) and mean15 < 0
            and isinstance(median15, (int, float)) and median15 < 0
        )
        lead_supported = (
            isinstance(lead_pct, (int, float)) and lead_pct > 50
            and isinstance(mean_lead, (int, float)) and mean_lead > 0
        )
        blocks.append(BlockStage2(
            block=block,
            source=str(data.get("source", path)),
            row_count=int(data.get("row_count", 0)),
            session_count=int(data.get("session_count", 0)),
            event_count=int(s2.get("event_count", 0)),
            event_session_count=int(s2.get("session_count", 0)),
            prior_uptrend_event_count=int(s2.get("prior_uptrend_event_count", 0)),
            pcr_led_price_count=int(s2.get("pcr_led_price_count", 0)),
            pcr_led_price_pct=lead_pct,
            mean_lead_minutes=mean_lead,
            median_lead_minutes=s2.get("median_lead_minutes"),
            mean_forward_15m=mean15,
            median_forward_15m=median15,
            bearish_pct_15m=s2.get("bearish_pct_15m"),
            response_counts={str(k): int(v) for k, v in (s2.get("response_counts") or {}).items()},
            bearish_direction_supported=bearish_supported,
            lead_supported=lead_supported,
        ))

    prior_uptrend = [e for e in all_events if isinstance(e.get("prior_change_15m"), (int, float)) and e["prior_change_15m"] > 0]
    lead_values = [float(e["price_turn_lead_minutes"]) for e in prior_uptrend if isinstance(e.get("price_turn_lead_minutes"), int) and e["price_turn_lead_minutes"] > 0]
    pcr_led = len(lead_values)
    forward15 = [float(e["forward_change_15m"]) for e in all_events if isinstance(e.get("forward_change_15m"), (int, float))]
    bearish_count = sum(v < 0 for v in forward15)

    combined = CombinedStage2(
        total_row_count=total_rows,
        total_session_count=total_sessions,
        event_count=len(all_events),
        event_session_count_sum=sum(b.event_session_count for b in blocks),
        prior_uptrend_event_count=len(prior_uptrend),
        pcr_led_price_count=pcr_led,
        pcr_led_price_pct=(pcr_led * 100.0 / len(prior_uptrend)) if prior_uptrend else None,
        mean_lead_minutes=_mean(lead_values),
        median_lead_minutes=_median(lead_values),
        mean_forward_15m=_mean(forward15),
        median_forward_15m=_median(forward15),
        bearish_pct_15m=(bearish_count * 100.0 / len(forward15)) if forward15 else None,
        response_counts=combined_responses,
    )

    bearish_blocks = sum(b.bearish_direction_supported for b in blocks)
    lead_blocks = sum(b.lead_supported for b in blocks)
    if bearish_blocks == 5 and lead_blocks == 5:
        robustness = "CONSISTENT_5_OF_5"
    elif bearish_blocks >= 4 and lead_blocks >= 4:
        robustness = "MOSTLY_CONSISTENT"
    else:
        robustness = "MIXED_OR_WEAK"

    return PCRReversal100Report(
        status="AVAILABLE",
        stage=STAGE_2,
        block_count=5,
        total_row_count=total_rows,
        total_session_count=total_sessions,
        methodology=[
            "Stage-2 definition is frozen: moving PCR 5m and 15m falling while 30m remains rising.",
            "No PCR thresholds or reversal definitions are retuned using OOS-C or OOS-D.",
            "Each block is analyzed independently before the five-block summary is produced.",
            "Bearish direction support requires both mean and median +15m NIFTY moves below zero.",
            "Lead support requires PCR-led-price percentage above 50% and positive mean lead time.",
            "Combined lead statistics are recomputed from event-level records, not averaged from block percentages.",
            "Research only; no BUY/SELL or option-premium assumption is emitted.",
        ],
        blocks=blocks,
        combined=combined,
        bearish_direction_block_count=bearish_blocks,
        lead_support_block_count=lead_blocks,
        robustness_status=robustness,
    )


def compare_reversal_report_files(
    training: str | Path,
    oos_a: str | Path,
    oos_b: str | Path,
    oos_c: str | Path,
    oos_d: str | Path,
) -> PCRReversal100Report:
    return compare_reversal_reports({
        "TRAIN": training,
        "OOS_A": oos_a,
        "OOS_B": oos_b,
        "OOS_C": oos_c,
        "OOS_D": oos_d,
    })


def write_pcr_reversal_100_json(report: PCRReversal100Report, path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(report.model_dump_json(indent=2), encoding="utf-8")
