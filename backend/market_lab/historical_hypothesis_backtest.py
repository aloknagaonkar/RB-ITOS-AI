"""Event-based exploratory backtests for shortlisted historical PCR hypotheses.

This module evaluates NIFTY underlying direction only. It does not model option
premium, slippage, brokerage, order execution, or live trading. Thresholds are
computed from the same input dataset, so results are explicitly in-sample and
must not be treated as out-of-sample strategy performance.
"""

from __future__ import annotations

import csv
import json
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from pydantic import BaseModel, ConfigDict, Field

HOLD_MINUTES = (5, 10, 15, 30)
PRIMARY_HOLD_MINUTES = 15
RECONSTRUCTION_PROVENANCE = "HISTORICAL_CANDLE_RECONSTRUCTION"


class HypothesisBacktestModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class HoldOutcome(HypothesisBacktestModel):
    hold_minutes: int
    trade_count: int
    session_count: int
    mean_directional_points: float | None = None
    median_directional_points: float | None = None
    stdev_directional_points: float | None = None
    win_rate_pct: float | None = None
    loss_rate_pct: float | None = None
    flat_rate_pct: float | None = None
    mean_mfe_points: float | None = None
    mean_mae_points: float | None = None


class EventResult(HypothesisBacktestModel):
    session_date: str
    expiry: str
    signal_time: str
    entry_time: str
    entry_spot: float
    time_bucket: str
    expiry_day: bool
    outcomes: dict[str, dict[str, float | str | None]]


class SegmentOutcome(HypothesisBacktestModel):
    label: str
    event_count: int
    session_count: int
    primary_hold: HoldOutcome


class HypothesisResult(HypothesisBacktestModel):
    hypothesis_id: str
    description: str
    direction: str
    event_count: int
    session_count: int
    skipped_due_to_cooldown: int
    max_horizon_overlap_count: int
    max_consecutive_losses_15m: int
    thresholds_used: dict[str, float]
    holds: dict[str, HoldOutcome]
    per_session: list[SegmentOutcome]
    time_of_day: list[SegmentOutcome]
    expiry_regime: list[SegmentOutcome]
    events: list[EventResult]


class HistoricalHypothesisBacktestReport(HypothesisBacktestModel):
    status: str
    source: str
    row_count: int
    session_count: int
    cooldown_minutes: int
    hold_minutes: list[int]
    primary_hold_minutes: int
    provenance: str
    methodology: list[str] = Field(default_factory=list)
    global_thresholds: dict[str, float]
    hypotheses: list[HypothesisResult]


@dataclass(frozen=True)
class Hypothesis:
    hypothesis_id: str
    description: str
    required_features: tuple[str, ...]
    predicate: Callable[[dict[str, object], dict[str, float]], bool]


def _float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _quantile(values: list[float], probability: float) -> float:
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
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def load_hypothesis_evidence_csv(path: str | Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {
            "session_date", "expiry", "timestamp", "spot",
            "moving_pcr_change_15m", "fixed_moving_pcr_spread",
            "moving_call_oi_change_pct", "moving_put_oi_change_pct",
        }
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"historical evidence CSV missing columns: {', '.join(sorted(missing))}")
        for raw in reader:
            row: dict[str, object] = dict(raw)
            for key in (
                "spot", "moving_pcr_change_15m", "fixed_moving_pcr_spread",
                "moving_call_oi_change_pct", "moving_put_oi_change_pct",
            ):
                row[key] = _float(raw.get(key))
            put_change = row.get("moving_put_oi_change_pct")
            call_change = row.get("moving_call_oi_change_pct")
            row["moving_oi_imbalance_pct"] = (
                float(put_change) - float(call_change)
                if isinstance(put_change, float) and isinstance(call_change, float)
                else None
            )
            try:
                row["dt"] = datetime.fromisoformat(str(raw["timestamp"]))
            except ValueError as exc:
                raise ValueError(f"invalid timestamp in evidence CSV: {raw['timestamp']}") from exc
            rows.append(row)
    return rows


def _thresholds(rows: list[dict[str, object]]) -> dict[str, float]:
    feature_names = (
        "moving_pcr_change_15m",
        "fixed_moving_pcr_spread",
        "moving_oi_imbalance_pct",
    )
    result: dict[str, float] = {}
    for feature in feature_names:
        values = [float(row[feature]) for row in rows if isinstance(row.get(feature), float)]
        if not values:
            raise ValueError(f"no numeric values available for {feature}")
        result[f"{feature}_q20"] = _quantile(values, 0.20)
        result[f"{feature}_q80"] = _quantile(values, 0.80)
    return result


def _hypotheses() -> list[Hypothesis]:
    m = "moving_pcr_change_15m"
    spread = "fixed_moving_pcr_spread"
    oi = "moving_oi_imbalance_pct"
    return [
        Hypothesis(
            "H1_PCR_FALL_SPREAD_LOW",
            "Moving PCR 15m change in bottom 20% AND Moving-minus-Fixed PCR spread in bottom 20%",
            (m, spread),
            lambda r, t: float(r[m]) <= t[f"{m}_q20"] and float(r[spread]) <= t[f"{spread}_q20"],
        ),
        Hypothesis(
            "H2_MOVING_FALL_PUT_OI_PRESSURE",
            "Moving PCR 15m change in bottom 20% AND Moving Put-minus-Call OI imbalance in top 20%",
            (m, oi),
            lambda r, t: float(r[m]) <= t[f"{m}_q20"] and float(r[oi]) >= t[f"{oi}_q80"],
        ),
        Hypothesis(
            "H3_PCR_SPREAD_LOW",
            "Moving-minus-Fixed PCR spread in bottom 20%",
            (spread,),
            lambda r, t: float(r[spread]) <= t[f"{spread}_q20"],
        ),
        Hypothesis(
            "H4_MOVING_PCR_STRONG_FALL",
            "Moving PCR 15m change in bottom 20%",
            (m,),
            lambda r, t: float(r[m]) <= t[f"{m}_q20"],
        ),
    ]


def _available(row: dict[str, object], features: tuple[str, ...]) -> bool:
    return all(isinstance(row.get(feature), float) for feature in features)


def _time_bucket(dt: datetime) -> str:
    minutes = dt.hour * 60 + dt.minute
    if minutes < 10 * 60:
        return "OPEN_0915_0959"
    if minutes < 12 * 60:
        return "MORNING_1000_1159"
    if minutes < 14 * 60:
        return "MIDDAY_1200_1359"
    return "LATE_1400_1529"


def _hold_summary(events: list[EventResult], hold_minutes: int) -> HoldOutcome:
    key = f"{hold_minutes}m"
    points: list[float] = []
    mfes: list[float] = []
    maes: list[float] = []
    sessions: set[str] = set()
    for event in events:
        outcome = event.outcomes.get(key)
        if not outcome:
            continue
        point = outcome.get("directional_points")
        if not isinstance(point, (int, float)):
            continue
        points.append(float(point))
        sessions.add(event.session_date)
        mfe = outcome.get("mfe_points")
        mae = outcome.get("mae_points")
        if isinstance(mfe, (int, float)):
            mfes.append(float(mfe))
        if isinstance(mae, (int, float)):
            maes.append(float(mae))
    if not points:
        return HoldOutcome(hold_minutes=hold_minutes, trade_count=0, session_count=0)
    return HoldOutcome(
        hold_minutes=hold_minutes,
        trade_count=len(points),
        session_count=len(sessions),
        mean_directional_points=statistics.fmean(points),
        median_directional_points=statistics.median(points),
        stdev_directional_points=statistics.stdev(points) if len(points) > 1 else 0.0,
        win_rate_pct=sum(value > 0 for value in points) * 100.0 / len(points),
        loss_rate_pct=sum(value < 0 for value in points) * 100.0 / len(points),
        flat_rate_pct=sum(value == 0 for value in points) * 100.0 / len(points),
        mean_mfe_points=statistics.fmean(mfes) if mfes else None,
        mean_mae_points=statistics.fmean(maes) if maes else None,
    )


def _segment(label: str, events: list[EventResult]) -> SegmentOutcome:
    return SegmentOutcome(
        label=label,
        event_count=len(events),
        session_count=len({event.session_date for event in events}),
        primary_hold=_hold_summary(events, PRIMARY_HOLD_MINUTES),
    )


def _max_consecutive_losses(events: list[EventResult]) -> int:
    longest = current = 0
    key = f"{PRIMARY_HOLD_MINUTES}m"
    for event in sorted(events, key=lambda item: item.entry_time):
        outcome = event.outcomes.get(key)
        value = outcome.get("directional_points") if outcome else None
        if isinstance(value, (int, float)) and value < 0:
            current += 1
            longest = max(longest, current)
        elif isinstance(value, (int, float)):
            current = 0
    return longest


def _build_events(
    rows: list[dict[str, object]],
    hypothesis: Hypothesis,
    thresholds: dict[str, float],
    cooldown_minutes: int,
) -> tuple[list[EventResult], int, int]:
    by_session: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        session = row.get("session_date")
        if isinstance(session, str):
            by_session[session].append(row)

    events: list[EventResult] = []
    skipped = 0
    overlap_count = 0
    for session_date in sorted(by_session):
        session_rows = sorted(by_session[session_date], key=lambda row: row["dt"])
        by_time = {row["dt"]: row for row in session_rows}
        next_allowed: datetime | None = None
        previous_max_exit: datetime | None = None
        for row in session_rows:
            dt = row["dt"]
            if not isinstance(dt, datetime) or not _available(row, hypothesis.required_features):
                continue
            if not hypothesis.predicate(row, thresholds):
                continue
            if next_allowed is not None and dt < next_allowed:
                skipped += 1
                continue

            entry_dt = dt + timedelta(minutes=1)
            entry_row = by_time.get(entry_dt)
            entry_spot = entry_row.get("spot") if entry_row else None
            if not isinstance(entry_spot, float):
                continue

            outcomes: dict[str, dict[str, float | str | None]] = {}
            for hold in HOLD_MINUTES:
                exit_dt = entry_dt + timedelta(minutes=hold)
                exit_row = by_time.get(exit_dt)
                exit_spot = exit_row.get("spot") if exit_row else None
                if not isinstance(exit_spot, float):
                    outcomes[f"{hold}m"] = {
                        "exit_time": None,
                        "exit_spot": None,
                        "underlying_change_points": None,
                        "directional_points": None,
                        "mfe_points": None,
                        "mae_points": None,
                    }
                    continue
                window_spots = [
                    item.get("spot") for item in session_rows
                    if isinstance(item.get("dt"), datetime)
                    and entry_dt <= item["dt"] <= exit_dt
                    and isinstance(item.get("spot"), float)
                ]
                numeric_window = [float(value) for value in window_spots if isinstance(value, float)]
                underlying_change = float(exit_spot) - float(entry_spot)
                outcomes[f"{hold}m"] = {
                    "exit_time": exit_dt.isoformat(),
                    "exit_spot": float(exit_spot),
                    "underlying_change_points": underlying_change,
                    # All current shortlisted hypotheses are bearish / PE-direction studies.
                    "directional_points": -underlying_change,
                    "mfe_points": float(entry_spot) - min(numeric_window) if numeric_window else None,
                    "mae_points": max(numeric_window) - float(entry_spot) if numeric_window else None,
                }

            expiry = str(row.get("expiry") or "")
            event = EventResult(
                session_date=session_date,
                expiry=expiry,
                signal_time=dt.isoformat(),
                entry_time=entry_dt.isoformat(),
                entry_spot=float(entry_spot),
                time_bucket=_time_bucket(entry_dt),
                expiry_day=(session_date == expiry),
                outcomes=outcomes,
            )
            events.append(event)
            max_exit = entry_dt + timedelta(minutes=max(HOLD_MINUTES))
            if previous_max_exit is not None and entry_dt < previous_max_exit:
                overlap_count += 1
            previous_max_exit = max_exit
            next_allowed = dt + timedelta(minutes=cooldown_minutes)
    return events, skipped, overlap_count


def build_hypothesis_backtest_report(
    rows: list[dict[str, object]],
    source: str,
    cooldown_minutes: int = 15,
) -> HistoricalHypothesisBacktestReport:
    if cooldown_minutes < 1:
        raise ValueError("cooldown_minutes must be >= 1")
    if not rows:
        return HistoricalHypothesisBacktestReport(
            status="UNAVAILABLE", source=source, row_count=0, session_count=0,
            cooldown_minutes=cooldown_minutes, hold_minutes=list(HOLD_MINUTES),
            primary_hold_minutes=PRIMARY_HOLD_MINUTES, provenance=RECONSTRUCTION_PROVENANCE,
            global_thresholds={}, hypotheses=[], methodology=["No evidence rows available."],
        )

    thresholds = _thresholds(rows)
    hypotheses: list[HypothesisResult] = []
    for hypothesis in _hypotheses():
        events, skipped, overlaps = _build_events(rows, hypothesis, thresholds, cooldown_minutes)
        per_session_groups: dict[str, list[EventResult]] = defaultdict(list)
        time_groups: dict[str, list[EventResult]] = defaultdict(list)
        expiry_groups: dict[str, list[EventResult]] = defaultdict(list)
        for event in events:
            per_session_groups[event.session_date].append(event)
            time_groups[event.time_bucket].append(event)
            expiry_groups["EXPIRY_DAY" if event.expiry_day else "NON_EXPIRY_DAY"].append(event)

        used_thresholds = {
            key: value for key, value in thresholds.items()
            if any(feature in key for feature in hypothesis.required_features)
        }
        hypotheses.append(HypothesisResult(
            hypothesis_id=hypothesis.hypothesis_id,
            description=hypothesis.description,
            direction="BEARISH",
            event_count=len(events),
            session_count=len({event.session_date for event in events}),
            skipped_due_to_cooldown=skipped,
            max_horizon_overlap_count=overlaps,
            max_consecutive_losses_15m=_max_consecutive_losses(events),
            thresholds_used=used_thresholds,
            holds={f"{hold}m": _hold_summary(events, hold) for hold in HOLD_MINUTES},
            per_session=[_segment(label, per_session_groups[label]) for label in sorted(per_session_groups)],
            time_of_day=[_segment(label, time_groups[label]) for label in sorted(time_groups)],
            expiry_regime=[_segment(label, expiry_groups[label]) for label in sorted(expiry_groups)],
            events=events,
        ))

    sessions = {str(row.get("session_date")) for row in rows if row.get("session_date")}
    return HistoricalHypothesisBacktestReport(
        status="AVAILABLE",
        source=source,
        row_count=len(rows),
        session_count=len(sessions),
        cooldown_minutes=cooldown_minutes,
        hold_minutes=list(HOLD_MINUTES),
        primary_hold_minutes=PRIMARY_HOLD_MINUTES,
        provenance=RECONSTRUCTION_PROVENANCE,
        methodology=[
            "Exploratory in-sample event study on NIFTY spot; not option-premium P&L and not a live trading strategy.",
            "Signal thresholds are dataset-derived 20th/80th percentiles computed from the same input dataset.",
            "Each accepted signal enters on the next exact 1-minute observation; missing next-minute entries are skipped.",
            "Cooldown is applied independently per hypothesis to reduce repeated signals from persistent conditions.",
            "5m/10m/15m/30m exits require exact same-session timestamps; missing exits remain unavailable.",
            "MFE/MAE are close-to-close spot proxies because the evidence dataset contains minute spot observations, not intraminute highs/lows.",
            "All four shortlisted hypotheses are evaluated as bearish/PE-direction underlying studies.",
        ],
        global_thresholds=thresholds,
        hypotheses=hypotheses,
    )


def backtest_hypotheses_csv(
    path: str | Path,
    cooldown_minutes: int = 15,
) -> HistoricalHypothesisBacktestReport:
    rows = load_hypothesis_evidence_csv(path)
    return build_hypothesis_backtest_report(rows, str(path), cooldown_minutes)


def write_hypothesis_backtest_json(report: HistoricalHypothesisBacktestReport, path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
