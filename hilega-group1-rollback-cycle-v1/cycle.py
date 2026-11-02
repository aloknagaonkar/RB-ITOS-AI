"""Reuse an unchanged approved closed rollout plan for rollback and reinstallation."""
import hashlib
import json
from pathlib import Path


def need(ok,reason):
    if not ok:raise ValueError(reason)


def sha(raw):return hashlib.sha256(raw).hexdigest()


def regular(path):
    p=Path(path);need(p.is_absolute() and p.is_file() and not any(q.is_symlink() for q in [p,*p.parents]),'REGULAR_CYCLE_INPUT_REQUIRED')
    return p.read_bytes()


def validate_receipt(raw,digest):
    receipt=json.loads(raw)
    need(receipt['status']=='PASS_TARGETED_ONLY' and receipt['plan_sha256']==digest
        and receipt['closed_release_scope_regression_reexecuted'] is True,'PASSING_UNCHANGED_CLOSED_RELEASE_VALIDATION_REQUIRED')
    return receipt


def copy_plan(original,target,digest):
    need(not (target/'PLAN.json').exists() and not (target/'TRANSACTION.json').exists(),'NEW_REINSTALL_PLAN_FOLDER_REQUIRED')
    raw=regular(original);need(sha(raw)==digest,'ORIGINAL_APPROVED_PLAN_CHANGED')
    check=regular(original.parent/'CHECK-VALIDATION.json');validate_receipt(check,digest)
    (target/'PLAN.json').write_bytes(raw);(target/'CHECK-VALIDATION.json').write_bytes(check)
    provenance=dict(model='UNCHANGED_PLAN_VALIDATION_REUSE_V1',original_plan=str(original),plan_sha256=digest,
        original_validation_sha256=sha(check),new_plan_bytes_identical=True,new_validation_bytes_identical=True,
        tests_reexecuted=False,production_execution_enabled=False)
    (target/'VALIDATION-PROVENANCE.json').write_text(json.dumps(provenance,indent=2)+'\n')
    return provenance


def steps(original,reinstall):
    return [(original,'hold','INSTALLED_SERVICES_STOPPED'),(original,'rollback','ROLLED_BACK_SERVICES_STOPPED'),
        (original,'start','ROLLED_BACK_RUNNING'),(original,'status','ROLLED_BACK_RUNNING'),
        (reinstall,'apply','INSTALLED_SERVICES_STOPPED'),(reinstall,'start','CLOSED_BUNDLE_RUNNING'),
        (reinstall,'status','CLOSED_BUNDLE_RUNNING')]


def perform(sequence,invoke,persist,after_step=lambda index,result:None):
    state=dict(phase='EXECUTING',completed_steps=[],production_execution_enabled=False)
    for index,(plan,action,expected) in enumerate(sequence):
        state.update(next_step=index,action_in_progress=action,plan_in_progress=str(plan));persist(state)
        result=invoke(plan,action)
        need(result.get('phase')==expected and result.get('production_execution_enabled') is False,'UNEXPECTED_CLOSED_MAINTENANCE_RESULT')
        after_step(index,result)
        state['completed_steps'].append(dict(index=index,action=action,plan=str(plan),phase=result['phase']))
        persist(state)
    state.update(phase='ROLLBACK_AND_CANDIDATE_RESTORE_VERIFIED',next_step=len(sequence),action_in_progress=None)
    persist(state);return state
