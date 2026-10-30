from scripts.analyze_hilega_wma_gap_clear_losses import (
    checkpoint_row,
    classify_same_candle_conflicts,
    warning_reasons,
)


def feature(**overrides):
    row = {
        "wma_strength": 1.0,
        "directional_gap": 5.0,
        "gap_delta_1m": 0.2,
        "ema_directional_delta_1m": 0.3,
        "full_alignment": True,
        "points_from_candidate_entry": 2.0,
    }
    row.update(overrides)
    return row


def trace_row(timestamp, close, wma, ema, wma21, aligned=True):
    return {
        "minute_timestamp": timestamp,
        "direction": "BULLISH",
        "observed_close": close,
        "directional_wma_change": wma,
        "provisional_rsi9": 60.0,
        "provisional_ema3_rsi": ema,
        "provisional_wma21_rsi": wma21,
        "full_directional_alignment": aligned,
    }


def test_warning_reasons_make_each_failed_component_explicit():
    reasons = warning_reasons(feature(
        wma_strength=0.4,
        directional_gap=-1.0,
        gap_delta_1m=-0.2,
        ema_directional_delta_1m=-0.3,
        full_alignment=False,
        points_from_candidate_entry=-2.0,
    ), 0.75)
    assert reasons == [
        "WMA_BELOW_0_75",
        "GAP_NON_POSITIVE",
        "GAP_CONTRACTING",
        "EMA_NOT_CONTINUING",
        "RSI_EMA_WMA_NOT_ALIGNED",
        "NO_POSITIVE_PRICE_PROGRESS",
    ]


def test_checkpoint_requires_the_exact_future_minute():
    trace = [
        trace_row("2026-10-01T10:00:00+05:30", 100, 1.0, 60, 55),
        trace_row("2026-10-01T10:01:00+05:30", 102, 1.1, 61, 55.5),
    ]
    result = checkpoint_row(trace, 0, 1, 100)
    assert result is not None
    assert result["points_from_candidate_entry"] == 2
    assert result["directional_gap"] == 5.5
    assert checkpoint_row(trace, 0, 3, 100) is None


def test_same_candle_audit_distinguishes_label_from_completed_close():
    row = {
        "session_date": "2026-10-01",
        "trade_id": "NEW",
        "direction": "BULLISH",
        "signal_timestamp": "2026-10-01T10:00:00+05:30",
        "candidate_entry_timestamp": "2026-10-01T10:04:00+05:30",
        "canonical_exit_timestamp": "2026-10-01T11:00:00+05:30",
    }
    previous = {
        "session_date": "2026-10-01",
        "trade_id": "OLD",
        "direction": "BEARISH",
        "exit_timestamp": "2026-10-01T10:00:00+05:30",
    }
    conflicts = classify_same_candle_conflicts(row, [previous])
    kinds = {item["conflict_type"] for item in conflicts}
    assert "ENTRY_EQUALS_OTHER_EXIT_COMPLETED_CLOSE" in kinds
    assert "ENTRY_INSIDE_OTHER_EXIT_5M_CANDLE" in kinds
    assert "SIGNAL_EQUALS_OTHER_EXIT_LABEL" in kinds
