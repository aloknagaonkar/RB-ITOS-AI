from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from red_bar_lab.execution.independent_strategy_shadow_worker import (
    IndependentStrategyShadowWorker,
    _freshness,
    evaluate_shadow_strategy_cycle,
)
from red_bar_lab.strategy.models import ReferenceLevel


IST = ZoneInfo("Asia/Kolkata")


def candles(rows: int = 190) -> pd.DataFrame:
    start = pd.Timestamp("2026-08-18 09:15:00", tz="Asia/Kolkata")
    output = []
    for index in range(rows):
        base = 24000.0 + index * 0.5
        output.append(
            {
                "timestamp": start + pd.Timedelta(minutes=index),
                "open": base,
                "high": base + 1.0,
                "low": base - 1.0,
                "close": base + 0.4,
                "volume": 1000 + index,
            }
        )
    return pd.DataFrame(output)


def levels():
    return [
        ReferenceLevel(
            level_type="NEXT_RED_CANDLE",
            value=24010.0,
            source_timestamp=datetime(2026, 8, 18, 9, 20, tzinfo=IST),
            source_high=24012.0,
            source_low=24008.0,
            interval_minutes=5,
        )
    ]


def test_cycle_evaluates_all_three_strategies_without_production_authority():
    result = evaluate_shadow_strategy_cycle(
        candles(),
        reference_levels=levels(),
        instrument_key="NSE_INDEX|Nifty 50",
        now=pd.Timestamp("2026-08-18 12:30:30", tz="Asia/Kolkata"),
    )
    record = result.as_record()
    assert result.status == "READY"
    assert result.scan_identity.endswith("2026-08-18T12:24:00+05:30")
    assert result.red_bar["input_state"] == "READY"
    assert result.red_bar["reference_level_count"] == 1
    assert "status" in result.directional_regime
    assert "freshness_state" in result.directional_regime
    assert "status" in result.rsi_reversal
    assert "historical_signal_count" in result.rsi_reversal
    assert "fresh_signal_count" in result.rsi_reversal
    assert record["evaluation_source"] == "INDEPENDENT_STRATEGY_SHADOW_WORKER"
    assert record["shadow_only"] is True
    assert record["production_persistence"] is False
    assert record["capital_reserved"] is False
    assert record["bundle_consumed"] is False
    assert record["order_submitted"] is False
    assert result.directional_regime["production_persisted"] is False
    assert result.red_bar["production_persisted"] is False
    assert result.rsi_reversal["production_persisted"] is False


def test_cycle_reports_missing_red_bar_reference_inputs():
    result = evaluate_shadow_strategy_cycle(
        candles(),
        reference_levels=[],
        instrument_key="NSE_INDEX|Nifty 50",
        now=pd.Timestamp("2026-08-18 12:30:30", tz="Asia/Kolkata"),
    )
    assert result.red_bar["status"] == "INPUT_UNAVAILABLE"
    assert result.red_bar["input_state"] == "REFERENCE_LEVELS_UNAVAILABLE"
    assert result.red_bar["reference_level_count"] == 0
    assert result.red_bar["current_action"] == "WAIT_FOR_REFERENCE_LEVELS"


def test_freshness_classifies_fresh_stale_and_future_events():
    evaluated = pd.Timestamp("2026-08-18 10:04:00", tz="Asia/Kolkata")
    fresh = _freshness(
        detected_at="2026-08-18T10:00:00+05:30",
        fresh_until="2026-08-18T10:05:00+05:30",
        evaluated_at=evaluated,
    )
    stale = _freshness(
        detected_at="2026-08-18T09:50:00+05:30",
        fresh_until="2026-08-18T09:55:00+05:30",
        evaluated_at=evaluated,
    )
    future = _freshness(
        detected_at="2026-08-18T10:10:00+05:30",
        fresh_until="2026-08-18T10:15:00+05:30",
        evaluated_at=evaluated,
    )

    assert fresh["freshness_state"] == "FRESH"
    assert fresh["fresh"] is True
    assert fresh["current_action"] == "SHADOW_CANDIDATE"
    assert stale["freshness_state"] == "STALE"
    assert stale["fresh"] is False
    assert stale["current_action"] == "OBSERVE_ONLY"
    assert future["freshness_state"] == "FUTURE_TIMESTAMP"
    assert future["fresh"] is False


def test_worker_writes_separate_journal_once_and_refreshes_heartbeat(tmp_path: Path):
    now = pd.Timestamp("2026-08-18 12:30:30", tz="Asia/Kolkata")
    worker = IndependentStrategyShadowWorker(
        candle_loader=candles,
        reference_level_loader=levels,
        instrument_key="NSE_INDEX|Nifty 50",
        runs_root=tmp_path,
        now_provider=lambda: now,
        poll_seconds=1,
    )

    first = worker.run_once()
    second = worker.run_once()

    assert first.journal_written is True
    assert second.journal_written is False
    assert second.reason == "COMPLETED_CANDLE_ALREADY_SCANNED"
    assert worker.journal_path.exists()
    assert len(worker.journal_path.read_text(encoding="utf-8").splitlines()) == 1

    assert worker.status_path.exists()
    status = json.loads(worker.status_path.read_text(encoding="utf-8"))
    assert status["reason"] == "COMPLETED_CANDLE_ALREADY_SCANNED"
    assert status["shadow_only"] is True
    assert status["production_persistence"] is False
    assert status["capital_reserved"] is False
    assert status["bundle_consumed"] is False
    assert status["order_submitted"] is False

    assert not (tmp_path / "fresh_setup_bundles_v43").exists()
    assert not (tmp_path / "fresh_setup_signals_v43").exists()
    assert not (tmp_path / "rsi_extreme_reversal_v1").exists()


def test_worker_publishes_error_heartbeat_without_production_writes(tmp_path: Path):
    worker = IndependentStrategyShadowWorker(
        candle_loader=lambda: (_ for _ in ()).throw(RuntimeError("provider down")),
        reference_level_loader=levels,
        instrument_key="NSE_INDEX|Nifty 50",
        runs_root=tmp_path,
        now_provider=lambda: pd.Timestamp("2026-08-18 12:30:30", tz="Asia/Kolkata"),
        poll_seconds=1,
    )

    try:
        worker.run_once()
    except RuntimeError as exc:
        worker.write_error_status(exc)

    status = json.loads(worker.status_path.read_text(encoding="utf-8"))
    assert status["status"] == "ERROR"
    assert status["reason"] == "RuntimeError:provider down"
    assert status["production_persistence"] is False
    assert not worker.journal_path.exists()
