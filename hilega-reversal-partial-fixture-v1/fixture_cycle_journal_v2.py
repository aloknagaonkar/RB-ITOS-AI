"""Fixture exit-first reversals and monotonic partial-exit progress."""
import hashlib
from pathlib import Path

import fixture_cycle_api as api
from fixture_cycle_exit_v2 import (
    execute_cycle_exit_v2, record_cycle_closeout_v2, review_cycle_position,
)
from fixture_cycle_journal import (
    FixtureCycleJournalConsumer, META, CURSOR, PROGRESS,
    need, verified, sealed,
)
from fixture_cycle_execution import ADAPTER_SHA
from fixture_cycle_history import CLOSEOUTS, RETIREMENTS
from fixture_cycle_retirement import authenticated_closeout
from fixture_reference_retirement_candidate import ACTIVE
from market_lab.hilega_preparation_runtime_v1.ownership_state import rollback_database, SourceReader
from market_lab.hilega_preparation_runtime_v1.ownership_checks.risk_evidence_audit import read_connection
from market_lab.hilega_preparation_runtime_v1.ownership_checks.historical_receipt_checks import sha
from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import aware
from market_lab.hilega_production_simulator_bridge_v1 import verified_records, accepted

DEFERRED = 'fixture_cycle_deferred_reversals'


class FixtureCycleJournalConsumerV2(FixtureCycleJournalConsumer):
    def _decorate(self, record, result):
        if len(accepted(record)) == 2:
            complete = result['status'] in {
                'EXIT_CLOSED_RETIRED_CURSOR_ADVANCED', 'EXIT_RETIRED_CURSOR_RECOVERED'}
            result = dict(result, opposite_buy_submitted=False,
                          opposite_entry_status=('FRESH_POST_RESUME_CONFIRMATION_REQUIRED'
                              if complete else 'WAITING_FOR_EXISTING_POSITION_TO_CLOSE'))
        return result

    def _advance(self, cursor, record, progress=None, *, active_id=None, active_event=None):
        events = accepted(record)
        if len(events) != 2:
            return super()._advance(cursor, record, progress,
                                    active_id=active_id, active_event=active_event)
        need(progress is not None and progress['event']['role'] == 'EXIT'
             and active_id is None, 'REVERSAL_EXIT_MUST_COMPLETE_BEFORE_CURSOR')
        candidate = next(e for e in events if e['role'] == 'ENTRY')
        records = verified_records(self.path)
        need(len(records) >= record['sequence']
             and records[record['sequence']-1]['record_hash'] == record['record_hash'],
             'CONSUMER_JOURNAL_CHANGED_BEFORE_CURSOR')
        receipt = self._base(
            model='HILEGA_FIXTURE_DEFERRED_REVERSAL_V1',
            sequence=record['sequence'], record_hash=record['record_hash'],
            entry_event=candidate, closed_entry_id=cursor['active_entry_id'],
            exit_event_id=progress['event']['id'], entry_permission=False,
            opposite_buy_submitted=False, phase='FRESH_POST_RESUME_CONFIRMATION_REQUIRED')
        with self.app.db() as db:
            db.execute('BEGIN IMMEDIATE')
            current = self._read(db, CURSOR, '1')
            self._check_cursor(current)
            need(current['sequence'] == cursor['sequence']
                 and current['record_hash'] == cursor['record_hash'], 'CONSUMER_CURSOR_CHANGED')
            db.execute('CREATE TABLE IF NOT EXISTS '+DEFERRED+'(id TEXT PRIMARY KEY,data TEXT NOT NULL)')
            old = self._read(db, DEFERRED, candidate['id'])
            if old is not None:
                verified(old, self.pin)
                need(sha(old) == sha(sealed(receipt, self.pin)), 'DEFERRED_REVERSAL_CONFLICT')
            else:
                self._write(db, DEFERRED, candidate['id'], receipt)
            self._write(db, PROGRESS, progress['event']['id'], dict(progress, phase='COMPLETED'))
            self._write(db, CURSOR, '1', dict(
                cursor, sequence=record['sequence'], record_hash=record['record_hash'],
                active_entry_id=None, active_entry_event=None))

    def _observe_exit(self, key, event, progress, snapshot):
        at = self.clock()
        with self.app.lock():
            with self.app.db() as app:
                app.execute('BEGIN')
                with self.execution.tx() as broker:
                    source = read_connection(SourceReader(app, broker), self.pin['scope'],
                                             expected_mode='OFFLINE_FIXTURE')
                    report = review_cycle_position(app, source, snapshot, self.pin,
                                                   key, event, at.isoformat())
        previous = progress.get('observed_exit_filled_quantity', 0)
        filled = report['exit_filled_quantity']
        need(type(previous) is int and filled >= previous,
             'EXIT_FILL_REGRESSION_REQUIRES_REVIEW')
        if 'observed_exit_id' in progress:
            need(progress['observed_exit_id'] == report['exit_id'], 'OBSERVED_EXIT_ID_CHANGED')
        updated = dict(progress, observed_exit_id=report['exit_id'],
                       observed_exit_filled_quantity=filled,
                       observed_remaining_quantity=report['remaining_quantity'],
                       observed_pending_quantity=report['pending_exit_quantity'],
                       observed_at=at.isoformat(), observed_snapshot_fingerprint=sha(snapshot))
        with self.app.db() as db:
            updated = self._write(db, PROGRESS, event['id'], updated)
        return report, updated

    def _exit(self, event, cursor, record, progress):
        key, entry = cursor['active_entry_id'], cursor['active_entry_event']
        need(key is not None and entry is not None and event['direction'] == entry['direction']
             and event.get('entry_reference_at') is not None
             and aware(event['entry_reference_at']) == aware(entry['event_at']),
             'CONSUMER_EXIT_PARENT_MISMATCH')
        with self.app.db() as db:
            retired = self._read(db, RETIREMENTS, key)
            closed = self._read(db, CLOSEOUTS, key)
            if retired is not None:
                need(closed is not None, 'CONSUMER_RETIRED_CLOSEOUT_MISSING')
                view = api.history(db, self.pin)[0]
                need(view['entry_id'] == key and closed['event']['id'] == event['id'],
                     'CONSUMER_RETIRED_EVENT_CHANGED')
                need(not any(db.execute('SELECT 1 FROM '+t+' LIMIT 1').fetchone()
                             for t in ACTIVE), 'CONSUMER_RETIRED_REFERENCE_REAPPEARED')
            elif closed is not None:
                authenticated_closeout(closed, self.pin, key)
                need(closed['event']['id'] == event['id'], 'CONSUMER_CLOSEOUT_EVENT_CHANGED')
        if retired is not None:
            self._advance(cursor, record, progress)
            return self._decorate(record, self._result(
                'EXIT_RETIRED_CURSOR_RECOVERED', sequence=record['sequence'],
                entry_id=key, recovery_only=True))
        if closed is None:
            result = execute_cycle_exit_v2(
                self.app, self.execution, self.pin, adapter_module=self.module,
                entry_id=key, journal=self.path, sequence=record['sequence'],
                capture_provider=self.exit_provider, clock=self.clock)
            request = self._request(result['exit_id'])
            if request['state'] in {'UNKNOWN', 'IN_FLIGHT'}:
                self._phase(progress, 'EXIT_OUTCOME_UNKNOWN')
                return self._decorate(record, self._result(
                    'EXIT_UNKNOWN_CURSOR_HELD', sequence=cursor['sequence']))
            progress = self._phase(progress, 'EXIT_ACKNOWLEDGED')
            self.checkpoint('AFTER_EXIT_RESULT_BEFORE_CLOSEOUT')
        snapshot = self.closeout_provider()
        if closed is None:
            report, progress = self._observe_exit(key, event, progress, snapshot)
            remaining, pending = report['remaining_quantity'], report['pending_exit_quantity']
            if remaining or pending or not report['all_orders_terminal']:
                if remaining and pending == 0:
                    status = 'EXIT_TERMINAL_RESIDUAL_REVIEW_REQUIRED'
                elif report['exit_filled_quantity'] > 0:
                    status = 'EXIT_PARTIAL_PENDING_CURSOR_HELD'
                else:
                    status = 'EXIT_FILL_PENDING_CURSOR_HELD'
                self._phase(progress, status)
                return self._decorate(record, self._result(
                    status, sequence=cursor['sequence'], entry_id=key,
                    exit_filled_quantity=report['exit_filled_quantity'],
                    remaining_quantity=remaining, pending_exit_quantity=pending))
            record_cycle_closeout_v2(
                self.app, self.execution, self.pin, entry_id=key,
                journal=self.path, sequence=record['sequence'],
                capture_provider=lambda: snapshot, clock=self.clock)
            self.checkpoint('AFTER_CLOSEOUT_BEFORE_RETIREMENT')
        api.retire(self.app, self.execution.path, snapshot, self.pin, entry_id=key, clock=self.clock)
        self.checkpoint('AFTER_RETIREMENT_BEFORE_CURSOR')
        self._advance(cursor, record, progress)
        return self._decorate(record, self._result(
            'EXIT_CLOSED_RETIRED_CURSOR_ADVANCED', sequence=record['sequence'], entry_id=key))

    def poll(self):
        need(self.pin['scope'].startswith('FIXTURE:'), 'FIXTURE_JOURNAL_CONSUMER_ONLY')
        need(type(self.execution) is self.module.Store and self.execution.mode == 'OFFLINE_FIXTURE'
             and self.execution.scope == self.pin['scope'], 'EXACT_FIXTURE_CONSUMER_STORE_REQUIRED')
        module_path = Path(self.module.__file__)
        need(module_path.is_file() and not module_path.is_symlink()
             and hashlib.sha256(module_path.read_bytes()).hexdigest() == ADAPTER_SHA,
             'PINNED_FIXTURE_CONSUMER_ADAPTER_REQUIRED')
        self.app_path, broker_path = map(rollback_database, (self.app.path, self.execution.path))
        need(not self.app_path.samefile(broker_path), 'DISTINCT_CONSUMER_DATABASES_REQUIRED')
        journal = Path(self.journal)
        need(journal.is_file() and not journal.is_symlink(), 'REGULAR_CONSUMER_JOURNAL_REQUIRED')
        self.path = str(journal.resolve())
        with self._lock():
            records = verified_records(self.path)
            with self.app.db() as db:
                cursor, meta = self._read(db, CURSOR, '1'), self._read(db, META, '1')
                if cursor is None:
                    need(meta is None, 'CONSUMER_CURSOR_MISSING_NO_REBASELINE')
                    need(not any(db.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)
                    ).fetchone() for t in (META, CURSOR, PROGRESS)),
                        'CONSUMER_STATE_INCOMPLETE_NO_REBASELINE')
                    return self._baseline(db, records)
                self._check_cursor(cursor)
                verified(meta, self.pin)
                need(meta['model'] == 'HILEGA_FIXTURE_CONSUMER_META_V1'
                     and meta['account_scope'] == self.pin['scope'] and meta['journal'] == self.path
                     and meta['production_execution_enabled'] is False,
                     'CONSUMER_META_BINDING_INVALID')
            offset = cursor['sequence']
            need(len(records) >= offset
                 and (offset == 0 or records[offset-1]['record_hash'] == cursor['record_hash']),
                 'CONSUMER_JOURNAL_PREFIX_CHANGED')
            if len(records) == offset:
                return self._result('NO_NEW_JOURNAL_RECORDS', sequence=offset)
            record = records[offset]
            events = accepted(record)
            if not events:
                self._advance(cursor, record, active_id=cursor['active_entry_id'],
                              active_event=cursor['active_entry_event'])
                return self._result('NO_CONFIRMED_EVENT_CURSOR_ADVANCED', sequence=record['sequence'])
            need(len(events) in {1, 2}, 'CONSUMER_EVENT_COUNT_INVALID')
            if len(events) == 2:
                entries = [e for e in events if e['role'] == 'ENTRY']
                exits = [e for e in events if e['role'] == 'EXIT']
                need(len(entries) == len(exits) == 1
                     and entries[0]['direction'] != exits[0]['direction'],
                     'EXACT_OPPOSITE_REVERSAL_REQUIRED')
                event = exits[0]
            else:
                event = events[0]
            need(event['role'] in {'ENTRY', 'EXIT'}, 'CONSUMER_EVENT_ROLE_INVALID')
            progress = self._progress(event, cursor, record)
            return (self._entry(event, cursor, record, progress) if event['role'] == 'ENTRY'
                    else self._exit(event, cursor, record, progress))
