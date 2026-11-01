from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

import fixture_cycle_api as api
from fixture_cycle_journal import FixtureCycleJournalConsumer, CURSOR
from test_reusable_fixture_cycle import (
    synthetic_scope, env, bound_env, module, prepared, lifecycle,
    closed, history, reentry, second, ready, position, completed,
    third, third_ready, third_position, third_completed, cycle_base,
    prepare_next, current_capture, market_capture, resign, BULL, BEAR,
)
from test_hilega_application_preparation_v1 import append
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_production_simulator_bridge_v1 import verified_records, accepted


def create_consumer(h):
    setup = h.state['setup']
    return FixtureCycleJournalConsumer(
        setup['e']['store'], setup['execution'], PIN, adapter_module=h.state['mod'],
        journal=setup['e']['path'], preparation_provider=h.preparation,
        entry_capture_provider=h.entry, exit_capture_provider=h.exit,
        closeout_capture_provider=h.closeout, clock=lambda: h.now,
        checkpoint=lambda stage: h.checkpoint(stage))


def fresh_final_capture(h):
    row = (deepcopy(h.filled_snapshot) if h.filled_snapshot is not None
           else current_capture(h.state, h.now))
    row.update(generated_at=h.now.isoformat(), completed_at=h.now.isoformat(),
               session_date=h.now.date().isoformat())
    return resign(row)


@pytest.fixture
def harness(cycle_base):
    h = SimpleNamespace(state=cycle_base, now=cycle_base['at'], case=None,
                        exit_case=None, filled_snapshot=None, checkpoint=lambda stage: None)
    keys = {'account_capture', 'cash_capture', 'market_bundle', 'expected_version',
            'bridge_run_id', 'fee_buffer_paise'}
    h.preparation = Mock(side_effect=lambda event: {
        k: deepcopy(h.case['prepare_args'][k]) for k in keys})
    h.entry = Mock(side_effect=lambda: deepcopy(h.case['captures']))
    h.exit = Mock(side_effect=lambda: dict(account=current_capture(h.state, h.now),
                                          market=market_capture(h.state, h.now)))
    h.closeout = Mock(side_effect=lambda: fresh_final_capture(h))
    h.consumer = create_consumer(h)
    h.baseline = h.consumer.poll()
    return h


def cursor(h):
    with h.state['setup']['e']['store'].db() as db:
        return json.loads(db.execute('SELECT data FROM '+CURSOR+' WHERE id=?',
                                     ('1',)).fetchone()[0])


def queue_entry(h, *, direction='BULLISH'):
    # Reuse only the fixture's evidence/control/journal setup. The consumer,
    # not this helper, performs the actual preparation and BUY.
    def capture_arguments(*args, **kwargs):
        record = verified_records(kwargs['journal'])[kwargs['sequence']-1]
        return dict(request_id=accepted(record)[0]['id'])
    with patch.object(api, 'prepare', side_effect=capture_arguments):
        h.case = prepare_next(h.state, direction=direction)
    h.now = h.case['now']
    h.filled_snapshot = None
    return h.case


def queue_exit(h):
    setup = h.state['setup']
    parent = next(r for r in setup['execution'].requests()
                  if r['request_id'] == h.case['key'])
    h.state['mod'].FixtureTransport(setup['execution']).fill(
        parent['order_id'], parent['draft']['body']['quantity'])
    h.now = h.case['now']+timedelta(minutes=5)
    setup['e']['clock'][0] = h.now
    name = ('STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21'
            if parent['direction'] == 'BULLISH'
            else 'STRUCTURAL_EXIT_BEARISH_RSI_CROSS_ABOVE_WMA21')
    path = setup['e']['path']
    append(path, [name], at=h.now.isoformat())
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    last = rows[-1]
    last['payload']['event_details'][0]['entry_time'] = parent['signal_at']
    last.pop('record_hash')
    last['record_hash'] = hashlib.sha256(json.dumps(
        last, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
        default=str).encode()).hexdigest()
    path.write_text('\n'.join(json.dumps(row) for row in rows)+'\n')
    h.exit_case = dict(now=h.now, sequence=len(rows))


def fill_sell(h):
    setup = h.state['setup']
    request = next(r for r in setup['execution'].requests()
                   if r['reservation_reference'] == h.case['key']
                   and r['draft']['body']['transaction_type'] == 'SELL')
    h.state['mod'].FixtureTransport(setup['execution']).fill(
        request['order_id'], request['draft']['body']['quantity'])
    h.filled_snapshot = current_capture(h.state, h.now)


def finish_state(h):
    h.state['account'] = fresh_final_capture(h)
    h.state['at'] = h.exit_case['now']


def orders(h):
    return h.state['mod'].FixtureTransport(h.state['setup']['execution']).orders()


def test_first_use_baselines_without_replaying_history(harness):
    h = harness
    assert h.baseline['status'] == 'JOURNAL_BASELINED_NO_REPLAY'
    assert h.consumer.poll()['status'] == 'NO_NEW_JOURNAL_RECORDS'
    for provider in (h.preparation, h.entry, h.exit, h.closeout):
        provider.assert_not_called()
    assert len(orders(h)) == 6


def test_journal_drives_two_cycles_with_restart_and_next_entry(harness):
    h = harness
    for index, direction in ((4, 'BULLISH'), (5, 'BEARISH')):
        queue_entry(h, direction=direction)
        assert h.consumer.poll()['status'] == 'ENTRY_ACKNOWLEDGED_CURSOR_ADVANCED'
        queue_exit(h)
        before_exit = cursor(h)['sequence']
        assert h.consumer.poll()['status'] == 'EXIT_FILL_PENDING_CURSOR_HELD'
        assert cursor(h)['sequence'] == before_exit
        fill_sell(h)
        h.consumer = create_consumer(h)
        assert h.consumer.poll()['status'] == 'EXIT_CLOSED_RETIRED_CURSOR_ADVANCED'
        assert cursor(h)['active_entry_id'] is None
        with h.state['setup']['e']['store'].db() as db:
            view = api.history(db, PIN)[0]
        assert view['cycle_count'] == index
        assert len(orders(h)) == 2*index
        finish_state(h)


def test_lost_entry_cursor_recovers_without_capture_or_resend(harness):
    h = harness
    queue_entry(h)
    def interrupt(stage):
        if stage == 'AFTER_ENTRY_RESULT_BEFORE_CURSOR':
            raise RuntimeError('synthetic entry cursor interruption')
    h.checkpoint = interrupt
    with pytest.raises(RuntimeError, match='entry cursor'):
        h.consumer.poll()
    before = cursor(h)['sequence']
    h.checkpoint = lambda stage: None
    h.now += timedelta(hours=2)
    h.preparation.side_effect = AssertionError('No repeated preparation capture')
    h.entry.side_effect = AssertionError('No repeated entry capture')
    h.consumer = create_consumer(h)
    with patch.object(h.state['mod'].FixtureTransport, 'send',
                      side_effect=AssertionError('No duplicate BUY')):
        result = h.consumer.poll()
    assert result['status'] == 'ENTRY_ACKNOWLEDGED_CURSOR_ADVANCED'
    assert result['recovery_only'] is True
    assert cursor(h)['sequence'] == before+1
    assert len(orders(h)) == 7


def test_lost_preparation_progress_uses_committed_admission(harness):
    h = harness
    queue_entry(h)
    def interrupt(stage):
        if stage == 'AFTER_PREPARATION_BEFORE_PROGRESS':
            raise RuntimeError('synthetic preparation progress interruption')
    h.checkpoint = interrupt
    with pytest.raises(RuntimeError, match='preparation progress'):
        h.consumer.poll()
    assert len(orders(h)) == 6
    h.checkpoint = lambda stage: None
    h.preparation.side_effect = AssertionError('No duplicate preparation sweep')
    h.consumer = create_consumer(h)
    assert h.consumer.poll()['status'] == 'ENTRY_ACKNOWLEDGED_CURSOR_ADVANCED'
    assert h.preparation.call_count == 1
    assert len(orders(h)) == 7


def lost_send(h, side):
    original = h.state['mod'].FixtureTransport.send
    def send(transport, attempt_id, wire):
        if wire['method'] == 'POST' and wire['body']['transaction_type'] == side:
            transport.timeout_after = True
        return original(transport, attempt_id, wire)
    return send


def test_unknown_buy_holds_cursor_without_retry(harness):
    h = harness
    queue_entry(h)
    before = cursor(h)['sequence']
    with patch.object(h.state['mod'].FixtureTransport, 'send', new=lost_send(h, 'BUY')):
        assert h.consumer.poll()['status'] == 'ENTRY_UNKNOWN_CURSOR_HELD'
    h.entry.side_effect = AssertionError('No unknown entry recapture')
    h.consumer = create_consumer(h)
    with patch.object(h.state['mod'].FixtureTransport, 'send',
                      side_effect=AssertionError('No unknown BUY retry')):
        assert h.consumer.poll()['status'] == 'ENTRY_UNKNOWN_CURSOR_HELD'
    assert cursor(h)['sequence'] == before
    assert len(orders(h)) == 7


def test_unknown_sell_holds_cursor_and_never_attempts_closeout(harness):
    h = harness
    queue_entry(h)
    h.consumer.poll()
    queue_exit(h)
    before = cursor(h)['sequence']
    with patch.object(h.state['mod'].FixtureTransport, 'send', new=lost_send(h, 'SELL')):
        assert h.consumer.poll()['status'] == 'EXIT_UNKNOWN_CURSOR_HELD'
    h.exit.side_effect = AssertionError('No unknown exit recapture')
    h.closeout.side_effect = AssertionError('No closeout for unknown exit')
    h.consumer = create_consumer(h)
    with patch.object(h.state['mod'].FixtureTransport, 'send',
                      side_effect=AssertionError('No unknown SELL retry')):
        assert h.consumer.poll()['status'] == 'EXIT_UNKNOWN_CURSOR_HELD'
    assert cursor(h)['sequence'] == before
    assert len(orders(h)) == 8
    h.closeout.assert_not_called()


@pytest.mark.parametrize('stage', [
    'AFTER_CLOSEOUT_BEFORE_RETIREMENT', 'AFTER_RETIREMENT_BEFORE_CURSOR',
])
def test_exit_closeout_and_retirement_restart_without_resend(harness, stage):
    h = harness
    queue_entry(h)
    h.consumer.poll()
    queue_exit(h)
    h.consumer.poll()
    fill_sell(h)
    def interrupt(current):
        if current == stage:
            raise RuntimeError('synthetic durable exit interruption')
    h.checkpoint = interrupt
    with pytest.raises(RuntimeError, match='durable exit'):
        h.consumer.poll()
    h.checkpoint = lambda stage: None
    h.exit.side_effect = AssertionError('No repeated exit quote sweep')
    if stage == 'AFTER_RETIREMENT_BEFORE_CURSOR':
        h.now += timedelta(hours=2)
        h.closeout.side_effect = AssertionError('No capture for committed retirement')
    else:
        h.now += timedelta(seconds=5)
    h.consumer = create_consumer(h)
    with patch.object(h.state['mod'].FixtureTransport, 'send',
                      side_effect=AssertionError('No repeated SELL')):
        result = h.consumer.poll()
    assert result['status'] in {
        'EXIT_CLOSED_RETIRED_CURSOR_ADVANCED', 'EXIT_RETIRED_CURSOR_RECOVERED'}
    assert cursor(h)['active_entry_id'] is None
    assert len(orders(h)) == 8


def test_concurrent_pollers_submit_entry_once(harness):
    h = harness
    queue_entry(h)
    consumers = [create_consumer(h), create_consumer(h)]
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = [future.result(timeout=30) for future in
                   [workers.submit(c.poll) for c in consumers]]
    assert sorted(r['status'] for r in results) == sorted([
        'ENTRY_ACKNOWLEDGED_CURSOR_ADVANCED', 'NO_NEW_JOURNAL_RECORDS'])
    assert h.preparation.call_count == h.entry.call_count == 1
    assert len(orders(h)) == 7


def test_tampered_cursor_blocks_before_capture(harness):
    h = harness
    row = cursor(h)
    with h.state['setup']['e']['store'].db() as db:
        row['sequence'] -= 1
        db.execute('UPDATE '+CURSOR+' SET data=? WHERE id=?', (json.dumps(row), '1'))
    with pytest.raises(ValueError, match='CONSUMER_RECORD_SIGNATURE_INVALID'):
        h.consumer.poll()
    h.preparation.assert_not_called()


def test_truncated_journal_blocks_without_advancing(harness):
    h = harness
    path = h.state['setup']['e']['path']
    lines = path.read_text().splitlines()
    path.write_text('\n'.join(lines[:-1])+'\n')
    with pytest.raises(ValueError, match='CONSUMER_JOURNAL_PREFIX_CHANGED'):
        h.consumer.poll()
    h.preparation.assert_not_called()


def test_missing_cursor_cannot_silently_rebaseline(harness):
    h = harness
    with h.state['setup']['e']['store'].db() as db:
        db.execute('DELETE FROM '+CURSOR)
    with pytest.raises(ValueError, match='CONSUMER_CURSOR_MISSING_NO_REBASELINE'):
        h.consumer.poll()


def test_informational_record_advances_without_capture(harness):
    h = harness
    append(h.state['setup']['e']['path'], [], at=(h.now+timedelta(minutes=5)).isoformat())
    assert h.consumer.poll()['status'] == 'NO_CONFIRMED_EVENT_CURSOR_ADVANCED'
    h.preparation.assert_not_called()
    h.entry.assert_not_called()


def test_multi_event_reversal_holds_for_explicit_policy(harness):
    h = harness
    append(h.state['setup']['e']['path'],
           [BEAR, 'STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21'],
           at=(h.now+timedelta(minutes=5)).isoformat())
    with pytest.raises(ValueError, match='MULTI_EVENT_RECORD_REQUIRES_EXPLICIT_POLICY'):
        h.consumer.poll()
    h.preparation.assert_not_called()
    assert len(orders(h)) == 6


def test_paused_entry_blocks_before_capture(harness):
    h = harness
    queue_entry(h)
    with h.state['setup']['e']['store'].db() as db:
        control = json.loads(db.execute('SELECT data FROM control WHERE id=1').fetchone()[0])
        control['mode'] = 'PAUSED'
        db.execute('UPDATE control SET data=? WHERE id=1', (json.dumps(control),))
    with pytest.raises(ValueError, match='CONSUMER_ENTRY_CONTROL_NOT_ARMED'):
        h.consumer.poll()
    h.preparation.assert_not_called()
    assert len(orders(h)) == 6


def test_live_consumer_rejected_before_files():
    consumer = FixtureCycleJournalConsumer(
        None, None, dict(PIN, scope='UPSTOX:'+'a'*64), adapter_module=None,
        journal='/must-not-open', preparation_provider=Mock(), entry_capture_provider=Mock(),
        exit_capture_provider=Mock(), closeout_capture_provider=Mock(), clock=Mock())
    with pytest.raises(ValueError, match='FIXTURE_JOURNAL_CONSUMER_ONLY'):
        consumer.poll()
