"""Bidirectional PCR transition research over frozen historical blocks.

Bearish and bullish structures are evaluated independently.  The bullish side
is not inferred from bearish results: it is measured against the same evidence
blocks with symmetric, explicit price-turn and outcome rules.

Research only.  This module emits no CE/PE order or trade signal.
"""
from __future__ import annotations

import csv
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

FORWARD_MINUTES = (5, 10, 15, 30)
PRICE_TURN_SCAN_MINUTES = 15

DIRECTIONS = {
    "BEARISH": {
        "stage_1": (-1, 1, 1),
        "stage_2": (-1, -1, 1),
        "stage_3": (-1, -1, -1),
    },
    "BULLISH": {
        "stage_1": (1, -1, -1),
        "stage_2": (1, 1, -1),
        "stage_3": (1, 1, 1),
    },
}


class ResearchModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class DirectionBlockStats(ResearchModel):
    block: str
    source: str
    row_count: int
    session_count: int
    stage_2_event_count: int
    stage_2_event_session_count: int
    eligible_prior_trend_event_count: int
    price_already_turned_count: int
    pcr_led_price_count: int
    no_price_turn_within_15m_count: int
    pcr_led_price_pct: float | None = None
    mean_lead_minutes: float | None = None
    median_lead_minutes: float | None = None
    mean_forward_5m: float | None = None
    mean_forward_10m: float | None = None
    mean_forward_15m: float | None = None
    mean_forward_30m: float | None = None
    median_forward_15m: float | None = None
    directional_pct_15m: float | None = None
    response_counts: dict[str, int]
    direction_supported: bool
    lead_supported: bool


class DirectionCombinedStats(ResearchModel):
    direction: str
    event_count: int
    event_session_count_sum: int
    eligible_prior_trend_event_count: int
    pcr_led_price_count: int
    pcr_led_price_pct: float | None = None
    mean_lead_minutes: float | None = None
    median_lead_minutes: float | None = None
    mean_forward_15m: float | None = None
    median_forward_15m: float | None = None
    directional_pct_15m: float | None = None
    response_counts: dict[str, int]
    direction_support_block_count: int
    lead_support_block_count: int
    robustness_status: str


class DirectionReport(ResearchModel):
    direction: str
    stage_1_definition: str
    stage_2_definition: str
    stage_3_definition: str
    blocks: list[DirectionBlockStats]
    combined: DirectionCombinedStats


class BidirectionalReport(ResearchModel):
    status: str
    block_count: int
    total_row_count: int
    total_session_count: int
    methodology: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    bearish: DirectionReport
    bullish: DirectionReport


def _float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _parse_dt(value: object) -> datetime:
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def _load(path: str | Path) -> list[dict[str, object]]:
    required = {
        "session_date", "timestamp", "spot",
        "moving_pcr_change_5m", "moving_pcr_change_15m", "moving_pcr_change_30m",
        "forward_change_5m", "forward_change_10m", "forward_change_15m", "forward_change_30m",
    }
    numeric = required.difference({"session_date", "timestamp"})
    rows: list[dict[str, object]] = []
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError("historical evidence CSV missing columns: " + ", ".join(sorted(missing)))
        for raw in reader:
            row: dict[str, object] = dict(raw)
            for key in numeric:
                row[key] = _float(raw.get(key))
            row["dt"] = _parse_dt(raw.get("timestamp"))
            rows.append(row)
    return rows


def _sign(value: object) -> int | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _signs(row: dict[str, object]) -> tuple[int | None, int | None, int | None]:
    return (
        _sign(row.get("moving_pcr_change_5m")),
        _sign(row.get("moving_pcr_change_15m")),
        _sign(row.get("moving_pcr_change_30m")),
    )


def _event_rows(rows: list[dict[str, object]], expected: tuple[int, int, int]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    by_session: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        session = row.get("session_date")
        if isinstance(session, str):
            by_session[session].append(row)
    for session in sorted(by_session):
        was_in_state = False
        for row in sorted(by_session[session], key=lambda item: item["dt"]):
            in_state = _signs(row) == expected
            if in_state and not was_in_state:
                result.append(row)
            was_in_state = in_state
    return result


def _exact_change(by_time: dict[datetime, dict[str, object]], dt: datetime, minutes: int) -> float | None:
    now = by_time.get(dt)
    before = by_time.get(dt - timedelta(minutes=minutes))
    if not now or not before:
        return None
    a, b = now.get("spot"), before.get("spot")
    if not isinstance(a, float) or not isinstance(b, float):
        return None
    return a - b


def _forward(row: dict[str, object], minutes: int) -> float | None:
    value = row.get(f"forward_change_{minutes}m")
    return float(value) if isinstance(value, float) else None


def _first_price_turn(
    by_time: dict[datetime, dict[str, object]],
    event_dt: datetime,
    direction: str,
) -> int | None:
    desired_positive = direction == "BULLISH"
    for lead in range(0, PRICE_TURN_SCAN_MINUTES + 1):
        change = _exact_change(by_time, event_dt + timedelta(minutes=lead), 5)
        if change is None:
            continue
        if (desired_positive and change > 0) or ((not desired_positive) and change < 0):
            return lead
    return None


def _eligible(prior15: float | None, direction: str) -> bool:
    if prior15 is None:
        return False
    return prior15 < 0 if direction == "BULLISH" else prior15 > 0


def _response_label(
    direction: str,
    prior15: float | None,
    f5: float | None,
    f15: float | None,
    f30: float | None,
) -> str:
    if prior15 is None or f15 is None:
        return "UNAVAILABLE"
    bullish = direction == "BULLISH"
    prior_opposite = prior15 < 0 if bullish else prior15 > 0
    favorable15 = f15 > 0 if bullish else f15 < 0
    favorable30 = None if f30 is None else (f30 > 0 if bullish else f30 < 0)
    favorable5 = None if f5 is None else (f5 > 0 if bullish else f5 < 0)
    prefix = "BULLISH" if bullish else "BEARISH"
    if prior_opposite:
        if favorable15 and favorable30 is True:
            return f"TRUE_{prefix}_REVERSAL"
        if favorable15 and favorable30 is False:
            return f"{prefix}_PULLBACK"
        if favorable5 is True and not favorable15:
            return f"SHORT_{prefix}_REVERSAL"
        return f"FALSE_{prefix}_WARNING"
    if favorable15:
        return f"{prefix}_CONTINUATION"
    return f"FALSE_{prefix}_WARNING"


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _pct(part: int, whole: int) -> float | None:
    return part * 100.0 / whole if whole else None


def _analyze_block(name: str, path: str | Path, rows: list[dict[str, object]], direction: str) -> tuple[DirectionBlockStats, list[dict[str, object]]]:
    expected = DIRECTIONS[direction]["stage_2"]
    event_rows = _event_rows(rows, expected)
    by_session: dict[str, dict[datetime, dict[str, object]]] = defaultdict(dict)
    for row in rows:
        session, dt = row.get("session_date"), row.get("dt")
        if isinstance(session, str) and isinstance(dt, datetime):
            by_session[session][dt] = row

    events: list[dict[str, object]] = []
    for row in event_rows:
        session = str(row["session_date"])
        dt = row["dt"]
        if not isinstance(dt, datetime):
            continue
        lookup = by_session[session]
        prior15 = _exact_change(lookup, dt, 15)
        f5, f10, f15, f30 = (_forward(row, h) for h in FORWARD_MINUTES)
        lead = _first_price_turn(lookup, dt, direction)
        events.append({
            "session_date": session,
            "event_time": dt.isoformat(),
            "prior_change_15m": prior15,
            "forward_change_5m": f5,
            "forward_change_10m": f10,
            "forward_change_15m": f15,
            "forward_change_30m": f30,
            "price_turn_lead_minutes": lead,
            "response_label": _response_label(direction, prior15, f5, f15, f30),
        })

    eligible = [e for e in events if _eligible(e.get("prior_change_15m"), direction)]
    already = [e for e in eligible if e.get("price_turn_lead_minutes") == 0]
    led = [e for e in eligible if isinstance(e.get("price_turn_lead_minutes"), int) and e["price_turn_lead_minutes"] > 0]
    no_turn = [e for e in eligible if e.get("price_turn_lead_minutes") is None]
    lead_values = [float(e["price_turn_lead_minutes"]) for e in led]
    forward = {h: [float(e[f"forward_change_{h}m"]) for e in events if isinstance(e.get(f"forward_change_{h}m"), (int, float))] for h in FORWARD_MINUTES}
    f15s = forward[15]
    directional = sum(v > 0 for v in f15s) if direction == "BULLISH" else sum(v < 0 for v in f15s)
    responses: dict[str, int] = defaultdict(int)
    for e in events:
        responses[str(e["response_label"])] += 1
    mean15, median15 = _mean(f15s), _median(f15s)
    direction_supported = bool(
        isinstance(mean15, (int, float)) and isinstance(median15, (int, float))
        and ((direction == "BULLISH" and mean15 > 0 and median15 > 0)
             or (direction == "BEARISH" and mean15 < 0 and median15 < 0))
    )
    lead_pct = _pct(len(led), len(eligible))
    mean_lead = _mean(lead_values)
    stats = DirectionBlockStats(
        block=name,
        source=str(path),
        row_count=len(rows),
        session_count=len({str(r["session_date"]) for r in rows if r.get("session_date")}),
        stage_2_event_count=len(events),
        stage_2_event_session_count=len({str(e["session_date"]) for e in events}),
        eligible_prior_trend_event_count=len(eligible),
        price_already_turned_count=len(already),
        pcr_led_price_count=len(led),
        no_price_turn_within_15m_count=len(no_turn),
        pcr_led_price_pct=lead_pct,
        mean_lead_minutes=mean_lead,
        median_lead_minutes=_median(lead_values),
        mean_forward_5m=_mean(forward[5]),
        mean_forward_10m=_mean(forward[10]),
        mean_forward_15m=mean15,
        mean_forward_30m=_mean(forward[30]),
        median_forward_15m=median15,
        directional_pct_15m=_pct(directional, len(f15s)),
        response_counts=dict(sorted(responses.items())),
        direction_supported=direction_supported,
        lead_supported=bool(isinstance(lead_pct, (int, float)) and lead_pct > 50 and isinstance(mean_lead, (int, float)) and mean_lead > 0),
    )
    return stats, events


def _definition(direction: str, stage: int) -> str:
    arrow = "rising" if direction == "BULLISH" else "falling"
    opposite = "falling" if direction == "BULLISH" else "rising"
    if stage == 1:
        return f"5m {arrow}; 15m and 30m {opposite}"
    if stage == 2:
        return f"5m and 15m {arrow}; 30m {opposite}"
    return f"5m, 15m and 30m all {arrow}"


def _direction_report(blocks: list[tuple[str, str | Path, list[dict[str, object]]]], direction: str) -> DirectionReport:
    block_stats: list[DirectionBlockStats] = []
    all_events: list[dict[str, object]] = []
    for name, path, rows in blocks:
        stats, events = _analyze_block(name, path, rows, direction)
        block_stats.append(stats)
        all_events.extend(events)

    eligible = [e for e in all_events if _eligible(e.get("prior_change_15m"), direction)]
    led = [e for e in eligible if isinstance(e.get("price_turn_lead_minutes"), int) and e["price_turn_lead_minutes"] > 0]
    lead_values = [float(e["price_turn_lead_minutes"]) for e in led]
    f15s = [float(e["forward_change_15m"]) for e in all_events if isinstance(e.get("forward_change_15m"), (int, float))]
    directional = sum(v > 0 for v in f15s) if direction == "BULLISH" else sum(v < 0 for v in f15s)
    responses: dict[str, int] = defaultdict(int)
    for e in all_events:
        responses[str(e["response_label"])] += 1
    direction_blocks = sum(b.direction_supported for b in block_stats)
    lead_blocks = sum(b.lead_supported for b in block_stats)
    if direction_blocks == len(block_stats) and lead_blocks == len(block_stats):
        robustness = f"CONSISTENT_{len(block_stats)}_OF_{len(block_stats)}"
    elif direction_blocks >= max(1, len(block_stats) - 1) and lead_blocks >= max(1, len(block_stats) - 1):
        robustness = "MOSTLY_CONSISTENT"
    else:
        robustness = "MIXED_OR_WEAK"
    combined = DirectionCombinedStats(
        direction=direction,
        event_count=len(all_events),
        event_session_count_sum=sum(b.stage_2_event_session_count for b in block_stats),
        eligible_prior_trend_event_count=len(eligible),
        pcr_led_price_count=len(led),
        pcr_led_price_pct=_pct(len(led), len(eligible)),
        mean_lead_minutes=_mean(lead_values),
        median_lead_minutes=_median(lead_values),
        mean_forward_15m=_mean(f15s),
        median_forward_15m=_median(f15s),
        directional_pct_15m=_pct(directional, len(f15s)),
        response_counts=dict(sorted(responses.items())),
        direction_support_block_count=direction_blocks,
        lead_support_block_count=lead_blocks,
        robustness_status=robustness,
    )
    return DirectionReport(
        direction=direction,
        stage_1_definition=_definition(direction, 1),
        stage_2_definition=_definition(direction, 2),
        stage_3_definition=_definition(direction, 3),
        blocks=block_stats,
        combined=combined,
    )


def analyze_bidirectional_blocks(blocks: list[tuple[str, str | Path]]) -> BidirectionalReport:
    if not blocks:
        raise ValueError("at least one --block is required")
    loaded: list[tuple[str, str | Path, list[dict[str, object]]]] = []
    for name, path in blocks:
        rows = _load(path)
        if not rows:
            raise ValueError(f"evidence block has no rows: {path}")
        loaded.append((name, path, rows))
    total_rows = sum(len(rows) for _, _, rows in loaded)
    total_sessions = sum(len({str(r["session_date"]) for r in rows if r.get("session_date")}) for _, _, rows in loaded)
    return BidirectionalReport(
        status="AVAILABLE",
        block_count=len(loaded),
        total_row_count=total_rows,
        total_session_count=total_sessions,
        methodology=[
            "Bearish Stage 2 remains frozen as moving-PCR 5m and 15m falling while 30m is rising.",
            "Bullish Stage 2 is tested independently as the symmetric research candidate: 5m and 15m rising while 30m is falling.",
            "Persistent minute states are deduplicated into first-entry Stage-2 events within each session.",
            "Bearish lead is measured to the first exact rolling 5m NIFTY momentum below zero; bullish lead uses the first exact rolling 5m momentum above zero, both within 15 minutes.",
            "Bearish reversal eligibility requires prior 15m spot change above zero; bullish reversal eligibility requires prior 15m spot change below zero.",
            "Direction support requires both mean and median +15m spot move to agree with the researched direction.",
            "No bullish conclusion is inferred from bearish evidence; both directions are measured independently in every block.",
            "Research only; no CE/PE BUY or option-premium P&L signal is emitted.",
        ],
        limitations=[
            "The bullish Stage-2 condition is a new frozen research candidate and has not previously passed discovery/OOS validation.",
            "A rolling 5m spot-momentum sign turn is a timing proxy, not a complete market-structure reversal definition.",
            "Current evidence does not yet include per-strike option premium plus OI positioning or underlying volume timing.",
        ],
        bearish=_direction_report(loaded, "BEARISH"),
        bullish=_direction_report(loaded, "BULLISH"),
    )


def write_bidirectional_json(report: BidirectionalReport, path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
