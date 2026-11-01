"""Two closed fixture cycles as one cumulative baseline, without rewriting V1."""
import hmac
import json

from closed_history_baseline_candidate import (
    TABLE as FIRST_HISTORY, authenticate as authenticate_first,
    order_identity, trade_identity,
)
from fixture_repeat_retirement_candidate import (
    TABLE as RETIREMENTS, authenticated_closeout,
)
from fixture_repeat_exit_candidate import CLOSEOUTS
from fixture_reference_retirement_candidate import ACTIVE
from market_lab.hilega_preparation_runtime_v1.ownership_checks.historical_receipt_checks import (
    _check, sha,
)
from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import (
    sign, verify, aware,
)
from market_lab.hilega_preparation_runtime_v1.ownership_checks.bridge import validate_account_rows

MODEL = 'HILEGA_FIXTURE_TWO_CYCLE_CUMULATIVE_BASELINE_V1'


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def signed_payload(row, pin, reason):
    payload = dict(row)
    signature = payload.pop('signature', None)
    need(isinstance(signature, str)
         and hmac.compare_digest(sign(payload, pin), signature), reason)
    return payload


def authenticate(row, pin):
    need(pin['scope'].startswith('FIXTURE:'), 'FIXTURE_THIRD_HISTORY_ONLY')
    signed_payload(row, pin, 'THIRD_HISTORY_SIGNATURE_INVALID')
    need(row['model'] == MODEL and row['account_scope'] == pin['scope']
         and all(row[k] is False for k in (
             'entry_permission', 'reservation_release_permission',
             'production_execution_enabled')),
         'THIRD_HISTORY_AUTHORITY_INVALID')
    closeout = authenticated_closeout(row['closeout'], pin, row['entry_id'])
    retirement = row['retirement']
    signed_payload(retirement, pin, 'THIRD_RETIREMENT_SIGNATURE_INVALID')
    archives = [authenticate_first(a, pin) for a in row['first_archives']]
    need(len(archives) == 1, 'EXACT_FIRST_CYCLE_ARCHIVE_REQUIRED')
    first = archives[0]
    need(first['entry_id'] != row['entry_id'], 'DUPLICATE_CYCLE_ID')
    need(retirement['model'] == 'HILEGA_FIXTURE_REPEAT_RETIREMENT_V1'
         and retirement['account_scope'] == pin['scope']
         and retirement['entry_id'] == row['entry_id']
         and retirement['closeout_fingerprint'] == sha(closeout)
         and retirement['history_fingerprints'] == sorted(sha(a) for a in archives)
         and retirement['local_reference_retired'] is True
         and retirement['reservation_release_permission'] is False
         and retirement['production_execution_enabled'] is False,
         'THIRD_RETIREMENT_BINDING_INVALID')
    need(row['source'] == closeout['source']
         and row['snapshot'] == closeout['snapshot']
         and row['assessed_at'] == closeout['assessed_at']
         and sha(row['source']) == row['source_fingerprint']
         and sha(row['snapshot']) == row['snapshot_fingerprint'],
         'THIRD_CUMULATIVE_EVIDENCE_CHANGED')
    source = row['source']
    need(source['mode'] == 'OFFLINE_FIXTURE'
         and source['scope'] == pin['scope'], 'THIRD_HISTORY_SCOPE_CHANGED')
    for table, category in ACTIVE.items():
        need(set(source[category]) == {row['entry_id']}
             and retirement['retired_reference_fingerprints'][table]
                 == sha(source[category][row['entry_id']]),
             'THIRD_RETIRED_REFERENCE_CHANGED')
    proof = row['second_admission']
    signed_payload(proof, pin, 'THIRD_SECOND_ADMISSION_SIGNATURE_INVALID')
    need(proof['event']['id'] == row['entry_id']
         and proof['event']['role'] == 'ENTRY'
         and proof['production_execution_enabled'] is False
         and sorted(proof['closed_history_fingerprints'])
             == sorted(sha(a) for a in archives),
         'THIRD_SECOND_ADMISSION_BINDING_INVALID')
    for table, category in ACTIVE.items():
        need(proof['active_fingerprints'][table]
             == sha(source[category][row['entry_id']]),
             'THIRD_SECOND_REFERENCE_CHANGED')
    verify(row['snapshot'], pin, as_of=row['assessed_at'])
    verify(retirement['snapshot'], pin, as_of=retirement['assessed_at'])
    orders, positions = validate_account_rows(row['snapshot'])
    retired_orders, retired_positions = validate_account_rows(retirement['snapshot'])
    need(sha(retirement['snapshot']) == retirement['snapshot_fingerprint']
         and {k: order_identity(v) for k, v in retired_orders.items()}
             == {k: order_identity(v) for k, v in orders.items()}
         and sorted(map(trade_identity, retirement['snapshot']['trades']))
             == sorted(map(trade_identity, row['snapshot']['trades']))
         and positions == retired_positions and not any(positions.values()),
         'THIRD_RETIREMENT_ACCOUNT_CHANGED')
    historical = _check('OFFLINE_FIXTURE', source['requests'],
                        source['attempts'], source['receipts'])
    need(all(json.loads(raw)['state'] not in {
        'UNKNOWN', 'IN_FLIGHT', 'CANCEL_IN_FLIGHT', 'CANCEL_OUTCOME_UNKNOWN',
    } for _, _, raw in source['requests']), 'THIRD_HISTORY_OUTCOME_UNRESOLVED')
    need(historical['unbound_request_count'] == 0
         and len(historical['bindings']) == 4
         and set(orders) == {b['order_id'] for b in historical['bindings']}
         and all(o['status'] == 'FILLED' and o['pending'] == 0
                 for o in orders.values()),
         'THIRD_HISTORY_REQUIRES_TWO_FULL_CYCLES')
    for link in historical['bindings']:
        order = orders[link['order_id']]
        need(all(order[k] == link[k] for k in (
            'instrument', 'product', 'side', 'quantity')),
            'THIRD_HISTORY_ORDER_BINDING_CHANGED')
    prior_requests = {rid: (fp, raw) for rid, fp, raw in first['source']['requests']}
    current_requests = {rid: (fp, raw) for rid, fp, raw in source['requests']}
    need(len(prior_requests) == 2 and len(current_requests) == 4
         and all(current_requests.get(rid) == value
                 for rid, value in prior_requests.items()),
         'THIRD_FIRST_REQUEST_HISTORY_CHANGED')
    prior_orders, _ = validate_account_rows(first['snapshot'])
    need(all(oid in orders and order_identity(orders[oid]) == order_identity(o)
             for oid, o in prior_orders.items()), 'THIRD_FIRST_ORDER_CHANGED')
    trades = {(t['order_id'], t['trade_id']): trade_identity(t)
              for t in row['snapshot']['trades']}
    need(all(trades.get((t['order_id'], t['trade_id'])) == trade_identity(t)
             for t in first['snapshot']['trades']), 'THIRD_FIRST_TRADE_CHANGED')
    for aid, raw in first['source']['receipts'].items():
        need(aid in source['receipts']
             and sha(json.loads(source['receipts'][aid])) == sha(json.loads(raw)),
             'THIRD_FIRST_RECEIPT_CHANGED')
    return row


def load_closed_history(db, pin):
    need(pin['scope'].startswith('FIXTURE:'), 'FIXTURE_THIRD_HISTORY_ONLY')
    rows = db.execute('SELECT id,data FROM '+RETIREMENTS).fetchall()
    need(len(rows) == 1, 'EXACT_SECOND_RETIREMENT_REQUIRED')
    entry_id, raw = rows[0]
    retirement = json.loads(raw)
    found = db.execute('SELECT data FROM '+CLOSEOUTS+' WHERE id=?',
                       (entry_id,)).fetchone()
    need(found is not None, 'THIRD_SECOND_CLOSEOUT_REQUIRED')
    closeout = json.loads(found[0])
    found = db.execute(
        'SELECT data FROM fixture_repeat_entry_admissions WHERE id=?',
        (entry_id,)).fetchone()
    need(found is not None, 'THIRD_SECOND_ADMISSION_REQUIRED')
    row = dict(
        model=MODEL, account_scope=pin['scope'], entry_id=entry_id,
        assessed_at=closeout['assessed_at'], source=closeout['source'],
        snapshot=closeout['snapshot'],
        source_fingerprint=sha(closeout['source']),
        snapshot_fingerprint=sha(closeout['snapshot']),
        closeout=closeout, retirement=retirement,
        second_admission=json.loads(found[0]),
        first_archives=[json.loads(raw) for raw, in db.execute(
            'SELECT data FROM '+FIRST_HISTORY)],
        entry_permission=False, reservation_release_permission=False,
        production_execution_enabled=False)
    row['signature'] = sign(row, pin)
    return [authenticate(row, pin)]


def review_reentry_history(snapshot, archives, pin, *, as_of):
    need(pin["scope"].startswith("FIXTURE:"), "FIXTURE_HISTORY_ONLY")
    verify(snapshot, pin, as_of=as_of)
    need(snapshot.get("profile_verified_before_and_after") is True
         and snapshot.get("account_position_rows_complete") is True,
         "COMPLETE_PINNED_CAPTURE_REQUIRED")
    current_orders, current_positions = validate_account_rows(snapshot)
    expected_orders, expected_trades, expected_position_keys = {}, {}, set()
    seen_entries = set()
    for archived in archives:
        row = authenticate(archived, pin)
        need(row["entry_id"] not in seen_entries, "DUPLICATE_CLOSED_LIFECYCLE")
        seen_entries.add(row["entry_id"])
        need(aware(row["snapshot"]["completed_at"])
             <= aware(snapshot["generated_at"]),
             "CURRENT_CAPTURE_PRECEDES_CLOSED_HISTORY")
        old_orders, old_positions = validate_account_rows(row["snapshot"])
        expected_position_keys.update(old_positions)
        for oid, order in old_orders.items():
            need(oid not in expected_orders, "ORDER_OWNED_BY_MULTIPLE_ARCHIVES")
            expected_orders[oid] = order_identity(order)
        for trade in row["snapshot"]["trades"]:
            key = trade["order_id"], trade["trade_id"]
            need(key not in expected_trades, "TRADE_OWNED_BY_MULTIPLE_ARCHIVES")
            expected_trades[key] = trade_identity(trade)

    need(set(current_orders) == set(expected_orders),
         "UNATTRIBUTED_OR_MISSING_ACCOUNT_ORDER")
    need(all(order_identity(order) == expected_orders[oid]
             for oid, order in current_orders.items()),
         "CLOSED_ORDER_EVIDENCE_CHANGED")
    current_trades = {
        (t["order_id"], t["trade_id"]): trade_identity(t)
        for t in snapshot["trades"]
    }
    need(current_trades == expected_trades, "CLOSED_TRADE_EVIDENCE_CHANGED")
    need(expected_position_keys <= set(current_positions),
         "MISSING_POSITION_ROW_IS_NOT_FLAT")
    need(not any(current_positions.values()), "ACCOUNT_NOT_FLAT")
    return dict(
        status="CLOSED_HISTORY_ATTRIBUTED_READ_ONLY",
        matched_closed_lifecycle_count=2*len(archives),
        matched_order_count=len(current_orders),
        matched_trade_count=len(current_trades),
        original_capture_fingerprint=sha(snapshot),
        signed_snapshot_modified=False,
        current_cash_assessed=False,
        entry_permission=False,
        reservation_release_permission=False,
        production_execution_enabled=False,
    )
