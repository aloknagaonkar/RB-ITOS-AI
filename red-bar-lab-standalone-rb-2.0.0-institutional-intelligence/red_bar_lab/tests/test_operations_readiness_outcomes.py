from red_bar_lab.services.operations_readiness_outcomes import (
    build_persistent_operations_outcomes,
)


def _gate():
    return {
        "policy_version": "operations-readiness-gate-v2",
        "authority": "OBSERVATIONAL_ONLY",
        "reference_results": {
            "RBV2-1": {
                "status": "READY",
                "reason_code": None,
                "reason": None,
                "reference_timestamp": "2026-08-21T06:05:00+00:00",
                "no_lookahead_passed": True,
            },
            "RBV2-2": {
                "status": "MISSING",
                "reason_code": "REFERENCE_NOT_FOUND",
                "reason": "NEXT_RED_CANDLE reference is missing.",
                "reference_timestamp": None,
                "no_lookahead_passed": None,
            },
        },
        "drilldown": (
            {
                "signal_id": "RBV2-1",
                "confirmation_timestamp": "2026-08-21T06:10:00+00:00",
                "reference_status": "READY",
                "reference_timestamp": "2026-08-21T06:05:00+00:00",
                "market_status": "READY",
                "volume_status": "READY",
                "option_status": "READY",
                "all_reasons": (),
            },
            {
                "signal_id": "RBV2-2",
                "confirmation_timestamp": "2026-08-21T06:15:00+00:00",
                "reference_status": "MISSING",
                "reference_timestamp": None,
                "market_status": "MISSING",
                "volume_status": "FAILED",
                "option_status": "STALE",
                "all_reasons": (
                    "REFERENCE_NOT_FOUND",
                    "MARKET_CONTEXT_MISSING",
                    "VOLUME_ENRICHMENT_FAILED",
                    "OPTION_CONTEXT_STALE",
                ),
            },
        ),
    }


def test_gate_produces_four_outcomes_per_signal():
    rows = build_persistent_operations_outcomes(
        _gate(),
        attempt_timestamp="2026-08-21T06:20:00+00:00",
    )

    assert len(rows) == 8
    assert {row["stage"] for row in rows} == {"REFERENCE", "MARKET", "VOLUME", "OPTIONS"}
    assert all(row["authority"] == "OBSERVATIONAL_ONLY" for row in rows)


def test_reference_outcome_preserves_cutoff_and_no_lookahead():
    rows = build_persistent_operations_outcomes(
        _gate(),
        attempt_timestamp="2026-08-21T06:20:00+00:00",
    )
    reference = next(
        row for row in rows
        if row["signal_id"] == "RBV2-1" and row["stage"] == "REFERENCE"
    )

    assert reference["input_cutoff_timestamp"] == "2026-08-21T06:10:00+00:00"
    assert reference["latest_source_timestamp"] == "2026-08-21T06:05:00+00:00"
    assert reference["no_lookahead_passed"] is True
    assert reference["final_retry_status"] == "COMPLETE"


def test_missing_failed_and_stale_reasons_are_stage_specific():
    rows = build_persistent_operations_outcomes(
        _gate(),
        attempt_timestamp="2026-08-21T06:20:00+00:00",
    )
    by_stage = {
        row["stage"]: row
        for row in rows
        if row["signal_id"] == "RBV2-2"
    }

    assert by_stage["REFERENCE"]["reason_code"] == "REFERENCE_NOT_FOUND"
    assert by_stage["MARKET"]["reason_code"] == "MARKET_CONTEXT_MISSING"
    assert by_stage["VOLUME"]["reason_code"] == "VOLUME_ENRICHMENT_FAILED"
    assert by_stage["OPTIONS"]["reason_code"] == "OPTION_CONTEXT_STALE"
    assert all(row["final_retry_status"] == "PENDING" for row in by_stage.values())
