import json
from pathlib import Path
import pytest
from cycle import copy_plan,sha,validate_receipt,steps,perform


def sources(tmp_path):
    old=tmp_path/'original';old.mkdir();plan=old/'PLAN.json';plan.write_text('{"production_execution_enabled":false}\n')
    digest=sha(plan.read_bytes());receipt=dict(status='PASS_TARGETED_ONLY',plan_sha256=digest,closed_release_scope_regression_reexecuted=True)
    (old/'CHECK-VALIDATION.json').write_text(json.dumps(receipt));new=tmp_path/'new';new.mkdir()
    return plan,new,digest


def test_plan_and_existing_validation_are_reused_byte_for_byte(tmp_path):
    old,new,digest=sources(tmp_path);p=copy_plan(old,new,digest)
    assert (new/'PLAN.json').read_bytes()==old.read_bytes()
    assert (new/'CHECK-VALIDATION.json').read_bytes()==(old.parent/'CHECK-VALIDATION.json').read_bytes()
    assert p['tests_reexecuted'] is False


def test_changed_original_plan_is_not_reapproved(tmp_path):
    old,new,digest=sources(tmp_path);old.write_text('{}')
    with pytest.raises(ValueError,match='APPROVED_PLAN_CHANGED'):copy_plan(old,new,digest)
    assert not (new/'PLAN.json').exists()


def test_targeted_only_receipt_cannot_authorize_cycle(tmp_path):
    old,new,digest=sources(tmp_path)
    raw=json.loads((old.parent/'CHECK-VALIDATION.json').read_text());raw['closed_release_scope_regression_reexecuted']=False
    with pytest.raises(ValueError,match='VALIDATION_REQUIRED'):validate_receipt(json.dumps(raw),digest)


def test_reinstall_folder_cannot_overwrite_an_existing_transaction(tmp_path):
    old,new,digest=sources(tmp_path);(new/'TRANSACTION.json').write_text('{}')
    with pytest.raises(ValueError,match='NEW_REINSTALL'):copy_plan(old,new,digest)


def test_cycle_sequence_restores_old_then_exact_candidate():
    sequence=steps(Path('/old/PLAN.json'),Path('/new/PLAN.json'))
    assert [s[1] for s in sequence]==['hold','rollback','start','status','apply','start','status']
    assert sequence[3][2]=='ROLLED_BACK_RUNNING' and sequence[-1][2]=='CLOSED_BUNDLE_RUNNING'
    assert not any('database' in s[1] for s in sequence)


def test_completed_cycle_records_every_verified_phase():
    sequence=steps(Path('/old'),Path('/new'));saved=[];calls=[]
    def invoke(plan,action):
        expected=sequence[len(calls)][2];calls.append(action)
        return dict(phase=expected,production_execution_enabled=False)
    r=perform(sequence,invoke,lambda row:saved.append(json.loads(json.dumps(row))))
    assert r['phase']=='ROLLBACK_AND_CANDIDATE_RESTORE_VERIFIED' and len(r['completed_steps'])==7
    assert saved[0]['next_step']==0 and saved[-1]['next_step']==7


def test_failed_action_stops_without_advancing_or_automatic_recovery():
    sequence=steps(Path('/old'),Path('/new'));calls=[];saved=[]
    def invoke(plan,action):
        calls.append(action)
        if action=='rollback':raise RuntimeError('simulated failure')
        return dict(phase='INSTALLED_SERVICES_STOPPED',production_execution_enabled=False)
    with pytest.raises(RuntimeError):perform(sequence,invoke,lambda row:saved.append(json.loads(json.dumps(row))))
    assert calls==['hold','rollback'] and len(saved[-1]['completed_steps'])==1
    assert saved[-1]['action_in_progress']=='rollback'


def test_unexpected_live_permission_stops_cycle():
    with pytest.raises(ValueError,match='UNEXPECTED_CLOSED'):perform(steps(Path('/old'),Path('/new')),
        lambda *a:dict(phase='INSTALLED_SERVICES_STOPPED',production_execution_enabled=True),lambda r:None)
