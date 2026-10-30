import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_script():
    path = ROOT / "scripts/materialize_midpoint_historical_health.py"
    spec = importlib.util.spec_from_file_location("historical_health_dedupe", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _row(event_id: str, event_type: str, minute: str, family: str = "E"):
    return {
        "event_id": event_id,
        "event_timestamp": f"2026-10-01T{minute}:00+05:30",
        "event_type": event_type,
        "direction": "BEARISH",
        "reference_type": "RED",
        "family": family,
    }


def test_recorded_live_health_wins_over_reconstructed_overlay():
    module = _load_script()
    recorded = [
        _row("live-entry", "ENTRY_HEALTH_SNAPSHOT", "12:10"),
        _row("live-continuous", "CONTINUOUS_HEALTH_CHECK", "12:11"),
    ]
    generated = [
        _row("overlay-entry", "ENTRY_HEALTH_SNAPSHOT", "12:10"),
        _row("overlay-continuous", "CONTINUOUS_HEALTH_CHECK", "12:11"),
    ]
    overlay, duplicates = module.remove_recorded_health(generated, recorded)
    assert overlay == []
    assert duplicates == 2


def test_overlay_fills_only_health_missing_from_live_audit():
    module = _load_script()
    recorded = [_row("live-entry", "ENTRY_HEALTH_SNAPSHOT", "12:10")]
    missing = _row("overlay-continuous", "CONTINUOUS_HEALTH_CHECK", "12:11")
    overlay, duplicates = module.remove_recorded_health(
        [
            _row("overlay-entry", "ENTRY_HEALTH_SNAPSHOT", "12:10"),
            missing,
        ],
        recorded,
    )
    assert overlay == [missing]
    assert duplicates == 1


def test_counter_preserves_distinct_repeated_lane_occurrences():
    module = _load_script()
    one_recorded = [_row("live-one", "CONTINUOUS_HEALTH_CHECK", "12:11")]
    generated = [
        _row("overlay-one", "CONTINUOUS_HEALTH_CHECK", "12:11"),
        _row("overlay-two", "CONTINUOUS_HEALTH_CHECK", "12:11"),
    ]
    overlay, duplicates = module.remove_recorded_health(generated, one_recorded)
    assert overlay == [generated[1]]
    assert duplicates == 1


def test_recorded_t5_unavailable_is_not_replaced_with_hindsight_check():
    module = _load_script()
    recorded = [_row("live", "T5_HEALTH_UNAVAILABLE", "12:15")]
    generated = [_row("overlay", "T5_HEALTH_CHECK", "12:15")]
    overlay, duplicates = module.remove_recorded_health(generated, recorded)
    assert overlay == []
    assert duplicates == 1
