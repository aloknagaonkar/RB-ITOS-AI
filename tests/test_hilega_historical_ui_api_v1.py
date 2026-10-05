import json
from datetime import datetime, timezone
from pathlib import Path
import pytest
from fastapi import HTTPException
from market_lab import hilega_wma_gap_historical_v1
from market_lab.hilega_historical_ui_api_v1 import (
    _v2_report,
    list_available,
    load_capture,
    strategy_test,
)
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


def test_v1_missing_canonical_evidence_has_strategy_specific_error(monkeypatch):
    def missing_session(session_date):
        raise FileNotFoundError(session_date)

    monkeypatch.setattr(hilega_wma_gap_historical_v1, "build_v1_session", missing_session)

    with pytest.raises(HTTPException) as exc:
        strategy_test("2026-10-01", "V1")

    assert exc.value.status_code == 404
    assert exc.value.detail == (
        "Canonical Hilega v1 replay unavailable for 2026-10-01: no published "
        "canonical trade evidence is available for this date. Live records "
        "are not substituted."
    )


def test_wma_gap_missing_evidence_keeps_wma_gap_error(monkeypatch):
    def missing_session(session_date):
        raise FileNotFoundError(session_date)

    monkeypatch.setattr(hilega_wma_gap_historical_v1, "build_wma_gap_session", missing_session)

    with pytest.raises(HTTPException) as exc:
        strategy_test("2026-10-01", "V2")

    assert exc.value.status_code == 404
    assert exc.value.detail == (
        "WMA-gap replay unavailable for 2026-10-01: no matching canonical "
        "trade evidence was found in the published frozen or "
        "forward-confirmation artifacts."
    )
