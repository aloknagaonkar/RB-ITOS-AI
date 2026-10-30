import csv
import json
from pathlib import Path

from market_lab.historical_paper_replay_date_v1 import (
    build_historical_oi_features,
    load_historical_futures_5m,
)
from market_lab.historical_positioning_adapter_v1 import load_positioning_file


def _positioning(path: Path):
    rows = []
    for minute, spot, ce_base, pe_base in [
        ("09:20", 100.0, 1000, 1000),
        ("09:25", 101.0, 1010, 1020),
        ("09:30", 102.0, 1020, 1050),
    ]:
        for offset in range(-5, 6):
            strike = 100 + offset * 5
            rows.append({
                "session_date": "2026-08-25",
                "expiry": "2026-08-25",
                "timestamp": f"2026-08-25T{minute}:00+05:30",
                "underlying": "NSE_INDEX|Nifty 50",
                "spot": spot,
                "moving_atm": 100.0,
                "strike": strike,
                "strike_offset": offset,
                "ce_instrument_key": f"CE{strike}",
                "pe_instrument_key": f"PE{strike}",
                "ce_close": 10.0,
                "pe_close": 10.0,
                "ce_open_interest": ce_base + offset,
                "pe_open_interest": pe_base + 2 * offset,
                "ce_volume": 100,
                "pe_volume": 100,
            })
    payload = {
        "schema_version": 1,
        "status": "AVAILABLE",
        "underlying": "NSE_INDEX|Nifty 50",
        "session_date": "2026-08-25",
        "expiry": "2026-08-25",
        "wings": 5,
        "strike_interval": 5,
        "row_count": len(rows),
        "rows": rows,
    }
    path.write_text(json.dumps(payload))


def test_build_historical_features_uses_real_0920_baseline(tmp_path):
    p = tmp_path / "p.json"
    _positioning(p)
    session = load_positioning_file(p)
    features = build_historical_oi_features(session)
    assert len(features) == 2
    assert features[0].timestamp.endswith("09:25:00+05:30")
    assert features[0].previous_session_imbalance == 0


def test_load_futures_aggregates_complete_1m_rows_to_5m(tmp_path):
    p = tmp_path / "f.csv"
    fields = [
        "session_date","expiry","instrument_key","trading_symbol",
        "contract_source","timestamp","open","high","low","close",
        "volume","open_interest","typical_price",
        "session_cumulative_volume","session_vwap"
    ]
    with p.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for minute in range(15, 25):
            writer.writerow({
                "session_date":"2026-08-25",
                "expiry":"2026-08-25",
                "instrument_key":"FUT",
                "trading_symbol":"NIFTY FUT",
                "contract_source":"X",
                "timestamp":f"2026-08-25T09:{minute:02d}:00+05:30",
                "open":100+minute,
                "high":101+minute,
                "low":99+minute,
                "close":100.5+minute,
                "volume":10,
                "open_interest":1000,
                "typical_price":100,
                "session_cumulative_volume":10,
                "session_vwap":100,
            })
    candles = load_historical_futures_5m("2026-08-25", csv_path=p)
    assert len(candles) == 2
    assert candles[0].timestamp.minute == 15
    assert candles[0].volume == 50
    assert candles[1].timestamp.minute == 20
