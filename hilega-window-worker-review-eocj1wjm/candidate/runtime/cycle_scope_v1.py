"""Scoped broker reads plus FULL original signed-account history validation."""
from contextlib import contextmanager
import json
import re
from application_cycle_close_v1 import (
    ARCHIVES, ACTIVE, archive_checked, attribute_history, order_identity, trade_identity,
    transaction, one, need, digest, validate_account_rows, verify, aware, day,
)
from market_lab.hilega_execution_port_v1 import adapter as port


class BrokerScope:
    """SELECT-only projection. INSERT/UPDATE/DELETE always use the real tables."""
    def __init__(self,db,entry_id,history=False):
        need(not isinstance(db,BrokerScope) or db.entry_id==entry_id,'CURRENT_SCOPE_PARENT_CHANGED')
        self.raw=getattr(db,'raw',db);self.entry_id=entry_id;self.history=history
        # The current and historical readers share only this transaction's
        # explicitly registered pending IDs. A new transaction starts empty.
        self._pending_ids=getattr(db,'_pending_ids',set())
    @property
    def in_transaction(self):return self.raw.in_transaction
    def reserve_current_request(self,request_id,*,entry_id):
        need(self.in_transaction and not self.history and entry_id==self.entry_id
             and isinstance(request_id,str) and re.fullmatch(r'[0-9a-f]{64}',request_id) is not None,
             'INVALID_CURRENT_SCOPE_RESERVATION')
        need(self.raw.execute('SELECT 1 FROM broker.requests WHERE id=?',(request_id,)).fetchone() is None
             and self.raw.execute('SELECT 1 FROM broker.candidate_existing_request_claims_v1 WHERE id=?',(request_id,)).fetchone() is None
             and self.raw.execute('SELECT 1 FROM preparation_execution_adoption_candidates_v1 WHERE id=?',(request_id,)).fetchone() is None,
             'CURRENT_SCOPE_RESERVATION_COLLISION')
        self._pending_ids.add(request_id)
    def ids(self):
        rows=self.raw.execute('SELECT id,data FROM broker.requests').fetchall()
        owners={key:json.loads(raw)['reservation_reference'] for key,raw in rows}
        for key in self._pending_ids:
            need(key not in owners or owners[key]==self.entry_id,'PENDING_REQUEST_SCOPE_CHANGED')
            raw=self.raw.execute('SELECT data FROM broker.candidate_existing_request_claims_v1 WHERE id=?',(key,)).fetchone()
            if raw is not None:
                claim=json.loads(raw[0])
                need(claim.get('model')=='HILEGA_APPLICATION_EXIT_ATTEMPT_CANDIDATE_V1'
                     and claim.get('request_id')==key and claim.get('entry_id')==self.entry_id
                     and claim.get('production_execution_enabled') is False
                     and claim.get('live_clearance_granted') is False
                     and claim.get('event',{}).get('role')=='EXIT'
                     and port.sha(['APPLICATION_EXIT_CANDIDATE_V1',self.entry_id,claim['event']['id']])==key,
                     'PENDING_EXIT_CLAIM_SCOPE_CHANGED')
                app=self.raw.execute('SELECT data FROM preparation_execution_adoption_candidates_v1 WHERE id=?',(key,)).fetchone()
                need(app is not None and json.loads(app[0])==claim,'PENDING_EXIT_ADOPTION_CLAIM_CHANGED')
        return sorted({key for key,owner in owners.items() if owner==self.entry_id}|self._pending_ids)
    def execute(self,sql,parameters=()):
        if not sql.lstrip().upper().startswith('SELECT'):return self.raw.execute(sql,parameters)
        ids=self.ids();params=[];op='NOT IN' if self.history else 'IN'
        def replace(match):
            table=match.group(1);marks=','.join('?' for _ in ids) or 'NULL';params.extend(ids)
            if table=='attempts':condition='request_id '+op+' ('+marks+')'
            elif table=='receipts':condition='id '+op+' (SELECT id FROM broker.attempts WHERE request_id IN ('+marks+'))'
            else:condition='id '+op+' ('+marks+')'
            return 'FROM (SELECT * FROM broker.'+table+' WHERE '+condition+')'
        rewritten=re.sub(r'\bFROM\s+broker\.(requests|attempts|receipts|candidate_existing_request_claims_v1)\b',replace,sql,flags=re.I)
        return self.raw.execute(rewritten,tuple(params)+tuple(parameters))


@contextmanager
def cycle_transaction(app,path,entry_id):
    with transaction(app,path) as db:yield BrokerScope(db,entry_id)


def archives(db,pin):
    raw=getattr(db,'raw',db)
    values=[]
    for key,text in raw.execute('SELECT id,data FROM '+ARCHIVES):
        row=archive_checked(json.loads(text),pin)
        need(row['entry_id']==key,'ARCHIVE_ENTRY_BINDING_CHANGED');values.append(row)
    need(values,'CLOSED_HISTORY_REQUIRED');return values


def current_ids(db):
    need(isinstance(db,BrokerScope) and not db.history,'CURRENT_CYCLE_SCOPE_REQUIRED')
    return set(db.ids())


def verify_lifecycle_capture(db,snapshot,pin,now):
    # Never rewrite/re-sign/filter the original signed envelope before verifying.
    verify(snapshot,pin,as_of=now.isoformat())
    orders,positions=validate_account_rows(snapshot)
    history_orders={};history_trades={};old_position_keys=set();expected_broker={
        'requests':{},'attempts':{},'receipts':{},'candidate_existing_request_claims_v1':{}}
    for archive in archives(db,pin):
        closed=archive['closeout'];source=closed['source']['broker']
        owned_ids={json.loads(row[2])['order_id'] for row in source['requests']}
        old_orders,old_positions=validate_account_rows(closed['snapshot']);old_position_keys.update(old_positions)
        need(aware(closed['snapshot']['completed_at'])<=aware(snapshot['generated_at']),
             'CAPTURE_PRECEDES_CLOSED_HISTORY')
        for oid in owned_ids:
            need(oid in old_orders and oid not in history_orders,'HISTORICAL_ORDER_OWNERSHIP_CONFLICT')
            history_orders[oid]=order_identity(old_orders[oid])
        for trade in closed['snapshot']['trades']:
            if trade['order_id'] in owned_ids:
                key=(trade['order_id'],trade['trade_id']);need(key not in history_trades,'HISTORICAL_TRADE_OWNERSHIP_CONFLICT')
                history_trades[key]=trade_identity(trade)
        for table,expected in expected_broker.items():
            for row in source[table]:
                need(row[0] not in expected,'HISTORICAL_BROKER_OWNERSHIP_CONFLICT');expected[row[0]]=row
    history=BrokerScope(db,db.entry_id,history=True)
    fields={'requests':'id,fingerprint,data','attempts':'id,request_id,operation,data',
            'receipts':'id,data','candidate_existing_request_claims_v1':'id,data'}
    for table,expected in expected_broker.items():
        actual={row[0]:list(row) for row in history.execute('SELECT '+fields[table]+' FROM broker.'+table)}
        need(actual==expected,'HISTORICAL_ADAPTER_EVIDENCE_CHANGED')
    request_rows=db.execute('SELECT id,data FROM broker.requests').fetchall()
    current_order_ids={json.loads(raw)['order_id'] for key,raw in request_rows if json.loads(raw).get('order_id')}
    need(not (current_order_ids & set(history_orders)),'CURRENT_ORDER_REUSES_CLOSED_ORDER_ID')
    need(set(orders)==set(history_orders)|current_order_ids,'UNATTRIBUTED_OR_MISSING_LIFECYCLE_ORDER')
    need(all(order_identity(orders[k])==v for k,v in history_orders.items()),'HISTORICAL_ACCOUNT_ORDER_CHANGED')
    old_trades={(t['order_id'],t['trade_id']):trade_identity(t) for t in snapshot['trades'] if t['order_id'] in history_orders}
    need(old_trades==history_trades,'HISTORICAL_ACCOUNT_TRADE_CHANGED')
    need(old_position_keys<=set(positions),'MISSING_HISTORICAL_POSITION_ROW')
    # Closed cycles contribute zero net position. The current cycle's signed
    # orders/trades determine the entire remaining net quantity for each key.
    expected_positions={}
    for oid in current_order_ids:
        o=orders[oid];key=(o['instrument'],o['product'])
        expected_positions[key]=expected_positions.get(key,0)+o['filled']*(1 if o['side']=='BUY' else -1)
    need(all(q>=0 for q in expected_positions.values()),'CURRENT_CYCLE_OVERSELL')
    need(all(k in positions and positions[k]==q for k,q in expected_positions.items())
         and all(q==0 for k,q in positions.items() if k not in expected_positions),'CURRENT_AND_HISTORICAL_POSITION_MISMATCH')
    return {oid:orders[oid] for oid in current_order_ids},positions


def recover_entry_only(adapter,key):
    with adapter.store.tx() as db:
        rows=db.execute("SELECT data FROM attempts WHERE request_id=? AND operation='PLACE'",(key,)).fetchall()
        need(len(rows)==1,'SINGLE_ENTRY_RECOVERY_ATTEMPT_REQUIRED');attempt=json.loads(rows[0][0])
        row=json.loads(db.execute('SELECT data FROM requests WHERE id=?',(key,)).fetchone()[0])
        receipt=db.execute('SELECT data FROM receipts WHERE id=?',(attempt['attempt_id'],)).fetchone()
    if receipt:return adapter._bind_receipt(attempt,json.loads(receipt[0]))
    with adapter.store.tx() as db:
        row['state']=attempt['state']='UNKNOWN'
        db.execute('UPDATE requests SET data=? WHERE id=?',(port.encode(row),key))
        db.execute('UPDATE attempts SET data=? WHERE id=?',(port.encode(attempt),attempt['attempt_id']))
    return attempt
