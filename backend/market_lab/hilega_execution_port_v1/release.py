"""Exactly-once release consumer for marked OFFLINE integration databases only."""
import hashlib,json,sqlite3
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime

class Blocked(ValueError):pass

def enc(v):return json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False)
def sha(v):return hashlib.sha256(enc(v).encode()).hexdigest()
def ident(v):
    if not isinstance(v,str) or not 1<=len(v)<=200 or any(ord(c)<32 for c in v):raise Blocked('INVALID_ID')
    return v

class ReleaseConsumer:
    def __init__(self,evidence_link):
        self.evidence=evidence_link;self.link=evidence_link.link;self.service=self.link.service
        self.checkpoint=lambda point:None
        self._scope_guard()
    def _scope_guard(self):
        parent=self.service.store.path.parent.resolve()
        marker=parent/'ISOLATED_LINK_VALIDATION.json'
        try:value=json.loads(marker.read_text())
        except (OSError,ValueError):raise Blocked('MARKED_ISOLATED_CONTROLLER_REQUIRED') from None
        if value!={'controller_db':str(self.service.store.path.resolve()),'purpose':'ISOLATED_CONTROLLER_ADAPTER_VALIDATION'}:raise Blocked('MARKED_ISOLATED_CONTROLLER_REQUIRED')
        if self.link.adapter.store.mode!='OFFLINE_FIXTURE':raise Blocked('OFFLINE_FIXTURE_ADAPTER_REQUIRED')
        for path in (self.service.store.path,self.evidence.path,self.evidence.ledger.path,self.link.adapter.store.path):
            path=Path(path)
            if path.is_symlink() or path.resolve().parent!=parent:raise Blocked('ISOLATED_DATABASE_SCOPE_REQUIRED')
    @contextmanager
    def transaction(self):
        self._scope_guard()
        d=sqlite3.connect(self.service.store.path,timeout=15)
        try:
            d.execute('PRAGMA synchronous=FULL')
            # Keep all evidence stable while consuming it. The installed Ledger's
            # unqualified own_* tables resolve into the attached ownership DB.
            main_tables={x[0] for x in d.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if any(x.startswith('own_') for x in main_tables):raise Blocked('OWNERSHIP_TABLE_SHADOWING_REJECTED')
            for name,path in [('ownership',self.evidence.ledger.path),('evidence',self.evidence.path),('adapter',self.link.adapter.store.path)]:
                d.execute('ATTACH DATABASE ? AS '+name,(str(Path(path).resolve()),))
            for name in ('main','ownership','evidence','adapter'):
                if d.execute('PRAGMA '+name+'.journal_mode').fetchone()[0].lower()!='delete':raise Blocked('ROLLBACK_JOURNAL_REQUIRED')
            d.execute('BEGIN IMMEDIATE')
            yield d
            d.commit()
        except BaseException:d.rollback();raise
        finally:d.close()
    def consume(self,controller_id,*,snapshot_id,request_id,as_of):
        ident(controller_id);ident(snapshot_id);ident(request_id)
        with self.service.store.lock():
            with self.transaction() as d:
                d.execute('CREATE TABLE IF NOT EXISTS broker_fixture_release_receipts(id TEXT PRIMARY KEY,controller_id TEXT UNIQUE NOT NULL,data TEXT NOT NULL)')
                d.execute('CREATE TABLE IF NOT EXISTS broker_fixture_settlements(controller_id TEXT PRIMARY KEY,data TEXT NOT NULL)')
                old=d.execute('SELECT data FROM broker_fixture_release_receipts WHERE id=? OR controller_id=?',(request_id,controller_id)).fetchall()
                if old:
                    receipts=[json.loads(x[0]) for x in old]
                    if any(x['controller_id']!=controller_id or x['snapshot_id']!=snapshot_id for x in receipts):raise Blocked('RELEASE_REQUEST_CONFLICT')
                    receipt=receipts[0]
                    row=d.execute('SELECT data FROM sim_allocation_reservations WHERE id=?',(controller_id,)).fetchone()
                    if not row or json.loads(row[0])['held_cents']!=0:raise Blocked('RELEASED_HOLD_REGRESSION_REQUIRES_REVIEW')
                    return dict(receipt,idempotent_replay=True,release_applied=False,current_proof_revalidated=False)
                control=json.loads(d.execute('SELECT data FROM control WHERE id=1').fetchone()[0])
                if control['mode']!='PAUSED':raise Blocked('CONTROLLER_MUST_REMAIN_PAUSED')
                source=d.execute('SELECT data FROM evidence.verified_snapshot WHERE id=1').fetchone()
                if not source:raise Blocked('VERIFIED_SNAPSHOT_REQUIRED')
                snapshot=json.loads(source[0])
                if snapshot.get('snapshot_id')!=snapshot_id or snapshot.get('evidence_mode')!='OFFLINE_FIXTURE' or snapshot.get('account_scope')!=self.evidence.scope:raise Blocked('SNAPSHOT_SCOPE_OR_ID_MISMATCH')
                adapter_meta=json.loads(d.execute('SELECT data FROM adapter.meta WHERE id=1').fetchone()[0])
                if adapter_meta!={'scope':self.evidence.scope,'mode':'OFFLINE_FIXTURE'}:raise Blocked('ADAPTER_SCOPE_OR_MODE_MISMATCH')
                state_row=d.execute('SELECT data FROM ownership.own_state WHERE account=?',(self.evidence.scope,)).fetchone()
                state=json.loads(state_row[0]) if state_row else {}
                if state.get('status')!='RECONCILED_OFFLINE_FIXTURE' or state.get('exposure_verified') is not True or state.get('snapshot_id')!=snapshot_id:raise Blocked('CURRENT_VERIFIED_OWNERSHIP_REQUIRED')
                recorded=d.execute('SELECT hash FROM ownership.own_snapshots WHERE account=? AND id=?',(self.evidence.scope,snapshot_id)).fetchone()
                if not recorded or recorded[0]!=sha(snapshot):raise Blocked('SOURCE_EVIDENCE_CHANGED')
                mapping_row=d.execute('SELECT data FROM evidence.links WHERE request_id=?',(controller_id,)).fetchone()
                mapping=json.loads(mapping_row[0]) if mapping_row else None
                if not mapping or mapping['role']!='ENTRY' or mapping['controller_id']!=controller_id:raise Blocked('CONTROLLER_OWNERSHIP_MAPPING_REQUIRED')
                # Validate every linked order's durable PLACE receipt, not a caller
                # acknowledgement or a symbol-based ownership assumption.
                for item in [json.loads(x[0]) for x in d.execute('SELECT data FROM evidence.links')]:
                    r=d.execute('SELECT data FROM adapter.requests WHERE id=?',(item['request_id'],)).fetchone()
                    req=json.loads(r[0]) if r else None
                    attempt=d.execute('SELECT id,data FROM adapter.attempts WHERE request_id=? AND operation=?',(item['request_id'],'PLACE')).fetchone()
                    receipt=d.execute('SELECT data FROM adapter.receipts WHERE id=?',(attempt[0],)).fetchone() if attempt else None
                    if not req or not req.get('order_id') or not receipt:raise Blocked('BOUND_DURABLE_RECEIPT_REQUIRED')
                    a=json.loads(attempt[1]);ack=json.loads(receipt[0]);parsed=self.link.mapping.place_ack(ack.get('body'))
                    if a['wire'].get('body')!=req['draft']['body'] or sha(req['draft']['body'])!=req['draft']['fingerprint'] or ack.get('origin')!='EXPLICIT_FIXTURE_TRANSPORT' or ack.get('attempt_id')!=a['attempt_id'] or ack.get('wire_fingerprint')!=sha(a['wire']) or parsed.get('order_id')!=req['order_id']:raise Blocked('RECEIPT_PROVENANCE_MISMATCH')
                # Re-run the actual installed Ledger validator inside a savepoint.
                # Roll back its temporary state/events; keep all DB locks until the
                # controller hold+settlement+receipt transaction is committed.
                d.execute('SAVEPOINT validate_ownership')
                candidate=dict(snapshot,snapshot_id='consume-'+sha([controller_id,snapshot_id,snapshot]))
                proof=self.evidence.ledger._reconcile(d,candidate,as_of)
                d.execute('ROLLBACK TO validate_ownership');d.execute('RELEASE validate_ownership')
                if proof.get('status')!='RECONCILED_OFFLINE_FIXTURE' or proof.get('exposure_verified') is not True:raise Blocked('REVALIDATED_OWNERSHIP_REQUIRED')
                position=next((p for p in proof['positions'] if p['entry_id']==mapping['ownership_id']),None)
                if not position or position['remaining']!=0:raise Blocked('POSITION_NOT_FLAT')
                own_intents={iid:json.loads(data) for iid,data in d.execute('SELECT id,data FROM ownership.own_intents WHERE account=?',(self.evidence.scope,))}
                related={iid for iid,row in own_intents.items() if iid==mapping['ownership_id'] or row.get('parent')==mapping['ownership_id']}
                bindings=dict(d.execute('SELECT order_id,intent_id FROM ownership.own_bindings WHERE account=?',(self.evidence.scope,)))
                orders={o['order_id']:o for o in snapshot['orders']};oids={oid for oid,iid in bindings.items() if iid in related}
                if len(oids)!=len(related) or any(oid not in orders or orders[oid]['status'] not in {'FILLED','CANCELLED','REJECTED'} for oid in oids):raise Blocked('RELATED_ORDERS_NOT_TERMINAL')
                intent_row=d.execute('SELECT data FROM intents WHERE id=?',(controller_id,)).fetchone()
                hold_row=d.execute('SELECT data FROM sim_allocation_reservations WHERE id=?',(controller_id,)).fetchone()
                intent=json.loads(intent_row[0]) if intent_row else None;hold=json.loads(hold_row[0]) if hold_row else None
                if not intent or intent.get('adapter_boundary')!='ISOLATED_ADAPTER_EVIDENCE_REQUIRES_OWNERSHIP_LINK' or not hold or hold['held_cents']<=0 or hold['held_cents']!=hold['amount_cents'] or hold['quantity']!=intent['quantity'] or hold['instrument']!=intent['instrument']:raise Blocked('EXACT_HELD_CONTROLLER_LINK_REQUIRED')
                entry_request=json.loads(d.execute('SELECT data FROM adapter.requests WHERE id=?',(controller_id,)).fetchone()[0])
                own=own_intents[mapping['ownership_id']]
                if entry_request['reservation_reference']!=controller_id or entry_request['draft']['body']['quantity']!=hold['quantity'] or own['quantity']!=hold['quantity'] or own['signal_id']!=intent['signal_id']:raise Blocked('RESERVATION_REFERENCE_MISMATCH')
                released=hold['held_cents'];hold.update(held_cents=0,state='RELEASED',release_source='OFFLINE_BROKER_OWNERSHIP_CONSUMER',updated_at=as_of)
                d.execute('UPDATE sim_allocation_reservations SET data=? WHERE id=?',(enc(hold),controller_id))
                self.checkpoint('AFTER_HOLD_UPDATE_BEFORE_RECEIPT')
                settlement=dict(controller_id=controller_id,ownership_entry_id=mapping['ownership_id'],remaining=0,entry_filled=position['entry_filled'],exit_filled=position['exit_filled'],snapshot_id=snapshot_id,evidence_mode='OFFLINE_FIXTURE',source_fingerprint=sha(snapshot),production_execution_enabled=False)
                d.execute('INSERT INTO broker_fixture_settlements VALUES(?,?)',(controller_id,enc(settlement)))
                receipt=dict(request_id=request_id,controller_id=controller_id,snapshot_id=snapshot_id,released_cents=released,source_fingerprint=sha(snapshot),at=as_of,status='OFFLINE_RELEASE_COMMITTED',release_applied=True,idempotent_replay=False,production_execution_enabled=False,orders_sent_to_upstox=False)
                d.execute('INSERT INTO broker_fixture_release_receipts VALUES(?,?,?)',(request_id,controller_id,enc(receipt)))
                d.execute('INSERT INTO events(data) VALUES(?)',(enc(dict(type='OFFLINE_BROKER_OWNERSHIP_RELEASE_COMMITTED',at=as_of,intent_id=controller_id,released_cents=released,snapshot_id=snapshot_id)),))
                # Preserve Pause and do not mark the legacy SimBroker reconciled.
                control.update(mode='PAUSED',version=control['version']+1,reconciled=False,reason='OFFLINE_BROKER_SETTLEMENT_REQUIRES_PORT_INTEGRATION')
                d.execute('UPDATE control SET data=? WHERE id=1',(enc(control),))
            self.checkpoint('AFTER_COMMIT_BEFORE_ACK')
            return receipt
    def status(self):
        with self.service.store.db() as d:
            tables={x[0] for x in d.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            receipts=[json.loads(x[0]) for x in d.execute('SELECT data FROM broker_fixture_release_receipts')] if 'broker_fixture_release_receipts' in tables else []
            settlements=[json.loads(x[0]) for x in d.execute('SELECT data FROM broker_fixture_settlements')] if 'broker_fixture_settlements' in tables else []
            hold_total=sum(json.loads(x[0])['held_cents'] for x in d.execute('SELECT data FROM sim_allocation_reservations'))
            return dict(receipts=receipts,settlements=settlements,held_cents=hold_total,production_execution_enabled=False,entry_permission=False,legacy_simulator_fill_rows_unchanged=True)
