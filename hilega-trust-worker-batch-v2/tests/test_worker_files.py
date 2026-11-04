from datetime import timedelta
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import pytest
from authority_contract import verify,digest
from authority_files import private_bytes,trust_roots,grant_file,issue_candidate_grant
from worker_binding import registration,RegisteredAuthorityWorker,ensure_paused
from test_authority import expected,ROOT,NOW
from test_factory import binding_for
from test_closed_application_coordinator_v1 import env,bound_env,ready,case,flow
from test_private_context import private,enroll,LiveProviders,pc,port,base


def write(path,value):
    path.write_bytes(value if isinstance(value,bytes) else json.dumps(value).encode());path.chmod(0o600)
    return digest(path.read_bytes())


def setup_registry(folder,bind=None):
    bind=bind or expected();folder.chmod(0o700);key=folder/'issuer.key';key_sha=write(key,ROOT)
    value=dict(model='HILEGA_PINNED_TRUST_REGISTRY_CANDIDATE_V1',issuer_id='synthetic-root',enabled=True,
        account_scope=bind['account_scope'],release_sha256=bind['release_sha256'],key_file=str(key),key_sha256=key_sha,production_execution_enabled=False)
    path=folder/'registry.json';sha=write(path,value);return path,sha,value


def test_candidate_issuer_and_pinned_grant_file(tmp_path):
    path,sha,_=setup_registry(tmp_path)
    value=issue_candidate_grant(expected(),registry_path=path,registry_sha256=sha,issuer_id='synthetic-root',grant_id='g',issued_at=NOW.isoformat(),expires_at=(NOW+timedelta(hours=1)).isoformat())
    grant_path=tmp_path/'grant.json';gs=write(grant_path,value)
    result=verify(grant_file(grant_path,gs),expected(),trust_roots(path,sha,expected()),NOW)
    assert not result['execution_permission']


def test_registry_wrong_scope_rejected(tmp_path):
    p,s,v=setup_registry(tmp_path);v['account_scope']='UPSTOX:'+'f'*64;s=write(p,v)
    with pytest.raises(ValueError,match='SCOPE_OR_RELEASE'):trust_roots(p,s,expected())


def test_revoked_registry_rejected(tmp_path):
    p,s,v=setup_registry(tmp_path);v['enabled']=False;s=write(p,v)
    with pytest.raises(ValueError,match='ENABLED'):trust_roots(p,s,expected())


def test_rotated_issuer_key_requires_new_binding(tmp_path):
    p,s,v=setup_registry(tmp_path);Path(v['key_file']).write_bytes(b'T'*32)
    with pytest.raises(ValueError,match='HASH_CHANGED'):trust_roots(p,s,expected())


def test_changed_grant_rejected(tmp_path):
    p=tmp_path/'grant';s=write(p,{});p.write_text('{"changed":true}')
    with pytest.raises(ValueError,match='HASH_CHANGED'):grant_file(p,s)


def test_public_key_permissions_rejected(tmp_path):
    p,s,v=setup_registry(tmp_path);Path(v['key_file']).chmod(0o644)
    with pytest.raises(ValueError,match='FILE_REQUIRED'):trust_roots(p,s,expected())


def test_symlink_rejected(tmp_path):
    p=tmp_path/'key';s=write(p,ROOT);link=tmp_path/'link';link.symlink_to(p)
    with pytest.raises(ValueError,match='PATH_REQUIRED'):private_bytes(link,s)


def test_hardlink_rejected(tmp_path):
    import os
    p=tmp_path/'key';s=write(p,ROOT);os.link(p,tmp_path/'other')
    with pytest.raises(ValueError,match='FILE_REQUIRED'):private_bytes(p,s)


def disabled():
    return json.loads(Path(__file__).parents[1].joinpath('FACTORY-REGISTRATION.json').read_text())


def test_disabled_registration_cannot_hide_private_bindings(tmp_path):
    v=disabled();v['grant_file']='/missing';p=tmp_path/'reg';s=write(p,v)
    with pytest.raises(ValueError,match='NO_PRIVATE_BINDINGS'):registration(p,s)


def test_registry_cannot_enable_production(tmp_path):
    p,s,v=setup_registry(tmp_path);v['production_execution_enabled']=True;s=write(p,v)
    with pytest.raises(ValueError):trust_roots(p,s,expected())


def test_real_gate_precedes_private_providers(flow,tmp_path):
    v=disabled();v.update(enabled=True,expected_binding=expected(),private_config_file='/missing/config',private_config_sha256=expected()['private_context_sha256'],trust_registry_file='/missing/trust',trust_registry_sha256='a'*64,grant_file='/missing/grant',grant_sha256='b'*64)
    p=tmp_path/'reg';s=write(p,v);worker=RegisteredAuthorityWorker(p,s)
    with patch('worker_binding.trust_roots',side_effect=AssertionError('No issuer key read')) as roots,\
         patch('worker_binding.grant_file',side_effect=AssertionError('No grant read')) as grant:
        assert worker.poll(flow['source'],flow['path'])['status']=='EXECUTION_SESSION_FACTORY_CLOSED_IN_CODE'
    roots.assert_not_called();grant.assert_not_called()


def test_disabled_registration_ignores_environment_activation(tmp_path,monkeypatch):
    p=tmp_path/'reg';s=write(p,disabled());monkeypatch.setenv('HILEGA_PRODUCTION_EXECUTION_ENABLED','1')
    with patch('market_lab.hilega_execution_session_factory_v1.worker_poll',return_value={'closed':True}) as old:
        source=object();journal=object();assert RegisteredAuthorityWorker(p,s).poll(source,journal)=={'closed':True}
        old.assert_called_once_with(source,journal)


def setup_worker(private):
    e,folder,config=private;enroll(e);bind=binding_for(private)
    reg,rs,_=setup_registry(folder,bind)
    value=issue_candidate_grant(bind,registry_path=reg,registry_sha256=rs,issuer_id='synthetic-root',grant_id='synthetic-file-grant',issued_at=(e['clock'][0]-timedelta(seconds=1)).isoformat(),expires_at=(e['clock'][0]+timedelta(hours=1)).isoformat())
    gp=folder/'grant.json';gs=write(gp,value)
    v=disabled();v.update(enabled=True,expected_binding=bind,private_config_file=str(folder/'context.json'),private_config_sha256=bind['private_context_sha256'],trust_registry_file=str(reg),trust_registry_sha256=rs,grant_file=str(gp),grant_sha256=gs)
    rp=folder/'worker-registration.json';s=write(rp,v)
    return RegisteredAuthorityWorker(rp,s,clock=lambda:e['clock'][0]),reg


def test_file_bound_worker_delegates_two_candidate_cycles(private):
    e,folder,config=private;worker,_=setup_worker(private)
    with patch.object(port,'require_live_clearance',return_value=None),patch.object(port.HttpTransport,'check',return_value=None),\
         patch.object(port.HttpTransport,'send',side_effect=lambda aid,wire:e['send'](aid,wire)),\
         patch.object(LiveProviders,'account',side_effect=lambda:base.account(e)),\
         patch.object(LiveProviders,'entry_market',side_effect=lambda:base.market(e)),\
         patch.object(pc,'capture_owned',side_effect=lambda *args:base.market(e)),\
         patch.object(base,'poll',side_effect=lambda e,**kw:worker.poll(e['source'],e['path'])):
        base.finish(e);base.resume_and_signal(e);base.poll(e);base.poll(e);base.finish(e)
    assert base.read_state(e)['completed_cycles']==2 and e['send'].call_count==4


def test_rotated_root_blocks_cached_worker_without_resend(private):
    e,folder,config=private;worker,registry=setup_worker(private)
    with patch.object(port,'require_live_clearance',return_value=None),patch.object(port.HttpTransport,'check',return_value=None),\
         patch.object(port.HttpTransport,'send',side_effect=lambda aid,wire:e['send'](aid,wire)),\
         patch.object(LiveProviders,'entry_market',side_effect=lambda:base.market(e)):
        assert worker.poll(e['source'],e['path'])['phase']=='ENTRY_REVIEW'
        count=e['send'].call_count;key=Path(json.loads(registry.read_text())['key_file']);key.write_bytes(b'T'*32)
        with pytest.raises(ValueError,match='HASH_CHANGED'):worker.poll(e['source'],e['path'])
    assert e['send'].call_count==count and e['store'].control()['mode']=='PAUSED'


def test_startup_recovery_pauses_without_context():
    state=dict(mode='ARMED',version=1,session_date='2026-11-02');calls=[]
    def command(action,**kw):calls.append(action);state['mode']='PAUSED'
    service=SimpleNamespace(store=SimpleNamespace(control=lambda:dict(state),stop_state=lambda:{'pending':False}),command=command)
    ensure_paused(service);ensure_paused(service)
    assert calls==['pause'] and state['mode']=='PAUSED'


def test_missing_adapter_is_not_created(private):
    e,folder,config=private;missing=folder/'missing.sqlite';changed=dict(config,adapter_db=str(missing));write(folder/'context.json',changed)
    worker,_=setup_worker(private)
    with patch.object(port,'require_live_clearance',return_value=None),patch.object(port,'Store',side_effect=AssertionError('No implicit Store creation')):
        with pytest.raises(ValueError,match='EXISTING_ADAPTER_DATABASE'):worker.poll(e['source'],e['path'])
    assert not missing.exists() and e['send'].call_count==0
