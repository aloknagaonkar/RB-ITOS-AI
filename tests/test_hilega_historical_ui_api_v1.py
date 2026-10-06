import json
from datetime import datetime, timezone
from pathlib import Path
import pytest
from fastapi import HTTPException
from market_lab.hilega_historical_ui_api_v1 import _v2_report, list_available, load_capture
from market_lab.live_shadow_step_audit_v1 import ShadowStepAuditStoreV1


def test_read_only_capture(tmp_path: Path):
    folder=tmp_path/'hilega-phase7d-2026-09-23-d4'
    folder.mkdir()
    store=ShadowStepAuditStoreV1(folder/'step-audit.jsonl')
    cp=datetime(2026,9,23,9,20,tzinfo=timezone.utc)
    store.append(event_time=cp, checkpoint=cp, stage='STRATEGY_DECISION',status='OK',payload={'bar_close':23000})
    store.append(event_time=cp, checkpoint=cp, stage='STRATEGY_DECISION_RESULT',status='OK',payload={'state_after':'IDLE'})
    (folder/'source-manifest.json').write_text(json.dumps({'expiry':'2026-09-29'}))
    initial=(folder/'step-audit.jsonl').read_bytes()
    sessions=list_available(tmp_path)
    assert sessions[0]['capture_id']==folder.name
    result=load_capture(folder.name,tmp_path)
    assert result['audit_chain_ok']
    assert result['report_count']==1
    assert result['manifest']['expiry']=='2026-09-29'
    assert (folder/'step-audit.jsonl').read_bytes()==initial
    with pytest.raises(HTTPException) as exc:
        load_capture('../../.env',tmp_path)
    assert exc.value.status_code==404


def test_v2_report_preserves_wma_slope_candle_evidence():
    report = _v2_report({
        "bar_timestamp": "2026-09-24T09:20:00+05:30",
        "wma21_slope_required": True,
        "wma21_slope_change": 0.25,
        "wma21_slope_direction": "RISING",
        "wma21_slope_gate_status": "PASS",
        "wma21_current_candle": "2026-09-24T09:20:00+05:30",
        "wma21_previous_candle": "2026-09-24T09:15:00+05:30",
        "wma21_slope_interval_minutes": 5,
    })
    assert report["conditions"]["wma21_slope_direction"] == "RISING"
    assert report["conditions"]["wma21_slope_gate_status"] == "PASS"
    assert report["conditions"]["wma21_current_candle"].endswith("09:20:00+05:30")
    assert report["conditions"]["wma21_previous_candle"].endswith("09:15:00+05:30")
    assert report["conditions"]["wma21_slope_interval_minutes"] == 5


def test_strategy_test_fails_forward_eligibility_on_live_replay_mismatch(monkeypatch):
    import market_lab.hilega_historical_ui_api_v1 as api
    import market_lab.hilega_wma_gap_historical_v1 as replay
    candidate = {
        "reports": [], "warning": "zero", "performance_summary": [
            {"strategy_id":"LIVE_RECORDED_V1", "signals":0, "completed":0},
            {"strategy_id":"HILEGA_V1_REPLAY", "signals":0, "completed":0},
            {"strategy_id":"HILEGA_WMA_GAP_V2_REPLAY", "signals":0, "completed":0},
        ],
    }
    recorded = {"source":"DIRECTIONAL_LIVE_SHADOW", "reports":[{
        "checkpoint":"2026-10-05T09:20:00+05:30",
        "transitions":[{"event_type":"ENTRY_OPENING_BULLISH_CONFIRMED", "event_time":"2026-10-05T09:20:00+05:30", "price":100}],
    }]}
    monkeypatch.setattr(replay, "build_wma_gap_session", lambda *_: candidate)
    monkeypatch.setattr(api, "load_session", lambda *_args, **_kwargs: recorded)
    result = api.strategy_test("2026-10-05", "V2")
    assert result["parity"]["status"] == "PARITY_MISMATCH"
    assert result["parity"]["recorded_live_signals"] == 1
    assert result["parity"]["canonical_replay_signals"] == 0
    assert result["forward_confirmation_eligible"] is False
