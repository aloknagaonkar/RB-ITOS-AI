from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from market_lab.hilega_directional_pe_historical_shadow_v1 import (
    replay_pe_shadow_from_directional_summary,
)
from market_lab.hilega_milega_pe_option_candidate_v1 import build_bearish_pe_candidate_set
from market_lab.hilega_milega_pe_option_shadow_lifecycle_v1 import (
    HilegaMilegaPEOptionShadowLifecycleV1,
)

IST = ZoneInfo("Asia/Kolkata")


def contracts(expiry="2026-09-29"):
    return [
        {
            "instrument_key": f"PE_{strike}",
            "strike_price": strike,
            "side": "PE",
            "expiry": expiry,
        }
        for strike in [23200, 23250, 23300, 23350, 23400]
    ]


def test_pe_candidate_set_is_exact_atm_plus_minus_2_and_unselected():
    from datetime import date
    c = build_bearish_pe_candidate_set(
        signal_spot=23312.0,
        expiry=date(2026, 9, 29),
        contracts=contracts(),
    )
    assert c.status == "AVAILABLE"
    assert c.side == "PE"
    assert c.atm == 23300.0
    assert c.selected_instrument_key is None
    assert [x.relation_to_atm for x in c.candidates] == [-2, -1, 0, 1, 2]
    assert [x.strike for x in c.candidates] == [23200, 23250, 23300, 23350, 23400]


def _write_option_cache(root: Path):
    cache = root/"historical-option-ohlc-cache-test"
    cache.mkdir(parents=True)
    rows = []
    start = datetime(2026, 9, 24, 9, 15, tzinfo=IST)
    for strike in [23200, 23250, 23300, 23350, 23400]:
        key = f"PE_{strike}"
        price = 100.0 + (strike - 23300) / 50 * 2
        for i in range(120):
            ts = start + timedelta(minutes=i)
            # deterministic rising PE path
            o = price + i * 0.20
            rows.append({
                "session_date": "2026-09-24",
                "expiry": "2026-09-29",
                "underlying": "NSE_INDEX|Nifty 50",
                "instrument_key": key,
                "strike": strike,
                "side": "PE",
                "timestamp": ts.isoformat(),
                "open": o,
                "high": o + 1.0,
                "low": o - 0.5,
                "close": o + 0.4,
                "volume": 100,
                "open_interest": 1000,
                "provenance": "TEST",
            })
    payload = {
        "status": "AVAILABLE",
        "session_date": "2026-09-24",
        "expiry": "2026-09-29",
        "wings": 2,
        "strike_interval": 50,
        "row_count": len(rows),
        "rows": rows,
    }
    (cache/"test__2026-09-24__pe.json").write_text(json.dumps(payload))


def _write_directional_summary(path: Path):
    payload = {
        "trades": [
            {
                "session_date": "2026-09-24",
                "direction": "BEARISH",
                "entry_time": "09:25",
                "entry_event": "ENTRY_BEARISH_ROUTE_B_STRUCTURAL",
                "entry_price": 23312.0,
                "exit_time": "09:45",
                "exit_event": "STRUCTURAL_EXIT_BEARISH_RSI_CROSS_ABOVE_WMA21",
                "exit_price": 23290.0,
                "points": 22.0,
                "outcome": "POSITIVE",
                "holding_minutes": 20,
            },
            {
                "session_date": "2026-09-24",
                "direction": "BULLISH",
                "entry_time": "10:00",
                "entry_event": "ENTRY_PATH1_ROUTE_B_STRUCTURAL",
                "entry_price": 23300.0,
                "exit_time": "10:20",
                "exit_event": "STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21",
                "exit_price": 23320.0,
                "points": 20.0,
                "outcome": "POSITIVE",
                "holding_minutes": 20,
            },
        ]
    }
    path.write_text(json.dumps(payload))


def test_historical_pe_shadow_tracks_all_five_exact_pe_legs(tmp_path):
    data_root = tmp_path/"data"
    _write_option_cache(data_root)
    ds = tmp_path/"directional.json"
    _write_directional_summary(ds)

    result = replay_pe_shadow_from_directional_summary(
        directional_summary_path=ds,
        output_root=tmp_path/"out",
        data_root=data_root,
    )
    assert result["bearish_trades_requested"] == 1
    assert result["complete_closed_trades"] == 1
    assert result["option_selection_enabled"] is False
    assert result["quantity"] is None
    assert result["rupee_pnl_enabled"] is False

    legs = json.loads(
        (tmp_path/"out"/"2026-09-24"/"trade-001-pe-shadow.json").read_text()
    )["legs"]
    assert len(legs) == 5
    assert {x["side"] for x in legs} == {"PE"}
    assert all(x["entry_open"] is not None for x in legs)
    assert all(x["exit_open"] is not None for x in legs)
    assert all(x["realized_points"] is not None for x in legs)
    assert all(x["mfe_points"] is not None for x in legs)
    assert all(x["mae_points"] is not None for x in legs)


def test_missing_exact_pe_contract_never_falls_back(tmp_path):
    data_root = tmp_path/"data"
    _write_option_cache(data_root)
    # Delete one strike from cache rows.
    path = next((data_root/"historical-option-ohlc-cache-test").glob("*.json"))
    payload = json.loads(path.read_text())
    payload["rows"] = [r for r in payload["rows"] if r["strike"] != 23400]
    payload["row_count"] = len(payload["rows"])
    path.write_text(json.dumps(payload))

    ds = tmp_path/"directional.json"
    _write_directional_summary(ds)
    result = replay_pe_shadow_from_directional_summary(
        directional_summary_path=ds,
        output_root=tmp_path/"out",
        data_root=data_root,
    )
    assert result["complete_closed_trades"] == 0
    assert result["trades"][0]["status"] in {"BLOCKED", "INCOMPLETE"}
    assert "23400_PE" in (result["trades"][0]["issue"] or "")
