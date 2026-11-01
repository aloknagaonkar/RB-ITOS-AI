"""Reusable fixture-cycle history; no live execution authority."""
import hmac
import json

from third_entry_history_candidate import (
    load_closed_history as load_two_cycles,
    authenticate as authenticate_two_cycles,
)
from closed_history_baseline_candidate import order_identity, trade_identity
from fixture_reference_retirement_candidate import ACTIVE
from market_lab.hilega_preparation_runtime_v1.ownership_checks.bridge import validate_account_rows
from market_lab.hilega_preparation_runtime_v1.ownership_checks.historical_receipt_checks import _check, sha
from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import sign, verify, aware

MODEL = 'HILEGA_FIXTURE_CYCLE_HISTORY_VIEW_V1'
ADMISSIONS = 'fixture_cycle_admissions'
CLOSEOUTS = 'fixture_cycle_closeouts'
RETIREMENTS = 'fixture_cycle_retirements'


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def signed(row, pin, reason):
    payload = dict(row)
    signature = payload.pop('signature', None)
    need(isinstance(signature, str)
         and hmac.compare_digest(sign(payload, pin), signature), reason)


def account_identity(snapshot):
    orders, positions = validate_account_rows(snapshot)
    return (
        {key: order_identity(value) for key, value in orders.items()},
        {(t['order_id'], t['trade_id']): trade_identity(t)
         for t in snapshot['trades']}, positions)


def cycle_delta(previous, closeout):
    source, snapshot = closeout['source'], closeout['snapshot']
    prior_requests = {r[0] for r in previous['source']['requests']}
    prior_orders = {o['order_id'] for o in previous['snapshot']['orders']}
    prior_trades = {(t['order_id'], t['trade_id'])
                    for t in previous['snapshot']['trades']}
    return dict(
        request_fingerprints={rid: fp for rid, fp, raw in source['requests']
                              if rid not in prior_requests},
        order_fingerprints={o['order_id']: sha(o) for o in snapshot['orders']
                            if o['order_id'] not in prior_orders},
        trade_fingerprints=sorted([
            [t['order_id'], t['trade_id'], sha(t)] for t in snapshot['trades']
            if (t['order_id'], t['trade_id']) not in prior_trades]))


def verify_step(previous, step, pin, index):
    closeout, retirement, admission = (step[k] for k in (
        'closeout', 'retirement', 'admission'))
    legacy = index == 3
    prefix = 'THIRD' if legacy else 'CYCLE'
    key = closeout['entry_id']
    for row, reason in (
        (closeout, 'CYCLE_CLOSEOUT_SIGNATURE_INVALID'),
        (retirement, 'CYCLE_RETIREMENT_SIGNATURE_INVALID'),
        (admission, 'CYCLE_ADMISSION_SIGNATURE_INVALID'),
    ):
        signed(row, pin, reason)
        need(row.get('production_execution_enabled') is False,
             'CYCLE_AUTHORITY_CHANGED')
    need(closeout['model'] == 'HILEGA_FIXTURE_'+prefix+'_CLOSEOUT_V1'
         and retirement['model'] == 'HILEGA_FIXTURE_'+prefix+'_RETIREMENT_V1'
         and closeout['account_scope'] == retirement['account_scope'] == pin['scope']
         and retirement['entry_id'] == admission['event']['id'] == key
         and admission['event']['role'] == 'ENTRY'
         and closeout['active_references_retired'] is False
         and closeout['reservation_release_permission'] is False
         and retirement['local_reference_retired'] is True
         and retirement['reservation_release_permission'] is False,
         'CYCLE_CLOSURE_BINDING_INVALID')
    need(retirement['closeout_fingerprint'] == sha(closeout)
         and retirement['history_fingerprints'] == [sha(previous)]
         and admission['closed_history_fingerprints'] == [sha(previous)],
         'CYCLE_PREDECESSOR_CHANGED')
    if not legacy:
        need(admission['model'] == 'HILEGA_FIXTURE_CYCLE_ADMISSION_V1'
             and admission['cycle_index'] == retirement['cycle_index'] == index
             and retirement['predecessor_fingerprint'] == sha(previous)
             and retirement['cycle_delta'] == cycle_delta(previous, closeout),
             'CYCLE_SEAL_SEQUENCE_OR_DELTA_CHANGED')
    source, snapshot = closeout['source'], closeout['snapshot']
    need(source['scope'] == pin['scope'] and source['mode'] == 'OFFLINE_FIXTURE'
         and source['control']['mode'] == 'PAUSED'
         and source['control'].get('production_execution_enabled') is False
         and sha(source) == closeout['source_fingerprint']
         and sha(snapshot) == closeout['snapshot_fingerprint']
         and sha(dict(source=source, snapshot=snapshot, event=closeout['event']))
             == closeout['input_fingerprint'],
         'CYCLE_CLOSURE_EVIDENCE_CHANGED')
    review = closeout['review']
    need(review['remaining_quantity'] == review['pending_exit_quantity'] == 0
         and review['all_orders_terminal'] is True,
         'CYCLE_NOT_TERMINAL_FLAT')
    verify(snapshot, pin, as_of=closeout['assessed_at'])
    verify(retirement['snapshot'], pin, as_of=retirement['assessed_at'])
    need(aware(closeout['assessed_at']) <= aware(retirement['assessed_at']),
         'CYCLE_RETIREMENT_PRECEDES_CLOSEOUT')
    need(sha(retirement['snapshot']) == retirement['snapshot_fingerprint']
         and account_identity(retirement['snapshot']) == account_identity(snapshot),
         'CYCLE_RETIREMENT_CAPTURE_CHANGED')
    for table, category in ACTIVE.items():
        need(set(source[category]) == {key}
             and admission['active_fingerprints'][table]
                 == retirement['retired_reference_fingerprints'][table]
                 == sha(source[category][key]), 'CYCLE_REFERENCE_BINDING_CHANGED')
    need(source['bindings'][key]['model']
         == 'HILEGA_FIXTURE_'+prefix+'_DISABLED_BINDING_V1',
         'CYCLE_BINDING_MODEL_CHANGED')
    prior_orders, prior_trades, prior_positions = account_identity(previous['snapshot'])
    orders, trades, positions = account_identity(snapshot)
    need(all(orders.get(k) == value for k, value in prior_orders.items())
         and all(trades.get(k) == value for k, value in prior_trades.items()),
         'CYCLE_PREVIOUS_ACCOUNT_EVIDENCE_CHANGED')
    need(set(prior_positions) <= set(positions) and not any(positions.values()),
         'CYCLE_ZERO_POSITION_EVIDENCE_REQUIRED')
    event = closeout['event']
    exit_id = sha(['SYNTHETIC_STRATEGY_EXIT', key, event['id']])
    requests = {rid: (fp, json.loads(raw)) for rid, fp, raw in source['requests']}
    old_requests = {rid: fp for rid, fp, raw in previous['source']['requests']}
    need(len(requests) == len(source['requests'])
         and set(requests) == set(old_requests) | {key, exit_id}
         and not ({key, exit_id} & set(old_requests))
         and all(requests[rid][0] == fp for rid, fp in old_requests.items()),
         'CYCLE_REQUEST_HISTORY_CHANGED')
    for rid, (fp, request) in requests.items():
        need(request['request_id'] == rid and sha({k: request[k] for k in (
            'request_id', 'draft', 'signal_id', 'signal_at', 'direction',
            'reservation_reference')}) == fp
             and request['state'] not in {
                 'UNKNOWN', 'IN_FLIGHT', 'CANCEL_IN_FLIGHT', 'CANCEL_OUTCOME_UNKNOWN'},
             'CYCLE_REQUEST_CHANGED_OR_UNKNOWN')
    entry = requests[key][1]
    need(requests[key][0] == admission['request_fingerprint']
         == source['bindings'][key]['request_fingerprint']
         and entry['signal_at'] == admission['event']['event_at']
         and entry['direction'] == admission['event']['direction']
         and event['role'] == 'EXIT' and event['direction'] == entry['direction']
         and aware(event['entry_reference_at']) == aware(entry['signal_at'])
         and aware(previous['snapshot']['completed_at']) < aware(entry['signal_at'])
         <= aware(event['event_at']) <= aware(snapshot['completed_at']),
         'CYCLE_SIGNAL_OR_PARENT_CHANGED')
    old_attempts = {aid: (rid, op, sha(json.loads(raw)['wire']))
                    for aid, rid, op, raw in previous['source']['attempts']}
    attempts = {aid: (rid, op, sha(json.loads(raw)['wire']))
                for aid, rid, op, raw in source['attempts']}
    need(len(attempts) == len(source['attempts'])
         and all(attempts.get(k) == value for k, value in old_attempts.items())
         and len(attempts)-len(old_attempts) == 2
         and all(op == 'PLACE' and rid in {key, exit_id}
                 for aid, (rid, op, _) in attempts.items() if aid not in old_attempts),
         'CYCLE_TRANSPORT_HISTORY_CHANGED')
    for aid, raw in previous['source']['receipts'].items():
        need(aid in source['receipts']
             and sha(json.loads(source['receipts'][aid])) == sha(json.loads(raw)),
             'CYCLE_RECEIPT_HISTORY_CHANGED')
    bindings = _check('OFFLINE_FIXTURE', source['requests'],
                       source['attempts'], source['receipts'])
    links = {link['request_id']: link for link in bindings['bindings']}
    need(bindings['unbound_request_count'] == 0 and key in links and exit_id in links
         and set(orders) == {link['order_id'] for link in links.values()},
         'CYCLE_ORDER_HISTORY_UNATTRIBUTED')
    normalized, _ = validate_account_rows(snapshot)
    need(all(o['status'] == 'FILLED' and o['pending'] == 0
             for o in normalized.values()), 'CYCLE_FULL_FILL_POLICY_REQUIRED')
    for link in links.values():
        order = normalized[link['order_id']]
        need(all(order[k] == link[k] for k in ('instrument', 'product', 'side', 'quantity')),
             'CYCLE_ORDER_LINK_CHANGED')
    buy, sell = normalized[links[key]['order_id']], normalized[links[exit_id]['order_id']]
    need(set(orders)-set(prior_orders)
         == {links[key]['order_id'], links[exit_id]['order_id']}
         and len(set(orders)-set(prior_orders)) == 2
         and aware(buy['placed_at']) >= aware(entry['signal_at'])
         and aware(sell['placed_at']) >= aware(event['event_at']),
         'CYCLE_CANNOT_ADOPT_OLD_ORDER')
    need(buy['side'] == 'BUY' and sell['side'] == 'SELL'
         and buy['instrument'] == sell['instrument']
         and buy['product'] == sell['product']
         and buy['filled'] == sell['filled'] == buy['quantity'] == sell['quantity'],
         'CYCLE_EXIT_QUANTITY_CHANGED')


def build_view(root, steps, pin):
    authenticate_two_cycles(root, pin)
    previous = root
    retired = [root['first_archives'][0]['entry_id'], root['entry_id']]
    for index, step in enumerate(steps, 3):
        verify_step_with_ids(previous, retired, step, pin, index)
        retired.append(step['closeout']['entry_id'])
        last = step['closeout']
        previous = dict(
            model=MODEL, account_scope=pin['scope'], cycle_count=index,
            entry_id=last['entry_id'], assessed_at=last['assessed_at'],
            source=last['source'], snapshot=last['snapshot'],
            source_fingerprint=sha(last['source']), snapshot_fingerprint=sha(last['snapshot']),
            root=root, steps=steps[:index-2], retired_entry_ids=list(retired),
            entry_permission=False, reservation_release_permission=False,
            production_execution_enabled=False)
        previous['signature'] = sign(previous, pin)
    need(bool(steps), 'RETIRED_THIRD_CYCLE_BOOTSTRAP_REQUIRED')
    return previous


def verify_step_with_ids(previous, retired_ids, step, pin, index):
    # Root is the signed legacy two-cycle model and lacks retired_entry_ids.
    # Pass bookkeeping independently, preserving its exact predecessor hash.
    need(step['closeout']['entry_id'] not in retired_ids, 'CYCLE_ID_REUSED')
    verify_step(previous, step, pin, index)


def authenticate(row, pin):
    need(pin['scope'].startswith('FIXTURE:'), 'FIXTURE_CYCLE_HISTORY_ONLY')
    signed(row, pin, 'CYCLE_HISTORY_SIGNATURE_INVALID')
    need(row['model'] == MODEL and row['account_scope'] == pin['scope'],
         'CYCLE_HISTORY_SCOPE_CHANGED')
    rebuilt = build_view(row['root'], row['steps'], pin)
    need(sha(rebuilt) == sha(row), 'CYCLE_HISTORY_VIEW_CHANGED')
    return row


def read_json(db, table, key):
    found = db.execute('SELECT data FROM '+table+' WHERE id=?', (key,)).fetchone()
    need(found is not None, 'CYCLE_CHAIN_RECORD_MISSING')
    return json.loads(found[0])


def load_closed_history(db, pin, *, before_entry_id=None):
    need(pin['scope'].startswith('FIXTURE:'), 'FIXTURE_CYCLE_HISTORY_ONLY')
    roots = load_two_cycles(db, pin)
    need(len(roots) == 1, 'EXACT_TWO_CYCLE_ROOT_REQUIRED')
    third_rows = db.execute('SELECT id,data FROM fixture_third_reference_retirements').fetchall()
    need(len(third_rows) == 1, 'EXACT_THIRD_RETIREMENT_REQUIRED')
    key, raw = third_rows[0]
    steps = [dict(
        closeout=read_json(db, 'fixture_third_position_closeouts', key),
        retirement=json.loads(raw),
        admission=read_json(db, 'fixture_third_entry_admissions', key))]
    exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (RETIREMENTS,)).fetchone()
    rows = db.execute('SELECT id,data FROM '+RETIREMENTS).fetchall() if exists else []
    records = [(key, json.loads(raw)) for key, raw in rows]
    records.sort(key=lambda item: item[1]['cycle_index'])
    for expected, (key, retirement) in enumerate(records, 4):
        need(type(retirement['cycle_index']) is int
             and retirement['cycle_index'] == expected
             and retirement['entry_id'] == key, 'CYCLE_CHAIN_GAP_OR_FORK')
        if key == before_entry_id:
            break
        steps.append(dict(closeout=read_json(db, CLOSEOUTS, key),
                          retirement=retirement, admission=read_json(db, ADMISSIONS, key)))
    return [build_view(roots[0], steps, pin)]


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
        matched_closed_lifecycle_count=sum(a["cycle_count"] for a in archives),
        matched_order_count=len(current_orders),
        matched_trade_count=len(current_trades),
        original_capture_fingerprint=sha(snapshot),
        signed_snapshot_modified=False,
        current_cash_assessed=False,
        entry_permission=False,
        reservation_release_permission=False,
        production_execution_enabled=False,
    )
