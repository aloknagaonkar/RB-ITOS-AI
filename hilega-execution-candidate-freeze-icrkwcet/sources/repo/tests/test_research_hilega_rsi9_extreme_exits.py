from datetime import datetime, timedelta, timezone

from scripts.research_hilega_rsi9_extreme_exits import rsi9_index


def test_rsi9_index_uses_nine_completed_closes_before_first_value():
    base = datetime(2026, 10, 1, 9, 15, tzinfo=timezone.utc)
    rows = [(base + timedelta(minutes=i), 100.0 + i) for i in range(55)]
    index = rsi9_index({"2026-10-01": rows})
    # Completed closes: 09:19, 09:24, ..., first RSI9 at the tenth close, 10:04.
    assert min(index) == base + timedelta(minutes=49)
    assert index[min(index)] == 100.0
