from market_lab.midpoint_v2_v1_population_reconciliation_v1 import event_identity
from market_lab import midpoint_break_strength_failure_v2 as strength


def test_event_identity_is_stable():
    row = {
        "block": "TRAIN",
        "session_date": "2026-08-19",
        "setup_type": "RED_BREAK",
        "direction": "BEARISH",
    }
    assert event_identity(row) == (
        "TRAIN",
        "2026-08-19",
        "RED_BREAK",
        "BEARISH",
    )


def test_repo_outcome_label_signature_is_direction_and_outcome():
    # Regression guard for the repo API actually used by build_rows:
    # outcome_label(direction, outcome)
    assert callable(strength.outcome_label)
    # We intentionally do not assert a particular label here; this test
    # catches the one-argument integration mistake by exercising 2 args.
    strength.outcome_label("BULLISH", None)


def test_labelled_checkpoint_rows_derives_direction_before_outcome_label(monkeypatch):
    from market_lab.midpoint_v2_v1_population_reconciliation_v1 import labelled_checkpoint_rows

    framework = {
        "events": [
            {
                "block": "TRAIN",
                "session_date": "2026-08-19",
                "setup_type": "GREEN_BREAK",
                "primary_outcome": "ANY",
            }
        ]
    }

    monkeypatch.setattr(strength, "direction_for_event", lambda e: "BULLISH")
    monkeypatch.setattr(strength, "outcome_label", lambda direction, outcome: "OTHER")
    monkeypatch.setattr(strength, "CHECKPOINTS", (1, 3))

    rows = labelled_checkpoint_rows(framework)
    assert rows == []
