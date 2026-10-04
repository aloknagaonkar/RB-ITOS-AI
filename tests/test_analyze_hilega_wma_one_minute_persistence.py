from scripts import analyze_hilega_wma_one_minute_persistence as m


def row(ts, *, direction="BULLISH", wma_change=1.0, rsi=60, ema=55, wma=50):
    return {
        "trade_id": "t1",
        "session_date": "2026-10-01",
        "direction": direction,
        "strategy_signal_timestamp": "2026-10-01T10:00:00+05:30",
        "minute_timestamp": f"2026-10-01T{ts}:00+05:30",
        "directional_wma_change": wma_change,
        "full_directional_alignment": (
            rsi > ema > wma if direction == "BULLISH" else rsi < ema < wma
        ),
        "provisional_rsi9": rsi,
        "provisional_ema3_rsi": ema,
        "provisional_wma21_rsi": wma,
        "observed_close": 100,
    }


def test_bullish_pair_passes_all_components():
    armed = row("10:05", ema=55, wma=50)
    current = row("10:06", ema=56, wma=50.5)
    result = m.evaluate_pair(armed, current, threshold=0.75)
    assert result["persistence_passed"] is True
    assert result["directional_ema_delta"] == 1
    assert result["directional_gap_delta"] == 0.5


def test_false_bullish_rebound_fails_contracting_gap_and_ema():
    armed = row("10:05", ema=56, wma=50)
    current = row("10:06", ema=55, wma=50.5)
    result = m.evaluate_pair(armed, current, threshold=0.75)
    assert result["persistence_passed"] is False
    assert result["ema_continues"] is False
    assert result["gap_not_contracting"] is False


def test_bearish_direction_is_normalized():
    armed = row("10:05", direction="BEARISH", rsi=40, ema=45, wma=50)
    current = row(
        "10:06", direction="BEARISH", rsi=38, ema=44, wma=50.5
    )
    result = m.evaluate_pair(armed, current, threshold=0.75)
    assert result["persistence_passed"] is True
    assert result["directional_ema_delta"] == 1
    assert result["directional_gap_delta"] == 1.5


def test_threshold_must_be_maintained():
    armed = row("10:05", wma_change=0.8)
    current = row("10:06", wma_change=0.7, ema=56, wma=50.5)
    result = m.evaluate_pair(armed, current, threshold=0.75)
    assert result["persistence_passed"] is False
    assert "WMA_THRESHOLD_NOT_MAINTAINED" in result["failure_reasons"]


def test_find_persistence_can_rearm_after_failed_pair():
    rows = [
        row("10:05", ema=55, wma=50),
        row("10:06", ema=54, wma=50.5),
        row("10:07", ema=55, wma=51),
    ]
    passed, attempts = m.find_persistence(rows, 0.75)
    assert len(attempts) == 2
    assert passed is not None
    assert passed["confirmation_timestamp"].startswith("2026-10-01T10:07")


def test_non_consecutive_minutes_do_not_form_pair():
    passed, attempts = m.find_persistence(
        [row("10:05"), row("10:07", ema=56, wma=50.5)], 0.75
    )
    assert passed is None
    assert attempts == []

