import json
from datetime import date
from pathlib import Path

import pytest

from market_lab.hilega_current_day_directional_recovery_v1 import (
    extract_underlying_1m_from_market_evidence,
    extract_underlying_5m_from_audit,
    merge_recorded_5m_sources,
)
from market_lab.hilega_milega_strategy_v1 import FiveMinuteBar
from market_lab.domain import IST


def _audit_row(ts, o, h, l, c):
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


def _minute(ts, o, h, l, c):
    return {
        "provider": "upstox",
        "instrument_key": "NSE_INDEX|Nifty 50",
        "session_date": "2026-09-24",
        "interval_seconds": 60,
        "timestamp": ts,
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "volume": 0,
        "open_interest": 0,
    }


def test_extract_primary_5m_dedupes_identical(tmp_path: Path):
    p = tmp_path / "audit.jsonl"
    rows = [
        _audit_row("2026-09-24T09:20:00+05:30", 101, 103, 100, 102),
        _audit_row("2026-09-24T09:15:00+05:30", 100, 102, 99, 101),
        _audit_row("2026-09-24T09:15:00+05:30", 100, 102, 99, 101),
    ]
    p.write_text("\n".join(json.dumps(x) for x in rows) + "\n")
    bars = extract_underlying_5m_from_audit(p, date(2026, 9, 24))
    assert [x.ts.strftime("%H:%M") for x in bars] == ["09:15", "09:20"]


def test_market_evidence_filters_target_session_and_dedupes(tmp_path: Path):
    p = tmp_path / "evidence.jsonl"
    target = _minute(
        "2026-09-24T14:35:00+05:30", 10, 12, 9, 11
    )
    other = dict(target)
    other["session_date"] = "2026-08-10"
    other["timestamp"] = "2026-08-10T14:35:00+05:30"

    records = [
        {"kind": "warmup", "response": [other]},
        {"kind": "whatever-live-kind", "response": [target]},
        {"kind": "repeated-snapshot", "response": {"candles": [target]}},
    ]
    p.write_text("\n".join(json.dumps(x) for x in records) + "\n")

    rows = extract_underlying_1m_from_market_evidence(
        p, date(2026, 9, 24)
    )
    assert len(rows) == 1
    assert rows[0].timestamp.strftime("%H:%M") == "14:35"
    assert rows[0].open == 10


def test_market_evidence_rejects_conflicting_duplicate(tmp_path: Path):
    p = tmp_path / "evidence.jsonl"
    a = _minute("2026-09-24T14:35:00+05:30", 10, 12, 9, 11)
    b = dict(a)
    b["close"] = 99
    p.write_text(
        json.dumps({"response": [a]}) + "\n"
        + json.dumps({"response": [b]}) + "\n"
    )

    with pytest.raises(ValueError, match="conflicting duplicate 1m"):
        extract_underlying_1m_from_market_evidence(
            p, date(2026, 9, 24)
        )


def test_merge_supplements_only_missing_and_rejects_conflict():
    a = FiveMinuteBar(
        ts=__import__("datetime").datetime(
            2026, 9, 24, 14, 30, tzinfo=IST
        ),
        open=10, high=12, low=9, close=11,
    )
    b = FiveMinuteBar(
        ts=__import__("datetime").datetime(
            2026, 9, 24, 14, 35, tzinfo=IST
        ),
        open=11, high=13, low=10, close=12,
    )
    rows, counts = merge_recorded_5m_sources([a], [a, b])
    assert len(rows) == 2
    assert counts["supplemented_missing_5m_bars"] == 1
    assert counts["agreeing_overlap_5m_bars"] == 1

    bad = FiveMinuteBar(
        ts=a.ts, open=10, high=12, low=9, close=999
    )
    with pytest.raises(ValueError, match="5m evidence conflict"):
        merge_recorded_5m_sources([a], [bad])
