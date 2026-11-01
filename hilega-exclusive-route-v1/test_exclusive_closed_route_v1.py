"""Actual staged Source/worker tests. Temporary databases, intercepted transport."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import sys
from unittest.mock import Mock,patch
import pytest
import test_closed_application_coordinator_v1 as base
from test_closed_application_coordinator_v1 import env,bound_env,ready,case,flow
from market_lab.hilega_exclusive_closed_route_v1 import (
    TABLE,enroll_candidate_route,candidate_poll,closed_poll,STAGED_SOURCE_SHA256,
)
from market_lab.hilega_preparation_runtime_v1.source import Source
from market_lab.hilega_execution_port_v1 import adapter as port


def cursor(e):
    with e['store'].db() as db:return db.execute('SELECT data FROM preparation_source WHERE id=1').fetchone()[0]


def owner(e):
    with e['store'].db() as db:return json.loads(db.execute('SELECT data FROM '+TABLE+' WHERE id=1').fetchone()[0])


@pytest.fixture
def routed(flow):
    e=flow;enroll_candidate_route(base.session(e))
    with patch.object(base,'poll',side_effect=lambda e,**kw:candidate_poll(base.session(e,**kw))):yield e


def test_unenrolled_source_uses_original_preparation_route(flow):
    e=flow;before=cursor(e)
    result=closed_poll(e['source'],e['path'])
    assert result['status']=='APPLICATION_PREPARATION_SOURCE_PROCESSED' and cursor(e)==before
    assert e['send'].call_count==0 and base.count(e,TABLE)==0


def test_enrollment_is_signed_idempotent_and_does_not_submit(flow):
    e=flow;s=base.session(e)
    first=enroll_candidate_route(s);saved=owner(e);second=enroll_candidate_route(s)
    assert first['idempotent_replay'] is False and second['idempotent_replay'] is True
    assert saved==owner(e) and e['send'].call_count==0
    assert base.count(e,base.STATE)==0


def test_legacy_source_cannot_consume_new_entry_after_enrollment(routed):
    e=routed;base.finish(e);base.resume_and_signal(e);before=cursor(e)
    e['source'].provider=Mock(side_effect=AssertionError('Legacy source must not capture'))
    output=e['source'].run_source_once(e['path'])
    assert output['status']=='COORDINATOR_OWNS_SOURCE_ROUTE_CLOSED' and cursor(e)==before
    e['source'].provider.assert_not_called()
    assert base.poll(e)['phase']=='PREPARE_PENDING' and base.poll(e)['phase']=='BUY_PENDING'
    assert e['send'].call_count==2


def test_direct_coordinator_tick_requires_route_context(routed):
    e=routed
    row=base.worker_tick(base.session(e))
    assert row['status']=='COORDINATOR_REQUIRES_EXCLUSIVE_ROUTE_CONTEXT'
    assert e['send'].call_count==0 and base.count(e,base.STATE)==0
    assert candidate_poll(base.session(e))['phase']=='ENTRY_REVIEW'


def test_nested_source_exit_and_two_cycles_use_one_route_owner(routed):
    e=routed;base.finish(e);assert base.read_state(e)['completed_cycles']==1
    base.resume_and_signal(e);base.poll(e);base.poll(e);base.finish(e)
    assert base.read_state(e)['completed_cycles']==2 and e['send'].call_count==4
    assert base.count(e,base.ARCHIVES)==2
    assert closed_poll(e['source'],e['path'])['status']=='COORDINATOR_OWNS_SOURCE_ROUTE_CLOSED'


def test_competing_legacy_and_candidate_poll_preserve_fresh_signal(routed):
    e=routed;base.finish(e);base.resume_and_signal(e)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a=pool.submit(closed_poll,e['source'],e['path'])
        b=pool.submit(candidate_poll,base.session(e))
        legacy,coordinated=a.result(),b.result()
    assert legacy['status']=='COORDINATOR_OWNS_SOURCE_ROUTE_CLOSED'
    assert coordinated['phase']=='PREPARE_PENDING'
    assert base.poll(e)['phase']=='BUY_PENDING' and e['send'].call_count==2


def test_two_enrolled_pollers_submit_only_one_buy(routed):
    e=routed
    with ThreadPoolExecutor(max_workers=2) as pool:rows=list(pool.map(lambda _:candidate_poll(base.session(e)),range(2)))
    assert e['send'].call_count==1 and base.read_state(e)['phase']=='ENTRY_REVIEW'
    assert all(r['production_execution_enabled'] is False for r in rows)


def test_owner_commit_interruption_rolls_back(flow):
    e=flow
    with pytest.raises(RuntimeError):
        enroll_candidate_route(base.session(e),checkpoint=base.interrupt('BEFORE_SOURCE_OWNER_COMMIT'))
    assert base.count(e,TABLE)==0 and e['send'].call_count==0
    assert enroll_candidate_route(base.session(e))['idempotent_replay'] is False


def test_route_lock_is_released_after_candidate_exception(routed):
    e=routed
    with pytest.raises(RuntimeError):candidate_poll(base.session(e,checkpoint=base.interrupt('AFTER_BUY_ACTION_BEFORE_STATE')))
    assert closed_poll(e['source'],e['path'])['status']=='COORDINATOR_OWNS_SOURCE_ROUTE_CLOSED'
    e['providers']['entry'].side_effect=AssertionError('No repeated capture')
    assert candidate_poll(base.session(e))['phase']=='ENTRY_REVIEW' and e['send'].call_count==1


def test_tampered_owner_blocks_candidate_and_keeps_legacy_closed(routed):
    e=routed
    with e['store'].db() as db:
        row=owner(e);row['signature']='changed'
        db.execute('UPDATE '+TABLE+' SET data=?',(json.dumps(row),))
    with pytest.raises(ValueError,match='SOURCE_OWNER_SIGNATURE_INVALID'):candidate_poll(base.session(e))
    assert closed_poll(e['source'],e['path'])['status']=='COORDINATOR_OWNS_SOURCE_ROUTE_CLOSED'
    assert e['send'].call_count==0


def test_deleted_owner_row_cannot_rebaseline_or_fall_back(routed):
    e=routed
    with e['store'].db() as db:db.execute('DELETE FROM '+TABLE)
    for action in (lambda:candidate_poll(base.session(e)),lambda:closed_poll(e['source'],e['path']),
                   lambda:enroll_candidate_route(base.session(e))):
        with pytest.raises(ValueError,match='SOURCE_OWNER_MISSING_OR_AMBIGUOUS_NO_REBASELINE'):action()
    assert e['send'].call_count==0


@pytest.mark.parametrize('change',['lease','seed','journal','authority'])
def test_restart_cannot_take_over_a_different_binding(routed,tmp_path,change):
    e=routed;s=base.session(e)
    if change=='lease':s.bridge='different-lease'
    elif change=='seed':s.seed='different-seed'
    elif change=='authority':s.authority=dict(s.authority,authority_id='different-authority')
    else:
        path=tmp_path/'other.jsonl';path.write_text(e['path'].read_text());s.journal=path
    with pytest.raises(ValueError):candidate_poll(s)
    assert e['send'].call_count==0


def test_gate_closed_enrolled_poll_creates_no_coordinator_state(routed):
    e=routed
    with patch.object(e['transport'],'check',side_effect=port.GateClosed('PRODUCTION_MUTATIONS_CLOSED_IN_CODE')):
        output=candidate_poll(base.session(e))
    assert output['status']=='EXECUTION_COORDINATOR_CLOSED_IN_CODE'
    assert base.count(e,base.STATE)==0 and e['send'].call_count==0
    for p in e['providers'].values():p.assert_not_called()


def test_staged_actual_worker_once_holds_enrolled_route(routed):
    e=routed;before=cursor(e)
    stage=Path(os.environ['HILEGA_EXCLUSIVE_TEST_STAGE'])
    spec=importlib.util.spec_from_file_location('staged_actual_worker',stage/'scripts/hilega_production_simulator_bridge.py')
    worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)
    import market_lab.hilega_production_bridge_health_v1 as health
    with patch.object(sys,'argv',['worker','--once','--source',str(e['path'])]),\
         patch.dict(os.environ,HILEGA_PRODUCTION_WORKSPACE_MODE='SIMULATION_ONLY',HILEGA_PRODUCTION_SIM_BRIDGE_ENABLED='1'),\
         patch('dotenv.load_dotenv',return_value=False),\
         patch.object(worker,'Store',return_value=e['store']),patch.object(worker,'Service',return_value=e['s']),\
         patch.object(health,'worker_lock',return_value=nullcontext()),patch.object(health,'claim',return_value='synthetic-lease'),\
         patch.object(health,'heartbeat',return_value={'healthy':False}),patch.object(health,'finish') as finish,\
         patch.object(e['s'],'watch_bridge_health'),patch('builtins.print') as output:
        assert worker.main()==0
    printed=json.loads(output.call_args.args[0])
    assert printed['status']=='COORDINATOR_OWNS_SOURCE_ROUTE_CLOSED' and cursor(e)==before
    assert e['send'].call_count==0;finish.assert_called_once()
    fresh=Source(e['s'],run_id='synthetic-lease',provider=Mock(side_effect=AssertionError('No capture')))
    assert closed_poll(fresh,e['path'])['status']=='COORDINATOR_OWNS_SOURCE_ROUTE_CLOSED'


def test_staged_coordinator_cli_remains_closed_without_backend(tmp_path):
    import subprocess
    script=Path(os.environ['HILEGA_EXCLUSIVE_TEST_STAGE'])/'closed_application_coordinator_v1.py'
    run=subprocess.run([sys.executable,'-I',str(script),'--once'],cwd=tmp_path,capture_output=True,text=True,timeout=10)
    assert run.returncode==0,run.stderr
    output=json.loads(run.stdout)
    assert output['status']=='EXECUTION_COORDINATOR_CLOSED_IN_CODE'
    assert output['application_database_opened'] is False and not list(tmp_path.iterdir())


def test_evidence_provider_cannot_advance_source_in_buy_phase(routed):
    e=routed;before=cursor(e)
    e['providers']['entry'].side_effect=lambda kind:e['source'].run_source_once(e['path'])
    with pytest.raises(ValueError,match='SOURCE_ONLY_DURING_COORDINATOR_EXIT_PHASE'):
        candidate_poll(base.session(e))
    assert cursor(e)==before and e['send'].call_count==0
