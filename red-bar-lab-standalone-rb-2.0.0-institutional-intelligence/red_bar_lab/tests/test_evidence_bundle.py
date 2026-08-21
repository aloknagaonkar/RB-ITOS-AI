import json

from red_bar_lab.services.evidence_bundle import (
    build_evidence_bundles,
    evidence_bundles_csv,
    evidence_bundles_json,
    persist_evidence_bundles,
    read_evidence_bundles,
)


def _gate():
    return {
        "policy_version": "operations-readiness-gate-v2",
        "authority": "OBSERVATIONAL_ONLY",
        "reference_results": {
            "RBV2-1": {
                "status": "READY",
                "reference_type": "NEXT_RED_CANDLE",
                "reference_timestamp": "2026-08-21T10:15:00+05:30",
                "reason_code": None,
            }
        },
        "drilldown": (
            {
                "signal_id": "RBV2-1",
                "confirmation_timestamp": "2026-08-21T10:20:00+05:30",
                "reference_status": "READY",
                "reference_type": "NEXT_RED_CANDLE",
                "reference_timestamp": "2026-08-21T10:15:00+05:30",
                "market_status": "READY",
                "market_source": "LIVE_PERSISTED",
                "market_cutoff_timestamp": "2026-08-21T10:20:00+05:30",
                "market_latest_timestamp": "2026-08-21T10:19:00+05:30",
                "market_row_count": 65,
                "market_fallback_used": False,
                "market_no_lookahead_passed": True,
                "market_mandatory_present": 12,
                "market_mandatory_expected": 12,
                "market_mandatory_coverage_pct": 100.0,
                "market_optional_present": 4,
                "market_optional_expected": 8,
                "market_optional_coverage_pct": 50.0,
                "market_missing_mandatory_fields": (),
                "market_missing_optional_fields": ("atr14_5m",),
                "volume_status": "READY",
                "volume_source": "LIVE_PERSISTED",
                "volume_cutoff_timestamp": "2026-08-21T10:20:00+05:30",
                "volume_latest_timestamp": "2026-08-21T10:19:00+05:30",
                "volume_row_count": 65,
                "volume_fallback_used": False,
                "volume_no_lookahead_passed": True,
                "volume_mandatory_present": 9,
                "volume_mandatory_expected": 9,
                "volume_mandatory_coverage_pct": 100.0,
                "volume_optional_present": 4,
                "volume_optional_expected": 4,
                "volume_optional_coverage_pct": 100.0,
                "volume_missing_mandatory_fields": (),
                "volume_missing_optional_fields": (),
                "option_status": "READY",
                "option_mandatory_present": 8,
                "option_mandatory_expected": 8,
                "option_mandatory_coverage_pct": 100.0,
                "option_optional_present": 6,
                "option_optional_expected": 10,
                "option_optional_coverage_pct": 60.0,
                "option_missing_mandatory_fields": (),
                "option_missing_optional_fields": ("atm_call_iv",),
                "core_eligible": True,
                "hybrid_eligible": True,
                "all_reasons": (),
            },
        ),
    }


def test_bundle_id_is_deterministic_and_contains_audit_fields():
    first = build_evidence_bundles(_gate())[0]
    second = build_evidence_bundles(_gate())[0]

    assert first.bundle_id == second.bundle_id
    assert first.as_of_timestamp == "2026-08-21T10:20:00+05:30"
    assert first.market["source"] == "LIVE_PERSISTED"
    assert first.market["mandatory_coverage_pct"] == 100.0
    assert first.core_eligible is True
    assert first.hybrid_eligible is True
    assert first.authority == "OBSERVATIONAL_ONLY"


def test_bundle_persistence_is_idempotent(tmp_path):
    path = tmp_path / "operations.db"
    bundles = build_evidence_bundles(_gate())

    first = persist_evidence_bundles(path, bundles)
    second = persist_evidence_bundles(path, bundles)
    stored = read_evidence_bundles(path)

    assert first == second
    assert len(stored) == 1
    assert stored[0]["bundle_id"] == first[0]


def test_json_and_csv_exports_are_available():
    bundles = build_evidence_bundles(_gate())
    json_payload = evidence_bundles_json(bundles)
    csv_payload = evidence_bundles_csv(bundles)

    assert json.loads(json_payload)[0]["signal_id"] == "RBV2-1"
    assert "bundle_id,signal_id" in csv_payload
    assert "OBSERVATIONAL_ONLY" in csv_payload
