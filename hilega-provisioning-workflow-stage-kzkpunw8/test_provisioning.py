from datetime import timedelta
import json
from pathlib import Path
from unittest.mock import Mock,patch
import pytest
import test_closed_application_coordinator_v1 as base
from test_closed_application_coordinator_v1 import env,bound_env,ready,case,flow
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_execution_port_v1 import adapter as port
from market_lab.hilega_exclusive_closed_route_v1 import TABLE
from market_lab.hilega_private_context_v1 import PrivateContextLoader,LiveProviders
from market_lab.hilega_execution_session_factory_v1 import ExecutionSessionFactory,worker_poll
import market_lab.hilega_private_context_v1 as pc
from market_lab.hilega_provisioning_workflow_v1 import provision_and_enroll_candidate,recover_committed_context


@pytest.fixture
def setup(flow,tmp_path):
    e=flow;parent=tmp_path/'private';parent.mkdir(mode=0o700)
    pin=dict(PIN,model='HILEGA_UPSTOX_ACCOUNT_PIN_V1',broker='UPSTOX',approved_at=e['clock'][0].isoformat())
    secret=Mock(return_value='synthetic-token')
    return e,parent,pin,secret


def run(setup,**kwargs):
    e,parent,pin,secret=setup
    return provision_and_enroll_candidate(e['source'],e['adapter_store'],pin,e['path'],e['key'],parent,secret,clock=lambda:e['clock'][0],**kwargs)


def only_folder(parent):
    rows=list(parent.iterdir());assert len(rows)==1;return rows[0]


def test_closed_gate_creates_no_private_files_or_owner(setup):
    e,parent,pin,secret=setup
    with pytest.raises(port.GateClosed):run(setup)
    assert not list(parent.iterdir()) and base.count(e,TABLE)==0
    secret.assert_not_called();assert e['send'].call_count==0


def test_fresh_first_seed_provisions_private_context_and_signed_owner_without_send(setup):
    e,parent,pin,secret=setup
    with patch.object(port,'require_live_clearance',return_value=None):result=run(setup)
    folder=Path(result['private_folder']);assert result['production_authority_provisioned'] is False
    assert all(p.stat().st_mode&0o077==0 for p in folder.iterdir())
    assert base.count(e,TABLE)==1 and e['send'].call_count==0;secret.assert_called_once()
    assert json.loads((folder/'authority.json').read_text())['key']!=pin['key']


@pytest.mark.parametrize('point',['AFTER_PRIVATE_FILES_BEFORE_ENROLLMENT','BEFORE_OWNER_COMMIT'])
def test_precommit_interruption_keeps_intent_and_rolls_back_owner(setup,point):
    e,parent,pin,secret=setup
    with patch.object(port,'require_live_clearance',return_value=None):
        with pytest.raises(RuntimeError):run(setup,checkpoint=base.interrupt(point))
    folder=only_folder(parent)
    assert (folder/'INTENT.json').exists() and (folder/'REVIEW_REQUIRED.json').exists()
    assert base.count(e,TABLE)==0 and e['send'].call_count==0


def test_postcommit_interruption_recovers_same_context_without_new_key(setup):
    e,parent,pin,secret=setup
    with patch.object(port,'require_live_clearance',return_value=None):
        with pytest.raises(RuntimeError):run(setup,checkpoint=base.interrupt('AFTER_OWNER_COMMIT_BEFORE_RECEIPT'))
        folder=only_folder(parent);before=(folder/'authority.json').read_bytes();digest=json.loads((folder/'INTENT.json').read_text())['config_sha256']
        with patch('secrets.token_hex',side_effect=AssertionError('No new key')):
            result=recover_committed_context(e['source'],e['adapter_store'],e['path'],folder/'context.json',digest,clock=lambda:e['clock'][0])
    assert result['new_key_created'] is False and base.count(e,TABLE)==1
    assert (folder/'authority.json').read_bytes()==before and e['send'].call_count==0


def test_stale_seed_rejected_before_secret_read_or_file_creation(setup):
    e,parent,pin,secret=setup;e['clock'][0]+=timedelta(seconds=61)
    with patch.object(port,'require_live_clearance',return_value=None):
        with pytest.raises(ValueError):run(setup)
    secret.assert_not_called();assert not list(parent.iterdir()) and base.count(e,TABLE)==0


def test_expiry_before_owner_commit_rolls_back_owner(setup):
    e,parent,pin,secret=setup
    def expire(at):
        if at=='BEFORE_OWNER_COMMIT':e['clock'][0]+=timedelta(seconds=31)
    with patch.object(port,'require_live_clearance',return_value=None):
        with pytest.raises(ValueError):run(setup,checkpoint=expire)
    assert base.count(e,TABLE)==0 and e['send'].call_count==0


def test_second_provision_attempt_cannot_create_another_authority(setup):
    e,parent,pin,secret=setup
    with patch.object(port,'require_live_clearance',return_value=None):
        run(setup)
        with pytest.raises(ValueError,match='EXISTING_OWNER_REQUIRES_RECOVERY'):run(setup)
    assert len(list(parent.iterdir()))==1 and secret.call_count==1 and base.count(e,TABLE)==1


def test_changed_hold_after_private_files_blocks_enrollment(setup):
    e,parent,pin,secret=setup
    def change(at):
        if at=='AFTER_PRIVATE_FILES_BEFORE_ENROLLMENT':
            with e['store'].db() as db:
                key,raw=db.execute('SELECT id,data FROM preparation_shadow_holds').fetchone();row=json.loads(raw);row['held_cents']+=1
                db.execute('UPDATE preparation_shadow_holds SET data=? WHERE id=?',(json.dumps(row),key))
    with patch.object(port,'require_live_clearance',return_value=None):
        with pytest.raises(ValueError):run(setup,checkpoint=change)
    assert base.count(e,TABLE)==0 and e['send'].call_count==0


def test_provisioned_context_runs_existing_candidate_cycle_under_intercepted_transport(setup):
    e,parent,pin,secret=setup
    with patch.object(port,'require_live_clearance',return_value=None):
        result=run(setup);folder=Path(result['private_folder'])
        factory=ExecutionSessionFactory(PrivateContextLoader(e['source'],e['adapter_store'],e['path'],folder/'context.json',result['config_sha256'],clock=lambda:e['clock'][0]))
        with patch.object(port.HttpTransport,'check',return_value=None),patch.object(port.HttpTransport,'send',side_effect=lambda aid,wire:e['send'](aid,wire)),\
             patch.object(LiveProviders,'account',side_effect=lambda:base.account(e)),patch.object(LiveProviders,'entry_market',side_effect=lambda:base.market(e)),\
             patch.object(pc,'capture_owned',side_effect=lambda *args:base.market(e)),\
             patch.object(base,'poll',side_effect=lambda e,**kw:worker_poll(e['source'],e['path'],factory=factory)):
            base.finish(e)
    assert base.read_state(e)['completed_cycles']==1 and e['send'].call_count==2
