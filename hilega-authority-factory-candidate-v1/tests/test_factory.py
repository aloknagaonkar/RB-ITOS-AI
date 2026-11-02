from datetime import timedelta
import json
import os
from pathlib import Path
from unittest.mock import Mock,patch
import pytest
from test_authority import expected,grant,ROOT
from authority_contract import digest
from factory_adapter import AuthorityBoundFactory,pause_for_recovery
from test_closed_application_coordinator_v1 import env,bound_env,ready,case,flow
from test_private_context import private,enroll,loader,LiveProviders,pc,port,base


def binding_for(private):
    e,folder,config=private;bundle=Path(os.environ['HILEGA_PACKAGE_B_BUNDLE'])
    from market_lab.hilega_exclusive_closed_route_v1 import TABLE
    with e['store'].db() as db:owner=db.execute('SELECT data FROM '+TABLE+' WHERE id=1').fetchone()[0]
    return dict(account_scope=json.loads((folder/'pin.json').read_text())['scope'],
        release_sha256=digest((bundle/'RELEASE-MANIFEST.json').read_bytes()),
        policy_sha256=digest((bundle/'runtime/POSITION-POLICY.json').read_bytes()),
        private_context_sha256=digest((folder/'context.json').read_bytes()),authority_id=e['authority']['authority_id'],
        authority_key_sha256=digest(bytes.fromhex(e['authority']['key'])),owner_row_sha256=digest(owner.encode()),
        seed_request_id=config['seed_request_id'],bridge_run_id=config['bridge_run_id'])



def test_real_gate_precedes_grant_trust_and_private_loading():
    private_load=Mock(side_effect=AssertionError('No private I/O'))
    trust=Mock(side_effect=AssertionError('No trust read'));grants=Mock(side_effect=AssertionError('No grant read'))
    factory=AuthorityBoundFactory(private_load,expected_binding=expected(),grant_loader=grants,trust_loader=trust,clock=lambda:None)
    result=factory.poll(object(),object())
    assert result['status']=='EXECUTION_SESSION_FACTORY_CLOSED_IN_CODE'
    private_load.assert_not_called();trust.assert_not_called();grants.assert_not_called()


def test_verified_grant_private_loader_and_existing_factory_run_two_cycles(private):
    e,folder,config=private;enroll(e);bind=binding_for(private);value=grant(bind,e['clock'][0])
    factory=AuthorityBoundFactory(loader(private),expected_binding=bind,grant_loader=lambda:value,trust_loader=lambda:{'synthetic-root':ROOT},clock=lambda:e['clock'][0])
    with patch.object(port,'require_live_clearance',return_value=None),patch.object(port.HttpTransport,'check',return_value=None),\
         patch.object(port.HttpTransport,'send',side_effect=lambda aid,wire:e['send'](aid,wire)),\
         patch.object(LiveProviders,'account',side_effect=lambda:base.account(e)),\
         patch.object(LiveProviders,'entry_market',side_effect=lambda:base.market(e)),\
         patch.object(pc,'capture_owned',side_effect=lambda *args:base.market(e)),\
         patch.object(base,'poll',side_effect=lambda e,**kw:factory.poll(e['source'],e['path'])):
        base.finish(e);base.resume_and_signal(e);base.poll(e);base.poll(e);base.finish(e)
    assert base.read_state(e)['completed_cycles']==2 and e['send'].call_count==4


def test_expired_grant_blocks_cached_session_and_pauses_without_resend(private):
    e,folder,config=private;enroll(e);bind=binding_for(private);value=grant(bind,e['clock'][0])
    factory=AuthorityBoundFactory(loader(private),expected_binding=bind,grant_loader=lambda:value,trust_loader=lambda:{'synthetic-root':ROOT},clock=lambda:e['clock'][0])
    with patch.object(port,'require_live_clearance',return_value=None),patch.object(port.HttpTransport,'check',return_value=None),\
         patch.object(port.HttpTransport,'send',side_effect=lambda aid,wire:e['send'](aid,wire)),\
         patch.object(LiveProviders,'entry_market',side_effect=lambda:base.market(e)):
        assert factory.poll(e['source'],e['path'])['phase']=='ENTRY_REVIEW'
        count=e['send'].call_count;e['clock'][0]+=timedelta(hours=2)
        with pytest.raises(ValueError,match='EXPIRED_OR_FUTURE'):factory.poll(e['source'],e['path'])
    assert e['send'].call_count==count and e['store'].control()['mode']=='PAUSED'


def test_native_recovery_does_not_read_context_or_send(flow):
    e=flow
    with patch.object(pc,'private_read',side_effect=AssertionError('No private context during recovery')):
        result=pause_for_recovery(e['source'].s)
    assert result['controller_paused'] and not result['controller_resumed'] and e['send'].call_count==0
