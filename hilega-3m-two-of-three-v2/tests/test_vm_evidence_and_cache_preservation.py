"""Offline regression cases for the newer VM provenance/cache protections."""
from datetime import datetime,date,timedelta
from pathlib import Path
import pytest
from market_lab import hilega_candle_evidence_v1 as evidence
from market_lab.gateways import normalize_upstox_historical_candles
from market_lab.hilega_three_minute_v1 import hilega_alignment_dual_exit_live_v1 as module
from market_lab import hilega_milega_historical_replay_v1 as cache
from market_lab.hilega_wma_gap_live_v2 import HilegaWmaGapLiveCoordinatorV2
from market_lab.domain import IST

def at(clock):return datetime.fromisoformat('2026-10-26T'+clock+':00+05:30')

def captured(monkeypatch,tmp_path,stamps,received):
    root=tmp_path/'evidence';root.mkdir(exist_ok=True,mode=0o700);root.chmod(0o700)
    monkeypatch.setenv(evidence.FLAG,'1')
    monkeypatch.setenv('HILEGA_CANDLE_EVIDENCE_ROOT',str(root))
    body=dict(status='success',data=dict(candles=[[t.isoformat(),100,101,99,100,10,0] for t in stamps]))
    rows=normalize_upstox_historical_candles(evidence.INSTRUMENT,date(2026,10,26),body)
    return evidence.capture(rows,body,date(2026,10,26),received-timedelta(seconds=1),received)

def coordinator(tmp_path):
    from types import SimpleNamespace
    return module.HilegaAlignmentDualExitLiveCoordinator(market_sources=SimpleNamespace(),option_expiry=None,
        step_audit_path=tmp_path/'audit.jsonl',health_path=tmp_path/'health.jsonl')

def test_three_minute_consume_retains_verified_input_context(monkeypatch,tmp_path):
    batch=captured(monkeypatch,tmp_path,[at('09:15')+timedelta(minutes=i) for i in range(3)],at('09:18'))
    live=coordinator(tmp_path);recorded=[];seen=[]
    monkeypatch.setattr(HilegaWmaGapLiveCoordinatorV2,'_audit',
        lambda self,now,stage,status,payload=None,**kw:recorded.append((stage,payload)))
    def advance(row,bars,**kw):
        assert at('09:15') in bars and len(bars)==1
        assert live._active_candle_evidence['snapshot_id']==batch.candle_evidence['snapshot_id']
        seen.append(row.timestamp);live._last_minute=row.timestamp
        live._audit(at('09:18'),'COMBINED_THREE_MINUTE_EVALUATION','PROCESSED',{})
    live._advance=advance
    assert live._consume(batch,at('09:18'),recovered=False)==3
    assert len(seen)==3 and len(recorded)==3
    assert all(payload['candle_evidence']==batch.candle_evidence and 'audit_payload_created_at' in payload for _,payload in recorded)
    assert live._active_candle_evidence is None

def test_altered_input_blocks_before_consumption(monkeypatch,tmp_path):
    batch=captured(monkeypatch,tmp_path,[at('09:15')+timedelta(minutes=i) for i in range(3)],at('09:18'))
    altered=evidence.CapturedCandles(batch[:-1],batch.candle_evidence)
    live=coordinator(tmp_path)
    live._advance=lambda *args,**kw:pytest.fail('Tampered candles reached strategy processing')
    with pytest.raises(ValueError,match='CANDLE_EVIDENCE_ROWS_CHANGED'):
        live._consume(altered,at('09:18'),recovered=False)
    assert live._last_minute is None

def test_session_close_audit_retains_verified_evidence(monkeypatch,tmp_path):
    batch=captured(monkeypatch,tmp_path,[at('15:29')],at('15:30'))
    live=coordinator(tmp_path);recorded=[];exits=[]
    monkeypatch.setattr(HilegaWmaGapLiveCoordinatorV2,'_audit',
        lambda self,now,stage,status,payload=None,**kw:recorded.append((stage,payload)))
    live._close_option=lambda **kw:exits.append(kw)
    live.gate.owner='BEARISH';live.gate.active=dict(time=at('15:00'),price=110.)
    result=live.process_cutoff(at('15:30'),intraday=batch)
    assert result is not None and live.gate.owner=='NONE' and live.gate.locked
    rows=[payload for stage,payload in recorded if stage=='DIRECTIONAL_SESSION_CUTOFF']
    assert len(rows)==1 and rows[0]['candle_evidence']==batch.candle_evidence
    assert len(exits)==1 and exits[0]['exit_reason']=='SESSION_END_1530'
    assert live._active_candle_evidence is None

def test_newer_operational_cache_protections_remain(monkeypatch,tmp_path):
    target=tmp_path/'hilega-milega-underlying-cache-v1'/'2026-10-26.json'
    body=dict(data=dict(candles=[[(at('09:15')+timedelta(minutes=i)).isoformat(),100,101,99,100,10,0] for i in range(375)]))
    rows=normalize_upstox_historical_candles(evidence.INSTRUMENT,date(2026,10,26),body)
    cache._write_cache(target,evidence.INSTRUMENT,date(2026,10,26),rows)
    saved=target.read_bytes()
    with pytest.raises(ValueError,match='EMPTY_REFRESH_CANNOT_REPLACE_OPERATIONAL_CACHE'):
        cache._write_cache(target,evidence.INSTRUMENT,date(2026,10,26),[])
    assert target.read_bytes()==saved
    with pytest.raises(ValueError,match='COMPLETE_375_MINUTE_WARMUP_REQUIRED'):
        cache._write_cache(target,evidence.INSTRUMENT,date(2026,10,26),rows[:-1])
    assert target.read_bytes()==saved
    assert not list(target.parent.glob('*.complete-*'))
