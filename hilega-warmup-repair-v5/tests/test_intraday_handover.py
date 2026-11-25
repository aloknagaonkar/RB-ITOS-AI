from datetime import datetime
from io import BytesIO
from types import SimpleNamespace as Obj
import json
import pytest
import repair


def setup(monkeypatch,tmp_path):
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return cls(2026,11,23,12,45,20,tzinfo=repair.IST)
    monkeypatch.setattr(repair,'datetime',Clock)
    data=dict(strategy_version='old',current=dict(session_date='2026-11-23',
        state_available=True,trade_owner='BEARISH',last_completed_bar='2026-11-23T12:42:00+05:30'),
        worker_component_health=dict(timestamp='2026-11-23T12:45:10+05:30',components=dict(hilega='OK')))
    monkeypatch.setattr(repair.safety,'api_status',lambda base:data)
    monkeypatch.setattr(repair.safety,'sandbox_clear',lambda repo:{})
    monkeypatch.setattr(repair.safety,'no_execution_workers',lambda repo:None)
    dashboard=dict(trades=[dict(strategy_version='old',status='ACTIVE',direction='BEARISH',
                               signal_boundary='2026-11-23T12:03:00+05:30')])
    monkeypatch.setattr(repair,'urlopen',lambda *a,**kw:BytesIO(json.dumps(dashboard).encode()))
    return Obj(api_url='http://127.0.0.1:8123',allow_intraday=True),dict(repo=tmp_path),data


def test_authorized_intraday_handover_allows_shadow_state_without_fabricating_close(monkeypatch,tmp_path):
    args,context,data=setup(monkeypatch,tmp_path)
    snapshot=repair.transition_guard(args,context,'old')
    assert snapshot['current']['trade_owner']=='BEARISH'
    assert snapshot['option_observations'][0]['status']=='ACTIVE'
    assert snapshot['historical_shadow_exits_fabricated'] is False
    assert data['current']['trade_owner']=='BEARISH'


def test_without_flag_original_working_hours_guard_remains(monkeypatch,tmp_path):
    args,context,data=setup(monkeypatch,tmp_path);args.allow_intraday=False
    with pytest.raises(ValueError,match='AFTER_1535'):
        repair.transition_guard(args,context,'old')


@pytest.mark.parametrize('owner',['NONE','BULLISH','BEARISH'])
def test_all_known_observation_owners_can_be_snapshotted(monkeypatch,tmp_path,owner):
    args,context,data=setup(monkeypatch,tmp_path);data['current']['trade_owner']=owner
    assert repair.transition_guard(args,context,'old')['current']['trade_owner']==owner


@pytest.mark.parametrize('bad',['stale_health','future_health','stale_bar','future_bar','wrong_day','unknown_owner','missing_state','wrong_version','component_error'])
def test_intraday_health_state_and_version_checks_remain_mandatory(monkeypatch,tmp_path,bad):
    args,context,data=setup(monkeypatch,tmp_path)
    if bad=='stale_health':data['worker_component_health']['timestamp']='2026-11-23T12:40:00+05:30'
    elif bad=='future_health':data['worker_component_health']['timestamp']='2026-11-23T12:46:00+05:30'
    elif bad=='stale_bar':data['current']['last_completed_bar']='2026-11-23T12:30:00+05:30'
    elif bad=='future_bar':data['current']['last_completed_bar']='2026-11-23T12:45:00+05:30'
    elif bad=='wrong_day':data['current']['session_date']='2026-11-20'
    elif bad=='unknown_owner':data['current']['trade_owner']='UNKNOWN'
    elif bad=='missing_state':data['current']['state_available']=False
    elif bad=='component_error':data['worker_component_health']['components']['hilega']='ERROR'
    else:data['strategy_version']='unexpected'
    with pytest.raises(ValueError):repair.transition_guard(args,context,'old')


def test_open_broker_ledger_still_blocks_intraday_handover(monkeypatch,tmp_path):
    args,context,data=setup(monkeypatch,tmp_path)
    def blocked(repo):raise ValueError('OPEN_OR_UNCERTAIN_SANDBOX_STATE')
    monkeypatch.setattr(repair.safety,'sandbox_clear',blocked)
    with pytest.raises(ValueError,match='OPEN_OR_UNCERTAIN'):
        repair.transition_guard(args,context,'old')


def test_execution_process_still_blocks_intraday_handover(monkeypatch,tmp_path):
    args,context,data=setup(monkeypatch,tmp_path)
    def blocked(repo):raise ValueError('EXECUTION_WORKER_ACTIVE_PID')
    monkeypatch.setattr(repair.safety,'no_execution_workers',blocked)
    with pytest.raises(ValueError,match='EXECUTION_WORKER_ACTIVE'):
        repair.transition_guard(args,context,'old')


def test_policy_snapshot_preserves_journal_bytes_and_active_owner(tmp_path):
    path=tmp_path/repair.AUDIT;path.parent.mkdir(parents=True)
    record=dict(stage='DIRECTIONAL_DECISION',status='PROCESSED',event_time='2026-11-23T12:45:00+05:30',
        sequence=12,record_hash='original-hash',payload=dict(strategy_version='old',
        decision_timestamp='2026-11-23T12:45:00+05:30',trade_owner_after='BEARISH',
        bearish_state='BEARISH_ACTIVE',bar_timestamp='2026-11-23T12:42:00+05:30'))
    path.write_text(json.dumps(record)+'\n');before=path.read_bytes()
    result=repair.frozen_policy_snapshot(tmp_path,'2026-11-23','old')
    assert result['state']['trade_owner']=='BEARISH'
    assert result['journal_anchor']['record_hash']=='original-hash'
    assert result['option_positions_closed_by_installer'] is False
    assert path.read_bytes()==before
