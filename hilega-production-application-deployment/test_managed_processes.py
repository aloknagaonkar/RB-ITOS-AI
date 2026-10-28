"""Synthetic /proc and PID records only; never signals an actual process."""
import json
from pathlib import Path
import pytest
import managed_processes as m


@pytest.fixture
def env(tmp_path):
    root=tmp_path/'repo';root.mkdir();proc=tmp_path/'proc';proc.mkdir()
    for role,pid in [('api',101),('worker',102)]:
        path=root/'data/runtime'/f'{role}.json';path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(dict(service=role,pid=pid,project_root=str(root))))
    return root,proc


def process(env,pid,role,*,cwd=None,state='S',production=False):
    root,proc=env;p=proc/str(pid);p.mkdir()
    args=['python','scripts/hilega_production_simulator_bridge.py','--watch'] if production else ['python','-m','market_lab.runtime',role]
    (p/'cmdline').write_bytes(b'\0'.join(x.encode() for x in args)+b'\0')
    (p/'cwd').symlink_to(cwd or root,target_is_directory=True)
    fields=[state]+['0']*18+['123456']
    (p/'stat').write_text(str(pid)+' (python process) '+' '.join(fields))


def test_matches_actual_api_worker_pid_roles(env):
    process(env,101,'api');process(env,102,'worker')
    result=m.inspect(*env)
    assert all(r['state']=='MATCHED_RUNNING' for r in result['records'])
    assert result['quiescent'] is False
    assert all(r['start_ticks']==123456 for r in result['active_processes'])


def test_running_managed_role_blocks_apply(env):
    process(env,101,'api')
    with pytest.raises(m.ManagedBlocked,match='STILL_RUNNING'):m.require_stopped(*env)


def test_stopped_records_are_retained_and_accepted(env):
    assert m.require_stopped(*env)['quiescent'] is True
    assert (env[0]/'data/runtime/api.json').exists()


def test_unrelated_bridge_repo_is_not_stop_scope(env,tmp_path):
    bridge=tmp_path/'bridge';bridge.mkdir()
    process(env,580,'api',cwd=bridge)
    assert m.require_stopped(*env)['quiescent'] is True


def test_source_worker_blocks_even_without_pid_record(env):
    process(env,103,'unused',production=True)
    with pytest.raises(m.ManagedBlocked,match='STILL_RUNNING'):m.require_stopped(*env)


def test_duplicates_fail_closed(env):
    process(env,101,'api');process(env,104,'api')
    with pytest.raises(m.ManagedBlocked,match='DUPLICATE_MANAGED_ROLE'):m.inspect(*env)


def test_wrong_pid_record_requires_review(env):
    process(env,104,'api')
    with pytest.raises(m.ManagedBlocked,match='NOT_MATCHED_BY_PID_RECORD'):m.inspect(*env)


def test_role_mismatch_requires_review(env):
    process(env,101,'worker')
    with pytest.raises(m.ManagedBlocked,match='PID_ROLE_MISMATCH'):m.inspect(*env)


def test_missing_record_not_silently_bypassed(env):
    (env[0]/'data/runtime/api.json').unlink()
    with pytest.raises(m.ManagedBlocked,match='PID_RECORD_REQUIRED'):m.require_stopped(*env)


def test_zombie_is_not_a_running_code_reader(env):
    process(env,101,'api',state='Z')
    assert m.require_stopped(*env)['quiescent'] is True


def test_other_runtime_roles_are_not_in_stop_scope(env):
    process(env,110,'historical-evidence')
    assert m.require_stopped(*env)['quiescent'] is True
