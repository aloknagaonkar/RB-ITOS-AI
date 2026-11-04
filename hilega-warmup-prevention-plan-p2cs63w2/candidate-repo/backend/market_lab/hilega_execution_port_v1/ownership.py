"""Bound adapter receipts + explicit offline executions -> installed ownership Ledger.
No live capture relabeling, application fill writes or reservation release authority.
"""
import json,os,sqlite3,hashlib
from pathlib import Path
from contextlib import contextmanager
from market_lab.hilega_production_ownership_v1 import Ledger

class Blocked(ValueError):pass

def enc(v):return json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False)
def sha(v):return hashlib.sha256(enc(v).encode()).hexdigest()

class EvidenceLink:
    def __init__(self,controller_link,path):
        if controller_link.adapter.store.mode!='OFFLINE_FIXTURE':raise Blocked('OFFLINE_ADAPTER_REQUIRED_NO_LIVE_RELABELING')
        self.link=controller_link;self.adapter=controller_link.adapter;self.service=controller_link.service
        self.path=Path(path)
        if self.path.parent.resolve()!=self.service.store.path.parent.resolve():raise Blocked('ISOLATED_LINK_DIRECTORY_REQUIRED')
        fd=os.open(self.path,os.O_WRONLY|os.O_CREAT|os.O_NOFOLLOW,0o600);os.close(fd);self.path.chmod(0o600)
        self.scope=self.adapter.store.scope
        self.ledger=Ledger(Path(str(self.path)+'.ownership.sqlite'),self.scope)
        with self.tx() as d:
            d.executescript('''CREATE TABLE IF NOT EXISTS link_meta(id INTEGER PRIMARY KEY,data TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS links(request_id TEXT PRIMARY KEY,data TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS verified_snapshot(id INTEGER PRIMARY KEY,data TEXT NOT NULL);''')
            expected=enc(dict(scope=self.scope,controller_db=str(self.service.store.path.resolve()),adapter_db=str(self.adapter.store.path.resolve()),mode='OFFLINE_LINK_ONLY'))
            old=d.execute('SELECT data FROM link_meta WHERE id=1').fetchone()
            if old and old[0]!=expected:raise Blocked('OWNERSHIP_LINK_SCOPE_MISMATCH')
            d.execute('INSERT OR IGNORE INTO link_meta VALUES(1,?)',(expected,))
    @contextmanager
    def tx(self):
        d=sqlite3.connect(self.path,timeout=15);d.execute('PRAGMA synchronous=FULL');d.execute('BEGIN IMMEDIATE')
        try:yield d;d.commit()
        except BaseException:d.rollback();raise
        finally:d.close()
    def links(self):
        with self.tx() as d:return [json.loads(x[0]) for x in d.execute('SELECT data FROM links ORDER BY rowid')]
    def _save(self,row):
        with self.tx() as d:
            old=d.execute('SELECT data FROM links WHERE request_id=?',(row['request_id'],)).fetchone()
            if old and old[0]!=enc(row):raise Blocked('LINK_REFERENCE_CONFLICT')
            d.execute('INSERT OR IGNORE INTO links VALUES(?,?)',(row['request_id'],enc(row)))
    def register_entry(self,controller_id):
        row=next((x for x in self.adapter.store.requests() if x['request_id']==controller_id),None)
        intent=next((x for x in self.service.store.intents() if x['id']==controller_id),None)
        from market_lab.hilega_sim_allocation_v1 import rows as reservations
        hold=next((x for x in reservations(self.service.store) if x['id']==controller_id),None)
        if not row or not intent or not hold or hold['held_cents']<=0:raise Blocked('CONTROLLER_INTENT_AND_HELD_RESERVATION_REQUIRED')
        b=row['draft']['body']
        if row['reservation_reference']!=controller_id or b['transaction_type']!='BUY' or b['quantity']!=intent['quantity'] or hold['quantity']!=intent['quantity']:raise Blocked('RESERVATION_ADAPTER_LINK_MISMATCH')
        own=self.ledger.register_entry(signal_id=intent['signal_id'],signal_at=intent['signal_at'],intent_at=row['draft']['created_at'],direction=row['direction'],instrument=b['instrument_token'],product=b['product'],quantity_=b['quantity'],policy_id='BULLISH_GAP2_FULL_WMA2',strategy_version='bullish-gap2-full-wma2-2.0.0-wma40-reversal')
        self._save(dict(request_id=controller_id,controller_id=controller_id,ownership_id=own,role='ENTRY'))
        return own
    def register_exit(self,adapter_request_id,controller_id,*,as_of):
        parent=next((x for x in self.links() if x['request_id']==controller_id and x['role']=='ENTRY'),None)
        if parent is None:raise Blocked('REGISTERED_PARENT_REQUIRED')
        row=next((x for x in self.adapter.store.requests() if x['request_id']==adapter_request_id),None)
        if row is None or row['draft']['body']['transaction_type']!='SELL':raise Blocked('PREPARED_EXIT_ADAPTER_REQUEST_REQUIRED')
        state=self.ledger.report(as_of=as_of)['state']
        if state.get('exposure_verified') is not True:raise Blocked('FRESH_OWNERSHIP_PROOF_REQUIRED')
        position=next((p for p in state['positions'] if p['entry_id']==parent['ownership_id']),None)
        b=row['draft']['body']
        if not position or b['instrument_token']!=position['instrument'] or b['product']!=position['product'] or not 0<b['quantity']<=position['remaining']:raise Blocked('EXIT_EXCEEDS_VERIFIED_REMAINING_OR_WRONG_INSTRUMENT')
        own=self.ledger.register_exit(entry_id=parent['ownership_id'],exit_key=adapter_request_id,intent_at=row['draft']['created_at'],quantity_=b['quantity'],reason='EXPLICIT_OFFLINE_ADAPTER_EXIT')
        self._save(dict(request_id=adapter_request_id,controller_id=controller_id,ownership_id=own,role='EXIT'))
        return own
    def bind_receipts(self):
        for link in self.links():
            request=next(x for x in self.adapter.store.requests() if x['request_id']==link['request_id'])
            oid=request.get('order_id')
            if oid is None:continue # Ledger will reject unbound acceptance; no tag adoption.
            with self.adapter.store.tx() as d:
                attempt=d.execute('SELECT id,data FROM attempts WHERE request_id=? AND operation=?',(link['request_id'],'PLACE')).fetchone()
                receipt=d.execute('SELECT data FROM receipts WHERE id=?',(attempt[0],)).fetchone() if attempt else None
            if not receipt:raise Blocked('DURABLE_PLACE_RECEIPT_REQUIRED')
            a=json.loads(attempt[1]);r=json.loads(receipt[0])
            if r.get('origin')!='EXPLICIT_FIXTURE_TRANSPORT' or r.get('attempt_id')!=a['attempt_id'] or r.get('wire_fingerprint')!=sha(a['wire']):raise Blocked('RECEIPT_PROVENANCE_MISMATCH')
            parsed=self.link.mapping.place_ack(r['body'])
            if parsed.get('status')!='ACKNOWLEDGED_NOT_FILLED' or parsed.get('order_id')!=oid:raise Blocked('ACK_ORDER_BINDING_MISMATCH')
            self.ledger.bind_order(intent_id=link['ownership_id'],order_id=oid,at=request['draft']['created_at'])
    def reconcile(self,snapshot,*,as_of):
        if snapshot.get('evidence_mode')!='OFFLINE_FIXTURE' or snapshot.get('account_scope')!=self.scope:raise Blocked('EXPLICIT_OFFLINE_EVIDENCE_REQUIRED')
        self.bind_receipts()
        result=self.ledger.reconcile(snapshot,as_of=as_of)
        if result['status']=='RECONCILED_OFFLINE_FIXTURE':
            with self.tx() as d:d.execute('INSERT OR REPLACE INTO verified_snapshot VALUES(1,?)',(enc(snapshot),))
        return dict(reconciliation=result,assessment=self.assess(as_of=as_of),controller_updated=False,orders_sent_to_upstox=False)
    def assess(self,*,as_of):
        report=self.ledger.report(as_of=as_of);state=report['state'];ready=[];reasons=[]
        with self.tx() as d:stored=d.execute('SELECT data FROM verified_snapshot WHERE id=1').fetchone()
        snapshot=json.loads(stored[0]) if stored else None
        if state.get('exposure_verified') is not True or state.get('status')!='RECONCILED_OFFLINE_FIXTURE' or snapshot is None or snapshot.get('snapshot_id')!=state.get('snapshot_id'):
            reasons.append('FRESH_MATCHING_OWNERSHIP_PROOF_REQUIRED')
        else:
            orders={o['order_id']:o for o in snapshot['orders']};bindings=report['order_bindings'];owned=report['registered_intents']
            for parent in [x for x in self.links() if x['role']=='ENTRY']:
                position=next((p for p in state['positions'] if p['entry_id']==parent['ownership_id']),None)
                related={r['id'] for r in owned if r['id']==parent['ownership_id'] or r.get('parent')==parent['ownership_id']}
                related_oids={oid for oid,iid in bindings.items() if iid in related}
                complete=len(related_oids)==len(related) and all(oid in orders and orders[oid]['status'] in {'FILLED','CANCELLED','REJECTED'} for oid in related_oids)
                if position and position['remaining']==0 and complete:ready.append(parent['controller_id'])
        return dict(status='OFFLINE_TERMINAL_FLAT_ASSESSED' if ready and not reasons else 'HOLD_RETAINED',release_assessment_controller_ids=ready if not reasons else [],reasons=reasons,
            assessment_only=True,reservations_released=False,controller_updated=False,entry_permission=False,production_execution_enabled=False,live_ownership_verified=False)
