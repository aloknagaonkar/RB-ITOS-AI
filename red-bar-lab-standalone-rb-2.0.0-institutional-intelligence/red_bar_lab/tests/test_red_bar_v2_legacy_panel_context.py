from red_bar_lab.operations.red_bar_v2_ui_snapshot import RedBarV2UISnapshot
from red_bar_lab.ui.red_bar_v2_legacy_panel import (
    _rsi_position,
    _rsi_vwap_context,
)


def _snapshot(*, rsi, futures_close, futures_vwap):
    return RedBarV2UISnapshot(
        index_rsi=rsi,
        futures_close=futures_close,
        futures_vwap=futures_vwap,
    )


def test_rsi_position_uses_strategy_55_45_thresholds():
    assert _rsi_position(56.0) == "BULLISH THRESHOLD PASSED (>55)"
    assert _rsi_position(53.92) == "NEUTRAL STRATEGY ZONE (45–55)"
    assert _rsi_position(44.0) == "BEARISH THRESHOLD PASSED (<45)"


def test_rsi_vwap_label_is_context_only():
    assert _rsi_vwap_context(
        _snapshot(rsi=60.0, futures_close=24300.0, futures_vwap=24290.0)
    ) == "BULLISH CONTEXT"
    assert _rsi_vwap_context(
        _snapshot(rsi=53.92, futures_close=24288.2, futures_vwap=24285.71)
    ) == "NEUTRAL RSI / VWAP CONTEXT ONLY"
    assert _rsi_vwap_context(
        _snapshot(rsi=40.0, futures_close=24270.0, futures_vwap=24290.0)
    ) == "BEARISH CONTEXT"
