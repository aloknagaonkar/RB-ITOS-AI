from copy import deepcopy
from datetime import timedelta
import hashlib
import json
from unittest.mock import patch

import pytest

from fixture_cycle_journal_v2 import FixtureCycleJournalConsumerV2, DEFERRED
from fixture_cycle_exit_v2 import execute_cycle_exit_v2, record_cycle_closeout_v2
from fixture_cycle_journal import PROGRESS
from fixture_cycle_history import CLOSEOUTS
from test_fixture_cycle_journal import (
    synthetic_scope, env, bound_env, module, prepared, lifecycle,
    closed, history, reentry, second, ready, position, completed,
    third, third_ready, third_position, third_completed, cycle_base,
    harness as harness_v1, queue_entry, queue_exit, fill_sell, finish_state,
    cursor, orders, lost_send, fresh_final_capture, resign, BULL, BEAR,
)
from test_hilega_application_preparation_v1 import append
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_production_simulator_bridge_v1 import verified_records, accepted


def create_v2(h):
    setup = h.state['setup']
    return FixtureCycleJournalConsumerV2(
        setup['e']['store'], setup['execution'], PIN, adapter_module=h.state['mod'],
        journal=setup['e']['path'], preparation_provider=h.preparation,
        entry_capture_provider=h.entry, exit_capture_provider=h.exit,
        closeout_capture_provider=h.closeout, clock=lambda: h.now,
        checkpoint=lambda stage: h.checkpoint(stage))


@pytest.fixture
def harness_v2(harness_v1):
    h = harness_v1
    def stable_capture():
        row = fresh_final_capture(h)
        if h.case is not None and h.exit_case is not None:
            parent = next(r for r in h.state['setup']['execution'].requests()
                          if r['request_id'] == h.case['key'])
            for trade in row['trades']:
                if trade['order_id'] == parent['order_id']:
                    trade['filled_at'] = h.exit_case['now'].isoformat()
            resign(row)
            if h.filled_snapshot is not None:
                h.filled_snapshot = deepcopy(row)
        return row
    h.closeout.side_effect = stable_capture
    h.consumer = create_v2(h)
    return h


def rewrite_last(path, rows):
    row = rows[-1]
    row.pop('record_hash', None)
    row['record_hash'] = hashlib.sha256(json.dumps(
        row, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
        default=str).encode()).hexdigest()
    path.write_text('\n'.join(json.dumps(r) for r in rows)+'\n')


def queue_reversal(h):
    setup = h.state['setup']
    parent = next(r for r in setup['execution'].requests()
                  if r['request_id'] == h.case['key'])
    h.state['mod'].FixtureTransport(setup['execution']).fill(
        parent['order_id'], parent['draft']['body']['quantity'])
    h.now = h.case['now']+timedelta(minutes=5)
    setup['e']['clock'][0] = h.now
    exit_name = ('STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21'
                 if parent['direction'] == 'BULLISH'
                 else 'STRUCTURAL_EXIT_BEARISH_RSI_CROSS_ABOVE_WMA21')
    entry_name = BEAR if parent['direction'] == 'BULLISH' else BULL
    path = setup['e']['path']
    append(path, [exit_name, entry_name], at=h.now.isoformat())
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    for detail in rows[-1]['payload']['event_details']:
        if detail['event_type'] == exit_name:
            detail['entry_time'] = parent['signal_at']
    rewrite_last(path, rows)
    h.exit_case = dict(now=h.now, sequence=len(rows))
    return next(e for e in accepted(verified_records(path)[-1]) if e['role'] == 'ENTRY')


def sell_request(h):
    return next(r for r in h.state['setup']['execution'].requests()
                if r['reservation_reference'] == h.case['key']
                and r['draft']['body']['transaction_type'] == 'SELL')


def partial_fill(h):
    request = sell_request(h)
    quantity = request['draft']['body']['quantity']
    filled = quantity//2
    h.state['mod'].FixtureTransport(h.state['setup']['execution']).fill(
        request['order_id'], filled)
    return filled, quantity-filled


def test_reversal_closes_first_and_requires_fresh_post_resume_entry(harness_v2):
    h = harness_v2
    queue_entry(h)
    h.consumer.poll()
    old_entry = h.case['key']
    candidate = queue_reversal(h)
    record = verified_records(h.state['setup']['e']['path'])[-1]
    result = h.consumer.poll()
    assert result['status'] == 'EXIT_FILL_PENDING_CURSOR_HELD'
    assert result['opposite_buy_submitted'] is False
    assert len(orders(h)) == 8
    fill_sell(h)
    result = h.consumer.poll()
    assert result['status'] == 'EXIT_CLOSED_RETIRED_CURSOR_ADVANCED'
    assert result['opposite_entry_status'] == 'FRESH_POST_RESUME_CONFIRMATION_REQUIRED'
    assert len(orders(h)) == 8
    with h.state['setup']['e']['store'].db() as db:
        receipt = json.loads(db.execute('SELECT data FROM '+DEFERRED+' WHERE id=?',
                                        (candidate['id'],)).fetchone()[0])
        closure = json.loads(db.execute('SELECT data FROM '+CLOSEOUTS+' WHERE id=?',
                                        (old_entry,)).fetchone()[0])
    assert receipt['entry_event'] == candidate
    assert receipt['record_hash'] == closure['event']['source_record_hash'] == record['record_hash']
    assert receipt['entry_permission'] is False
    assert not any(r['request_id'] == candidate['id'] for r in h.state['setup']['execution'].requests())
    finish_state(h)
    queue_entry(h, direction='BEARISH')
    assert h.case['key'] != candidate['id']
    assert h.consumer.poll()['status'] == 'ENTRY_ACKNOWLEDGED_CURSOR_ADVANCED'
    assert len(orders(h)) == 9


def test_reversal_retirement_cursor_restart_never_buys_opposite(harness_v2):
    h = harness_v2
    queue_entry(h)
    h.consumer.poll()
    candidate = queue_reversal(h)
    h.consumer.poll()
    fill_sell(h)
    def interrupt(stage):
        if stage == 'AFTER_RETIREMENT_BEFORE_CURSOR':
            raise RuntimeError('synthetic reversal cursor interruption')
    h.checkpoint = interrupt
    with pytest.raises(RuntimeError, match='reversal cursor'):
        h.consumer.poll()
    h.checkpoint = lambda stage: None
    h.now += timedelta(hours=2)
    h.exit.side_effect = AssertionError('No repeated exit capture')
    h.closeout.side_effect = AssertionError('No capture after committed retirement')
    h.consumer = create_v2(h)
    with patch.object(h.state['mod'].FixtureTransport, 'send',
                      side_effect=AssertionError('No repeated SELL or opposite BUY')):
        assert h.consumer.poll()['status'] == 'EXIT_RETIRED_CURSOR_RECOVERED'
    assert len(orders(h)) == 8
    assert cursor(h)['active_entry_id'] is None
    with h.state['setup']['e']['store'].db() as db:
        assert db.execute('SELECT COUNT(*) FROM '+DEFERRED+' WHERE id=?',
                          (candidate['id'],)).fetchone()[0] == 1


def test_partial_sell_progress_survives_long_wait_and_restart(harness_v2):
    h = harness_v2
    queue_entry(h)
    h.consumer.poll()
    queue_exit(h)
    h.consumer.poll()
    before = cursor(h)['sequence']
    filled, remaining = partial_fill(h)
    result = h.consumer.poll()
    assert result['status'] == 'EXIT_PARTIAL_PENDING_CURSOR_HELD'
    assert result['exit_filled_quantity'] == filled
    assert result['remaining_quantity'] == result['pending_exit_quantity'] == remaining
    assert cursor(h)['sequence'] == before
    h.now += timedelta(hours=2)
    h.consumer = create_v2(h)
    h.exit.side_effect = AssertionError('No quote recapture for committed SELL')
    with patch.object(h.state['mod'].FixtureTransport, 'send',
                      side_effect=AssertionError('No second SELL while pending')):
        again = h.consumer.poll()
    assert again['remaining_quantity'] == remaining
    assert len(orders(h)) == 8
    fill_sell(h)
    with patch.object(h.state['mod'].FixtureTransport, 'send',
                      side_effect=AssertionError('No new SELL after final fill')):
        result = h.consumer.poll()
    assert result['status'] == 'EXIT_CLOSED_RETIRED_CURSOR_ADVANCED'
    assert cursor(h)['active_entry_id'] is None


def test_reversal_partial_fill_never_opens_opposite_position(harness_v2):
    h = harness_v2
    queue_entry(h)
    h.consumer.poll()
    candidate = queue_reversal(h)
    h.consumer.poll()
    _, remaining = partial_fill(h)
    result = h.consumer.poll()
    assert result['remaining_quantity'] == remaining
    assert result['opposite_entry_status'] == 'WAITING_FOR_EXISTING_POSITION_TO_CLOSE'
    assert len(orders(h)) == 8
    assert not any(r['request_id'] == candidate['id'] for r in h.state['setup']['execution'].requests())


def test_fill_regression_blocks_without_resubmission(harness_v2):
    h = harness_v2
    queue_entry(h)
    h.consumer.poll()
    queue_exit(h)
    h.consumer.poll()
    filled, _ = partial_fill(h)
    h.consumer.poll()
    request = sell_request(h)
    with h.state['setup']['execution'].tx() as db:
        row = json.loads(db.execute('SELECT data FROM fixture_orders WHERE id=?',
                                    (request['order_id'],)).fetchone()[0])
        row['filled'] = filled-1
        db.execute('UPDATE fixture_orders SET data=? WHERE id=?',
                   (json.dumps(row), request['order_id']))
    before = cursor(h)['sequence']
    with pytest.raises(ValueError, match='EXIT_FILL_REGRESSION_REQUIRES_REVIEW'):
        h.consumer.poll()
    assert cursor(h)['sequence'] == before
    assert len(orders(h)) == 8
    event = next(e for e in accepted(verified_records(h.state['setup']['e']['path'])[-1])
                 if e['role'] == 'EXIT')
    with h.state['setup']['e']['store'].db() as db:
        progress = json.loads(db.execute('SELECT data FROM '+PROGRESS+' WHERE id=?',
                                         (event['id'],)).fetchone()[0])
    assert progress['observed_exit_filled_quantity'] == filled


def test_cancelled_partial_exit_requires_residual_review(harness_v2):
    h = harness_v2
    queue_entry(h)
    h.consumer.poll()
    queue_exit(h)
    h.consumer.poll()
    _, remaining = partial_fill(h)
    request = sell_request(h)
    with h.state['setup']['execution'].tx() as db:
        row = json.loads(db.execute('SELECT data FROM fixture_orders WHERE id=?',
                                    (request['order_id'],)).fetchone()[0])
        row['status'] = 'CANCELLED'  # Synthetic externally observed cancellation.
        db.execute('UPDATE fixture_orders SET data=? WHERE id=?',
                   (json.dumps(row), request['order_id']))
    result = h.consumer.poll()
    assert result['status'] == 'EXIT_TERMINAL_RESIDUAL_REVIEW_REQUIRED'
    assert result['remaining_quantity'] == remaining and result['pending_exit_quantity'] == 0
    assert cursor(h)['active_entry_id'] == h.case['key']
    assert len(orders(h)) == 8


def test_unknown_reversal_sell_blocks_opposite_and_retry(harness_v2):
    h = harness_v2
    queue_entry(h)
    h.consumer.poll()
    queue_reversal(h)
    with patch.object(h.state['mod'].FixtureTransport, 'send', new=lost_send(h, 'SELL')):
        result = h.consumer.poll()
    assert result['status'] == 'EXIT_UNKNOWN_CURSOR_HELD'
    assert result['opposite_buy_submitted'] is False
    h.exit.side_effect = AssertionError('No unknown-outcome recapture')
    with patch.object(h.state['mod'].FixtureTransport, 'send',
                      side_effect=AssertionError('No SELL retry or opposite BUY')):
        assert h.consumer.poll()['status'] == 'EXIT_UNKNOWN_CURSOR_HELD'
    assert len(orders(h)) == 8
    h.closeout.assert_not_called()


def test_reversal_wrong_parent_blocks_before_exit_capture(harness_v2):
    h = harness_v2
    queue_entry(h)
    h.consumer.poll()
    queue_reversal(h)
    path = h.state['setup']['e']['path']
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    for detail in rows[-1]['payload']['event_details']:
        if detail['event_type'].startswith('STRUCTURAL_EXIT'):
            detail['entry_time'] = h.now.isoformat()
    rewrite_last(path, rows)
    with pytest.raises(ValueError, match='CONSUMER_EXIT_PARENT_MISMATCH'):
        h.consumer.poll()
    h.exit.assert_not_called()
    assert len(orders(h)) == 7


@pytest.mark.parametrize('operation', ['consumer', 'sell', 'closeout'])
def test_v2_live_scope_rejected_before_files(operation):
    pin = dict(PIN, scope='UPSTOX:'+'a'*64)
    def unavailable():
        raise AssertionError('Provider or clock accessed')
    with pytest.raises(ValueError):
        if operation == 'consumer':
            FixtureCycleJournalConsumerV2(
                None, None, pin, adapter_module=None, journal='/must-not-open',
                preparation_provider=unavailable, entry_capture_provider=unavailable,
                exit_capture_provider=unavailable, closeout_capture_provider=unavailable,
                clock=unavailable).poll()
        else:
            kwargs = dict(entry_id='blocked', journal='/must-not-open', sequence=1,
                          capture_provider=unavailable, clock=unavailable)
            if operation == 'sell':
                execute_cycle_exit_v2(None, None, pin, adapter_module=None, **kwargs)
            else:
                record_cycle_closeout_v2(None, None, pin, **kwargs)
