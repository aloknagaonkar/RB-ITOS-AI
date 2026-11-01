"""Read-only projection of committed application preparation, never authority."""
import hashlib
import json


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                         ensure_ascii=False, default=str).encode()).hexdigest()


def inspect_committed(db):
    """Caller owns snapshot/transaction. SELECT only; no callbacks or transport."""
    need(db.in_transaction, 'CALLER_SNAPSHOT_REQUIRED')
    tables = {row[0] for row in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    required = {'preparation_plans', 'preparation_shadow_holds',
                'preparation_outbox', 'preparation_source', 'preparation_consumed'}
    need(required <= tables, 'APPLICATION_PREPARATION_SCHEMA_REQUIRED')
    def rows(table):
        result = {}
        for key, raw in db.execute('SELECT id,data FROM '+table):
            need(key not in result, 'DUPLICATE_APPLICATION_REFERENCE')
            result[key] = json.loads(raw)
        return result
    plans, holds, outbox = [rows(t) for t in (
        'preparation_plans', 'preparation_shadow_holds', 'preparation_outbox')]
    need(set(plans) == set(holds) == set(outbox), 'APPLICATION_REFERENCE_SET_MISMATCH')
    cursor_row = db.execute('SELECT data FROM preparation_source WHERE id=1').fetchone()
    need(cursor_row is not None, 'APPLICATION_CURSOR_REQUIRED')
    cursor = json.loads(cursor_row[0])
    references = []
    for key, plan in sorted(plans.items()):
        hold, out = holds[key], outbox[key]
        need(plan['id'] == hold['id'] == out['id'] == out['reservation_reference'] == key,
             'APPLICATION_REFERENCE_ID_MISMATCH')
        need(all(row.get(flag) is False for row in (plan, hold, out) for flag in (
            'orders_sent', 'production_execution_enabled', 'entry_permission',
            'reservation_release_permission')), 'APPLICATION_AUTHORITY_CHANGED')
        need(plan['status'] == 'EVIDENCE_LINKED_UNSENT'
             and out['status'] == 'NON_EXECUTABLE_PRICING_POLICY_PENDING'
             and out.get('request_body') is None
             and hold.get('real_cash_reserved') is False,
             'DISABLED_APPLICATION_CONTRACT_REQUIRED')
        need(type(hold['held_cents']) is int and hold['held_cents'] > 0,
             'APPLICATION_HOLD_INVALID')
        need(plan['instrument'] == out['instrument']
             and type(plan['quantity']) is int and plan['quantity'] > 0
             and plan['quantity'] == out['quantity'], 'APPLICATION_CONTRACT_MISMATCH')
        need(out['bundle_fingerprint'] == plan['evidence']['bundle_fingerprint'],
             'APPLICATION_EVIDENCE_LINK_MISMATCH')
        need(type(plan['source_sequence']) is int and plan['source_sequence'] > 0
             and plan['source_sequence'] <= cursor['sequence'], 'APPLICATION_CURSOR_BEHIND_PLAN')
        if plan['source_sequence'] == cursor['sequence']:
            need(plan['source_record_hash'] == cursor['hash'], 'APPLICATION_CURSOR_HASH_MISMATCH')
        # Consumption fingerprints have additional strategy fields: presence only
        # here; this observer does not authenticate the underlying journal.
        need(db.execute('SELECT 1 FROM preparation_consumed WHERE id=?', (key,)).fetchone()
             is not None, 'APPLICATION_CONSUMPTION_REFERENCE_REQUIRED')
        references.append(dict(signal_id=key, source_sequence=plan['source_sequence'],
            source_record_hash=plan['source_record_hash'], plan_fingerprint=sha(plan),
            hold_fingerprint=sha(hold), outbox_fingerprint=sha(out),
            binding_verification='NOT_ASSESSED', current_freshness_verified=False))
    exit_count = 0
    if 'preparation_exit_dispatch' in tables:
        for raw, in db.execute('SELECT data FROM preparation_exit_dispatch'):
            row = json.loads(raw)
            need(row.get('dispatch_status') == 'REFUSED_CLOSED'
                 and row.get('automatic_execution_eligible') is False
                 and row.get('production_execution_enabled') is False,
                 'CLOSED_EXIT_CONTRACT_CHANGED')
            exit_count += 1
    return dict(model='HILEGA_CLOSED_HANDOFF_OBSERVATION_V1',
        status='APPLICATION_REFERENCES_OBSERVED_EXECUTION_CLOSED',
        references=references, closed_exit_record_count=exit_count,
        observation_fingerprint=sha(dict(references=references, closed_exits=exit_count)),
        journal_authenticity_verified=False, fixture_admission_created=False,
        existing_preparation_adopted=False, automatic_execution_eligible=False,
        orders_sent=False, entry_permission=False, reservation_release_permission=False,
        production_execution_enabled=False)
