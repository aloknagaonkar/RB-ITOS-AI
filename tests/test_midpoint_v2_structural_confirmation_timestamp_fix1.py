from datetime import datetime, timedelta


def test_absolute_confirmation_timestamp_semantics():
    t3 = datetime.fromisoformat("2026-06-01T09:30:00+05:30")

    assert (t3 + timedelta(minutes=1)).isoformat() == "2026-06-01T09:31:00+05:30"

    start = 2
    chained_idx = 3
    absolute = start + chained_idx
    assert absolute == 5
    assert (t3 + timedelta(minutes=absolute + 1)).isoformat() == "2026-06-01T09:36:00+05:30"
