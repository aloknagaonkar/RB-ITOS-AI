from fastapi import HTTPException
from market_lab import hilega_historical_ui_api_v1 as api
from market_lab import hilega_wma_gap_historical_v1 as history

def test_missing_v2_does_not_hide_other_rows(monkeypatch):
    monkeypatch.setattr(api,'load_session',lambda day:dict(source='DIRECTIONAL_LIVE_SHADOW',reports=[]))
    monkeypatch.setattr(history,'recorded_live_metrics',lambda rows:dict(strategy_id='LIVE_RECORDED_V1',available=True,net_points=12))
    def strategy(day,strategy,input_basis):
        if strategy=='V2':raise HTTPException(404,'candidate missing')
        identifier='HILEGA_V1_REPLAY' if strategy=='V1' else 'HILEGA_V2_ALIGNMENT_DUAL_EXIT_REPLAY_V1'
        return dict(source=strategy,performance_summary=[dict(strategy_id=identifier,available=True,net_points=20)])
    monkeypatch.setattr(api,'strategy_test',strategy)
    rows=api.comparison_metrics('2026-10-15','LOCAL')['performance_summary']
    assert [r['available'] for r in rows]==[True,True,False,True]
    assert rows[0]['net_points']==12
    assert rows[2]['unavailable_reason']=='candidate missing'

def test_recovered_data_is_not_recorded_live(monkeypatch):
    monkeypatch.setattr(api,'load_session',lambda day:dict(source='RECOVERED_HISTORICAL_REPLAY',reports=[]))
    def unavailable(*args,**kwargs):raise FileNotFoundError('missing')
    monkeypatch.setattr(api,'strategy_test',unavailable)
    rows=api.comparison_metrics('2026-10-15','LOCAL')['performance_summary']
    assert not any(r['available'] for r in rows)
    assert 'not live evidence' in rows[0]['unavailable_reason']

def test_input_basis_only_applies_to_combined(monkeypatch):
    monkeypatch.setattr(api,'load_session',lambda day:dict(source='DIRECTIONAL_LIVE_SHADOW',reports=[]))
    monkeypatch.setattr(history,'recorded_live_metrics',lambda rows:dict(strategy_id='LIVE_RECORDED_V1',available=False))
    seen=[]
    def unavailable(day,strategy,input_basis):
        seen.append((strategy,input_basis));raise FileNotFoundError('missing')
    monkeypatch.setattr(api,'strategy_test',unavailable)
    api.comparison_metrics('2026-10-15','VALIDATED')
    assert seen==[('V1','LOCAL'),('V2','LOCAL'),('V2_ALIGN','VALIDATED')]
