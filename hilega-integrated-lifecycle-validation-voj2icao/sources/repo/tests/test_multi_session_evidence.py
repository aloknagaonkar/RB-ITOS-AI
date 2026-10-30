from datetime import date, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from market_lab.domain import PCRConfig, PCRTrendClassification, SessionAnalysisObservation
import market_lab.multi_session_evidence as multi_session_evidence
from market_lab.multi_session_evidence import (
    CompatibleConfigDiscovery,
    CompatibleEvidenceHistoryInput,
    build_compatible_pattern_evidence,
    collect_compatible_session_analysis,
    discover_compatible_configs,
)
from market_lab.storage import Configuration, initialize, make_engine


@pytest.fixture
def engine(tmp_path):
    value = make_engine("sqlite:///" + (tmp_path / "configs.db").as_posix())
    initialize(value)
    yield value
    value.dispose()


def add_config(session, **changes):
    config = PCRConfig(expiry=date(2026, 9, 15)).model_copy(update=changes)
    row = Configuration(created_at="2026-09-11T09:15:00+05:30", payload=config.model_dump(mode="json"))
    session.add(row)
    session.flush()
    return row.id


def test_requested_config_includes_itself_and_compatible_expiry_versions(engine):
    with Session(engine) as session, session.begin():
        first = add_config(session)
        second = add_config(session, expiry=date(2026, 9, 22), name="Different version")
        result = discover_compatible_configs(session, first)
    assert result.compatible_config_ids == (1, first, second)
    assert result.configuration_versions == (1, first, second)
    assert result.expiries == (date(2026, 9, 15), date(2026, 9, 18), date(2026, 9, 22))


@pytest.mark.parametrize("changes", [
    {"wings": 7},
    {"underlying": "NSE_INDEX|BANKNIFTY"},
    {"trend_flat_threshold": 0.02},
])
def test_semantic_changes_are_excluded(engine, changes):
    with Session(engine) as session, session.begin():
        requested = add_config(session)
        incompatible = add_config(session, **changes)
        result = discover_compatible_configs(session, requested)
    assert requested in result.compatible_config_ids
    assert incompatible not in result.compatible_config_ids


def test_requested_config_not_found_uses_value_error(engine):
    with Session(engine) as session:
        with pytest.raises(ValueError, match="Configuration not found"):
            discover_compatible_configs(session, 999)


def analysis(observation_id, config_id, minute, fingerprint, forward_change=None):
    received_at = datetime.fromisoformat("2026-09-11T09:20:00+05:30") + timedelta(minutes=minute)
    return SessionAnalysisObservation(
        observation_id=observation_id,
        received_at=received_at,
        underlying="NSE_INDEX|Nifty 50",
        expiry=date(2026, 9, 15),
        calculation_fingerprint=fingerprint,
        configuration_version=config_id,
        underlying_spot=25_000 + minute,
        moving_pcr=1.1,
        forward_change_5m=forward_change,
    )


def test_compatible_observations_are_combined_unchanged_and_ordered(engine, monkeypatch):
    with Session(engine) as session, session.begin():
        first = add_config(session)
        second = add_config(session, expiry=date(2026, 9, 22))
        excluded = add_config(session, wings=7)
        later = analysis(20, first, 5, "fingerprint-a", None)
        earlier = analysis(10, second, 0, "fingerprint-b", 12.5)
        excluded_value = analysis(30, excluded, 1, "excluded", 99)
        values = {first: [later], second: [earlier], excluded: [excluded_value]}
        monkeypatch.setattr(multi_session_evidence, "session_analysis_results", lambda _, config_id: values.get(config_id, []))
        result = collect_compatible_session_analysis(session, first)
    assert result.compatible_config_ids == (1, first, second)
    assert result.observations == (earlier, later)
    assert result.observations[1].forward_change_5m is None
    assert result.calculation_fingerprints == ("fingerprint-a", "fingerprint-b")
    assert result.expiries == (date(2026, 9, 15), date(2026, 9, 18), date(2026, 9, 22))


def test_equal_observations_from_different_configs_are_not_deduplicated(engine, monkeypatch):
    with Session(engine) as session, session.begin():
        first = add_config(session)
        second = add_config(session)
        one = analysis(7, first, 0, "same")
        two = one.model_copy(update={"configuration_version": second})
        monkeypatch.setattr(multi_session_evidence, "session_analysis_results", lambda _, config_id: {first: [one], second: [two]}.get(config_id, []))
        result = collect_compatible_session_analysis(session, first)
    assert result.observations == (one, two)


def test_compatible_configs_with_no_history_return_empty_collection(engine, monkeypatch):
    with Session(engine) as session, session.begin():
        requested = add_config(session)
        monkeypatch.setattr(multi_session_evidence, "session_analysis_results", lambda *_: [])
        result = collect_compatible_session_analysis(session, requested)
    assert requested in result.compatible_config_ids
    assert result.observations == ()
    assert result.calculation_fingerprints == ()


def test_combined_observations_build_one_evidence_report_from_individual_outcomes():
    first_config = PCRConfig(expiry=date(2026, 9, 15))
    second_config = first_config.model_copy(update={"expiry": date(2026, 9, 22)})
    compatibility = first_config.evidence_compatibility_fingerprint()
    discovery = CompatibleConfigDiscovery(4, first_config, compatibility, ((4, first_config), (5, second_config)))
    observations = []
    for index in range(12):
        value = analysis(index + 1, 4 if index < 6 else 5, index, "exact-a" if index < 6 else "exact-b", float(index - 3))
        observations.append(value.model_copy(update={
            "received_at": value.received_at + timedelta(days=index // 4),
            "expiry": first_config.expiry if index < 6 else second_config.expiry,
            "moving_change_5m": 0.02,
            "moving_trend_5m": PCRTrendClassification.RISING,
        }))
    history = CompatibleEvidenceHistoryInput(discovery, ("exact-a", "exact-b"), tuple(observations))
    report = build_compatible_pattern_evidence(history)
    row = next(item for item in report.rows if item.pattern_kind == "single_mode_trend" and item.mode == "moving" and item.horizon_minutes == 5)
    assert report.observation_count == 12 and report.distinct_session_count == 3
    assert report.calculation_fingerprints == ("exact-a", "exact-b")
    assert report.configuration_versions == (4, 5)
    assert report.expiries == (date(2026, 9, 15), date(2026, 9, 22))
    assert row.available_count == 12 and row.available_session_count == 3
    assert row.average_points == sum(float(index - 3) for index in range(12)) / 12
    assert row.maturity == "MULTI_SESSION"


def test_empty_compatible_history_returns_metadata_only_report():
    config = PCRConfig(expiry=date(2026, 9, 15))
    discovery = CompatibleConfigDiscovery(4, config, config.evidence_compatibility_fingerprint(), ((4, config),))
    report = build_compatible_pattern_evidence(CompatibleEvidenceHistoryInput(discovery, (), ()))
    assert report.observation_count == 0 and report.distinct_session_count == 0 and report.rows == []
    assert report.configuration_versions == (4,) and report.expiries == (date(2026, 9, 15),)
