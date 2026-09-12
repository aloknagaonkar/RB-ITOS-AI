"""Event-based PCR transition and early-reversal research.

This module promotes the strongest 60-session PCR candidate into an event-based
study without turning it into a trading signal.  It deduplicates persistent
minute states, measures Stage-1/2/3 PCR transitions, compares them with exact
rolling spot momentum, and labels the *price response* with explicit rules.

No option premium, execution, VWAP/EMA, or volume assumptions are introduced.
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

STAGES = {
    "STAGE_1_5M_BEARISH_ONLY": (-1, 1, 1),
    "STAGE_2_5M_15M_BEARISH_30M_RISING": (-1, -1, 1),
    "STAGE_3_ALL_5M_15M_30M_BEARISH": (-1, -1, -1),
}
FORWARD_MINUTES = (5, 10, 15, 30)
PRICE_TURN_SCAN_MINUTES = 15


class ReversalModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class EventOutcome(ReversalModel):
    session_date: str
    stage: str
    event_time: str
    spot: float
    prior_change_5m: float | None = None
    prior_change_15m: float | None = None
    prior_change_30m: float | None = None
    forward_change_5m: float | None = None
    forward_change_10m: float | None = None
    forward_change_15m: float | None = None
    forward_change_30m: float | None = None
    price_turn_lead_minutes: int | None = None
    price_state_at_event: str
    response_label: str


class StageStats(ReversalModel):
    stage: str
    event_count: int
    session_count: int
    prior_uptrend_event_count: int
    price_already_bearish_count: int
    pcr_led_price_count: int
    no_price_turn_within_15m_count: int
    pcr_led_price_pct: float | None = None
    mean_lead_minutes: float | None = None
    median_lead_minutes: float | None = None
    response_counts: dict[str, int]
    mean_forward_5m: float | None = None
    mean_forward_10m: float | None = None
    mean_forward_15m: float | None = None
    mean_forward_30m: float | None = None
    median_forward_15m: float | None = None
    bearish_pct_15m: float | None = None
    events: list[EventOutcome]


class TransitionStats(ReversalModel):
    stage_1_event_count: int
    stage_1_to_2_count: int
    stage_2_to_3_count: int
    complete_1_to_2_to_3_count: int
    mean_stage_1_to_2_minutes: float | None = None
    median_stage_1_to_2_minutes: float | None = None
    mean_stage_2_to_3_minutes: float | None = None
    median_stage_2_to_3_minutes: float | None = None


class PCRReversalReport(ReversalModel):
    status: str
    source: str
    row_count: int
    session_count: int
    methodology: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    stages: list[StageStats]
    transitions: TransitionStats


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


def load_reversal_evidence_csv(path: str | Path) -> list[dict[str, object]]:
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


def _stage(row: dict[str, object]) -> str | None:
    signs = (
        _sign(row.get("moving_pcr_change_5m")),
        _sign(row.get("moving_pcr_change_15m")),
        _sign(row.get("moving_pcr_change_30m")),
    )
    for name, expected in STAGES.items():
        if signs == expected:
            return name
    return None


def _exact_change(by_time: dict[datetime, dict[str, object]], dt: datetime, minutes: int) -> float | None:
    now = by_time.get(dt)
    before = by_time.get(dt - timedelta(minutes=minutes))
    if not now or not before:
        return None
    a = now.get("spot")
    b = before.get("spot")
    if not isinstance(a, float) or not isinstance(b, float):
        return None
    return a - b


def _forward(row: dict[str, object], minutes: int) -> float | None:
    value = row.get(f"forward_change_{minutes}m")
    return float(value) if isinstance(value, float) else None


def _price_state(prior_5m: float | None, prior_15m: float | None) -> str:
    if prior_5m is None or prior_15m is None:
        return "UNAVAILABLE"
    if prior_5m > 0 and prior_15m > 0:
        return "UPTREND"
    if prior_5m < 0 and prior_15m < 0:
        return "DOWNTREND"
    return "MIXED"


def _first_bearish_5m_turn(
    by_time: dict[datetime, dict[str, object]],
    event_dt: datetime,
    scan_minutes: int = PRICE_TURN_SCAN_MINUTES,
) -> int | None:
    """Minutes after PCR event until exact rolling 5m spot momentum turns negative.

    Return 0 if spot 5m momentum is already bearish at the PCR event.  Positive
    values mean PCR state appeared before the defined price-momentum turn.
    """
    current = _exact_change(by_time, event_dt, 5)
    if current is not None and current < 0:
        return 0
    for lead in range(1, scan_minutes + 1):
        candidate_dt = event_dt + timedelta(minutes=lead)
        change = _exact_change(by_time, candidate_dt, 5)
        if change is not None and change < 0:
            return lead
    return None


def _response_label(
    prior_15m: float | None,
    f5: float | None,
    f15: float | None,
    f30: float | None,
) -> str:
    """Transparent descriptive labels for a bearish PCR-warning event.

    TRUE_BEARISH_REVERSAL: prior 15m price trend was up, and price is lower at
    both +15m and +30m (sustained reversal evidence).
    SHORT_BEARISH_REVERSAL: prior 15m was up; +5m is lower but +15m is not lower.
    PULLBACK: prior 15m was up; +15m lower but +30m recovered to >= event price.
    BEARISH_CONTINUATION: price was already non-up on prior 15m and +15m is lower.
    FALSE_WARNING: +15m is flat/up, with no short-reversal classification.
    """
    if prior_15m is None or f15 is None:
        return "UNAVAILABLE"
    if prior_15m > 0:
        if f15 < 0 and f30 is not None and f30 < 0:
            return "TRUE_BEARISH_REVERSAL"
        if f15 < 0 and f30 is not None and f30 >= 0:
            return "PULLBACK"
        if f5 is not None and f5 < 0 and f15 >= 0:
            return "SHORT_BEARISH_REVERSAL"
        return "FALSE_WARNING"
    if f15 < 0:
        return "BEARISH_CONTINUATION"
    return "FALSE_WARNING"


def _pct(part: int, whole: int) -> float | None:
    return part * 100.0 / whole if whole else None


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _event_rows(rows: list[dict[str, object]], stage_name: str) -> list[dict[str, object]]:
    """Only first row entering a stage; persistent minute rows are deduplicated."""
    result: list[dict[str, object]] = []
    by_session: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        session = row.get("session_date")
        if isinstance(session, str):
            by_session[session].append(row)
    for session in sorted(by_session):
        previous_stage: str | None = None
        for row in sorted(by_session[session], key=lambda item: item["dt"]):
            current = _stage(row)
            if current == stage_name and previous_stage != stage_name:
                result.append(row)
            previous_stage = current
    return result


def _stage_stats(rows: list[dict[str, object]], stage_name: str) -> StageStats:
    events: list[EventOutcome] = []
    by_session: dict[str, dict[datetime, dict[str, object]]] = defaultdict(dict)
    for row in rows:
        session = row.get("session_date")
        dt = row.get("dt")
        if isinstance(session, str) and isinstance(dt, datetime):
            by_session[session][dt] = row

    for row in _event_rows(rows, stage_name):
        session = str(row["session_date"])
        dt = row["dt"]
        if not isinstance(dt, datetime) or not isinstance(row.get("spot"), float):
            continue
        lookup = by_session[session]
        prior5 = _exact_change(lookup, dt, 5)
        prior15 = _exact_change(lookup, dt, 15)
        prior30 = _exact_change(lookup, dt, 30)
        f5, f10, f15, f30 = (_forward(row, h) for h in FORWARD_MINUTES)
        lead = _first_bearish_5m_turn(lookup, dt)
        events.append(EventOutcome(
            session_date=session,
            stage=stage_name,
            event_time=dt.isoformat(),
            spot=float(row["spot"]),
            prior_change_5m=prior5,
            prior_change_15m=prior15,
            prior_change_30m=prior30,
            forward_change_5m=f5,
            forward_change_10m=f10,
            forward_change_15m=f15,
            forward_change_30m=f30,
            price_turn_lead_minutes=lead,
            price_state_at_event=_price_state(prior5, prior15),
            response_label=_response_label(prior15, f5, f15, f30),
        ))

    response_counts: dict[str, int] = defaultdict(int)
    for event in events:
        response_counts[event.response_label] += 1
    prior_up = [e for e in events if e.prior_change_15m is not None and e.prior_change_15m > 0]
    already = [e for e in prior_up if e.price_turn_lead_minutes == 0]
    led = [e for e in prior_up if isinstance(e.price_turn_lead_minutes, int) and e.price_turn_lead_minutes > 0]
    no_turn = [e for e in prior_up if e.price_turn_lead_minutes is None]
    lead_values = [float(e.price_turn_lead_minutes) for e in led if e.price_turn_lead_minutes is not None]
    f5s = [e.forward_change_5m for e in events if e.forward_change_5m is not None]
    f10s = [e.forward_change_10m for e in events if e.forward_change_10m is not None]
    f15s = [e.forward_change_15m for e in events if e.forward_change_15m is not None]
    f30s = [e.forward_change_30m for e in events if e.forward_change_30m is not None]

    return StageStats(
        stage=stage_name,
        event_count=len(events),
        session_count=len({e.session_date for e in events}),
        prior_uptrend_event_count=len(prior_up),
        price_already_bearish_count=len(already),
        pcr_led_price_count=len(led),
        no_price_turn_within_15m_count=len(no_turn),
        pcr_led_price_pct=_pct(len(led), len(prior_up)),
        mean_lead_minutes=_mean(lead_values),
        median_lead_minutes=_median(lead_values),
        response_counts=dict(sorted(response_counts.items())),
        mean_forward_5m=_mean([float(x) for x in f5s]),
        mean_forward_10m=_mean([float(x) for x in f10s]),
        mean_forward_15m=_mean([float(x) for x in f15s]),
        mean_forward_30m=_mean([float(x) for x in f30s]),
        median_forward_15m=_median([float(x) for x in f15s]),
        bearish_pct_15m=_pct(sum(float(x) < 0 for x in f15s), len(f15s)),
        events=events,
    )


def _transition_stats(rows: list[dict[str, object]]) -> TransitionStats:
    by_session: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        if isinstance(row.get("session_date"), str):
            by_session[str(row["session_date"])].append(row)

    d12: list[float] = []
    d23: list[float] = []
    stage1_count = stage12_count = stage23_count = complete = 0
    for session_rows in by_session.values():
        ordered = sorted(session_rows, key=lambda item: item["dt"])
        entries: list[tuple[str, datetime]] = []
        prev: str | None = None
        for row in ordered:
            current = _stage(row)
            if current is not None and current != prev:
                entries.append((current, row["dt"]))
            prev = current
        for idx, (name, dt1) in enumerate(entries):
            if name != "STAGE_1_5M_BEARISH_ONLY":
                continue
            stage1_count += 1
            stage2: tuple[int, datetime] | None = None
            for j in range(idx + 1, len(entries)):
                n2, dt2 = entries[j]
                if dt2 - dt1 > timedelta(minutes=30):
                    break
                if n2 == "STAGE_2_5M_15M_BEARISH_30M_RISING":
                    stage2 = (j, dt2)
                    stage12_count += 1
                    d12.append((dt2 - dt1).total_seconds() / 60.0)
                    break
            if stage2 is None:
                continue
            j, dt2 = stage2
            for k in range(j + 1, len(entries)):
                n3, dt3 = entries[k]
                if dt3 - dt2 > timedelta(minutes=30):
                    break
                if n3 == "STAGE_3_ALL_5M_15M_30M_BEARISH":
                    stage23_count += 1
                    complete += 1
                    d23.append((dt3 - dt2).total_seconds() / 60.0)
                    break
    return TransitionStats(
        stage_1_event_count=stage1_count,
        stage_1_to_2_count=stage12_count,
        stage_2_to_3_count=stage23_count,
        complete_1_to_2_to_3_count=complete,
        mean_stage_1_to_2_minutes=_mean(d12),
        median_stage_1_to_2_minutes=_median(d12),
        mean_stage_2_to_3_minutes=_mean(d23),
        median_stage_2_to_3_minutes=_median(d23),
    )


def build_pcr_reversal_report(rows: list[dict[str, object]], source: str) -> PCRReversalReport:
    sessions = {str(row["session_date"]) for row in rows if row.get("session_date")}
    return PCRReversalReport(
        status="AVAILABLE" if rows else "UNAVAILABLE",
        source=source,
        row_count=len(rows),
        session_count=len(sessions),
        methodology=[
            "Moving-PCR Stage 1 is 5m falling while 15m and 30m are rising.",
            "Stage 2 is the frozen 60-session candidate: 5m and 15m falling while 30m remains rising.",
            "Stage 3 is 5m, 15m and 30m all falling.",
            "Persistent minute states are deduplicated: an event is only the first row entering a stage.",
            "PCR lead is measured against the first exact rolling 5m NIFTY spot momentum turn below zero within 15 minutes.",
            "Lead-time analysis is restricted to events where prior 15m spot change was positive for the bearish reversal question.",
            "Response labels use fixed transparent price rules; they are descriptive research labels, not trade signals.",
        ],
        limitations=[
            "Underlying volume is not present in the current evidence CSV, so PCR-vs-volume lead/lag is still unavailable.",
            "A rolling 5m spot-momentum sign change is an objective proxy for price turn; it is not a swing-structure or VWAP/EMA reversal definition.",
            "TRUE_BEARISH_REVERSAL requires prior 15m price uptrend and negative +15m and +30m spot changes; this is a research definition, not a universal market definition.",
            "No option-premium P&L, slippage, brokerage, or execution assumptions are included.",
        ],
        stages=[_stage_stats(rows, name) for name in STAGES],
        transitions=_transition_stats(rows),
    )


def analyze_pcr_reversal_csv(path: str | Path) -> PCRReversalReport:
    return build_pcr_reversal_report(load_reversal_evidence_csv(path), str(path))


def write_pcr_reversal_json(report: PCRReversalReport, path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
