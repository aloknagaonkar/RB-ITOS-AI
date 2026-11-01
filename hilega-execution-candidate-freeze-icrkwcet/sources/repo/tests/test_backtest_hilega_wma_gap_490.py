from scripts import backtest_hilega_wma_gap_490 as m


def row(ts, *, direction="BULLISH", strength=1.0, ema=55.0, wma=50.0):
    return {
        "trade_id": "t1",
        "session_date": "2026-10-01",
        "direction": direction,
        "strategy_signal_timestamp": "2026-10-01T10:00:00+05:30",
        "minute_timestamp": f"2026-10-01T{ts}:00+05:30",
        "directional_wma_change": strength,
        "provisional_ema3_rsi": ema,
        "provisional_wma21_rsi": wma,
        "observed_close": 100.0,
    }


def test_arming_candle_cannot_confirm_itself():
    confirmed, attempts = m.ordered_gap_confirmation(
        [row("10:05", strength=0.4, ema=52), row("10:06", strength=1.0, ema=56)],
        0.75,
    )
    assert confirmed is None
    assert attempts == []


def test_later_bullish_gap_expansion_confirms():
    confirmed, attempts = m.ordered_gap_confirmation(
        [row("10:05", ema=55), row("10:06", ema=56)], 0.75
    )
    assert confirmed is not None
    assert confirmed["confirmation_timestamp"].startswith("2026-10-01T10:06")
    assert attempts[0]["directional_gap_delta"] == 1.0


def test_later_bearish_gap_expansion_confirms():
    confirmed, _ = m.ordered_gap_confirmation(
        [
            row("10:05", direction="BEARISH", ema=45, wma=50),
            row("10:06", direction="BEARISH", ema=44, wma=50),
        ],
        0.75,
    )
    assert confirmed is not None
    assert confirmed["directional_gap_delta"] == 1.0


def test_contracting_gap_does_not_confirm():
    confirmed, attempts = m.ordered_gap_confirmation(
        [row("10:05", ema=56), row("10:06", ema=55)], 0.75
    )
    assert confirmed is None
    assert attempts[0]["failure_reasons"] == "DIRECTIONAL_GAP_NOT_EXPANDING"


def test_threshold_must_remain_armed():
    confirmed, attempts = m.ordered_gap_confirmation(
        [row("10:05", strength=1.0, ema=55), row("10:06", strength=0.7, ema=56)],
        0.75,
    )
    assert confirmed is None
    assert "WMA_THRESHOLD_NOT_MAINTAINED" in attempts[0]["failure_reasons"]


def test_failed_pair_can_rearm_and_later_pass():
    confirmed, attempts = m.ordered_gap_confirmation(
        [row("10:05", ema=56), row("10:06", ema=55), row("10:07", ema=57)],
        0.75,
    )
    assert len(attempts) == 2
    assert confirmed is not None
    assert confirmed["confirmation_timestamp"].startswith("2026-10-01T10:07")


def test_non_consecutive_rows_do_not_confirm():
    confirmed, attempts = m.ordered_gap_confirmation(
        [row("10:05", ema=55), row("10:07", ema=56)], 0.75
    )
    assert confirmed is None
    assert attempts == []


def test_directional_points():
    assert m.directional_points("BULLISH", 100, 112) == 12
    assert m.directional_points("BEARISH", 100, 88) == 12

