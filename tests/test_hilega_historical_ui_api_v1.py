import json
from datetime import datetime, timezone
from pathlib import Path
import pytest
from fastapi import HTTPException
from market_lab.hilega_historical_ui_api_v1 import list_available, load_capture
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
