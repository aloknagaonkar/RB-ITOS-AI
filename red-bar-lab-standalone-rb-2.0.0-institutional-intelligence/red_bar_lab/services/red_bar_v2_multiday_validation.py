from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Callable, Sequence

import pandas as pd

from red_bar_lab.services.red_bar_v2_futures_replay_service import (
    MonitoredRedBarV2FuturesReplayResult,
    run_monitored_red_bar_v2_futures_replay,
)
from red_bar_lab.services.red_bar_v2_validation_diagnostics import (
    diagnose_session_regime,
    evaluate_session_completeness,
)


@dataclass(frozen=True)
class RedBarV2ValidationDay:
    trading_date: str
    index_candles: pd.DataFrame
    futures_candles: pd.DataFrame
    futures_instrument_key: str
    futures_symbol: str | None = None
    futures_expiry: str | None = None
    exit_timestamps: tuple[datetime | pd.Timestamp, ...] = ()
    expected_regime: str | None = None


@dataclass(frozen=True)
class RedBarV2ValidationDayResult:
    trading_date: str
    regime: str
    regime_reason: str
    expected_regime: str | None
    regime_matches_expectation: bool | None
    session_open: float | None
    session_close: float | None
    session_high: float | None
    session_low: float | None
    net_points: float | None
    net_return_pct: float | None
    travelled_points: float | None
    directional_efficiency: float | None
    intraday_range_pct: float | None
    health_status: str
    health_reason: str
    session_completeness_status: str
    session_completeness_reason: str
    session_coverage_pct: float
    index_rows: int
    expected_index_rows: int
    futures_rows: int
    aligned_rows: int
    alignment_coverage_pct: float
    completed_5m_aligned_rows: int
    completed_5m_alignment_coverage_pct: float
    admitted_candidates: int
    blocked_candidates: int
    closed_trades: int
    final_trade_state: str
    admitted_bullish: int
    admitted_bearish: int
    admitted_reversals: int
    active_trade_block_episodes: int
    active_trade_block_occurrences: int


@dataclass(frozen=True)
class RedBarV2MultiDayValidationResult:
    days: tuple[RedBarV2ValidationDayResult, ...]
    total_days: int
    ready_days: int
    blocked_days: int
    complete_days: int
    partial_days: int
    total_admitted_candidates: int
    total_blocked_candidates: int
    total_closed_trades: int
    total_admitted_reversals: int
    regimes: tuple[str, ...]
    json_path: Path
    csv_path: Path


def classify_session_regime(index_candles: pd.DataFrame) -> str:
    return diagnose_session_regime(index_candles).regime


def _admission_metrics(
    monitored: MonitoredRedBarV2FuturesReplayResult,
) -> tuple[int, int, int, int, int, int]:
    admitted_directions: list[str] = []
    for event in monitored.replay.events:
        if event.event_type != "CANDIDATE_ADMISSION" or event.candidate_allowed is not True:
            continue
        direction = str(event.direction or "").upper()
        if direction in {"BULLISH", "BEARISH"}:
            admitted_directions.append(direction)

    bullish = sum(direction == "BULLISH" for direction in admitted_directions)
    bearish = sum(direction == "BEARISH" for direction in admitted_directions)
    reversals = sum(
        current != previous
        for previous, current in zip(admitted_directions, admitted_directions[1:])
    )
    block_episodes = sum(
        episode.admission_code == "ACTIVE_TRADE_BLOCK"
        for episode in monitored.event_episodes
    )
    block_occurrences = sum(
        episode.occurrences
        for episode in monitored.event_episodes
        if episode.admission_code == "ACTIVE_TRADE_BLOCK"
    )
    return bullish, bearish, reversals, block_episodes, block_occurrences, len(admitted_directions)


def _report_paths(artifacts_root: str | Path) -> tuple[Path, Path]:
    root = Path(artifacts_root) / "reports" / "red_bar_v2_multiday"
    root.mkdir(parents=True, exist_ok=True)
    return root / "validation_summary.json", root / "validation_days.csv"


def run_red_bar_v2_multiday_validation(
    days: Sequence[RedBarV2ValidationDay],
    *,
    instrument_key: str,
    artifacts_root: str | Path,
    replay_runner: Callable[..., MonitoredRedBarV2FuturesReplayResult] = run_monitored_red_bar_v2_futures_replay,
) -> RedBarV2MultiDayValidationResult:
    if not days:
        raise ValueError("Multi-day validation requires at least one day.")

    day_results: list[RedBarV2ValidationDayResult] = []
    for day in sorted(days, key=lambda item: item.trading_date):
        monitored = replay_runner(
            day.index_candles,
            day.futures_candles,
            instrument_key=instrument_key,
            vwap_instrument_key=day.futures_instrument_key,
            artifacts_root=artifacts_root,
            futures_symbol=day.futures_symbol,
            futures_expiry=day.futures_expiry,
            exit_timestamps=day.exit_timestamps,
        )
        regime = diagnose_session_regime(day.index_candles)
        completeness = evaluate_session_completeness(day.index_candles)
        expected = day.expected_regime.upper() if day.expected_regime else None
        regime_match = regime.regime == expected if expected else None
        bullish, bearish, reversals, block_episodes, block_occurrences, admitted_count = (
            _admission_metrics(monitored)
        )
        health = monitored.health
        replay = monitored.replay
        day_results.append(
            RedBarV2ValidationDayResult(
                trading_date=day.trading_date,
                regime=regime.regime,
                regime_reason=regime.reason,
                expected_regime=expected,
                regime_matches_expectation=regime_match,
                session_open=regime.session_open,
                session_close=regime.session_close,
                session_high=regime.session_high,
                session_low=regime.session_low,
                net_points=regime.net_points,
                net_return_pct=regime.net_return_pct,
                travelled_points=regime.travelled_points,
                directional_efficiency=regime.directional_efficiency,
                intraday_range_pct=regime.intraday_range_pct,
                health_status=health.status,
                health_reason=health.reason,
                session_completeness_status=completeness.status,
                session_completeness_reason=completeness.reason,
                session_coverage_pct=completeness.coverage_pct,
                index_rows=health.index_rows,
                expected_index_rows=completeness.expected_rows,
                futures_rows=health.futures_rows,
                aligned_rows=health.aligned_rows,
                alignment_coverage_pct=health.alignment_coverage_pct,
                completed_5m_aligned_rows=health.completed_5m_aligned_rows,
                completed_5m_alignment_coverage_pct=health.completed_5m_alignment_coverage_pct,
                admitted_candidates=replay.admitted_candidates,
                blocked_candidates=replay.blocked_candidates,
                closed_trades=replay.closed_trades,
                final_trade_state=replay.final_trade_state,
                admitted_bullish=bullish,
                admitted_bearish=bearish,
                admitted_reversals=reversals,
                active_trade_block_episodes=block_episodes,
                active_trade_block_occurrences=block_occurrences,
            )
        )
        if admitted_count != replay.admitted_candidates:
            raise ValueError(
                f"Admission count mismatch for {day.trading_date}: "
                f"events={admitted_count}, replay={replay.admitted_candidates}"
            )

    json_path, csv_path = _report_paths(artifacts_root)
    rows = [asdict(item) for item in day_results]
    summary = {
        "execution_scope": "HISTORICAL_REPLAY_ONLY",
        "instrument_key": instrument_key,
        "total_days": len(day_results),
        "ready_days": sum(item.health_status == "READY" for item in day_results),
        "blocked_days": sum(item.health_status != "READY" for item in day_results),
        "complete_days": sum(item.session_completeness_status == "COMPLETE" for item in day_results),
        "partial_days": sum(item.session_completeness_status == "PARTIAL" for item in day_results),
        "total_admitted_candidates": sum(item.admitted_candidates for item in day_results),
        "total_blocked_candidates": sum(item.blocked_candidates for item in day_results),
        "total_closed_trades": sum(item.closed_trades for item in day_results),
        "total_admitted_reversals": sum(item.admitted_reversals for item in day_results),
        "regimes": sorted({item.regime for item in day_results}),
        "days": rows,
    }
    temporary = json_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(json_path)
    pd.DataFrame(rows).to_csv(csv_path, index=False)

    return RedBarV2MultiDayValidationResult(
        days=tuple(day_results),
        total_days=summary["total_days"],
        ready_days=summary["ready_days"],
        blocked_days=summary["blocked_days"],
        complete_days=summary["complete_days"],
        partial_days=summary["partial_days"],
        total_admitted_candidates=summary["total_admitted_candidates"],
        total_blocked_candidates=summary["total_blocked_candidates"],
        total_closed_trades=summary["total_closed_trades"],
        total_admitted_reversals=summary["total_admitted_reversals"],
        regimes=tuple(summary["regimes"]),
        json_path=json_path,
        csv_path=csv_path,
    )
