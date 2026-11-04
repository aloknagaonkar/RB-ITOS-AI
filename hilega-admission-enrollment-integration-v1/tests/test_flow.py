import os,json
from pathlib import Path
from datetime import timedelta
import pytest
from test_bootstrap import setup,approve,folder
from admission_enrollment_flow import DisabledEnrollmentFlow
from local_admission import sha
from market_lab.hilega_execution_port_v1 import adapter as port
from market_lab.hilega_exclusive_closed_route_v1 import TABLE
import test_closed_application_coordinator_v1 as base

def flow(setup):
    e,parent,pin,secret=setup;release=Path(os.environ['HILEGA_PACKAGE_B_BUNDLE'])
    return DisabledEnrollmentFlow(e['source'],e['adapter_store'],pin,e['path'],e['key'],parent,release,sha((release/'RELEASE-MANIFEST.json').read_bytes()),clock=lambda:e['clock'][0])
def test_native_admission_request_is_read_only_and_unsigned(setup):
    e,parent,pin,secret=setup;before=e['store'].control();request=flow(setup).admission_request()
    assert request['approval_created'] is False and request['binding']['seed_request_id']==e['key']
    assert e['store'].control()==before and not list(parent.iterdir()) and base.count(e,TABLE)==0
    secret.assert_not_called()
def test_integrated_signed_enrollment_uses_native_gate_closed_path(setup):
    e,parent,pin,secret=setup
    with pytest.raises(port.GateClosed):port.require_live_clearance()
    result=flow(setup).enroll(approve(setup),secret)
    assert result['production_execution_enabled'] is False and base.count(e,TABLE)==1 and e['send'].call_count==0
    assert e['store'].control()['mode']=='PAUSED';secret.assert_called_once()
    with pytest.raises(port.GateClosed):port.require_live_clearance()
def test_unsigned_dict_is_not_an_approval(setup):
    e,parent,pin,secret=setup
    with pytest.raises(ValueError,match='SIGNED_LOCAL'):flow(setup).enroll({},secret)
    secret.assert_not_called();assert not list(parent.iterdir())
def test_changed_lease_blocks_before_secret_read(setup):
    e,parent,pin,secret=setup;approval=approve(setup);f=flow(setup);e['source'].run_id='changed'
    with pytest.raises(ValueError):f.enroll(approval,secret)
    secret.assert_not_called();assert not list(parent.iterdir())
def test_expired_grant_blocks_without_owner(setup):
    e,parent,pin,secret=setup;approval=approve(setup);f=flow(setup);e['clock'][0]+=timedelta(seconds=61)
    with pytest.raises(ValueError):f.enroll(approval,secret)
    assert base.count(e,TABLE)==0;secret.assert_not_called()
def test_postcommit_interruption_recovers_one_key_and_owner(setup):
    e,parent,pin,secret=setup;f=flow(setup)
    def fail(point):
        if point=='AFTER_OWNER_COMMIT_BEFORE_RECEIPT':raise RuntimeError('disposable interruption')
    with pytest.raises(RuntimeError):f.enroll(approve(setup),secret,checkpoint=fail)
    p=folder(parent);key=(p/'authority.json').read_bytes();digest=sha((p/'context.json').read_bytes())
    result=f.recover(p/'context.json',digest,approve(setup,operation='RECOVER_DISABLED_CONTEXT',fingerprint=digest))
    assert result['new_key_created'] is False and (p/'authority.json').read_bytes()==key and base.count(e,TABLE)==1
    assert e['send'].call_count==0 and secret.call_count==1
def test_native_precommit_expiry_rolls_owner_back(setup):
    e,parent,pin,secret=setup;f=flow(setup)
    def expire(point):
        if point=='BEFORE_OWNER_COMMIT':e['clock'][0]+=timedelta(seconds=61)
    with pytest.raises(ValueError):f.enroll(approve(setup),secret,checkpoint=expire)
    assert base.count(e,TABLE)==0 and e['send'].call_count==0
def test_disabled_owner_does_not_enable_final_activation(setup):
    e,parent,pin,secret=setup;f=flow(setup);f.enroll(approve(setup),secret)
    result=f.final_activation_review();assert result['activation_available'] is False and result['hard_order_gate_closed'] is True
    assert result['registry_enable_available'] is False and e['send'].call_count==0
