from pathlib import Path

from red_bar_lab.intelligence.fresh_setup_signal_engine import (
    FreshSetupSignalEngine,
)
from red_bar_lab.services.fresh_setup_signal_store import FreshSetupSignalStore
from red_bar_lab.services.signal_attribution import attach_signal_to_attribution


def bullish_inputs():
    snapshot = {
        "timestamp": "2026-08-13T10:00:00",
        "break_level": 24364.5,
        "invalidation_level": 24342.25,
        "red_bar_support": "NOT_AVAILABLE",
        "evidence": [
            "5M_CLOSE_ABOVE_EMA10",
            "5M_EMA10_RISING",
            "1M_EMA10_ABOVE_EMA30",
            "1M_HIGHER_LOW",
            "1M_STRUCTURE_BREAKOUT",
            "1M_POSITIVE_MOMENTUM",
        ],
    }
    transition = {
        "transition_id": "TR-BULL-1",
        "direction": "BULLISH",
        "updated_at": "2026-08-13T10:00:00",
    }
    attribution = {
        "regime_snapshot_id": "REG-NIFTY-1",
        "transition_id": "TR-BULL-1",
        "execution_allowed": False,
    }
    return snapshot, transition, attribution


def test_bullish_signals_are_generated_separately():
    snapshot, transition, attribution = bullish_inputs()
    signals = FreshSetupSignalEngine().detect(
        snapshot,
        transition,
        attribution,
    )
    setup_types = {signal.setup_type for signal in signals}
    assert "BULLISH_STRUCTURE_BREAK" in setup_types
    assert "BULLISH_EMA_RECLAIM" in setup_types
    assert "BULLISH_RANGE_BREAKOUT" in setup_types
    assert "BULLISH_PULLBACK_CONTINUATION" in setup_types
    assert all(signal.execution_allowed is False for signal in signals)


def test_signal_ids_and_freshness_are_populated():
    snapshot, transition, attribution = bullish_inputs()
    signal = FreshSetupSignalEngine().detect(
        snapshot,
        transition,
        attribution,
    )[0]
    assert signal.signal_id.startswith("SIG-")
    assert signal.fresh_until > signal.detected_at
    assert signal.transition_id == "TR-BULL-1"


def test_store_deduplicates_transition_setup_timestamp(tmp_path: Path):
    snapshot, transition, attribution = bullish_inputs()
    records = [
        signal.as_record()
        for signal in FreshSetupSignalEngine().detect(
            snapshot,
            transition,
            attribution,
        )
    ]
    store = FreshSetupSignalStore(tmp_path / "signals.jsonl")
    assert store.append_many_once(records) == len(records)
    assert store.append_many_once(records) == 0
    assert store.counts_by_type()


def test_signal_attribution_populates_signal_id_and_trigger():
    snapshot, transition, attribution = bullish_inputs()
    signal = FreshSetupSignalEngine().detect(
        snapshot,
        transition,
        attribution,
    )[0].as_record()
    updated = attach_signal_to_attribution(attribution, signal)
    assert updated["signal_id"] == signal["signal_id"]
    assert updated["primary_trigger"] == signal["setup_type"]
    assert updated["execution_allowed"] is False
