from __future__ import annotations

from red_bar_lab.operations.red_bar_v2_ui_snapshot import (
    RedBarV2UISnapshot,
    persist_red_bar_v2_ui_snapshot,
    read_red_bar_v2_ui_snapshot,
)
from red_bar_lab.ui.red_bar_v2_legacy_panel import render_red_bar_v2_legacy_panel


class _Column:
    def __init__(self, calls):
        self.calls = calls

    def metric(self, label, value):
        self.calls.append(("metric", label, value))


class _Expander:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _Streamlit:
    def __init__(self):
        self.calls = []

    def markdown(self, value):
        self.calls.append(("markdown", value))

    def caption(self, value):
        self.calls.append(("caption", value))

    def warning(self, value):
        self.calls.append(("warning", value))

    def columns(self, count):
        return [_Column(self.calls) for _ in range(count)]

    def write(self, value):
        self.calls.append(("write", value))

    def expander(self, label):
        self.calls.append(("expander", label))
        return _Expander()

    def dataframe(self, rows, **kwargs):
        self.calls.append(("dataframe", rows))


def _snapshot() -> RedBarV2UISnapshot:
    return RedBarV2UISnapshot(
        reference_status="REFERENCE_READY",
        reference_midpoint=24100.0,
        index_close=24080.0,
        index_rsi=42.5,
        futures_close=24105.0,
        futures_vwap=24120.0,
        alignment_status="READY",
        directional_state="CONFIRMED_BEARISH",
        direction="BEARISH",
        option_side="PE",
        reversal_status="BEARISH_REVERSAL_DETECTED",
        trade_status="ACTIVE",
        trade_id="RBV2-0001",
        admission_allowed=True,
        admission_code="REVERSAL_CONTEXT_ALIGNED_FLAT",
        admission_reason="Opposite context is aligned and execution is flat.",
        trend_strength="CONFIRMED",
        provisional_confirmed_state="CONFIRMED",
        midpoint_confirmation="BEARISH_CONFIRMED",
        midpoint_aligned=True,
    )


def test_ui_snapshot_round_trip(tmp_path):
    persist_red_bar_v2_ui_snapshot(_snapshot(), artifacts_root=tmp_path)
    restored = read_red_bar_v2_ui_snapshot(tmp_path)

    assert restored is not None
    assert restored.strategy_version == "RED_BAR_V2"
    assert restored.index_rsi == 42.5
    assert restored.futures_vwap == 24120.0
    assert restored.admission_code == "REVERSAL_CONTEXT_ALIGNED_FLAT"
    assert restored.recorded_at is not None


def test_legacy_panel_displays_required_v2_fields():
    st = _Streamlit()
    render_red_bar_v2_legacy_panel(st, _snapshot())
    labels = {
        call[1]
        for call in st.calls
        if call[0] == "metric"
    }

    assert {
        "Reference status",
        "Index RSI",
        "Futures VWAP",
        "RSI position",
        "Futures vs VWAP",
        "VWAP gap",
        "RSI + VWAP alignment",
        "Directional state",
        "Reversal status",
        "Trade status",
        "Admission code",
        "Provisional / confirmed",
        "Midpoint confirmation",
    }.issubset(labels)

    metrics = {
        call[1]: call[2]
        for call in st.calls
        if call[0] == "metric"
    }
    assert metrics["RSI position"] == "BELOW 50"
    assert metrics["Futures vs VWAP"] == "BELOW VWAP"
    assert metrics["VWAP gap"] == "-15.00"
    assert metrics["RSI + VWAP alignment"] == "BEARISH ALIGNED"


def test_legacy_panel_fails_safe_without_snapshot():
    st = _Streamlit()
    render_red_bar_v2_legacy_panel(st, None)
    assert any(call[0] == "warning" for call in st.calls)
