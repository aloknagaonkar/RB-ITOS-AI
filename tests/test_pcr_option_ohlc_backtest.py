import csv
import json
from datetime import datetime, timedelta, timezone

from market_lab.pcr_option_ohlc_backtest import analyze

IST = timezone(timedelta(hours=5, minutes=30))


def _write_positioning(path):
    fields = [
        "session_date", "timestamp", "moving_atm", "strike", "strike_offset",
        "ce_instrument_key", "pe_instrument_key",
    ]
    t0 = datetime(2026, 3, 16, 10, 0, tzinfo=IST)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for minute in range(0, 10):
            ts = t0 + timedelta(minutes=minute)
            w.writerow({
                "session_date": "2026-03-16",
                "timestamp": ts.isoformat(),
                "moving_atm": "23000",
                "strike": "23000",
                "strike_offset": "0",
                "ce_instrument_key": "CE23000",
                "pe_instrument_key": "PE23000",
            })


def _write_ohlc(path):
    fields = [
        "session_date", "expiry", "underlying", "instrument_key", "strike", "side",
        "timestamp", "open", "high", "low", "close", "volume", "open_interest", "provenance",
    ]
    t0 = datetime(2026, 3, 16, 10, 0, tzinfo=IST)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for minute in range(0, 20):
            ts = t0 + timedelta(minutes=minute)
            # CE rises steadily. At entry minute (10:02), open is 104.
            ce_open = 100 + 2 * minute
            w.writerow({
                "session_date": "2026-03-16", "expiry": "2026-03-17", "underlying": "NSE_INDEX|Nifty 50",
                "instrument_key": "CE23000", "strike": "23000", "side": "CE", "timestamp": ts.isoformat(),
                "open": ce_open, "high": ce_open + 3, "low": ce_open - 1, "close": ce_open + 1,
                "volume": 100, "open_interest": 1000, "provenance": "HISTORICAL_CANDLE_RECONSTRUCTION",
            })
            pe_open = 120 - minute
            w.writerow({
                "session_date": "2026-03-16", "expiry": "2026-03-17", "underlying": "NSE_INDEX|Nifty 50",
                "instrument_key": "PE23000", "strike": "23000", "side": "PE", "timestamp": ts.isoformat(),
                "open": pe_open, "high": pe_open + 1, "low": pe_open - 2, "close": pe_open - 1,
                "volume": 100, "open_interest": 1000, "provenance": "HISTORICAL_CANDLE_RECONSTRUCTION",
            })


def _write_confidence(path):
    t0 = datetime(2026, 3, 16, 10, 0, tzinfo=IST)
    payload = {
        "status": "AVAILABLE",
        "directions": {
            "bullish": {"events": [{
                "session_date": "2026-03-16", "timestamp": t0.isoformat(),
                "direction": "BULLISH", "outcome": "TRUE_BULLISH_REVERSAL",
                "confidence_tier": "VERY_HIGH", "confidence_score": 6,
                "first_confirmation_offset_minutes": 1,
            }]},
            "bearish": {"events": []},
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_ohlc_backtest_uses_next_minute_open_and_intrabar_high_low(tmp_path):
    positioning = tmp_path / "positioning.csv"
    ohlc = tmp_path / "ohlc.csv"
    confidence = tmp_path / "confidence.json"
    _write_positioning(positioning)
    _write_ohlc(ohlc)
    _write_confidence(confidence)

    result = analyze(confidence, positioning, ohlc)
    trade = result["trades"][0]
    assert trade["entry_rule"] == "NEXT_MINUTE_OPEN"
    # T0 10:00, confirmation T+1=10:01, entry next minute open 10:02 = 104.
    assert trade["entry_premium"] == 104.0
    # +3m means 10:05 candle close = 111.
    assert round(trade["returns_pct"]["3m"], 6) == round((111 - 104) / 104 * 100, 6)
    # Intrabar MFE uses HIGH, not close.
    assert trade["mfe_pct_15m"] > trade["returns_pct"]["15m"]
    assert trade["mae_pct_15m"] < 0
    assert result["directions"]["bullish"]["summary"]["candidate_count"] == 1


def test_target_stop_same_bar_is_ambiguous(tmp_path):
    positioning = tmp_path / "positioning.csv"
    ohlc = tmp_path / "ohlc.csv"
    confidence = tmp_path / "confidence.json"
    _write_positioning(positioning)
    _write_ohlc(ohlc)
    _write_confidence(confidence)

    # Rewrite entry bar so both +5% target and -5% stop are touched from 104 entry.
    rows = list(csv.DictReader(ohlc.open(newline="", encoding="utf-8")))
    for row in rows:
        if row["instrument_key"] == "CE23000" and row["timestamp"].startswith("2026-03-16T10:02:00"):
            row["open"] = "104"
            row["high"] = "110"
            row["low"] = "98"
            row["close"] = "104"
    with ohlc.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader(); w.writerows(rows)

    result = analyze(confidence, positioning, ohlc)
    ts = result["trades"][0]["target_stop"]["TARGET_5_STOP_5"]
    assert ts["result"] == "AMBIGUOUS_SAME_BAR"
    assert ts["minute"] == 0
