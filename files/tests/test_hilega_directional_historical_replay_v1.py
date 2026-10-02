from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from market_lab.domain import HistoricalCandle
from market_lab.hilega_directional_historical_replay_v1 import replay_directional_sessions

IST = ZoneInfo("Asia/Kolkata")
UTC = ZoneInfo("UTC")


class OscillatingGateway:
    def historical_candles(self, instrument_key: str, session_date: date):
        if session_date != date(2026, 9, 24):
            return []
        start = datetime(2026, 9, 24, 9, 15, tzinfo=IST)
        rows = []
        price = 23200.0
        for i in range(375):
            # Long deterministic waves create both directional conditions.
            block = (i // 35) % 4
            drift = {0: 0.55, 1: -0.70, 2: 0.65, 3: -0.60}[block]
            price += drift
            ts = start + timedelta(minutes=i)
            rows.append(
                HistoricalCandle(
                    provider="upstox",
                    instrument_key=instrument_key,
                    session_date=session_date,
                    timestamp=ts.astimezone(UTC),
                    open=price - drift * 0.4,
                    high=price + 0.35,
                    low=price - 0.35,
                    close=price,
                    volume=100,
                    open_interest=None,
                )
            )
        return rows


def test_directional_replay_writes_combined_artifacts(tmp_path):
    result = replay_directional_sessions(
        gateway=OscillatingGateway(),
        dates=[date(2026, 9, 24)],
        warmup_calendar_days=0,
        cache_root=tmp_path/"cache",
        output_root=tmp_path/"out",
    )
    assert result["status"] == "PASS"
    assert result["observation_only"] is True
    assert result["execution_enabled"] is False
    assert result["paper_order_enabled"] is False
    assert result["option_selection_enabled"] is False
    assert result["whipsaw_mitigation_status"] == "DEFERRED"
    assert result["directional_rules"]["same_candle_reversal"] is False

    d = tmp_path/"out"/"2026-09-24"
    for name in [
        "directional-candle-by-candle.csv",
        "directional-candle-by-candle.json",
        "directional-events.csv",
        "directional-events.json",
        "directional-trades.csv",
        "directional-manual-validation.txt",
    ]:
        assert (d/name).exists(), name

    summary = json.loads((tmp_path/"out"/"multi-session-directional-summary.json").read_text())
    assert summary["summary"]["sessions_passed"] == 1
    assert summary["manual_validation_required"] is True

    text = (d/"directional-manual-validation.txt").read_text()
    assert "HILEGA DIRECTIONAL MANUAL VALIDATION" in text
    assert "DIRECTIONAL TRADES" in text


def test_directional_replay_has_only_one_owner_per_candle(tmp_path):
    replay_directional_sessions(
        gateway=OscillatingGateway(),
        dates=[date(2026, 9, 24)],
        warmup_calendar_days=0,
        cache_root=tmp_path/"cache",
        output_root=tmp_path/"out",
    )
    rows = json.loads(
        (tmp_path/"out"/"2026-09-24"/"directional-candle-by-candle.json").read_text()
    )
    assert all(r["owner_after"] in {"NONE", "BULLISH", "BEARISH"} for r in rows)
    assert all(
        not (r["bullish_state"] == "BULLISH_ACTIVE" and r["bearish_state"] == "BEARISH_ACTIVE")
        for r in rows
    )


def test_directional_points_sign_is_direction_aware(tmp_path):
    result = replay_directional_sessions(
        gateway=OscillatingGateway(),
        dates=[date(2026, 9, 24)],
        warmup_calendar_days=0,
        cache_root=tmp_path/"cache",
        output_root=tmp_path/"out",
    )
    for t in result["trades"]:
        if t["direction"] == "BULLISH":
            expected = t["exit_price"] - t["entry_price"]
        else:
            expected = t["entry_price"] - t["exit_price"]
        assert abs(t["points"] - expected) < 1e-9


def test_metric_names_distinguish_armed_candles_from_arm_events(tmp_path):
    result = replay_directional_sessions(
        gateway=OscillatingGateway(),
        dates=[date(2026, 9, 24)],
        warmup_calendar_days=0,
        cache_root=tmp_path/"cache",
        output_root=tmp_path/"out",
    )
    s = result["summary"]
    assert "bullish_armed_candles_while_bearish_active" in s
    assert "bearish_armed_candles_while_bullish_active" in s
    assert "bullish_arm_events_while_bearish_active" in s
    assert "bearish_arm_events_while_bullish_active" in s
    assert "bullish_armed_while_bearish_active" not in s
    assert "bearish_armed_while_bullish_active" not in s


def test_reversal_block_counter_requires_actual_suppressed_entry(tmp_path):
    result = replay_directional_sessions(
        gateway=OscillatingGateway(),
        dates=[date(2026, 9, 24)],
        warmup_calendar_days=0,
        cache_root=tmp_path/"cache",
        output_root=tmp_path/"out",
    )
    rows = json.loads(
        (tmp_path/"out"/"2026-09-24"/"directional-candle-by-candle.json").read_text()
    )
    expected = sum(
        bool(r["suppressed_events"])
        and bool(r["note"])
        and "SAME_CANDLE" in str(r["note"])
        for r in rows
    )
    assert result["summary"]["same_candle_reversal_blocks"] == expected
