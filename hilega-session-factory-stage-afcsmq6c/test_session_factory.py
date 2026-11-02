from unittest.mock import Mock,patch
from pathlib import Path
import pytest
import test_closed_application_coordinator_v1 as base
from test_closed_application_coordinator_v1 import env,bound_env,ready,case,flow
from market_lab.hilega_execution_port_v1 import adapter as port
from market_lab.hilega_exclusive_closed_route_v1 import enroll_candidate_route
from market_lab.hilega_execution_session_factory_v1 import ExecutionSessionFactory,worker_poll
from hilega_application_preparation_fixtures import PIN


def context(e,**kwargs):
    value=dict(adapter=e['adapter'],pin=PIN,authority=e['authority'],seed_request_id=e['key'],bridge_run_id='synthetic-lease',
        providers=e['providers'],clock=lambda:e['clock'][0]);value.update(kwargs);return value


@pytest.fixture
def factory_flow(flow):
    e=flow;enroll_candidate_route(base.session(e));loader=Mock(side_effect=lambda:context(e));factory=ExecutionSessionFactory(loader)
    with patch.object(port,'require_live_clearance',return_value=None),patch.object(base,'poll',side_effect=lambda e,**kw:worker_poll(e['source'],e['path'],factory=factory)):
        yield e,factory,loader


def test_real_gate_precedes_context_and_credential_loading():
    loader=Mock(side_effect=AssertionError('No context or private authority load'))
    result=worker_poll(object(),object(),factory=ExecutionSessionFactory(loader))
    assert result['status']=='EXECUTION_SESSION_FACTORY_CLOSED_IN_CODE' and result['factory_context_loaded'] is False
    loader.assert_not_called()


def test_environment_flags_do_not_activate_factory(monkeypatch):
    monkeypatch.setenv('HILEGA_PRODUCTION_EXECUTION_ENABLED','1')
    loader=Mock(side_effect=AssertionError('No activation from environment'))
    assert worker_poll(object(),object(),factory=ExecutionSessionFactory(loader))['production_execution_enabled'] is False
    loader.assert_not_called()


def test_default_worker_path_remains_original_closed_preparation(flow):
    e=flow;result=worker_poll(e['source'],e['path'])
    assert result['status']=='APPLICATION_PREPARATION_SOURCE_PROCESSED' and e['send'].call_count==0


def test_factory_delegates_real_two_cycle_candidate_flow(factory_flow):
    e,factory,loader=factory_flow;base.finish(e);base.resume_and_signal(e);base.poll(e);base.poll(e);base.finish(e)
    assert base.read_state(e)['completed_cycles']==2 and e['send'].call_count==4
    loader.assert_called_once();e['token'].assert_not_called()


def test_factory_requires_explicit_signed_route_enrollment(flow):
    e=flow
    with patch.object(port,'require_live_clearance',return_value=None):
        with pytest.raises(ValueError,match='EXCLUSIVE_SOURCE_ENROLLMENT_REQUIRED'):
            worker_poll(e['source'],e['path'],factory=ExecutionSessionFactory(lambda:context(e)))
    assert e['send'].call_count==0 and base.count(e,base.STATE)==0


def test_changed_journal_cannot_reuse_cached_authority(factory_flow,tmp_path):
    e,factory,loader=factory_flow;base.poll(e);other=tmp_path/'other.jsonl';other.write_text(e['path'].read_text())
    with pytest.raises(ValueError,match='FACTORY_SOURCE_OR_JOURNAL_CHANGED'):worker_poll(e['source'],other,factory=factory)
    assert e['send'].call_count==1


def test_changed_source_lease_is_rejected_before_any_attempt(flow):
    e=flow
    with patch.object(port,'require_live_clearance',return_value=None):
        with pytest.raises(ValueError,match='FACTORY_SOURCE_LEASE_CHANGED'):
            worker_poll(e['source'],e['path'],factory=ExecutionSessionFactory(lambda:context(e,bridge_run_id='other')))
    assert e['send'].call_count==0


def test_unknown_factory_object_is_rejected():
    with pytest.raises(ValueError,match='EXACT_EXECUTION_SESSION_FACTORY_REQUIRED'):worker_poll(object(),object(),factory=object())


def test_restart_recovers_committed_buy_without_capture_or_resend(flow):
    e=flow;enroll_candidate_route(base.session(e))
    first=ExecutionSessionFactory(lambda:context(e,checkpoint=base.interrupt('AFTER_BUY_ACTION_BEFORE_STATE')))
    with patch.object(port,'require_live_clearance',return_value=None):
        with pytest.raises(RuntimeError):worker_poll(e['source'],e['path'],factory=first)
        e['providers']['entry'].side_effect=AssertionError('No replay capture')
        second=ExecutionSessionFactory(lambda:context(e))
        assert worker_poll(e['source'],e['path'],factory=second)['phase']=='ENTRY_REVIEW'
    assert e['send'].call_count==1


def test_malformed_factory_context_creates_no_state(flow):
    e=flow
    with patch.object(port,'require_live_clearance',return_value=None):
        with pytest.raises(ValueError,match='EXACT_FACTORY_CONTEXT_REQUIRED'):
            worker_poll(e['source'],e['path'],factory=ExecutionSessionFactory(lambda:dict(extra=True)))
    assert base.count(e,base.STATE)==0 and e['send'].call_count==0
