from datetime import date

import pytest
from fastapi.testclient import TestClient

import market_lab.api as api_module
from market_lab.api import create_app
from market_lab.domain import PCRConfig, PatternEvidenceReport
from market_lab.multi_session_evidence import CompatibleConfigDiscovery, CompatibleEvidenceHistoryInput
from market_lab.storage import initialize, make_engine


@pytest.fixture
def engine(tmp_path):
    value = make_engine("sqlite:///" + (tmp_path / "history-api.db").as_posix())
    initialize(value)
    yield value
    value.dispose()


def empty_report(history):
    config = history.discovery.requested_config
    return PatternEvidenceReport(
        calculation_fingerprint=config.trend_fingerprint("full"),
        evidence_compatibility_fingerprint=history.evidence_compatibility_fingerprint,
        calculation_fingerprints=history.calculation_fingerprints,
        configuration_versions=history.configuration_versions,
        expiries=history.expiries,
        configuration_version=history.requested_config_id,
        underlying=config.underlying,
        expiry=config.expiry,
        observation_count=0,
        distinct_session_count=0,
        rows=[],
    )


def test_history_endpoint_wires_compatible_collection_to_evidence(engine, monkeypatch):
    first = PCRConfig(expiry=date(2026, 9, 15))
    second = first.model_copy(update={"expiry": date(2026, 9, 22)})
    compatibility = first.evidence_compatibility_fingerprint()
    discovery = CompatibleConfigDiscovery(1, first, compatibility, ((1, first), (2, second)))
    history = CompatibleEvidenceHistoryInput(discovery, ("exact-a", "exact-b"), ())
    calls = []
    monkeypatch.setattr(api_module, "collect_compatible_session_analysis", lambda session, config_id: calls.append(config_id) or history)
    monkeypatch.setattr(api_module, "build_compatible_pattern_evidence", empty_report)

    with TestClient(create_app(engine)) as client:
        response = client.get("/api/pcr-pattern-evidence/history?config_id=1")

    assert response.status_code == 200 and calls == [1]
    payload = response.json()
    assert payload["evidence_compatibility_fingerprint"] == compatibility
    assert payload["calculation_fingerprints"] == ["exact-a", "exact-b"]
    assert payload["configuration_versions"] == [1, 2]
    assert payload["expiries"] == ["2026-09-15", "2026-09-22"]
    assert payload["observation_count"] == 0 and payload["distinct_session_count"] == 0
    assert payload["rows"] == []


def test_history_endpoint_translates_missing_config_to_404(engine, monkeypatch):
    def missing(*_):
        raise ValueError("Configuration not found")
    monkeypatch.setattr(api_module, "collect_compatible_session_analysis", missing)
    with TestClient(create_app(engine)) as client:
        response = client.get("/api/pcr-pattern-evidence/history?config_id=999")
    assert response.status_code == 404
    assert response.json() == {"detail": "Configuration not found"}


def test_existing_evidence_endpoint_remains_config_specific(engine, monkeypatch):
    requested = []
    monkeypatch.setattr(api_module, "session_analysis_results", lambda session, config_id: requested.append(config_id) or [])
    monkeypatch.setattr(api_module, "collect_compatible_session_analysis", lambda *_: pytest.fail("history service must not be used"))
    with TestClient(create_app(engine)) as client:
        response = client.get("/api/pcr-pattern-evidence?config_id=1")
    assert response.status_code == 200 and response.json() == []
    assert requested == [1]
