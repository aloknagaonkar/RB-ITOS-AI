from market_lab.historical_replay_session_config_v1 import replay_semantic_payload


BASE = {
    "name": "NIFTY PCR comparison",
    "provider": "upstox",
    "underlying": "NSE_INDEX|Nifty 50",
    "expiry": "2026-09-15",
    "wings": 5,
    "anchor_time": "09:20",
    "anchor_tolerance_seconds": 120,
    "interval_seconds": 60,
    "max_quote_age_seconds": 30,
    "max_collection_seconds": 20,
}


def test_collection_cadence_and_name_do_not_change_replay_semantics():
    a = replay_semantic_payload(BASE)
    b = replay_semantic_payload({
        **BASE,
        "name": "renamed collector",
        "interval_seconds": 15,
        "trend_flat_threshold": 0.01,
        "trend_timestamp_tolerance_seconds": 60,
    })
    assert a == b


def test_replay_relevant_change_is_detectable():
    a = replay_semantic_payload(BASE)
    b = replay_semantic_payload({**BASE, "wings": 4})
    assert a != b


def test_explicit_defaults_equal_implicit_defaults():
    implicit = replay_semantic_payload(BASE)
    explicit = replay_semantic_payload({
        **BASE,
        "trend_flat_threshold": 0.01,
        "trend_timestamp_tolerance_seconds": 60,
    })
    assert implicit == explicit


def test_snapshot_index_source_merges_equivalent_config_ids():
    from pathlib import Path
    text = Path("backend/market_lab/historical_replay_snapshot_index_v1.py").read_text(encoding="utf-8")
    assert "resolve_session_config_ids(engine, session_date)" in text
    assert "Observation.config_id.in_(config_ids)" in text


def test_day_resolver_delegates_to_equivalence_guard():
    from pathlib import Path
    text = Path("backend/market_lab/historical_replay_day_v1_1.py").read_text(encoding="utf-8")
    assert "historical_replay_session_config_v1" in text
    assert "def resolve_session_config_ids" in text
