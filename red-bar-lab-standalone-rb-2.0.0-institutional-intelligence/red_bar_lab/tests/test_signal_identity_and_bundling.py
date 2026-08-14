from pathlib import Path

from red_bar_lab.intelligence.fresh_setup_signal_engine import (
    FreshSetupSignalEngine,
)
from red_bar_lab.services.fresh_setup_signal_store import FreshSetupSignalStore
from red_bar_lab.services.fresh_setup_bundle import build_setup_bundles
from red_bar_lab.services.fresh_setup_bundle_store import FreshSetupBundleStore


def inputs():
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
    }
    return snapshot, transition, attribution


def test_signal_ids_are_deterministic():
    snapshot, transition, attribution = inputs()
    first = FreshSetupSignalEngine().detect(
        snapshot, transition, attribution
    )
    second = FreshSetupSignalEngine().detect(
        snapshot, transition, attribution
    )
    assert [x.signal_id for x in first] == [x.signal_id for x in second]


def test_store_returns_existing_canonical_records(tmp_path: Path):
    snapshot, transition, attribution = inputs()
    records = [
        signal.as_record()
        for signal in FreshSetupSignalEngine().detect(
            snapshot, transition, attribution
        )
    ]
    store = FreshSetupSignalStore(tmp_path / "signals.jsonl")
    first, inserted_first = store.resolve_many_once(records)
    second, inserted_second = store.resolve_many_once(records)

    assert inserted_first == len(records)
    assert inserted_second == 0
    assert [r["signal_id"] for r in first] == [
        r["signal_id"] for r in second
    ]


def test_bundle_selects_structure_break_as_primary():
    snapshot, transition, attribution = inputs()
    records = [
        signal.as_record()
        for signal in FreshSetupSignalEngine().detect(
            snapshot, transition, attribution
        )
    ]
    bundles = build_setup_bundles(records)
    assert len(bundles) == 1
    bundle = bundles[0]
    assert bundle.primary_setup_type == "BULLISH_STRUCTURE_BREAK"
    assert "BULLISH_RANGE_BREAKOUT" in bundle.supporting_setup_types
    assert "BULLISH_EMA_RECLAIM" in bundle.supporting_setup_types
    assert bundle.execution_allowed is False


def test_bundle_store_deduplicates_bundle_id(tmp_path: Path):
    snapshot, transition, attribution = inputs()
    records = [
        signal.as_record()
        for signal in FreshSetupSignalEngine().detect(
            snapshot, transition, attribution
        )
    ]
    bundle_records = [
        bundle.as_record()
        for bundle in build_setup_bundles(records)
    ]
    store = FreshSetupBundleStore(tmp_path / "bundles.jsonl")
    assert store.append_many_once(bundle_records) == 1
    assert store.append_many_once(bundle_records) == 0
