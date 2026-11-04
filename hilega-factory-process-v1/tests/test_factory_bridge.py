import json,os,time,traceback
from pathlib import Path
from unittest.mock import patch
import pytest
from test_worker_files import setup_worker
from test_closed_application_coordinator_v1 import env,bound_env,ready,case,flow
from test_private_context import private,LiveProviders,pc,port,base
from market_lab.hilega_production_simulator_bridge_v1 import Bridge
from factory_source import prepare_factory_source


def bridge(e,name='ownership.sqlite'):
    return Bridge(e['s'],e['store'].path.parent/name,run_id=e['source'].run_id)


def intercept(e):
    from contextlib import ExitStack
    stack=ExitStack()
    stack.enter_context(patch.object(port,'require_live_clearance',return_value=None))
    stack.enter_context(patch.object(port.HttpTransport,'check',return_value=None))
    stack.enter_context(patch.object(port.HttpTransport,'send',side_effect=lambda aid,wire:e['send'](aid,wire)))
    stack.enter_context(patch.object(LiveProviders,'account',side_effect=lambda:base.account(e)))
    stack.enter_context(patch.object(LiveProviders,'entry_market',side_effect=lambda:base.market(e)))
    stack.enter_context(patch.object(pc,'capture_owned',side_effect=lambda *args:base.market(e)))
    return stack


def test_registered_bridge_two_cycles_in_child_process(private):
    e,folder,cfg=private;worker,_=setup_worker(private);b=bridge(e);result=folder/'CHILD-RESULT.json'
    pid=os.fork()
    if pid==0:
        try:
            with intercept(e),patch.object(base,'poll',side_effect=lambda e,**kw:worker.poll(b,e['path'])):
                base.finish(e);base.resume_and_signal(e);base.poll(e);base.poll(e);base.finish(e)
            assert base.read_state(e)['completed_cycles']==2 and e['send'].call_count==4
            result.write_text(json.dumps(dict(completed_cycles=2,intercepted_sends=4,real_network=False)))
            os._exit(0)
        except BaseException:
            (folder/'CHILD-ERROR.txt').write_text(traceback.format_exc());os._exit(1)
    until=time.monotonic()+65
    while True:
        done,status=os.waitpid(pid,os.WNOHANG)
        if done:break
        if time.monotonic()>=until:
            os.kill(pid,9);os.waitpid(pid,0);pytest.fail('Factory child timed out')
        time.sleep(.1)
    assert os.WIFEXITED(status) and os.WEXITSTATUS(status)==0, (folder/'CHILD-ERROR.txt').read_text() if (folder/'CHILD-ERROR.txt').exists() else 'child terminated'
    assert json.loads(result.read_text())['completed_cycles']==2 and base.read_state(e)['completed_cycles']==2
    # Child gate override does not alter the parent or installed source bytes.
    with pytest.raises(port.GateClosed):port.require_live_clearance()
    assert e['send'].call_count==0


def test_real_gate_precedes_bridge_adaptation(private):
    e,folder,cfg=private;worker,_=setup_worker(private);b=bridge(e)
    with patch('factory_source.prepare_factory_source',side_effect=AssertionError('No bridge preparation')):
        assert worker.poll(b,e['path'])['status']=='EXECUTION_SESSION_FACTORY_CLOSED_IN_CODE'
    assert e['send'].call_count==0


def test_cached_bridge_new_lease_pauses_without_resend(private):
    e,folder,cfg=private;worker,_=setup_worker(private);b=bridge(e)
    with intercept(e):
        assert worker.poll(b,e['path'])['phase']=='ENTRY_REVIEW'
        count=e['send'].call_count;b.run_id='changed-lease'
        with pytest.raises(ValueError,match='SOURCE_LEASE_CHANGED'):worker.poll(b,e['path'])
    assert e['send'].call_count==count and e['store'].control()['mode']=='PAUSED'


def test_changed_bridge_instance_rejected(private):
    e,folder,cfg=private;worker,_=setup_worker(private);b=bridge(e)
    with intercept(e):
        assert worker.poll(b,e['path'])['phase']=='ENTRY_REVIEW'
        with pytest.raises(ValueError,match='INPUT_BRIDGE_CHANGED'):worker.poll(bridge(e,'other.sqlite'),e['path'])
    assert e['store'].control()['mode']=='PAUSED'


def test_missing_owner_table_not_created_by_adapter(flow):
    e=flow;b=bridge(e)
    with patch.object(port,'require_live_clearance',return_value=None):
        with pytest.raises(ValueError,match='EXISTING_FACTORY_PREPARATION'):prepare_factory_source(object(),b,e['path'])
    with e['store'].db() as db:assert db.execute("SELECT 1 FROM sqlite_master WHERE name='preparation_candidate_exclusive_source_owner_v1'").fetchone() is None
