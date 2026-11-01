from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import market_lab.hilega_directional_ce_historical_shadow_v1 as m

IST = ZoneInfo("Asia/Kolkata")


class Candle:
    def __init__(self, key: str, ts: datetime, open_: float, high: float, low: float, close: float):
        self.instrument_key = key
        self.timestamp = ts
        self.open = open_
        self.high = high
        self.low = low
        self.close = close
        self.volume = 100
        self.open_interest = None


def test_ce_historical_shadow_uses_existing_ce_builder_and_lifecycle(tmp_path, monkeypatch):
    day = "2026-09-17"
    expiry = "2026-09-22"
    directional = tmp_path / "directional.json"
    directional.write_text(json.dumps({
        "trades": [{
            "session_date": day,
            "direction": "BULLISH",
            "entry_time": "09:25",
            "entry_event": "ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21",
            "entry_price": 23252.05,
            "exit_time": "09:30",
            "exit_event": "STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21",
            "exit_price": 23260.0,
        }]
    }))

    rows = []
    for rel in (-2, -1, 0, 1, 2):
        strike = 23250 + rel * 50
        key = f"CE-{strike}"
        for minute, px in [("09:30", 100 + rel), ("09:31", 102 + rel),
                           ("09:32", 103 + rel), ("09:33", 104 + rel),
                           ("09:34", 105 + rel), ("09:35", 110 + rel)]:
            h, mm = map(int, minute.split(":"))
            rows.append(SimpleNamespace(
                instrument_key=key, strike=float(strike), side="CE", expiry=expiry,
                timestamp=datetime(2026, 9, 17, h, mm, tzinfo=IST),
                open=float(px), high=float(px+1), low=float(px-1), close=float(px),
                volume=100, open_interest=None,
            ))

    session = SimpleNamespace(expiry=expiry, rows=rows)

    monkeypatch.setattr(m, "choose_option_ohlc_session", lambda *a, **k: session)

    def candles(session_obj, *, instrument_key: str, side: str):
        return [x for x in session_obj.rows if x.instrument_key == instrument_key and x.side == side]
    monkeypatch.setattr(m, "instrument_candles", candles)

    result = m.replay_ce_shadow_from_directional_summary(
        directional_summary_path=directional,
        output_root=tmp_path/"out",
        dates=[date(2026, 9, 17)],
    )

    assert result["bullish_trades_requested"] == 1
    assert result["complete_closed_trades"] == 1
    assert result["option_selection_enabled"] is False
    assert result["quantity"] is None
    assert result["rupee_pnl_enabled"] is False

    trades = (tmp_path/"out"/day/"ce-shadow-trades.csv").read_text()
    legs = (tmp_path/"out"/day/"ce-shadow-legs.csv").read_text()
    assert "CLOSED" in trades
    assert "CE-23250" in legs
