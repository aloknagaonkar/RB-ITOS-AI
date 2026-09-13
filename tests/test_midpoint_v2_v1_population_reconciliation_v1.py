from market_lab.midpoint_v2_v1_population_reconciliation_v1 import event_identity


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
