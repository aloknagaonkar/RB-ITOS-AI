"""Offline ownership/fill reconciliation. No broker transport or order submission.

This ledger accepts explicitly scoped canonical fixtures only. It cannot activate
production or infer account identity from an instrument. Existing simulator and
broker observation databases are not read or modified.
"""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime,timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo
import hashlib,json,os,sqlite3

MODEL='HILEGA_PRODUCTION_OWNERSHIP_V1'
IST=ZoneInfo('Asia/Kolkata')
TERMINAL={'FILLED','CANCELLED','REJECTED'}
STATUSES=TERMINAL|{'OPEN','PARTIAL'}

class ReviewRequired(ValueError):pass

def enc(v):return json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(v):return hashlib.sha256(enc(v).encode()).hexdigest()
def ident(v):
    if not isinstance(v,str) or not v.strip() or len(v)>200 or any(ord(c)<32 for c in v):raise ReviewRequired('INVALID_IDENTIFIER')
    return v

def quantity(v,zero=False):
    if type(v) is not int or v<(0 if zero else 1):raise ReviewRequired('INVALID_QUANTITY')
    return v

def price(v):
    if isinstance(v,bool) or not isinstance(v,(int,float,str,Decimal)):raise ReviewRequired('INVALID_FILL_PRICE')
    try:d=Decimal(str(v))
    except InvalidOperation:raise ReviewRequired('INVALID_FILL_PRICE') from None
    if not d.is_finite() or d<=0:raise ReviewRequired('INVALID_FILL_PRICE')
    return d

def timestamp(v):
    try:t=datetime.fromisoformat(v)
    except (ValueError,TypeError):raise ReviewRequired('INVALID_TIMESTAMP') from None
    if t.tzinfo is None:raise ReviewRequired('AWARE_TIMESTAMP_REQUIRED')
    return t

def session(v):return timestamp(v).astimezone(IST).date().isoformat()

class Ledger:
    def __init__(self,path,account_scope):
        self.account=ident(account_scope);self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        fd=os.open(self.path,os.O_CREAT|os.O_RDWR,0o600);os.close(fd)
        os.chmod(self.path,0o600)
        with self.db() as d:
            d.executescript('''
            CREATE TABLE IF NOT EXISTS own_intents(account TEXT,id TEXT,data TEXT,PRIMARY KEY(account,id));
            CREATE TABLE IF NOT EXISTS own_bindings(account TEXT,order_id TEXT,intent_id TEXT,PRIMARY KEY(account,order_id),UNIQUE(account,intent_id));
            CREATE TABLE IF NOT EXISTS own_fills(account TEXT,order_id TEXT,trade_id TEXT,data TEXT,PRIMARY KEY(account,order_id,trade_id));
            CREATE TABLE IF NOT EXISTS own_order_evidence(account TEXT,order_id TEXT,data TEXT,PRIMARY KEY(account,order_id));
            CREATE TABLE IF NOT EXISTS own_snapshots(account TEXT,id TEXT,hash TEXT,PRIMARY KEY(account,id));
            CREATE TABLE IF NOT EXISTS own_state(account TEXT PRIMARY KEY,data TEXT);
            CREATE TABLE IF NOT EXISTS own_events(seq INTEGER PRIMARY KEY AUTOINCREMENT,account TEXT,data TEXT);
            ''')
    @contextmanager
    def db(self):
        d=sqlite3.connect(self.path,timeout=15)
        d.execute('PRAGMA synchronous=FULL')
        d.execute('BEGIN IMMEDIATE')
        try:yield d;d.commit()
        except BaseException:d.rollback();raise
        finally:d.close()
    def _event(self,d,kind,at,**kw):
        d.execute('INSERT INTO own_events(account,data) VALUES(?,?)',(self.account,enc(dict(type=kind,at=at,**kw))))
    def _intents(self,d):return {r[0]:json.loads(r[1]) for r in d.execute('SELECT id,data FROM own_intents WHERE account=?',(self.account,))}
    def _bindings(self,d):return dict(d.execute('SELECT order_id,intent_id FROM own_bindings WHERE account=?',(self.account,)))
    def _invalidate(self,d,at,reason):
        prior=d.execute('SELECT data FROM own_state WHERE account=?',(self.account,)).fetchone()
        prior=json.loads(prior[0]) if prior else {}
        value=dict(status='REVIEW_REQUIRED',reason=reason,observed_at=at,exposure_verified=False,
                   last_successful_observed_at=prior.get('last_successful_observed_at'))
        d.execute('INSERT OR REPLACE INTO own_state VALUES(?,?)',(self.account,enc(value)))
    def register_entry(self,*,signal_id,signal_at,intent_at,direction,instrument,product,quantity_,policy_id,strategy_version):
        signal_id=ident(signal_id);instrument=ident(instrument);product=ident(product)
        ident(policy_id);ident(strategy_version);quantity(quantity_)
        if direction not in {'BULLISH','BEARISH'}:raise ReviewRequired('INVALID_DIRECTION')
        if timestamp(intent_at)<timestamp(signal_at):raise ReviewRequired('INTENT_BEFORE_SIGNAL')
        if session(signal_at)!=session(intent_at):raise ReviewRequired('CROSS_SESSION_SIGNAL')
        iid=digest([self.account,session(signal_at),signal_id,instrument,product,'ENTRY'])
        row=dict(id=iid,role='ENTRY',side='BUY',signal_id=signal_id,signal_at=signal_at,intent_at=intent_at,
                 session_date=session(intent_at),direction=direction,instrument=instrument,product=product,
                 quantity=quantity_,policy_id=policy_id,strategy_version=strategy_version)
        with self.db() as d:
            existing=self._intents(d).get(iid)
            if existing and existing!=row:raise ReviewRequired('SIGNAL_INTENT_CONFLICT')
            if not existing:
                d.execute('INSERT INTO own_intents VALUES(?,?,?)',(self.account,iid,enc(row)))
                self._invalidate(d,intent_at,'NEW_INTENT_REQUIRES_RECONCILIATION')
                self._event(d,'ENTRY_INTENT_RECORDED',intent_at,intent_id=iid,signal_id=signal_id,order_permission=False)
        return iid
    def register_exit(self,*,entry_id,exit_key,intent_at,quantity_,reason,external=False,actor=None):
        ident(exit_key);ident(reason);quantity(quantity_);timestamp(intent_at)
        if type(external) is not bool:raise ReviewRequired('INVALID_EXTERNAL_FLAG')
        if external:ident(actor)
        iid=digest([self.account,entry_id,'EXIT',exit_key])
        with self.db() as d:
            rows=self._intents(d);entry=rows.get(entry_id)
            if not entry or entry['role']!='ENTRY':raise ReviewRequired('ENTRY_OWNERSHIP_REQUIRED')
            if timestamp(intent_at)<timestamp(entry['intent_at']):raise ReviewRequired('EXIT_BEFORE_ENTRY')
            if quantity_>entry['quantity']:raise ReviewRequired('EXIT_EXCEEDS_REQUESTED_ENTRY')
            row=dict(id=iid,role='EXIT',side='SELL',parent=entry_id,instrument=entry['instrument'],product=entry['product'],
                     quantity=quantity_,intent_at=intent_at,session_date=session(intent_at),reason=reason,
                     external=external,attribution_actor=actor if external else None)
            existing=rows.get(iid)
            if existing and existing!=row:raise ReviewRequired('EXIT_INTENT_CONFLICT')
            if not existing:
                d.execute('INSERT INTO own_intents VALUES(?,?,?)',(self.account,iid,enc(row)))
                self._invalidate(d,intent_at,'NEW_EXIT_REQUIRES_RECONCILIATION')
                self._event(d,'EXTERNAL_EXIT_MAPPING_RECORDED' if external else 'EXIT_INTENT_RECORDED',intent_at,
                            intent_id=iid,parent=entry_id,actor=actor if external else None,order_permission=False)
        return iid
    def bind_order(self,*,intent_id,order_id,at):
        ident(order_id);timestamp(at)
        with self.db() as d:
            rows=self._intents(d)
            if intent_id not in rows:raise ReviewRequired('UNKNOWN_INTENT')
            if timestamp(at)<timestamp(rows[intent_id]['intent_at']):raise ReviewRequired('BIND_BEFORE_INTENT')
            bindings=self._bindings(d)
            if bindings.get(order_id)==intent_id:return
            if order_id in bindings or intent_id in bindings.values():raise ReviewRequired('ORDER_OWNERSHIP_CONFLICT')
            d.execute('INSERT INTO own_bindings VALUES(?,?,?)',(self.account,order_id,intent_id))
            self._invalidate(d,at,'ORDER_BINDING_REQUIRES_RECONCILIATION')
            self._event(d,'BROKER_ORDER_BOUND',at,intent_id=intent_id,order_id=order_id)
    def _load_fills(self,d):
        return {(r[0],r[1]):json.loads(r[2]) for r in d.execute('SELECT order_id,trade_id,data FROM own_fills WHERE account=?',(self.account,))}
    def _position_rows(self,rows,bindings,fills):
        by_intent={}
        for (oid,_),f in fills.items():
            iid=bindings[oid];by_intent.setdefault(iid,[]).append(f)
        result=[]
        for iid,e in rows.items():
            if e['role']!='ENTRY':continue
            buys=by_intent.get(iid,[]);bq=sum(t['quantity'] for t in buys)
            cost=sum((price(t['price'])*t['quantity'] for t in buys),Decimal(0))
            avg=cost/bq if bq else None
            exits=[x for x in rows.values() if x.get('parent')==iid]
            sells=[f for x in exits for f in by_intent.get(x['id'],[])]
            sq=sum(t['quantity'] for t in sells)
            if sq>bq:raise ReviewRequired('EXIT_FILLS_EXCEED_ENTRY_FILLS')
            if buys and sells and min(timestamp(f['filled_at']) for f in sells)<min(timestamp(f['filled_at']) for f in buys):raise ReviewRequired('EXIT_FILL_BEFORE_ENTRY_FILL')
            # Validate chronological quantity: an exit cannot borrow a future entry fill.
            running=0
            for f,sign in sorted([(f,1) for f in buys]+[(f,-1) for f in sells],key=lambda x:(timestamp(x[0]['filled_at']),-x[1])):
                running+=sign*f['quantity']
                if running<0:raise ReviewRequired('EXIT_PRECEDES_AVAILABLE_ENTRY_QUANTITY')
            realised=sum(((price(f['price'])-avg)*f['quantity'] for f in sells),Decimal(0)) if avg is not None else None
            result.append(dict(entry_id=iid,signal_id=e['signal_id'],direction=e['direction'],instrument=e['instrument'],product=e['product'],
                policy_id=e['policy_id'],strategy_version=e['strategy_version'],entry_filled=bq,exit_filled=sq,remaining=bq-sq,
                average_entry=str(avg) if avg is not None else None,gross_realised_premium_value=str(realised) if realised is not None else None,
                fees_included=False,unrealised_pnl=None,entry_fill_times=[f['filled_at'] for f in buys],exit_fill_times=[f['filled_at'] for f in sells]))
        return result
    def reconcile(self,snapshot,*,as_of):
        """Atomic evidence update; invalid evidence never partially changes fill ledger."""
        timestamp(as_of)
        try:
            with self.db() as d:return self._reconcile(d,snapshot,as_of)
        except (ReviewRequired,KeyError,TypeError,ValueError,ArithmeticError) as exc:
            code=str(exc) if isinstance(exc,ReviewRequired) else 'MALFORMED_EVIDENCE_REQUIRES_REVIEW'
            with self.db() as d:
                self._invalidate(d,as_of,code)
                self._event(d,'RECONCILIATION_BLOCKED',as_of,reason=code)
            return dict(status='REVIEW_REQUIRED',reason=code,exposure_verified=False,production_execution_enabled=False,orders_sent=False)
    def _reconcile(self,d,s,as_of):
        if not isinstance(s,dict) or s.get('evidence_mode')!='OFFLINE_FIXTURE':raise ReviewRequired('OFFLINE_FIXTURE_REQUIRED')
        if s.get('account_scope')!=self.account:raise ReviewRequired('ACCOUNT_SCOPE_MISMATCH')
        sid=ident(s.get('snapshot_id'));observed=s.get('observed_at');t=timestamp(observed)
        age=(timestamp(as_of)-t).total_seconds()
        if not 0<=age<=30:raise ReviewRequired('SNAPSHOT_STALE_OR_FUTURE')
        if session(observed)!=session(as_of):raise ReviewRequired('SESSION_MISMATCH')
        if s.get('complete') is not True:raise ReviewRequired('SNAPSHOT_INCOMPLETE')
        fingerprint=digest(s)
        prior=d.execute('SELECT hash FROM own_snapshots WHERE account=? AND id=?',(self.account,sid)).fetchone()
        if prior:
            if prior[0]!=fingerprint:raise ReviewRequired('SNAPSHOT_ID_REUSED_WITH_CHANGED_EVIDENCE')
            state=d.execute('SELECT data FROM own_state WHERE account=?',(self.account,)).fetchone()
            return dict(status='IDEMPOTENT_REPLAY',current_state=json.loads(state[0]) if state else None,
                        exposure_verified=False,production_execution_enabled=False,orders_sent=False)
        last=d.execute('SELECT data FROM own_state WHERE account=?',(self.account,)).fetchone()
        if last:
            previous=json.loads(last[0]).get('last_successful_observed_at')
            if previous and t<timestamp(previous):raise ReviewRequired('OUT_OF_ORDER_SNAPSHOT')
        rows=self._intents(d);bindings=self._bindings(d);reverse={iid:oid for oid,iid in bindings.items()}
        active_keys={(r['instrument'],r['product']) for r in rows.values() if r['role']=='ENTRY'}
        for iid,r in rows.items():
            if iid not in reverse:raise ReviewRequired('ORDER_ACCEPTANCE_UNKNOWN_NO_RESUBMISSION')
        orders={}
        if not all(isinstance(s.get(n),list) for n in ('orders','trades','positions')):raise ReviewRequired('EVIDENCE_LIST_REQUIRED')
        for o in s['orders']:
            if not isinstance(o,dict):raise ReviewRequired('INVALID_ORDER')
            oid=ident(o.get('order_id'))
            if oid in orders:raise ReviewRequired('DUPLICATE_ORDER_EVIDENCE')
            ident(o.get('instrument'));ident(o.get('product'))
            if o.get('side') not in {'BUY','SELL'} or o.get('status') not in STATUSES:raise ReviewRequired('INVALID_ORDER_STATE')
            quantity(o.get('quantity'));quantity(o.get('filled'),True);quantity(o.get('pending'),True)
            if o['filled']+o['pending']>o['quantity']:raise ReviewRequired('INVALID_ORDER_QUANTITIES')
            if o['status']=='FILLED' and (o['filled']!=o['quantity'] or o['pending']!=0):raise ReviewRequired('INCONSISTENT_FILLED_ORDER')
            if o['status'] in {'CANCELLED','REJECTED'} and o['pending']!=0:raise ReviewRequired('TERMINAL_ORDER_HAS_PENDING_QUANTITY')
            if o['status']=='REJECTED' and o['filled']!=0:raise ReviewRequired('REJECTED_ORDER_HAS_FILLS')
            orders[oid]=o
            if oid not in bindings and (o['filled'] or o['status'] not in TERMINAL) and (o['instrument'],o['product']) in active_keys:
                raise ReviewRequired('UNMAPPED_ACTIVITY_ON_OWNED_INSTRUMENT')
        known=self._load_fills(d);incoming={}
        for f in s['trades']:
            if not isinstance(f,dict):raise ReviewRequired('INVALID_FILL')
            oid=ident(f.get('order_id'));tid=ident(f.get('trade_id'));quantity(f.get('quantity'));amount=price(f.get('price'))
            when=timestamp(f.get('filled_at'))
            if when>t or session(f['filled_at'])!=session(observed):raise ReviewRequired('FILL_TIME_OUTSIDE_SNAPSHOT_SESSION')
            o=orders.get(oid)
            if not o:raise ReviewRequired('FILL_WITHOUT_ORDER_EVIDENCE')
            if any(f.get(k)!=o.get(k) for k in ('instrument','product','side')):raise ReviewRequired('FILL_ORDER_IDENTITY_MISMATCH')
            normal=dict(order_id=oid,trade_id=tid,instrument=o['instrument'],product=o['product'],side=o['side'],
                        quantity=f['quantity'],price=str(amount.normalize()),filled_at=when.astimezone(timezone.utc).isoformat())
            key=(oid,tid)
            if key in incoming and incoming[key]!=normal:raise ReviewRequired('DUPLICATE_FILL_CONFLICT')
            if key in known and known[key]!=normal:raise ReviewRequired('PREVIOUS_FILL_CHANGED')
            incoming[key]=normal
            if oid in bindings:
                if when<timestamp(rows[bindings[oid]]['intent_at']):raise ReviewRequired('FILL_BEFORE_INTENT')
        for key,f in known.items():
            if session(f['filled_at'])==session(observed) and key not in incoming:raise ReviewRequired('PREVIOUS_FILL_DISAPPEARED')
        # Order status/quantity is a cross-check; it NEVER manufactures executions.
        for oid,o in orders.items():
            if sum(f['quantity'] for (k,_),f in incoming.items() if k==oid)!=o['filled']:raise ReviewRequired('ORDER_TRADE_FILL_TOTAL_MISMATCH')
        for oid,iid in bindings.items():
            r=rows[iid]
            if r['session_date']!=session(observed) and oid not in orders:
                previous=d.execute('SELECT data FROM own_order_evidence WHERE account=? AND order_id=?',(self.account,oid)).fetchone()
                if previous and json.loads(previous[0])['status'] in TERMINAL:continue
                raise ReviewRequired('PRIOR_SESSION_ORDER_OUTCOME_UNRESOLVED')
            o=orders.get(oid)
            if not o:raise ReviewRequired('OWNED_ORDER_EVIDENCE_MISSING')
            if any(o.get(k)!=r.get(k) for k in ('instrument','product','side','quantity')):raise ReviewRequired('BOUND_ORDER_IDENTITY_MISMATCH')
            prev=d.execute('SELECT data FROM own_order_evidence WHERE account=? AND order_id=?',(self.account,oid)).fetchone()
            if prev:
                p=json.loads(prev[0])
                if o['filled']<p['filled']:raise ReviewRequired('CUMULATIVE_FILL_REGRESSION')
                if p['status'] in TERMINAL and o['status'] not in TERMINAL:raise ReviewRequired('TERMINAL_ORDER_REGRESSION')
                if p['status']=='FILLED' and o['status']!='FILLED':raise ReviewRequired('FILLED_ORDER_STATUS_CHANGED')
        merged=dict(known);merged.update({key:f for key,f in incoming.items() if key[0] in bindings})
        positions=self._position_rows(rows,bindings,merged)
        broker={}
        for p in s['positions']:
            if not isinstance(p,dict):raise ReviewRequired('INVALID_POSITION')
            key=(ident(p.get('instrument')),ident(p.get('product')))
            if key in broker:raise ReviewRequired('DUPLICATE_POSITION_EVIDENCE')
            q=p.get('quantity')
            if type(q) is not int:raise ReviewRequired('INVALID_POSITION_QUANTITY')
            broker[key]=q
            if q!=0 and key not in active_keys:raise ReviewRequired('UNOWNED_BROKER_EXPOSURE')
        for key in active_keys:
            expected=sum(p['remaining'] for p in positions if (p['instrument'],p['product'])==key)
            if key not in broker:raise ReviewRequired('MISSING_POSITION_IS_NOT_FLAT')
            if broker[key]!=expected:raise ReviewRequired('BROKER_POSITION_QUANTITY_MISMATCH')
        for iid,r in rows.items():
            if r['role']=='ENTRY':continue
            entry=next(p for p in positions if p['entry_id']==r['parent'])
            if r['quantity']>entry['entry_filled']:raise ReviewRequired('EXIT_ORDER_EXCEEDS_FILLED_ENTRY')
        # Pending exits reserve the remaining quantity; overlapping exit intents cannot pass.
        for p in positions:
            pending=sum(orders[reverse[r['id']]]['pending'] for r in rows.values()
                        if r.get('parent')==p['entry_id'] and reverse[r['id']] in orders)
            if pending>p['remaining']:raise ReviewRequired('PENDING_EXITS_EXCEED_REMAINING')
        pending_orders=[o['order_id'] for oid,o in orders.items() if oid in bindings and o['status'] not in TERMINAL]
        for key,f in merged.items():
            if key not in known:
                owner=rows[bindings[key[0]]]
                self._event(d,'FILL_LINKED_OFFLINE',as_of,intent_id=owner['id'],entry_id=owner.get('parent',owner['id']),
                            order_id=f['order_id'],trade_id=f['trade_id'],side=f['side'],quantity=f['quantity'],
                            price=f['price'],filled_at=f['filled_at'])
            d.execute('INSERT OR IGNORE INTO own_fills VALUES(?,?,?,?)',(self.account,*key,enc(f)))
        for oid,o in orders.items():
            if oid in bindings:d.execute('INSERT OR REPLACE INTO own_order_evidence VALUES(?,?,?)',(self.account,oid,enc(o)))
        d.execute('INSERT INTO own_snapshots VALUES(?,?,?)',(self.account,sid,fingerprint))
        state=dict(status='RECONCILED_OFFLINE_FIXTURE',observed_at=observed,last_successful_observed_at=observed,
                   snapshot_id=sid,exposure_verified=True,pending_orders=pending_orders,
                   reversal_buy_allowed=False,positions=positions,fill_count=len(merged),account_scope=self.account)
        d.execute('INSERT OR REPLACE INTO own_state VALUES(?,?)',(self.account,enc(state)))
        self._event(d,'OWNERSHIP_RECONCILED_OFFLINE',as_of,snapshot_id=sid,fill_count=len(merged),position_count=len(positions))
        return dict(state,production_execution_enabled=False,orders_sent=False)
    def report(self,*,as_of):
        timestamp(as_of)
        with self.db() as d:
            r=d.execute('SELECT data FROM own_state WHERE account=?',(self.account,)).fetchone()
            state=json.loads(r[0]) if r else dict(status='NOT_RECONCILED',exposure_verified=False)
            if state.get('exposure_verified'):
                age=(timestamp(as_of)-timestamp(state['observed_at'])).total_seconds()
                if not 0<=age<=30 or session(as_of)!=session(state['observed_at']):
                    state=dict(status='STALE',reason='SNAPSHOT_STALE_OR_FUTURE',exposure_verified=False)
            events=[dict(sequence=r[0],**json.loads(r[1])) for r in d.execute('SELECT seq,data FROM own_events WHERE account=? ORDER BY seq',(self.account,))]
            intents=self._intents(d);bindings=self._bindings(d);fills=self._load_fills(d)
            return dict(model=MODEL,evidence_mode='OFFLINE_FIXTURE',state=state,events=events[-200:],
                        registered_intents=list(intents.values()),order_bindings=bindings,
                        historical_execution_fills=list(fills.values()),historical_fills_are_not_current_position_proof=True,
                        production_execution_enabled=False,orders_sent=False,order_submission_supported=False,
                        entry_permission=False,real_broker_account_identity_verified=False)
