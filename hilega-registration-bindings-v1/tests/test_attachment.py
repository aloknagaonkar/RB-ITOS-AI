from datetime import timedelta
import json,os
from pathlib import Path
from unittest.mock import patch
import pytest
import factory_attachment as fa
from authority_contract import digest,canonical
from test_worker_files import setup_worker,write
from test_closed_application_coordinator_v1 import env,bound_env,ready,case,flow
from test_private_context import private,LiveProviders,port,pc,base


@pytest.fixture(autouse=True)
def clean_attachment(monkeypatch):
    for name in ['_WORKER','_REFERENCE','_SOURCE','_JOURNAL']:monkeypatch.setattr(fa,name,None)
    monkeypatch.setattr(fa,'_STARTED',False)
    monkeypatch.delenv('HILEGA_FACTORY_ATTACHMENT_FILE',raising=False);monkeypatch.delenv('HILEGA_FACTORY_ATTACHMENT_SHA256',raising=False)


def attach(private,monkeypatch,**changes):
    e,folder,cfg=private;worker,_=setup_worker(private);reg=json.loads(worker.path.read_text());bind=reg['expected_binding']
    value=dict(model='HILEGA_PINNED_FACTORY_ATTACHMENT_CANDIDATE_V1',release_sha256=bind['release_sha256'],policy_sha256=bind['policy_sha256'],
        application_db=str(e['store'].path.resolve()),journal=str(e['path'].resolve()),bridge_run_id=e['source'].run_id,
        registration_file=str(worker.path),registration_sha256=worker.expected,expected_binding_sha256=digest(canonical(bind)),
        issued_at=e['clock'][0].isoformat(),expires_at=(e['clock'][0]+timedelta(seconds=50)).isoformat(),production_execution_enabled=False)
    value.update(changes);path=folder/'attachment.json';sha=write(path,value)
    monkeypatch.setenv('HILEGA_FACTORY_ATTACHMENT_FILE',str(path));monkeypatch.setenv('HILEGA_FACTORY_ATTACHMENT_SHA256',sha)
    return path,value


def opened(e):
    from contextlib import ExitStack
    stack=ExitStack();stack.enter_context(patch.object(port,'require_live_clearance',return_value=None))
    stack.enter_context(patch.object(port.HttpTransport,'check',return_value=None))
    stack.enter_context(patch.object(port.HttpTransport,'send',side_effect=lambda aid,wire:e['send'](aid,wire)))
    stack.enter_context(patch.object(LiveProviders,'entry_market',side_effect=lambda:base.market(e)))
    return stack


def test_real_gate_before_any_attachment_private_read(flow,monkeypatch):
    monkeypatch.setenv('HILEGA_FACTORY_ATTACHMENT_FILE','/missing/attachment.json');monkeypatch.setenv('HILEGA_FACTORY_ATTACHMENT_SHA256','0'*64)
    with patch('authority_files.private_bytes',side_effect=AssertionError('No private descriptor read')):
        value=fa.attachment_poll(flow['source'],flow['path'])
    assert value['status']=='EXECUTION_SESSION_FACTORY_CLOSED_IN_CODE' and flow['send'].call_count==0


def test_attachment_wrong_release_rejected(private,monkeypatch):
    e,folder,cfg=private;attach(private,monkeypatch,release_sha256='0'*64)
    with opened(e):
        with pytest.raises(ValueError,match='ATTACHMENT_RELEASE_CHANGED'):fa.attachment_poll(e['source'],e['path'])
    assert e['send'].call_count==0 and e['store'].control()['mode']=='PAUSED'


def test_cached_descriptor_expiry_pauses_before_another_send(private,monkeypatch):
    e,folder,cfg=private;attach(private,monkeypatch)
    with opened(e):
        assert fa.attachment_poll(e['source'],e['path'])['phase']=='ENTRY_REVIEW'
        count=e['send'].call_count;e['clock'][0]+=timedelta(seconds=51)
        with pytest.raises(ValueError,match='ATTACHMENT_EXPIRED_OR_FUTURE'):fa.attachment_poll(e['source'],e['path'])
    assert e['send'].call_count==count and e['store'].control()['mode']=='PAUSED'


def test_cached_descriptor_pointer_change_requires_review(private,monkeypatch):
    e,folder,cfg=private;attach(private,monkeypatch)
    with opened(e):
        fa.attachment_poll(e['source'],e['path']);count=e['send'].call_count
        monkeypatch.setenv('HILEGA_FACTORY_ATTACHMENT_SHA256','1'*64)
        with pytest.raises(ValueError,match='ATTACHMENT_POINTER_CHANGED'):fa.attachment_poll(e['source'],e['path'])
    assert e['send'].call_count==count and e['store'].control()['mode']=='PAUSED'


def test_removing_pointer_cannot_fall_back_to_default(private,monkeypatch):
    e,folder,cfg=private;attach(private,monkeypatch)
    with opened(e):
        fa.attachment_poll(e['source'],e['path']);count=e['send'].call_count
        monkeypatch.delenv('HILEGA_FACTORY_ATTACHMENT_FILE');monkeypatch.delenv('HILEGA_FACTORY_ATTACHMENT_SHA256')
        with pytest.raises(ValueError,match='EXACT_ATTACHMENT_POINTER_PAIR'):fa.attachment_poll(e['source'],e['path'])
    assert e['send'].call_count==count and e['store'].control()['mode']=='PAUSED'


def test_descriptor_wrong_lease_rejected_before_factory(private,monkeypatch):
    e,folder,cfg=private;attach(private,monkeypatch,bridge_run_id='unapproved-other-lease')
    with opened(e):
        with pytest.raises(ValueError,match='ATTACHMENT_SOURCE_LEASE_CHANGED'):fa.attachment_poll(e['source'],e['path'])
    assert e['send'].call_count==0 and e['store'].control()['mode']=='PAUSED'
