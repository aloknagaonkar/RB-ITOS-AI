from types import SimpleNamespace

import pandas as pd

from red_bar_lab.ui.rsi_decision_trace_alignment import (
    build_aligned_rsi_setup_state,
    confirmation_candle_index,
    install_rsi_decision_trace_alignment,
)


def _frame():
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                [
                    "2026-08-17T07:45:00Z",
                    "2026-08-17T07:46:00Z",
                    "2026-08-17T07:47:00Z",
                ],
                utc=True,
            )
        }
    )


def test_confirmation_close_time_maps_to_previous_minute_candle_open():
    frame = _frame()
    signal = {"confirmation_timestamp": "2026-08-17T13:17:00+05:30"}

    assert confirmation_candle_index(frame, signal) == 1


def test_open_time_signal_records_remain_compatible():
    frame = _frame()
    signal = {"confirmation_timestamp": "2026-08-17T13:16:00+05:30"}

    assert confirmation_candle_index(frame, signal) == 0


def test_unalignable_confirmed_signal_never_falls_back_to_latest_candle():
    frame = _frame()
    signal = {"confirmation_timestamp": "2026-08-17T14:30:00+05:30"}

    assert confirmation_candle_index(frame, signal) == -1


def test_no_signal_still_uses_latest_candle_for_current_evaluation():
    frame = _frame()

    assert confirmation_candle_index(frame, {}) == 2


def test_confirmed_trace_is_labeled_as_historical_signal_event():
    def original_builder(*args, **kwargs):
        return {
            "status": "CONFIRMED",
            "waiting_for": "old",
            "blocker": "old",
            "decision_trace": {
                "final_outcome": "CONFIRMED",
                "next_step": "old",
            },
        }

    result = build_aligned_rsi_setup_state(original_builder)()

    assert result["decision_trace"]["trace_scope"] == "CONFIRMED_SIGNAL_EVENT"
    assert "Sections 3 and 4" in result["decision_trace"]["next_step"]
    assert "current lifecycle" in result["blocker"]
    assert "execution-source gate" in result["waiting_for"]


def test_install_replaces_page_builder_and_detector_index(monkeypatch):
    import red_bar_lab.ui.strategy_setup_detection as setup_detection

    page_module = SimpleNamespace(
        build_rsi_setup_state=lambda *args, **kwargs: {
            "status": "CONFIRMED",
            "decision_trace": {"final_outcome": "CONFIRMED"},
        }
    )

    original_index = setup_detection._evaluation_index
    try:
        install_rsi_decision_trace_alignment(page_module)
        assert setup_detection._evaluation_index is confirmation_candle_index
        result = page_module.build_rsi_setup_state()
        assert result["decision_trace"]["trace_scope"] == "CONFIRMED_SIGNAL_EVENT"
    finally:
        monkeypatch.setattr(setup_detection, "_evaluation_index", original_index)
