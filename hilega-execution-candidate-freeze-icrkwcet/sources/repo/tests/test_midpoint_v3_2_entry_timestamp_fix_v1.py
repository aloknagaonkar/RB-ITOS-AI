from market_lab.midpoint_v3_2_chronology_fix_v1 import chronology_key, validate_chronology_rows

def test_exit_research_source_contains_entry_timestamp_propagation():
    from pathlib import Path
    p = Path("backend/market_lab/midpoint_v3_2_exit_management_research_v1.py")
    text = p.read_text(encoding="utf-8")
    assert '"entry_timestamp": trade.get("entry_timestamp")' in text

def test_validation_uses_exact_timestamp_helper():
    from pathlib import Path
    p = Path("backend/market_lab/midpoint_v3_2_frozen_exit_validation_v1.py")
    text = p.read_text(encoding="utf-8")
    assert "validate_chronology_rows(rows)" in text

def test_chronology_orders_same_day_by_entry_time():
    rows = [
        {"session_date": "2026-09-08", "direction": "BULLISH",
         "entry_timestamp": "2026-09-08T11:15:00+05:30"},
        {"session_date": "2026-09-08", "direction": "BEARISH",
         "entry_timestamp": "2026-09-08T10:05:00+05:30"},
    ]
    validate_chronology_rows(rows)
    ordered = sorted(rows, key=chronology_key)
    assert ordered[0]["direction"] == "BEARISH"
