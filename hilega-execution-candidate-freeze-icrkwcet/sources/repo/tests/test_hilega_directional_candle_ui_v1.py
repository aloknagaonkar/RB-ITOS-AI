from __future__ import annotations

import json
from pathlib import Path

import market_lab.hilega_directional_candle_ui_v1 as m


class Store:
    rows_by_path = {}
    def __init__(self, path):
        self.path = str(path)
    def read_all(self):
        return self.rows_by_path.get(self.path, [])


def test_historical_directional_rows_preserve_bearish(tmp_path, monkeypatch):
    day = "2026-09-17"
    root = tmp_path/"hist"
    p = root/day/"directional-candle-by-candle.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps([
        {
            "session_date": day, "time":"09:20",
            "bar_timestamp": f"{day}T09:20:00+05:30",
            "open":1,"high":2,"low":0,"close":1.5,"volume":0,
            "rsi9":48,"ema3_rsi":50,"wma21_rsi":49,
            "owner_before":"NONE","owner_after":"NONE",
            "bullish_state":"PATH1_IDLE",
            "bearish_state":"BEARISH_PATH1_ARMED",
            "bullish_armed":False,"bearish_armed":True,
            "action":"ARMED_INFORMATION",
            "accepted_events":"BEARISH_PATH1_ARMED_RSI_CROSS_EMA3_DOWN",
            "suppressed_events":"","note":None,
        },
        {
            "session_date": day, "time":"10:30",
            "bar_timestamp": f"{day}T10:30:00+05:30",
            "open":1,"high":2,"low":0,"close":1.5,"volume":0,
            "rsi9":40,"ema3_rsi":42,"wma21_rsi":45,
            "owner_before":"NONE","owner_after":"BEARISH",
            "bullish_state":"PATH1_IDLE",
            "bearish_state":"BEARISH_ACTIVE",
            "bullish_armed":False,"bearish_armed":False,
            "action":"BEARISH_ENTRY",
            "accepted_events":"ENTRY_BEARISH_ROUTE_B_STRUCTURAL",
            "suppressed_events":"","note":None,
        },
    ]))
    monkeypatch.setattr(m, "HIST_ROOT", root)
    result = m.build_historical_directional_candles(day)
    assert result["row_count"] == 2
    assert result["rows"][0]["bearish_armed"] is True
    assert result["rows"][1]["action"] == "BEARISH_ENTRY"
    assert result["rows"][1]["owner_after"] == "BEARISH"


def test_historical_falls_back_to_recorded_live_session(tmp_path, monkeypatch):
    day = "2026-10-01"
    monkeypatch.setattr(m, "HIST_ROOT", tmp_path / "missing")
    monkeypatch.setattr(m, "build_live_directional_candles", lambda selected: {
        "model": "HILEGA_DIRECTIONAL_CANDLE_UI_V1",
        "mode": "LIVE",
        "session_date": selected,
        "row_count": 1,
        "directional_row_count": 1,
        "rows": [{"bar_timestamp": f"{day}T09:20:00+05:30"}],
    })

    result = m.build_historical_directional_candles(day)
    assert result["mode"] == "HISTORICAL_LIVE_CAPTURE"
    assert result["row_count"] == 1
    assert "recorded directional live" in result["warning"]


def test_live_merges_candle_and_directional_evidence(tmp_path, monkeypatch):
    day = "2026-09-24"
    bullish = tmp_path/"bullish.jsonl"
    directional = tmp_path/"directional.jsonl"
    bullish.write_text("")
    directional.write_text("")
    monkeypatch.setattr(m, "LIVE_BULLISH_AUDIT", bullish)
    monkeypatch.setattr(m, "LIVE_DIRECTIONAL_AUDIT", directional)
    monkeypatch.setattr(
        m,
        "LIVE_DIRECTIONAL_EVIDENCE_ROOT",
        tmp_path / "directional-evidence",
    )
    monkeypatch.setattr(
        m,
        "UNDERLYING_CACHE_ROOT",
        tmp_path / "underlying-cache",
    )
    monkeypatch.setattr(m, "ShadowStepAuditStoreV1", Store)

    Store.rows_by_path[str(bullish)] = [
        {"stage":"UNDERLYING_5M_BUILD","checkpoint":f"{day}T09:15:00+05:30",
         "payload":{"bar_timestamp":f"{day}T09:15:00+05:30","open":100,"high":105,"low":99,"close":104}},
        {"stage":"INDICATOR_CALCULATION","checkpoint":f"{day}T09:15:00+05:30",
         "payload":{"close":104,"rsi9":55,"ema3_rsi":53,"wma21_rsi":50}},
        {"stage":"INDICATOR_CALCULATION","checkpoint":f"{day}T14:35:00+05:30",
         "payload":{"close":110,"rsi9":60,"ema3_rsi":58,"wma21_rsi":54}},
    ]
    Store.rows_by_path[str(directional)] = [
        {"stage":"DIRECTIONAL_DECISION","checkpoint":f"{day}T14:35:00+05:30",
         "payload":{"bar_timestamp":f"{day}T14:35:00+05:30",
                    "trade_owner_before":"BULLISH","trade_owner_after":"BULLISH",
                    "bullish_state":"BULLISH_ACTIVE","bearish_state":"BEARISH_PATH1_IDLE",
                    "bullish_armed":False,"bearish_armed":False,
                    "accepted_events":[],"suppressed_events":[]}}
    ]

    result = m.build_live_directional_candles(day)
    assert result["row_count"] == 2
    assert result["directional_row_count"] == 1
    assert result["rows"][0]["time"] == "09:15"
    assert result["rows"][0]["directional_evidence"] is False
    assert result["rows"][1]["time"] == "14:35"
    assert result["rows"][1]["owner_after"] == "BULLISH"
    assert result["rows"][1]["action"] == "BULLISH_ACTIVE"

    monkeypatch.setattr(m, "_base_live_rows", lambda _: (_ for _ in ()).throw(AssertionError("full evidence reconstruction")))
    fast = m.build_live_directional_candles(day, audit_only=True)
    assert fast["row_count"] == 2
    assert "verification was deferred" in fast["warning"]


def test_fast_evidence_tail_resolves_latest_underlying_response(tmp_path):
    from market_lab.hilega_market_evidence_v1 import EvidenceJournalV1
    path = tmp_path / "evidence.jsonl"
    journal = EvidenceJournalV1(path)
    response = [{"timestamp": "2026-09-29T09:15:00+05:30", "close": 100}]
    journal.append("underlying", {"now": "2026-09-29T09:16:00+05:30"}, response)
    journal.append("underlying", {"now": "2026-09-29T09:17:00+05:30"}, response)
    journal.close()
    rows = m._recent_underlying_records(path)
    assert len(rows) == 1
    assert rows[0]["args"]["now"] == "2026-09-29T09:17:00+05:30"
    assert rows[0]["response"] == response
