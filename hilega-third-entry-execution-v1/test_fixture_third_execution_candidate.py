from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import json
from unittest.mock import Mock, patch

import pytest

from fixture_third_execution_candidate import execute_third_fixture
from test_third_entry_preparation_candidate import (
    synthetic_scope, env, bound_env, module, prepared, lifecycle,
    closed, history, reentry, second, ready, position, completed, third,
    run as prepare_third,
)
from third_entry_preparation_candidate import TABLE as ADMISSIONS
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import sign


def build_case(third, module, *, bearish=False):
    result = prepare_third(third, bearish=bearish)
    return dict(
        setup=third['setup'], now=third['now'], mod=module,
        key=result['request_id'], old_requests=deepcopy(third['old_requests']),
        captures=dict(account=deepcopy(third['account']),
                      cash=deepcopy(third['cash']),
                      market=deepcopy(third['market'])))


@pytest.fixture
def third_ready(third, module):
    return build_case(third, module)


def run(case, *, provider=None, clock=None, **kwargs):
    setup = case['setup']
    return execute_third_fixture(
        setup['e']['store'], setup['execution'], PIN,
        adapter_module=case['mod'], request_id=case['key'],
        capture_provider=provider if provider is not None else (
            lambda: deepcopy(case['captures'])),
        clock=clock if clock is not None else (lambda: case['now']), **kwargs)


def counts(case):
    with case['setup']['execution'].tx() as db:
        claims = db.execute(
            'SELECT COUNT(*) FROM fixture_authorization_claims WHERE request_id=?',
            (case['key'],)).fetchone()[0]
        attempts = db.execute(
            'SELECT COUNT(*) FROM attempts WHERE request_id=?',
            (case['key'],)).fetchone()[0]
    return claims, attempts


def current_request(case):
    return next(r for r in case['setup']['execution'].requests()
                if r['request_id'] == case['key'])


@pytest.mark.parametrize('bearish', [False, True])
def test_third_buy_submits_once_preserving_two_cycles(third, module, bearish):
    case = build_case(third, module, bearish=bearish)
    before = module.FixtureTransport(case['setup']['execution']).orders()
    result = run(case)
    assert result['status'] == 'THIRD_ENTRY_ATTEMPT_RECORDED'
    assert result['production_execution_enabled'] is False
    assert result['orders_sent_to_upstox'] is False
    assert result['reservation_release_permission'] is False
    assert counts(case) == (1, 1)
    saved = case['setup']['execution'].requests()
    assert all(row in saved for row in case['old_requests'])
    assert len(saved) == 5
    current = current_request(case)
    assert current['state'] == 'ACKNOWLEDGED_NOT_FILLED'
    assert current['direction'] == ('BEARISH' if bearish else 'BULLISH')
    orders = module.FixtureTransport(case['setup']['execution']).orders()
    assert len(orders) == 5
    assert all(row in orders for row in before)
    assert sum(o['order_id'] == current['order_id'] for o in orders) == 1


def test_third_buy_delayed_recovery_never_captures_or_sends(third_ready):
    run(third_ready)
    provider = Mock(side_effect=AssertionError('No recovery capture'))
    with patch.object(third_ready['mod'].FixtureTransport, 'send',
                      side_effect=AssertionError('No repeated BUY')):
        result = run(third_ready, provider=provider,
                     clock=lambda: third_ready['now']+timedelta(hours=2))
    assert result['status'] == 'EXISTING_THIRD_ENTRY_RECOVERED_NO_SUBMISSION'
    assert result['recovery_only'] is True
    assert result['new_attempt_created'] is False
    assert counts(third_ready) == (1, 1)
    provider.assert_not_called()


def test_third_buy_exact_authorization_expiry_blocks(third_ready):
    now = third_ready['now']
    times = iter([now, now+timedelta(seconds=10)])
    with pytest.raises(ValueError, match='EXPIRED'):
        run(third_ready, clock=lambda: next(times))
    assert counts(third_ready) == (0, 0)
    assert current_request(third_ready)['state'] == 'PREPARED'


def test_third_buy_claim_interruption_rolls_back(third_ready):
    def interrupt(stage):
        if stage == 'AFTER_THIRD_AUTHORIZATION_CLAIM':
            raise RuntimeError('synthetic third claim interruption')
    with pytest.raises(RuntimeError, match='synthetic third claim'):
        run(third_ready, checkpoint=interrupt)
    assert counts(third_ready) == (0, 0)
    assert len(third_ready['mod'].FixtureTransport(
        third_ready['setup']['execution']).orders()) == 4
    assert current_request(third_ready)['state'] == 'PREPARED'


def test_third_buy_rechecks_current_cash(third_ready):
    captures = deepcopy(third_ready['captures'])
    cash = captures['cash']
    for key in ('funds_before', 'funds_after'):
        cash[key]['cash_available_to_trade'] = '1'
    cash.pop('signature')
    cash['signature'] = sign(cash, PIN)
    with pytest.raises(ValueError, match='CURRENT_REPEAT_CASH_BLOCKED'):
        run(third_ready, provider=lambda: captures)
    assert counts(third_ready) == (0, 0)


def test_third_buy_lost_response_stays_unknown_without_retry(third_ready):
    result = run(third_ready, timeout_after=True)
    assert result['adapter_result']['state'] == 'UNKNOWN'
    provider = Mock(side_effect=AssertionError('No uncertain retry capture'))
    with patch.object(third_ready['mod'].FixtureTransport, 'send',
                      side_effect=AssertionError('No uncertain retry send')):
        recovered = run(third_ready, provider=provider,
                        clock=lambda: third_ready['now']+timedelta(hours=2))
    assert recovered['recovery_only'] is True
    assert counts(third_ready) == (1, 1)
    provider.assert_not_called()
    assert current_request(third_ready)['state'] == 'UNKNOWN'
    assert len(third_ready['mod'].FixtureTransport(
        third_ready['setup']['execution']).orders()) == 5
    with third_ready['setup']['e']['store'].db() as db:
        hold = json.loads(db.execute(
            'SELECT data FROM preparation_cash_reservations WHERE id=?',
            (third_ready['key'],)).fetchone()[0])
        assert hold['held_cents'] > 0


def test_third_buy_tampered_admission_blocks(third_ready):
    with third_ready['setup']['e']['store'].db() as db:
        row = json.loads(db.execute(
            'SELECT data FROM '+ADMISSIONS+' WHERE id=?',
            (third_ready['key'],)).fetchone()[0])
        row['production_execution_enabled'] = True
        db.execute('UPDATE '+ADMISSIONS+' SET data=? WHERE id=?',
                   (json.dumps(row), third_ready['key']))
    with pytest.raises(ValueError, match='REPEAT_PREPARATION_SIGNATURE_INVALID'):
        run(third_ready)
    assert counts(third_ready) == (0, 0)


def test_concurrent_third_buy_callers_record_once(third_ready):
    provider = Mock(side_effect=lambda: deepcopy(third_ready['captures']))
    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(run, third_ready, provider=provider)
                   for _ in range(2)]
        results = [future.result(timeout=30) for future in futures]
    assert counts(third_ready) == (1, 1)
    assert provider.call_count == 1
    assert sorted(r['recovery_only'] for r in results) == [False, True]
    assert len(third_ready['mod'].FixtureTransport(
        third_ready['setup']['execution']).orders()) == 5


def test_third_live_scope_rejected_before_files():
    def unavailable():
        raise AssertionError('Capture or clock accessed')
    with pytest.raises(ValueError, match='FIXTURE_THIRD_EXECUTION_ONLY'):
        execute_third_fixture(
            None, None, dict(PIN, scope='UPSTOX:'+'a'*64),
            adapter_module=None, request_id='blocked',
            capture_provider=unavailable, clock=unavailable)
