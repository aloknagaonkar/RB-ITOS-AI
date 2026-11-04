from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock,patch
import json
import pytest
from worker_binding import poll_with_journal_health,RegisteredAuthorityWorker
from test_authority import expected
from test_worker_files import disabled,write,setup_worker
from test_closed_application_coordinator_v1 import env,bound_env,ready,case,flow
from test_private_context import private,port,LiveProviders,base


def cursor(e):
    with e['store'].db() as db:
        return db.execute('SELECT data FROM preparation_source WHERE id=1').fetchone()[0]


def test_result_gains_verified_source_time_without_consuming_cursor(flow):
    e=flow;before=cursor(e);worker=Mock();worker.poll.return_value={'status':'SYNTHETIC_FACTORY_RESULT','source_at':'fake'}
    value=poll_with_journal_health(worker,e['source'],e['path'])
    assert value['status']=='SYNTHETIC_FACTORY_RESULT' and value['source_at'] and value['source_at']!='fake'
    assert cursor(e)==before and e['send'].call_count==0


def test_process_clock_does_not_make_old_journal_fresh(flow):
    e=flow;worker=Mock();worker.poll.return_value={}
    first=poll_with_journal_health(worker,e['source'],e['path'])['source_at']
    e['clock'][0]+=timedelta(minutes=20)
    assert poll_with_journal_health(worker,e['source'],e['path'])['source_at']==first


def test_enabled_registration_with_real_gate_returns_source_time_without_private_reads(flow,tmp_path):
    e=flow;value=disabled();bind=expected()
    value.update(enabled=True,expected_binding=bind,private_config_file='/missing/context',private_config_sha256=bind['private_context_sha256'],trust_registry_file='/missing/registry',trust_registry_sha256='a'*64,grant_file='/missing/grant',grant_sha256='b'*64)
    path=tmp_path/'registration';digest=write(path,value);worker=RegisteredAuthorityWorker(path,digest)
    before=cursor(e)
    with patch('worker_binding.trust_roots',side_effect=AssertionError('No trust key read')) as roots,\
         patch('worker_binding.grant_file',side_effect=AssertionError('No grant read')) as grants:
        result=poll_with_journal_health(worker,e['source'],e['path'])
    assert result['status']=='EXECUTION_SESSION_FACTORY_CLOSED_IN_CODE' and result['source_at']
    roots.assert_not_called();grants.assert_not_called();assert cursor(e)==before


def test_invalid_journal_does_not_reach_factory(tmp_path):
    path=tmp_path/'journal';path.write_text('{"broken":true}\n');worker=Mock()
    with pytest.raises(Exception):poll_with_journal_health(worker,object(),path)
    worker.poll.assert_not_called()


def test_empty_journal_does_not_invent_source_time(tmp_path):
    path=tmp_path/'journal';path.write_text('');worker=Mock();worker.poll.return_value={}
    assert poll_with_journal_health(worker,object(),path)['source_at'] is None


def test_factory_failure_is_not_retried(flow):
    e=flow;worker=Mock();worker.poll.side_effect=ValueError('SYNTHETIC_FAILURE');before=cursor(e)
    with pytest.raises(ValueError,match='SYNTHETIC_FAILURE'):poll_with_journal_health(worker,e['source'],e['path'])
    assert worker.poll.call_count==1 and cursor(e)==before


def test_actual_outer_heartbeat_advances_on_same_lease_with_unchanged_source_time(flow):
    e=flow
    from market_lab.hilega_production_bridge_health_v1 import claim,heartbeat
    run=claim(e['source'].s);worker=Mock();worker.poll.return_value={};before=cursor(e)
    value=poll_with_journal_health(worker,e['source'],e['path'])
    heartbeat(e['source'].s,run,source_at=value['source_at'])
    with e['store'].db() as db:first=json.loads(db.execute('SELECT data FROM sim_bridge_health WHERE id=1').fetchone()[0])
    e['clock'][0]+=timedelta(seconds=1)
    heartbeat(e['source'].s,run,source_at=value['source_at'])
    with e['store'].db() as db:last=json.loads(db.execute('SELECT data FROM sim_bridge_health WHERE id=1').fetchone()[0])
    assert last['run_id']==first['run_id']==run and last['heartbeat_at']>first['heartbeat_at']
    assert last['source_at']==first['source_at']==value['source_at'] and cursor(e)==before


def test_changed_source_lease_cannot_reuse_cached_registration(private):
    e,folder,config=private;worker,_=setup_worker(private)
    with patch.object(port,'require_live_clearance',return_value=None),patch.object(port.HttpTransport,'check',return_value=None),\
         patch.object(port.HttpTransport,'send',side_effect=lambda aid,wire:e['send'](aid,wire)),\
         patch.object(LiveProviders,'entry_market',side_effect=lambda:base.market(e)):
        assert worker.poll(e['source'],e['path'])['phase']=='ENTRY_REVIEW'
        count=e['send'].call_count;e['source'].run_id='different-startup-lease'
        with pytest.raises(ValueError,match='SOURCE_LEASE_CHANGED'):worker.poll(e['source'],e['path'])
    assert e['send'].call_count==count and e['store'].control()['mode']=='PAUSED'
