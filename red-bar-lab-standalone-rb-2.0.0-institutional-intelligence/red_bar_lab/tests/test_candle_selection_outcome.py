from red_bar_lab.services.candle_selection_outcome import (
    build_candle_enrichment_outcome,
)
from red_bar_lab.services.point_in_time_candle_source import CandleSelectionResult


def test_ready_selection_maps_to_complete_outcome():
    selection = CandleSelectionResult(
        status="READY",
        selected_source="LIVE_PERSISTED",
        requested_cutoff="2026-08-21T10:25:00+05:30",
        latest_candle_timestamp="2026-08-21T10:20:00+05:30",
        row_count=20,
        no_lookahead_passed=True,
    )

    outcome = build_candle_enrichment_outcome(
        signal_id="RBV2-1",
        stage="MARKET",
        selection=selection,
        attempt_timestamp="2026-08-21T05:00:00+00:00",
    )

    assert outcome["status"] == "READY"
    assert outcome["input_source"] == "LIVE_PERSISTED"
    assert outcome["input_cutoff_timestamp"].endswith("10:25:00+05:30")
    assert outcome["latest_source_timestamp"].endswith("10:20:00+05:30")
    assert outcome["no_lookahead_passed"] is True
    assert outcome["final_retry_status"] == "COMPLETE"
    assert outcome["row_count"] == 20
    assert outcome["authority"] == "OBSERVATIONAL_ONLY"


def test_missing_selection_remains_pending_with_reason():
    selection = CandleSelectionResult(
        status="MISSING",
        selected_source="HISTORICAL_REPOSITORY",
        requested_cutoff="2026-08-21T10:25:00+05:30",
        latest_candle_timestamp=None,
        row_count=0,
        no_lookahead_passed=True,
        reason_code="COMPLETED_CANDLES_MISSING",
        reason="No completed candles were found.",
        fallback_used=True,
    )

    outcome = build_candle_enrichment_outcome(
        signal_id="RBV2-2",
        stage="VOLUME",
        selection=selection,
        attempt_timestamp="2026-08-21T05:00:00+00:00",
    )

    assert outcome["status"] == "MISSING"
    assert outcome["reason_code"] == "COMPLETED_CANDLES_MISSING"
    assert outcome["fallback_used"] is True
    assert outcome["final_retry_status"] == "PENDING"
