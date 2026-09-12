import csv
import json
from datetime import datetime, timedelta, timezone

from market_lab.pcr_option_premium_baseline import analyze

IST = timezone(timedelta(hours=5, minutes=30))


def _write_positioning(path):
    fields = [
        "session_date", "timestamp", "strike", "strike_offset",
        "ce_instrument_key", "pe_instrument_key", "ce_close", "pe_close",
    ]
    t0 = datetime(2026, 3, 16, 10, 0, tzinfo=IST)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for minute in range(0, 20):
            ts = t0 + timedelta(minutes=minute)
            # ATM row; same instruments remain visible for whole synthetic test.
            w.writerow({
                "session_date": "2026-03-16",
                "timestamp": ts.isoformat(),
                "strike": "23000",
                "strike_offset": "0",
                "ce_instrument_key": "CE23000",
                "pe_instrument_key": "PE23000",
                "ce_close": str(100 + 2 * minute),
                "pe_close": str(120 - minute),
            })


def _write_confidence(path):
    t0 = datetime(2026, 3, 16, 10, 0, tzinfo=IST)
    payload = {
        "status": "AVAILABLE",
        "directions": {
            "bullish": {
                "events": [{
                    "session_date": "2026-03-16",
                    "timestamp": t0.isoformat(),
                    "direction": "BULLISH",
                    "outcome": "TRUE_BULLISH_REVERSAL",
                    "confidence_tier": "VERY_HIGH",
                    "confidence_score": 6,
                    "first_confirmation_offset_minutes": 1,
                }]
            },
            "bearish": {
                "events": [{
                    "session_date": "2026-03-16",
                    "timestamp": t0.isoformat(),
                    "direction": "BEARISH",
                    "outcome": "FALSE_BEARISH_WARNING",
                    "confidence_tier": "LOW",  # must be excluded
                    "confidence_score": 0,
                    "first_confirmation_offset_minutes": 1,
                }]
            },
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_baseline_uses_next_minute_close_and_same_instrument(tmp_path):
    positioning = tmp_path / "positioning.csv"
    confidence = tmp_path / "confidence.json"
    _write_positioning(positioning)
    _write_confidence(confidence)

    result = analyze(confidence, positioning)
    assert result["status"] == "AVAILABLE"
    assert len(result["trades"]) == 1
    trade = result["trades"][0]
    assert trade["direction"] == "BULLISH"
    assert trade["option_side"] == "CE"
    assert trade["confirmation_offset_minutes"] == 1
    # T0=10:00, confirmation=10:01, entry=10:02 close => 104.
    assert trade["entry_premium"] == 104.0
    # +3m from entry = 10:05 close => 110.
    assert round(trade["returns_pct"]["3m"], 6) == round((110 - 104) / 104 * 100, 6)
    assert result["directions"]["bullish"]["summary"]["candidate_count"] == 1
    assert result["directions"]["bearish"]["summary"]["candidate_count"] == 0
