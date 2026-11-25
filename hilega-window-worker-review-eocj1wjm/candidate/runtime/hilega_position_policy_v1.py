"""Candidate admission guard. All unretired BUY requests occupy slots, including unknown/partial orders."""
import json
from pathlib import Path


def need(ok, reason):
    if not ok: raise ValueError(reason)


def validate_policy(policy):
    need(type(policy) is dict and set(policy)=={'model','max_simultaneous_positions','max_premium_per_entry_cents','daily_loss_cutoff_cents','production_execution_enabled'}, 'EXACT_POSITION_POLICY_REQUIRED')
    need(policy['model']=='HILEGA_POSITION_POLICY_CANDIDATE_V1' and policy['production_execution_enabled'] is False, 'CLOSED_POSITION_POLICY_REQUIRED')
    maximum=policy['max_simultaneous_positions']
    need(type(maximum) is int and 1<=maximum<=5, 'POSITION_LIMIT_BETWEEN_ONE_AND_FIVE_REQUIRED')
    need(policy['max_premium_per_entry_cents'] is None and policy['daily_loss_cutoff_cents'] is None, 'OPTIONAL_MONETARY_LIMITS_NOT_IMPLEMENTED')
    return maximum


def occupied(rows, retired, request_id, maximum):
    need(type(maximum) is int and 1<=maximum<=5, 'VALID_POSITION_LIMIT_REQUIRED')
    active=set();seen=set();target=False
    for key,row in rows:
        need(isinstance(key,str) and key and key not in seen and isinstance(row,dict) and row.get('request_id')==key, 'BROKER_REQUEST_IDENTITY_INVALID')
        seen.add(key)
        body=row.get('draft',{}).get('body',{})
        need(body.get('transaction_type') in {'BUY','SELL'} and type(body.get('quantity')) is int and body['quantity']>0, 'BROKER_REQUEST_SIDE_OR_QUANTITY_INVALID')
        if key==request_id:
            need(body['transaction_type']=='BUY' and key not in retired, 'ACTIVE_ENTRY_REQUEST_REQUIRED');target=True
        if body['transaction_type']=='BUY' and key not in retired: active.add(key)
    need(target, 'POSITION_POLICY_ENTRY_REQUEST_MISSING')
    need(len(active)<=maximum, 'MAX_SIMULTANEOUS_POSITIONS_REACHED')
    return dict(occupied_position_slots=len(active),max_simultaneous_positions=maximum,
        premium_cap_configured=False,daily_loss_cutoff_configured=False,production_execution_enabled=False)


def enforce(db, pin, request_id):
    # History projections must not hide earlier live/pending entry requests.
    raw=getattr(db,'raw',db)
    need(raw.in_transaction, 'POSITION_POLICY_ATTACHED_TRANSACTION_REQUIRED')
    metadata=json.loads(raw.execute('SELECT data FROM broker.meta WHERE id=1').fetchone()[0])
    need(metadata==dict(scope=pin['scope'],mode='LIVE_CLOSED'), 'POSITION_POLICY_ACCOUNT_SCOPE_CHANGED')
    policy=json.loads(Path(__file__).with_name('POSITION-POLICY.json').read_text())
    maximum=validate_policy(policy)
    tables={row[0] for row in raw.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    archives='preparation_candidate_closed_cycle_archives_v1'
    retirements='preparation_candidate_reference_retirements_v1'
    need((archives in tables)==(retirements in tables), 'INCOMPLETE_CYCLE_RETIREMENT_HISTORY')
    retired=set()
    if archives in tables:
        from application_cycle_close_v1 import archive_checked, signed, digest, ACTIVE
        markers={key:json.loads(text) for key,text in raw.execute('SELECT id,data FROM '+retirements)}
        archived={key:json.loads(text) for key,text in raw.execute('SELECT id,data FROM '+archives)}
        need(set(markers)==set(archived), 'UNPAIRED_CYCLE_RETIREMENT_HISTORY')
        for key, archive in archived.items():
            archive_checked(archive,pin);marker=markers[key];signed(marker,pin)
            need(marker.get('model')=='HILEGA_APPLICATION_LOCAL_REFERENCE_RETIREMENT_V1' and marker.get('entry_id')==archive['entry_id']==key
                 and marker.get('archive_fingerprint')==digest(archive) and marker.get('local_references_retired') is True, 'SIGNED_RETIREMENT_BINDING_CHANGED')
            need(not any(raw.execute('SELECT 1 FROM '+table+' WHERE id=?',(key,)).fetchone() for table in ACTIVE), 'RETIRED_ENTRY_HAS_ACTIVE_REFERENCES')
            retired.add(key)
    rows=[(key,json.loads(text)) for key,text in raw.execute('SELECT id,data FROM broker.requests')]
    return occupied(rows,retired,request_id,maximum)
