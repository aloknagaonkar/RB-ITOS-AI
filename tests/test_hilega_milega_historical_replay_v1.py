from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from market_lab.domain import HistoricalCandle
from market_lab.hilega_milega_historical_replay_v1 import (
    _decision_reason_rows,
    aggregate_exact_5m,
    replay_sessions,
)
from market_lab.hilega_milega_strategy_v1 import (
    FiveMinuteBar,
    HilegaMilegaBullishEngineV1,
    IndicatorSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")
UTC = ZoneInfo("UTC")


def candle(sd: date, hh: int, mm: int, close: float) -> HistoricalCandle:
    ts = datetime(sd.year, sd.month, sd.day, hh, mm, tzinfo=IST).astimezone(UTC)
    return HistoricalCandle(
        provider="upstox",
        instrument_key="NSE_INDEX|Nifty 50",
        session_date=sd,
        timestamp=ts,
        open=close - 0.5,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=100,
        open_interest=None,
    )


def test_exact_5m_aggregation_uses_five_exact_minutes():
    sd = date(2026, 9, 17)
    rows = [candle(sd, 9, 15 + i, 100 + i) for i in range(10)]
    bars = aggregate_exact_5m(rows, sd)
    assert len(bars) == 2
    assert bars[0].ts.strftime("%H:%M") == "09:15"
    assert bars[0].open == pytest.approx(99.5)
    assert bars[0].close == pytest.approx(104)
    assert bars[1].ts.strftime("%H:%M") == "09:20"
    assert bars[1].close == pytest.approx(109)


def test_exact_5m_aggregation_fails_on_partial_bar():
    sd = date(2026, 9, 17)
    rows = [candle(sd, 9, 15 + i, 100 + i) for i in (0, 1, 2, 4)]
    with pytest.raises(ValueError, match="incomplete exact 5m candle"):
        aggregate_exact_5m(rows, sd)


def test_decision_audit_explains_route_a_failure_and_route_b_wait():
    cp = "2026-09-18T11:35:00+05:30"
    evaluated = {
        "checkpoint": cp,
        "stage": "STRATEGY_DECISION",
        "status": "EVALUATED",
        "payload": {
            "state_before": "PATH1_IDLE",
            "rsi9": 48.0,
            "ema3_rsi": 47.0,
            "wma21_rsi": 49.0,
            "previous_rsi9": 46.0,
            "previous_ema3_rsi": 46.5,
            "previous_wma21_rsi": 49.5,
            "rsi_cross_ema_up": True,
            "rsi_cross_wma_down": False,
            "rsi_gt_50": False,
            "rsi_gt_wma": False,
            "ema_gt_wma": False,
            "rsi_rising": True,
            "ema_rising": True,
            "full_alignment": False,
        },
    }
    result = {
        "checkpoint": cp,
        "stage": "STRATEGY_DECISION_RESULT",
        "status": "COMPLETE",
        "payload": {
            "state_after": "PATH1_ARMED",
            "route_a_eligible": True,
            "route_a_pass": False,
            "route_a_fail_reasons": ["RSI_NOT_ABOVE_50", "RSI_NOT_ABOVE_WMA21"],
            "route_b_eligible": True,
            "route_b_pass": False,
            "route_b_fail_reasons": ["NEITHER_RSI_NOR_EMA_ABOVE_WMA21"],
        },
    }
    transition = {
        "checkpoint": cp,
        "stage": "STRATEGY_TRANSITION",
        "status": "PATH1_ARMED_RSI_CROSS_EMA3_UP",
        "payload": {},
    }
    rows = _decision_reason_rows([evaluated, result, transition])
    assert len(rows) == 1
    row = rows[0]
    assert row["final_decision"] == "ARMED_WAITING"
    assert "RSI_NOT_ABOVE_50" in row["reasons"]
    assert "NEITHER_RSI_NOR_EMA_ABOVE_WMA21" in row["reasons"]


def test_new_session_does_not_use_prior_session_bar_for_path1_cross():
    engine = HilegaMilegaBullishEngineV1()
    d1 = date(2026, 9, 17)
    d2 = date(2026, 9, 18)
    b1 = FiveMinuteBar(datetime.combine(d1, datetime.min.time(), tzinfo=IST).replace(hour=15, minute=25), 1, 1, 1, 1)
    b2 = FiveMinuteBar(datetime.combine(d2, datetime.min.time(), tzinfo=IST).replace(hour=9, minute=15), 1, 1, 1, 1)
    # Previous day ends RSI below EMA. New day opens RSI above EMA. This must
    # not be interpreted as a fresh intraday cross.
    engine.process_enriched_bar_for_test(b1, IndicatorSnapshot(40, 45, 35))
    events = engine.process_enriched_bar_for_test(b2, IndicatorSnapshot(60, 50, 40))
    assert not any("PATH1" in e.event_type for e in events)


class FakeGateway:
    def historical_candles(self, instrument_key: str, session_date: date):
        # Weekends / non-targets can be absent. For the test day provide the
        # full regular session so exact aggregation and audit writing run.
        if session_date != date(2026, 9, 17):
            return []
        start = datetime(2026, 9, 17, 9, 15, tzinfo=IST)
        rows = []
        price = 23000.0
        for i in range(375):
            ts = start + timedelta(minutes=i)
            price += 0.25
            rows.append(
                HistoricalCandle(
                    provider="upstox",
                    instrument_key=instrument_key,
                    session_date=session_date,
                    timestamp=ts.astimezone(UTC),
                    open=price - 0.1,
                    high=price + 0.2,
                    low=price - 0.2,
                    close=price,
                    volume=100,
                    open_interest=None,
                )
            )
        return rows


def test_replay_writes_hash_audit_and_human_decision_reports(tmp_path):
    payload = replay_sessions(
        gateway=FakeGateway(),
        dates=[date(2026, 9, 17)],
        warmup_calendar_days=0,
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "out",
    )
    assert payload["summary"]["sessions_passed"] == 1
    session_dir = tmp_path / "out" / "2026-09-17"
    assert (session_dir / "step-audit.jsonl").exists()
    assert (session_dir / "signal-decision-audit.csv").exists()
    assert (session_dir / "signal-decision-audit.json").exists()
    assert (session_dir / "signal-decision-audit.txt").exists()
    assert (session_dir / "candle-by-candle-strategy-audit.csv").exists()
    assert (session_dir / "candle-by-candle-strategy-audit.json").exists()
    assert (session_dir / "candle-by-candle-strategy-audit.txt").exists()
    text = (session_dir / "signal-decision-audit.txt").read_text()
    assert "HILEGA-MILEGA DECISION AUDIT" in text
    assert "STRUCTURAL CHECKS" in text
    assert "ROUTE A" in text
    assert "ROUTE B" in text
    candle_text = (session_dir / "candle-by-candle-strategy-audit.txt").read_text()
    assert "HILEGA-MILEGA CANDLE-BY-CANDLE STRATEGY AUDIT" in candle_text
    assert (tmp_path / "out" / "multi-session-candle-by-candle-strategy-audit.csv").exists()
    summary = json.loads((tmp_path / "out" / "multi-session-summary.json").read_text())
    assert summary["execution_enabled"] is False
    assert summary["observation_only"] is True
