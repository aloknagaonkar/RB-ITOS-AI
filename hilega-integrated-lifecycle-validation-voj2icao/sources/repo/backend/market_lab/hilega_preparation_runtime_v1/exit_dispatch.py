"""Durable closed exit dispatch. No ownership, request or release authority."""
import json
from contextlib import ExitStack

MODEL = 'HILEGA_APPLICATION_CLOSED_EXIT_DISPATCH_V1'
REASON = 'EXIT_OR_REVERSAL_REQUIRES_LIVE_OWNERSHIP'


def dispatch_closed(source, events, cursor, *, fingerprint):
    """Consume a confirmed exit boundary atomically with a non-executable record.

    Called only after the Source verifies the journal and accepted event schema.
    Reversals retain exit-first blocking: their ENTRY is consumed without admission.
    These records are never a queue eligible for automatic execution or replay.
    """
    exits = [e for e in events if e['role'] == 'EXIT']
    if len(exits) != 1 or len(events) not in (1, 2):
        raise ValueError('EXACTLY_ONE_CONFIRMED_EXIT_REQUIRED')
    if len({e['id'] for e in events}) != len(events):
        raise ValueError('DUPLICATE_BOUNDARY_EVENT')
    if any(e['role'] not in {'ENTRY', 'EXIT'} for e in events):
        raise ValueError('EXECUTION_EVENT_ROLE_REQUIRED')
    event = exits[0]
    with ExitStack() as resources, source.s.store.lock(), source.s.store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS preparation_exit_dispatch('
                   'id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,data TEXT NOT NULL)')
        fp = fingerprint(event)
        boundary = sorted((e['id'], fingerprint(e)) for e in events)
        old = db.execute('SELECT fingerprint,data FROM preparation_exit_dispatch '
                         'WHERE id=?', (event['id'],)).fetchone()
        if old is not None:
            saved = json.loads(old[1])
            if (old[0] != fp or saved['event_fingerprint'] != fp
                    or fingerprint(saved['event']) != fp
                    or saved['boundary_fingerprints'] != [list(v) for v in boundary]
                    or saved['model'] != MODEL or saved['dispatch_status'] != 'REFUSED_CLOSED'
                    or saved['production_execution_enabled'] is not False
                    or saved['orders_sent'] is not False):
                raise ValueError('EXIT_DISPATCH_RECORD_CONFLICT')
        else:
            from .ownership_state import closed_exit_context
            context = closed_exit_context(source,db,event,now=source.s.now(),resources=resources)
            row = dict(entry_ownership_context=context,model=MODEL, id=event['id'], event=event,
                event_fingerprint=fp, boundary_fingerprints=boundary, observed_at=source.s.now().isoformat(),
                dispatch_status='REFUSED_CLOSED', reason=REASON,
                reversal_entry_suppressed=any(e['role']=='ENTRY' for e in events),
                executable_request_created=False, automatic_execution_eligible=False,
                strategy_ownership_verified=False, fill_quantity_verified=False,
                exit_quantity=None, parent_request_id=None,
                reservation_release_permission=False, entry_permission=False,
                production_execution_enabled=False, orders_sent=False,
                production_ready=False)
            db.execute('INSERT INTO preparation_exit_dispatch VALUES(?,?,?)',
                       (event['id'], fp, json.dumps(row, sort_keys=True)))
        source.checkpoint('AFTER_CLOSED_EXIT_DISPATCH_INSERT')
        for current in events:
            current_fp = fingerprint(current)
            consumed = db.execute('SELECT fingerprint FROM preparation_consumed '
                                  'WHERE id=?', (current['id'],)).fetchone()
            if consumed is not None and consumed[0] != current_fp:
                raise ValueError('CONFIRMED_EVENT_CONFLICT')
            db.execute('INSERT OR IGNORE INTO preparation_consumed VALUES(?,?)',
                       (current['id'], current_fp))
        source._pause_in_transaction(db)
        if old is None:
            source._audit(db, 'BLOCKED', [REASON])
        source._cursor(db, cursor)
        source.checkpoint('BEFORE_CLOSED_EXIT_DISPATCH_COMMIT')
    return dict(status='EXIT_DISPATCH_REFUSED_CLOSED', idempotent_replay=old is not None,
                production_execution_enabled=False, orders_sent=False,
                reservation_release_permission=False)
