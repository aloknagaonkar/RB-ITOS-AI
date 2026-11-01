"""Durable single-event journal consumer for the reusable fixture cycle API."""
from contextlib import contextmanager
from copy import deepcopy
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import stat

import fixture_cycle_api as api
from fixture_cycle_execution import ADAPTER_SHA
from fixture_cycle_history import ADMISSIONS, CLOSEOUTS, RETIREMENTS
from fixture_cycle_retirement import authenticated_closeout
from fixture_reference_retirement_candidate import ACTIVE
from market_lab.hilega_preparation_runtime_v1.ownership_state import rollback_database
from market_lab.hilega_preparation_runtime_v1.ownership_checks.historical_receipt_checks import _check, sha
from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import sign, aware
from market_lab.hilega_production_simulator_bridge_v1 import verified_records, accepted

META = 'fixture_cycle_consumer_meta'
CURSOR = 'fixture_cycle_consumer_cursor'
PROGRESS = 'fixture_cycle_consumer_progress'


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def sealed(row, pin):
    value = deepcopy(row)
    value.pop('signature', None)
    value['signature'] = sign(value, pin)
    return value


def verified(row, pin):
    need(isinstance(row, dict), 'CONSUMER_SIGNED_RECORD_REQUIRED')
    payload = dict(row)
    signature = payload.pop('signature', None)
    need(isinstance(signature, str)
         and hmac.compare_digest(sign(payload, pin), signature),
         'CONSUMER_RECORD_SIGNATURE_INVALID')
    return row


class FixtureCycleJournalConsumer:
    def __init__(self, application_store, execution_store, pin, *, adapter_module,
                 journal, preparation_provider, entry_capture_provider,
                 exit_capture_provider, closeout_capture_provider, clock,
                 checkpoint=lambda stage: None):
        self.app, self.execution, self.pin = application_store, execution_store, pin
        self.module, self.journal = adapter_module, journal
        self.preparation_provider = preparation_provider
        self.entry_provider, self.exit_provider = entry_capture_provider, exit_capture_provider
        self.closeout_provider, self.clock, self.checkpoint = closeout_capture_provider, clock, checkpoint

    @contextmanager
    def _lock(self):
        # This lock is separate from Store.lock(), which the lifecycle API owns.
        path = Path(str(self.app_path)+'.fixture-cycle-consumer.lock')
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            need(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                 and stat.S_IMODE(info.st_mode) & 0o077 == 0,
                 'PRIVATE_CONSUMER_LOCK_REQUIRED')
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def _read(self, db, table, key):
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                            (table,)).fetchone()
        if not exists:
            return None
        found = db.execute('SELECT data FROM '+table+' WHERE id=?', (key,)).fetchone()
        return json.loads(found[0]) if found else None

    def _write(self, db, table, key, row):
        value = sealed(row, self.pin)
        db.execute('INSERT OR REPLACE INTO '+table+' VALUES(?,?)',
                   (key, json.dumps(value, sort_keys=True)))
        return value

    def _base(self, **kwargs):
        return dict(account_scope=self.pin['scope'], journal=self.path,
                    production_execution_enabled=False, orders_sent_to_upstox=False,
                    reservation_release_permission=False, **kwargs)

    def _result(self, status, **kwargs):
        return dict(status=status, production_execution_enabled=False,
                    orders_sent_to_upstox=False, reservation_release_permission=False, **kwargs)

    def _baseline(self, db, records):
        view = api.history(db, self.pin)[0]
        need(not any(db.execute('SELECT 1 FROM '+table+' LIMIT 1').fetchone()
                     for table in ACTIVE), 'CONSUMER_BASELINE_REQUIRES_NO_ACTIVE_CYCLE')
        control = json.loads(db.execute('SELECT data FROM control WHERE id=1').fetchone()[0])
        need(control['mode'] == 'PAUSED', 'CONSUMER_BASELINE_REQUIRES_PAUSED_CONTROL')
        with self.execution.tx() as broker:
            meta = json.loads(broker.execute('SELECT data FROM meta WHERE id=1').fetchone()[0])
            need(meta == dict(scope=self.pin['scope'], mode='OFFLINE_FIXTURE'),
                 'CONSUMER_BASELINE_ADAPTER_META_CHANGED')
            requests = broker.execute('SELECT id,fingerprint,data FROM requests').fetchall()
            attempts = broker.execute('SELECT id,request_id,operation,data FROM attempts').fetchall()
            receipts = dict(broker.execute('SELECT id,data FROM receipts'))
            orders = [json.loads(raw) for raw, in broker.execute('SELECT data FROM fixture_orders')]
        expected = view['source']
        need({rid: fp for rid, fp, _ in requests}
             == {rid: fp for rid, fp, _ in expected['requests']},
             'CONSUMER_BASELINE_UNATTRIBUTED_REQUEST')
        actual_links = _check('OFFLINE_FIXTURE', requests, attempts, receipts)
        old_links = _check('OFFLINE_FIXTURE', expected['requests'], expected['attempts'], expected['receipts'])
        ordered = lambda links: sorted(links, key=lambda row: row['request_id'])
        need(actual_links['unbound_request_count'] == 0
             and ordered(actual_links['bindings']) == ordered(old_links['bindings'])
             and all(json.loads(raw)['state'] not in {
                 'UNKNOWN', 'IN_FLIGHT', 'CANCEL_IN_FLIGHT', 'CANCEL_OUTCOME_UNKNOWN'}
                 for _, _, raw in requests), 'CONSUMER_BASELINE_UNRESOLVED_HISTORY')
        expected_orders = {o['order_id']: o for o in view['snapshot']['orders']}
        need({o['order_id'] for o in orders} == set(expected_orders)
             and all(all(o[k] == expected_orders[o['order_id']][k] for k in (
                 'instrument', 'product', 'side', 'quantity', 'filled', 'status'))
                 for o in orders), 'CONSUMER_BASELINE_FIXTURE_ORDER_CHANGED')
        meta = self._base(model='HILEGA_FIXTURE_CONSUMER_META_V1',
                          baseline_cycle_count=view['cycle_count'], baseline_history_fingerprint=sha(view))
        cursor = self._base(model='HILEGA_FIXTURE_CONSUMER_CURSOR_V1',
                            sequence=len(records), record_hash=records[-1]['record_hash'] if records else None,
                            active_entry_id=None, active_entry_event=None)
        db.execute('BEGIN IMMEDIATE')
        for table in (META, CURSOR, PROGRESS):
            db.execute('CREATE TABLE IF NOT EXISTS '+table+'(id TEXT PRIMARY KEY,data TEXT NOT NULL)')
        self._write(db, META, '1', meta)
        self._write(db, CURSOR, '1', cursor)
        return self._result('JOURNAL_BASELINED_NO_REPLAY', sequence=len(records))

    def _check_cursor(self, cursor):
        verified(cursor, self.pin)
        need(cursor['model'] == 'HILEGA_FIXTURE_CONSUMER_CURSOR_V1'
             and cursor['account_scope'] == self.pin['scope'] and cursor['journal'] == self.path
             and type(cursor['sequence']) is int and cursor['sequence'] >= 0
             and all(cursor.get(flag) is False for flag in (
                 'production_execution_enabled', 'orders_sent_to_upstox',
                 'reservation_release_permission')),
             'CONSUMER_CURSOR_BINDING_INVALID')
        active, event = cursor['active_entry_id'], cursor['active_entry_event']
        need((active is None and event is None)
             or (isinstance(event, dict) and event['id'] == active and event['role'] == 'ENTRY'),
             'CONSUMER_ACTIVE_ENTRY_CHANGED')

    def _progress(self, event, cursor, record):
        with self.app.db() as db:
            old = self._read(db, PROGRESS, event['id'])
            if old:
                verified(old, self.pin)
                need(old['model'] == 'HILEGA_FIXTURE_CONSUMER_PROGRESS_V1'
                     and old['production_execution_enabled'] is False
                     and old['event_fingerprint'] == sha(event) and old['sequence'] == record['sequence']
                     and old['record_hash'] == record['record_hash'] and old['journal'] == self.path
                     and old['account_scope'] == self.pin['scope'], 'CONSUMER_EVENT_CONFLICT')
                return old
            row = self._base(model='HILEGA_FIXTURE_CONSUMER_PROGRESS_V1',
                             event=event, event_fingerprint=sha(event), sequence=record['sequence'],
                             record_hash=record['record_hash'], phase='PENDING')
            return self._write(db, PROGRESS, event['id'], row)

    def _phase(self, progress, phase):
        with self.app.db() as db:
            return self._write(db, PROGRESS, progress['event']['id'], dict(progress, phase=phase))

    def _advance(self, cursor, record, progress=None, *, active_id=None, active_event=None):
        # Refuse cursor advancement if the journal prefix changed during slow work.
        records = verified_records(self.path)
        need(len(records) >= record['sequence']
             and records[record['sequence']-1]['record_hash'] == record['record_hash'],
             'CONSUMER_JOURNAL_CHANGED_BEFORE_CURSOR')
        with self.app.db() as db:
            db.execute('BEGIN IMMEDIATE')
            current = self._read(db, CURSOR, '1')
            self._check_cursor(current)
            need(current['sequence'] == cursor['sequence']
                 and current['record_hash'] == cursor['record_hash'], 'CONSUMER_CURSOR_CHANGED')
            if progress is not None:
                self._write(db, PROGRESS, progress['event']['id'], dict(progress, phase='COMPLETED'))
            updated = dict(cursor, sequence=record['sequence'], record_hash=record['record_hash'],
                           active_entry_id=active_id, active_entry_event=active_event)
            self._write(db, CURSOR, '1', updated)

    def _request(self, key):
        found = [row for row in self.execution.requests() if row['request_id'] == key]
        need(len(found) == 1, 'CONSUMER_EXACT_REQUEST_REQUIRED')
        return found[0]

    def _entry(self, event, cursor, record, progress):
        need(cursor['active_entry_id'] is None, 'CONSUMER_ACTIVE_CYCLE_BLOCKS_ENTRY')
        with self.app.db() as db:
            prepared = self._read(db, ADMISSIONS, event['id'])
            if prepared is None:
                control = json.loads(db.execute('SELECT data FROM control WHERE id=1').fetchone()[0])
                need(control['mode'] == 'ARMED', 'CONSUMER_ENTRY_CONTROL_NOT_ARMED')
            else:
                verified(prepared, self.pin)
                need(sha(prepared['event']) == sha(event), 'CONSUMER_PREPARED_EVENT_CHANGED')
        if prepared is None:
            supplied = self.preparation_provider(event)
            allowed = {'account_capture', 'cash_capture', 'market_bundle', 'expected_version',
                       'bridge_run_id', 'fee_buffer_paise'}
            need(isinstance(supplied, dict) and set(supplied) == allowed,
                 'CONSUMER_EXACT_PREPARATION_INPUTS_REQUIRED')
            api.prepare(self.app, self.execution.path, self.pin, journal=self.path,
                        sequence=record['sequence'], clock=self.clock, **supplied)
            self.checkpoint('AFTER_PREPARATION_BEFORE_PROGRESS')
        progress = self._phase(progress, 'PREPARED')
        result = api.buy(self.app, self.execution, self.pin, adapter_module=self.module,
                         request_id=event['id'], capture_provider=self.entry_provider, clock=self.clock)
        request = self._request(event['id'])
        if request['state'] in {'UNKNOWN', 'IN_FLIGHT'}:
            self._phase(progress, 'ENTRY_OUTCOME_UNKNOWN')
            return self._result('ENTRY_UNKNOWN_CURSOR_HELD', sequence=cursor['sequence'])
        need(request.get('order_id') is not None, 'CONSUMER_ENTRY_ACK_REQUIRED')
        self.checkpoint('AFTER_ENTRY_RESULT_BEFORE_CURSOR')
        self._advance(cursor, record, progress, active_id=event['id'], active_event=event)
        return self._result('ENTRY_ACKNOWLEDGED_CURSOR_ADVANCED', sequence=record['sequence'],
                            entry_id=event['id'], recovery_only=result['recovery_only'])

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
            return self._result('EXIT_RETIRED_CURSOR_RECOVERED', sequence=record['sequence'],
                                entry_id=key, recovery_only=True)
        if closed is None:
            result = api.sell(self.app, self.execution, self.pin, adapter_module=self.module,
                              entry_id=key, journal=self.path, sequence=record['sequence'],
                              capture_provider=self.exit_provider, clock=self.clock)
            request = self._request(result['exit_id'])
            if request['state'] in {'UNKNOWN', 'IN_FLIGHT'}:
                self._phase(progress, 'EXIT_OUTCOME_UNKNOWN')
                return self._result('EXIT_UNKNOWN_CURSOR_HELD', sequence=cursor['sequence'])
            progress = self._phase(progress, 'EXIT_ACKNOWLEDGED')
            self.checkpoint('AFTER_EXIT_RESULT_BEFORE_CLOSEOUT')
        snapshot = self.closeout_provider()
        if closed is None:
            try:
                api.closeout(self.app, self.execution, self.pin, entry_id=key,
                             journal=self.path, sequence=record['sequence'],
                             capture_provider=lambda: snapshot, clock=self.clock)
            except ValueError as exc:
                if str(exc) != 'REPEAT_POSITION_NOT_TERMINAL_FLAT':
                    raise
                return self._result('EXIT_FILL_PENDING_CURSOR_HELD', sequence=cursor['sequence'])
            self.checkpoint('AFTER_CLOSEOUT_BEFORE_RETIREMENT')
        api.retire(self.app, self.execution.path, snapshot, self.pin, entry_id=key, clock=self.clock)
        self.checkpoint('AFTER_RETIREMENT_BEFORE_CURSOR')
        self._advance(cursor, record, progress)
        return self._result('EXIT_CLOSED_RETIRED_CURSOR_ADVANCED', sequence=record['sequence'], entry_id=key)

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
            need(len(events) == 1, 'MULTI_EVENT_RECORD_REQUIRES_EXPLICIT_POLICY')
            event = events[0]
            need(event['role'] in {'ENTRY', 'EXIT'}, 'CONSUMER_EVENT_ROLE_INVALID')
            progress = self._progress(event, cursor, record)
            return (self._entry(event, cursor, record, progress) if event['role'] == 'ENTRY'
                    else self._exit(event, cursor, record, progress))
