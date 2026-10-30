import json
from pathlib import Path

from market_lab.session_data_gate_v1 import _check_positioning, _check_0920_baseline


def test_positioning_uses_open_interest_field_names(tmp_path):
    p = tmp_path / "p.json"
    payload = {
        "status": "AVAILABLE",
        "session_date": "2026-05-04",
        "rows": [
            {
                "timestamp": "2026-05-04T09:20:00+05:30",
                "ce_instrument_key": "CE",
                "pe_instrument_key": "PE",
                "ce_open_interest": 100,
                "pe_open_interest": 200,
            }
        ],
    }
    p.write_text(json.dumps(payload))

    check = _check_positioning(p, "2026-05-04")
    assert check.status == "PASS"
    assert check.details["rows_with_both_open_interest"] == 1

    baseline = _check_0920_baseline(check, "2026-05-04")
    assert baseline.status == "PASS"
    assert baseline.details["usable_open_interest_rows"] == 1
