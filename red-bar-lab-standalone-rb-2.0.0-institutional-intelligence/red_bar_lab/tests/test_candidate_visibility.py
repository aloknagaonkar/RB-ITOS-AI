from types import SimpleNamespace

from red_bar_lab.ui.candidate_visibility import (
    active_candidate_rows,
    archive_payload,
    investigation_candidate_rows,
    is_not_eligible,
)


def test_not_eligible_is_hidden_from_active_views():
    rows = [
        {"candidate_id": "A", "state": "VALID"},
        {"candidate_id": "B", "state": "NOT_ELIGIBLE"},
        {"candidate_id": "C", "state": "AGING"},
    ]
    active = active_candidate_rows(rows)
    assert [row["candidate_id"] for row in active] == ["A", "C"]


def test_not_eligible_is_retained_for_investigation():
    rows = [
        {"candidate_id": "A", "state": "VALID"},
        {"candidate_id": "B", "state": "NOT_ELIGIBLE"},
    ]
    archived = investigation_candidate_rows(rows)
    assert [row["candidate_id"] for row in archived] == ["B"]


def test_archived_flag_also_hides_row():
    row = {"candidate_id": "B", "state": "VALID", "archived": True}
    assert is_not_eligible(row) is True


def test_archive_payload_is_investigation_only():
    evaluation = SimpleNamespace(
        candidate_id="CAND-1",
        signal_id="SIG-1",
        candidate_symbol="NIFTY26AUG25000CE",
        instrument_token=123,
        reason="OPPORTUNITY_HEALTH_BELOW_MINIMUM",
        action="REJECT_CANDIDATE",
        health_score=54.0,
        market_drift="ELEVATED",
        created_session="MORNING",
        current_session="MIDDAY",
    )
    record = archive_payload(
        evaluation=evaluation,
        decision_timestamp="2026-08-13T12:30:00+05:30",
    )
    assert record["final_outcome"] == "NOT_ELIGIBLE"
    assert record["archived"] is True
    assert record["visible_in_active_views"] is False
    assert record["order_id"] is None
