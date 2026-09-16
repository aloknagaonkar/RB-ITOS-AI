import json
from pathlib import Path

from market_lab.historical_positioning_adapter_v1 import (
    choose_positioning_session,
    fixed_0920_rows,
    load_positioning_file,
    timestamp_groups,
)


def _write(path: Path, *, session_date="2026-08-25", expiry="2026-08-25"):
    payload = {
        "schema_version": 1,
        "status": "AVAILABLE",
        "underlying": "NSE_INDEX|Nifty 50",
        "session_date": session_date,
        "expiry": expiry,
        "wings": 5,
        "strike_interval": 50,
        "row_count": 4,
        "rows": [
            {
                "session_date": session_date,
                "expiry": expiry,
                "timestamp": f"{session_date}T09:20:00+05:30",
                "underlying": "NSE_INDEX|Nifty 50",
                "spot": 24585.4,
                "moving_atm": 24600.0,
                "strike": 24550.0,
                "strike_offset": -1,
                "ce_instrument_key": "CE1",
                "pe_instrument_key": "PE1",
                "ce_close": 100.0,
                "pe_close": 90.0,
                "ce_open_interest": 1000,
                "pe_open_interest": 1100,
                "ce_volume": 100,
                "pe_volume": 110,
            },
            {
                "session_date": session_date,
                "expiry": expiry,
                "timestamp": f"{session_date}T09:20:00+05:30",
                "underlying": "NSE_INDEX|Nifty 50",
                "spot": 24585.4,
                "moving_atm": 24600.0,
                "strike": 24600.0,
                "strike_offset": 0,
                "ce_instrument_key": "CE2",
                "pe_instrument_key": "PE2",
                "ce_close": 80.0,
                "pe_close": 70.0,
                "ce_open_interest": 1200,
                "pe_open_interest": 1300,
                "ce_volume": 120,
                "pe_volume": 130,
            },
            {
                "session_date": session_date,
                "expiry": expiry,
                "timestamp": f"{session_date}T09:25:00+05:30",
                "underlying": "NSE_INDEX|Nifty 50",
                "spot": 24610.0,
                "moving_atm": 24600.0,
                "strike": 24550.0,
                "strike_offset": -1,
                "ce_instrument_key": "CE1",
                "pe_instrument_key": "PE1",
                "ce_close": 105.0,
                "pe_close": 85.0,
                "ce_open_interest": 950,
                "pe_open_interest": 1250,
                "ce_volume": 200,
                "pe_volume": 220,
            },
            {
                "session_date": session_date,
                "expiry": expiry,
                "timestamp": f"{session_date}T09:25:00+05:30",
                "underlying": "NSE_INDEX|Nifty 50",
                "spot": 24610.0,
                "moving_atm": 24600.0,
                "strike": 24600.0,
                "strike_offset": 0,
                "ce_instrument_key": "CE2",
                "pe_instrument_key": "PE2",
                "ce_close": 85.0,
                "pe_close": 65.0,
                "ce_open_interest": 1150,
                "pe_open_interest": 1450,
                "ce_volume": 240,
                "pe_volume": 260,
            },
        ],
    }
    path.write_text(json.dumps(payload))


def test_load_positioning_file_and_group(tmp_path):
    path = tmp_path / "x.json"
    _write(path)
    s = load_positioning_file(path)
    assert s.session_date == "2026-08-25"
    assert len(s.rows) == 4
    groups = timestamp_groups(s)
    assert len(groups) == 2
    assert len(fixed_0920_rows(s)) == 2


def test_choose_shortest_nonexpired_expiry(tmp_path):
    d = tmp_path / "historical-positioning-cache-x"
    d.mkdir()
    _write(d / "later.json", expiry="2026-09-01")
    _write(d / "near.json", expiry="2026-08-25")
    s = choose_positioning_session("2026-08-25", data_root=tmp_path)
    assert s.expiry == "2026-08-25"
