from pathlib import Path
import json

from red_bar_lab.execution.directional_regime_native_signal import (
    enrich_bundle_from_primary_signal,
    read_fresh_bundles,
)


def test_bundle_inherits_execution_fields_from_primary_signal():
    bundle = {
        "bundle_id": "BND-1",
        "primary_signal_id": "SIG-1",
        "direction": "BULLISH",
        "detected_at": "2026-08-14T08:25:00+00:00",
        "current_regime": "BULLISH",
    }
    signal = {
        "signal_id": "SIG-1",
        "setup_type": "BULLISH_STRUCTURE_BREAK",
        "direction": "BULLISH",
        "detected_at": "2026-08-14T08:25:00+00:00",
        "fresh_until": "2026-08-14T08:29:00+00:00",
        "trigger_level": 24389.1,
        "invalidation_level": 24381.6,
        "red_bar_alignment": "NOT_AVAILABLE",
    }
    enriched = enrich_bundle_from_primary_signal(bundle, signal)
    assert enriched["fresh_until"] == signal["fresh_until"]
    assert enriched["primary_setup_type"] == "BULLISH_STRUCTURE_BREAK"
    assert enriched["trigger_level"] == 24389.1
    assert enriched["invalidation_level"] == 24381.6


def test_reader_creates_native_signal_from_normal_v43_bundle(tmp_path: Path):
    bundle_dir = tmp_path / "fresh_setup_bundles_v43"
    signal_dir = tmp_path / "fresh_setup_signals_v43"
    bundle_dir.mkdir()
    signal_dir.mkdir()

    bundle = {
        "bundle_id": "BND-1",
        "primary_signal_id": "SIG-1",
        "direction": "BULLISH",
        "detected_at": "2026-08-14T08:25:00+00:00",
        "current_regime": "BULLISH",
    }
    signal = {
        "signal_id": "SIG-1",
        "setup_type": "BULLISH_STRUCTURE_BREAK",
        "direction": "BULLISH",
        "detected_at": "2026-08-14T08:25:00+00:00",
        "fresh_until": "2026-08-14T08:29:00+00:00",
        "trigger_level": 24389.1,
        "invalidation_level": 24381.6,
    }

    (bundle_dir / "NIFTY.jsonl").write_text(
        json.dumps(bundle) + "\n",
        encoding="utf-8",
    )
    (signal_dir / "NIFTY.jsonl").write_text(
        json.dumps(signal) + "\n",
        encoding="utf-8",
    )

    rows = read_fresh_bundles(
        tmp_path,
        now="2026-08-14T13:57:00+05:30",
    )
    assert len(rows) == 1
    assert rows[0]["signal_id"] == "DRI-BND-1"
    assert rows[0]["primary_setup_type"] == "BULLISH_STRUCTURE_BREAK"
    assert rows[0]["option_type"] == "CE"
