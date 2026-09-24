import json
from datetime import date
from pathlib import Path

import pytest

from market_lab.hilega_current_day_directional_recovery_v1 import (
    extract_underlying_5m_from_audit,
)


def _row(ts, o, h, l, c):
    return {
        "stage": "UNDERLYING_5M_BUILD",
        "payload": {
            "bar_timestamp": ts,
            "open": o,
            "high": h,
            "low": l,
            "close": c,
        },
    }


def test_extract_current_day_underlying_5m_dedupes_identical(tmp_path: Path):
    p = tmp_path / "audit.jsonl"
    rows = [
        _row("2026-09-24T09:20:00+05:30", 101, 103, 100, 102),
        _row("2026-09-24T09:15:00+05:30", 100, 102, 99, 101),
        _row("2026-09-24T09:15:00+05:30", 100, 102, 99, 101),
        _row("2026-09-23T09:15:00+05:30", 1, 2, 0, 1),
    ]
    p.write_text("\n".join(json.dumps(x) for x in rows) + "\n")

    bars = extract_underlying_5m_from_audit(p, date(2026, 9, 24))

    assert [x.ts.strftime("%H:%M") for x in bars] == ["09:15", "09:20"]
    assert bars[0].open == 100
    assert bars[1].close == 102


def test_extract_current_day_underlying_5m_rejects_conflicting_duplicate(tmp_path: Path):
    p = tmp_path / "audit.jsonl"
    rows = [
        _row("2026-09-24T09:15:00+05:30", 100, 102, 99, 101),
        _row("2026-09-24T09:15:00+05:30", 100, 102, 99, 999),
    ]
    p.write_text("\n".join(json.dumps(x) for x in rows) + "\n")

    with pytest.raises(ValueError, match="conflicting duplicate"):
        extract_underlying_5m_from_audit(p, date(2026, 9, 24))
