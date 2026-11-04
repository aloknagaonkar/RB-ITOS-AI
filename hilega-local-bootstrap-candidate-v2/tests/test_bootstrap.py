from copy import deepcopy
from datetime import timedelta
import hashlib
import hmac
import json
import os
from pathlib import Path
import pytest
from local_admission import LocalApproval,expected,canonical,sha,MODEL
from local_context import recover_disabled_context
from test_provisioning import setup
from test_closed_application_coordinator_v1 import env,bound_env,ready,case,flow
import test_closed_application_coordinator_v1 as base
from market_lab.hilega_execution_port_v1 import adapter as port
from market_lab.hilega_provisioning_workflow_v1 import _scan,provision_disabled_owner,provision_and_enroll_candidate
from market_lab.hilega_exclusive_closed_route_v1 import TABLE

ROOT=b'LOCAL-BOOTSTRAP-TEST-ROOT-ONLY-0000'


def grant_for(setup,*,operation='ENROLL_DISABLED_OWNER',fingerprint=None,roots=None):
    e,parent,pin,secret=setup;clock=lambda:e['clock'][0]
    release=Path(os.environ['HILEGA_PACKAGE_B_BUNDLE']);release_sha=sha((release/'RELEASE-MANIFEST.json').read_bytes())
    fingerprint=fingerprint or _scan(e['source'],e['adapter_store'],pin,e['path'],e['key'],clock)
    bind=expected(e['source'],e['adapter_store'],pin,e['path'],e['key'],release,release_sha,private_parent=parent,state_fingerprint=fingerprint)
    value=dict(model=MODEL,operation=operation,issuer_id='local-test-root',grant_id='local-test-grant',binding=bind,
        issued_at=(clock()-timedelta(seconds=1)).isoformat(),expires_at=(clock()+timedelta(seconds=50)).isoformat(),
        order_transport_permission=False,production_execution_enabled=False)
    roots=roots if roots is not None else {'local-test-root':ROOT}
    value['signature']=hmac.new(roots['local-test-root'],canonical(value),hashlib.sha256).hexdigest()
    return value,bind,roots


def approve(setup,**kwargs):
    value,bind,roots=grant_for(setup,**kwargs)
    e=setup[0]
    return LocalApproval(value,bind,lambda:roots,operation=value['operation'],clock=lambda:e['clock'][0])


def run(setup,approval,**kwargs):
    e,parent,pin,secret=setup
    return provision_disabled_owner(e['source'],e['adapter_store'],pin,e['path'],e['key'],parent,secret,
        local_approval=approval,clock=lambda:e['clock'][0],**kwargs)


def folder(parent):
    values=list(parent.glob('candidate-context-*'));assert len(values)==1;return values[0]


def test_signed_local_enrollment_works_with_real_order_gate_closed(setup):
    e,parent,pin,secret=setup
    with pytest.raises(port.GateClosed):port.require_live_clearance()
    result=run(setup,approve(setup))
    assert result['status']=='CANDIDATE_PRIVATE_CONTEXT_AND_OWNER_READY' and base.count(e,TABLE)==1
    secret.assert_called_once();assert e['send'].call_count==0
    assert json.loads((folder(parent)/'authority.json').read_text())['key']!=pin['key']
    with e['adapter_store'].tx() as db:assert db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0]==0
    with pytest.raises(port.GateClosed):port.require_live_clearance()


def test_original_provisioner_still_closed_before_secret_read(setup):
    e,parent,pin,secret=setup
    with pytest.raises(port.GateClosed):provision_and_enroll_candidate(e['source'],e['adapter_store'],pin,e['path'],e['key'],parent,secret,clock=lambda:e['clock'][0])
    secret.assert_not_called();assert not list(parent.iterdir())


@pytest.mark.parametrize('field',['account_scope','seed_request_id','bridge_run_id','state_fingerprint','journal','private_parent'])
def test_wrong_binding_blocks_before_secret(setup,field):
    value,bind,roots=grant_for(setup)
    value=deepcopy(value)
    value['binding'][field]='f'*64 if field=='state_fingerprint' else 'changed'
    payload={k:v for k,v in value.items() if k!='signature'}
    value['signature']=hmac.new(roots['local-test-root'],canonical(payload),hashlib.sha256).hexdigest()
    e,parent,pin,secret=setup
    with pytest.raises(ValueError,match='BINDING_CHANGED'):LocalApproval(value,bind,lambda:roots,operation=value['operation'],clock=lambda:e['clock'][0])
    secret.assert_not_called();assert not list(parent.iterdir())


def test_bad_signature_blocks_before_files(setup):
    value,bind,roots=grant_for(setup);value['signature']='0'*64;e,parent,pin,secret=setup
    with pytest.raises(ValueError,match='SIGNATURE'):LocalApproval(value,bind,lambda:roots,operation=value['operation'],clock=lambda:e['clock'][0])
    secret.assert_not_called();assert not list(parent.iterdir())


def test_expired_approval_blocks_before_secret(setup):
    approval=approve(setup);e,parent,pin,secret=setup;e['clock'][0]+=timedelta(seconds=61)
    with pytest.raises(ValueError,match='EXPIRED_OR_FUTURE'):run(setup,approval)
    secret.assert_not_called();assert not list(parent.iterdir())


def test_capture_key_cannot_authorize_bootstrap(setup):
    e,parent,pin,secret=setup;approval=approve(setup,roots={'local-test-root':bytes.fromhex(pin['key'])})
    with pytest.raises(ValueError,match='CAPTURE_KEY'):run(setup,approval)
    secret.assert_not_called();assert not list(parent.iterdir())


@pytest.mark.parametrize('point',['AFTER_PRIVATE_FILES_BEFORE_ENROLLMENT','BEFORE_OWNER_COMMIT'])
def test_precommit_interruption_blocks_new_key_retry(setup,point):
    e,parent,pin,secret=setup;approval=approve(setup)
    def fail(at):
        if at==point:raise RuntimeError('synthetic interruption')
    with pytest.raises(RuntimeError):run(setup,approval,checkpoint=fail)
    key=(folder(parent)/'authority.json').read_bytes()
    assert base.count(e,TABLE)==0
    with pytest.raises(ValueError,match='EXISTING_LOCAL_CONTEXT'):run(setup,approval)
    assert (folder(parent)/'authority.json').read_bytes()==key and secret.call_count==1


def test_postcommit_recovery_keeps_same_key_and_owner_with_order_gate_closed(setup):
    e,parent,pin,secret=setup
    def fail(at):
        if at=='AFTER_OWNER_COMMIT_BEFORE_RECEIPT':raise RuntimeError('synthetic postcommit interruption')
    with pytest.raises(RuntimeError):run(setup,approve(setup),checkpoint=fail)
    p=folder(parent);digest=sha((p/'context.json').read_bytes());key=(p/'authority.json').read_bytes()
    approval=approve(setup,operation='RECOVER_DISABLED_CONTEXT',fingerprint=digest)
    result=recover_disabled_context(e['source'],e['adapter_store'],e['path'],p/'context.json',digest,pin,approval,clock=lambda:e['clock'][0])
    assert result['new_key_created'] is False and (p/'authority.json').read_bytes()==key
    assert base.count(e,TABLE)==1 and secret.call_count==1 and e['send'].call_count==0


def test_revocation_before_commit_rolls_back_owner(setup):
    value,bind,roots=grant_for(setup);e,parent,pin,secret=setup
    approval=LocalApproval(value,bind,lambda:roots,operation=value['operation'],clock=lambda:e['clock'][0])
    def revoke(at):
        if at=='BEFORE_OWNER_COMMIT':roots.clear()
    with pytest.raises(ValueError,match='NOT_TRUSTED'):run(setup,approval,checkpoint=revoke)
    assert base.count(e,TABLE)==0 and e['send'].call_count==0


def test_expiry_before_commit_rolls_back_owner(setup):
    e,parent,pin,secret=setup;approval=approve(setup)
    def expire(at):
        if at=='BEFORE_OWNER_COMMIT':e['clock'][0]+=timedelta(seconds=61)
    with pytest.raises(ValueError,match='EXPIRED_OR_FUTURE'):run(setup,approval,checkpoint=expire)
    assert base.count(e,TABLE)==0 and e['send'].call_count==0


def test_changed_source_lease_blocks_before_secret(setup):
    approval=approve(setup);e,parent,pin,secret=setup;e['source'].run_id='new-lease'
    with pytest.raises(ValueError,match='SOURCE_BINDING_CHANGED'):run(setup,approval)
    secret.assert_not_called()


def test_local_grant_cannot_enable_transport(setup):
    value,bind,roots=grant_for(setup);value['order_transport_permission']=True;e=setup[0]
    with pytest.raises(ValueError,match='CANNOT_ENABLE'):LocalApproval(value,bind,lambda:roots,operation=value['operation'],clock=lambda:e['clock'][0])


def test_recovery_does_not_implicitly_rebind_new_lease(setup):
    e,parent,pin,secret=setup;run(setup,approve(setup));p=folder(parent);digest=sha((p/'context.json').read_bytes())
    key=(p/'authority.json').read_bytes();e['source'].run_id='new-startup-lease'
    approval=approve(setup,operation='RECOVER_DISABLED_CONTEXT',fingerprint=digest)
    with pytest.raises(ValueError,match='SOURCE_BINDING_CHANGED'):recover_disabled_context(e['source'],e['adapter_store'],e['path'],p/'context.json',digest,pin,approval,clock=lambda:e['clock'][0])
    assert key==(p/'authority.json').read_bytes() and base.count(e,TABLE)==1 and secret.call_count==1
