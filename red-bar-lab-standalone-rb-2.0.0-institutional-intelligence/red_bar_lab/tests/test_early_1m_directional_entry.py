import pandas as pd

from red_bar_lab.execution.early_directional_entry import (
    EarlyOneMinuteDirectionalEntryEngine,
)


def bullish_break():
    rows = []
    price = 100.0

    for timestamp in pd.date_range(
        "2026-08-14 09:15",
        periods=45,
        freq="1min",
        tz="Asia/Kolkata",
    ):
        close = price + 0.08
        rows.append(
            {
                "timestamp": timestamp,
                "open": price,
                "high": max(price, close) + 0.15,
                "low": min(price, close) - 0.15,
                "close": close,
                "volume": 100,
            }
        )
        price = close

    rows[33].update(open=103.00, low=102.40, high=103.10, close=102.80)
    rows[34].update(open=102.80, low=102.20, high=102.90, close=102.50)
    rows[35].update(open=102.50, low=102.35, high=103.20, close=103.10)
    rows[36].update(open=103.10, low=103.00, high=104.00, close=103.90)
    rows[37].update(open=103.90, low=103.80, high=104.60, close=104.10)
    rows[38].update(high=104.30, close=104.00)
    rows[39].update(high=104.20, close=104.05)
    rows[40].update(open=104.05, low=104.00, high=104.25, close=104.20)
    rows[41].update(open=104.20, low=104.15, high=104.35, close=104.30)
    rows[42].update(open=104.30, low=104.25, high=104.45, close=104.40)
    rows[43].update(open=104.40, low=104.35, high=104.55, close=104.50)
    rows[44].update(open=104.50, low=104.45, high=105.40, close=105.30)

    return pd.DataFrame(rows)


def test_early_bullish_signal_without_bullish_5m_confirmation():
    result = EarlyOneMinuteDirectionalEntryEngine().evaluate(
        bullish_break(),
        five_minute_regime="SIDEWAYS",
        instrument_key="NIFTY",
    )

    assert result.status == "READY"
    assert result.direction == "BULLISH"
    assert result.bundle["entry_stage"] == "EARLY_1M"
    assert result.bundle["candidate_limit"] == 1


def test_opposite_five_minute_regime_blocks_early_entry():
    result = EarlyOneMinuteDirectionalEntryEngine().evaluate(
        bullish_break(),
        five_minute_regime="BEARISH",
        instrument_key="NIFTY",
    )

    assert result.status == "BLOCKED"
    assert result.reason == "OPPOSITE_5M_BEARISH"


def test_early_bundle_has_four_minute_freshness():
    result = EarlyOneMinuteDirectionalEntryEngine().evaluate(
        bullish_break(),
        five_minute_regime="SIDEWAYS",
        instrument_key="NIFTY",
    )

    detected = pd.Timestamp(result.bundle["detected_at"])
    fresh_until = pd.Timestamp(result.bundle["fresh_until"])

    assert (fresh_until - detected).total_seconds() == 240
