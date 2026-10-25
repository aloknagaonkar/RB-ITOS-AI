"""Confirmed strategy audit -> controlled simulator -> fixture ownership audit.
No broker transport, credentials or production order permissions.
"""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import fcntl,hashlib,json,os,uuid
from .hilega_production_foundation.core import Service,SimBroker,Blocked,TERMINAL,encode,money,positive_int,IST
from .hilega_production_ownership_v1 import Ledger

MODEL='HILEGA_PRODUCTION_SIMULATOR_BRIDGE_V1'
POLICY='BULLISH_GAP2_FULL_WMA2'
VERSION='bullish-gap2-full-wma2-2.0.0-wma40-reversal'
ENTRIES={'ENTRY_OPENING_BULLISH_CONFIRMED':'BULLISH','ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21':'BULLISH',
 'ENTRY_PATH1_ROUTE_B_STRUCTURAL':'BULLISH','ENTRY_OPENING_BEARISH_CONFIRMED':'BEARISH',
 'ENTRY_BEARISH_ROUTE_A_CROSS_RSI50_BELOW_WMA21':'BEARISH','ENTRY_BEARISH_ROUTE_B_STRUCTURAL':'BEARISH'}
EXITS={'STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21':'BULLISH','SESSION_CUTOFF_EXIT_1455_OPEN':'BULLISH',
 'STRUCTURAL_EXIT_BEARISH_RSI_CROSS_ABOVE_WMA21':'BEARISH','BEARISH_SESSION_CUTOFF_EXIT_1455_OPEN':'BEARISH'}
ARMS={'PATH1_ARMED_RSI_CROSS_EMA3_UP','BEARISH_PATH1_ARMED_RSI_CROSS_EMA3_DOWN'}

def aware(value):
    try:t=datetime.fromisoformat(value)
    except (TypeError,ValueError):raise Blocked('INVALID_SOURCE_TIMESTAMP') from None
    if t.tzinfo is None:raise Blocked('AWARE_SOURCE_TIMESTAMP_REQUIRED')
    return t

def key(parts):return hashlib.sha256(encode(parts).encode()).hexdigest()

def verified_records(path):
    """One locked, hash-verified snapshot of the existing append-only audit."""
    path=Path(path)
    with path.open('r',encoding='utf-8') as f:
        fcntl.flock(f,fcntl.LOCK_SH)
        try:
            text=f.read(64*1024*1024+1)
            if len(text)>64*1024*1024:raise Blocked('SOURCE_JOURNAL_TOO_LARGE')
            if text and not text.endswith('\n'):raise Blocked('SOURCE_JOURNAL_INCOMPLETE')
            records=[json.loads(line) for line in text.splitlines() if line.strip()]
        finally:fcntl.flock(f,fcntl.LOCK_UN)
    previous=None
    for sequence,row in enumerate(records,1):
        if not isinstance(row,dict) or row.get('sequence')!=sequence or row.get('previous_hash')!=previous:raise Blocked('SOURCE_CHAIN_INVALID')
        core={k:v for k,v in row.items() if k!='record_hash'}
        hashed=hashlib.sha256(json.dumps(core,sort_keys=True,separators=(',',':'),ensure_ascii=False,default=str).encode()).hexdigest()
        if row.get('record_hash')!=hashed:raise Blocked('SOURCE_CHAIN_INVALID')
        previous=hashed
    return records

def accepted(record):
    if not isinstance(record,dict):raise Blocked('SOURCE_RECORD_INVALID')
    if record.get('stage') not in {'DIRECTIONAL_DECISION','DIRECTIONAL_SESSION_CUTOFF'}:return []
    if record.get('status')!='PROCESSED':return []
    p=record.get('payload')
    if not isinstance(p,dict):raise Blocked('SOURCE_PAYLOAD_INVALID')
    names=p.get('accepted_events',[])
    if not isinstance(names,list) or not all(isinstance(n,str) for n in names):raise Blocked('ACCEPTED_EVENTS_INVALID')
    if not names:return []
    if p.get('reconstructed') is True:return []
    if p.get('policy_id')!=POLICY or p.get('strategy_version')!=VERSION:raise Blocked('SOURCE_POLICY_OR_VERSION_MISMATCH')
    if record['stage']=='DIRECTIONAL_DECISION' and p.get('reconstructed') is not False:raise Blocked('SOURCE_RECONSTRUCTION_FLAG_REQUIRED')
    if len(set(names))!=len(names):raise Blocked('DUPLICATE_EVENT_IN_BOUNDARY')
    if any(n not in ENTRIES and n not in EXITS and n not in ARMS for n in names):raise Blocked('UNKNOWN_ACCEPTED_EVENT')
    execution=[n for n in names if n in ENTRIES or n in EXITS]
    if not execution:return [] # armed/candidate alone is information, never an entry
    if len(execution)>2 or sum(n in ENTRIES for n in execution)>1 or sum(n in EXITS for n in execution)>1:raise Blocked('AMBIGUOUS_ACCEPTED_EXECUTION')
    if len(execution)==2:
        en=next(n for n in execution if n in ENTRIES);ex=next(n for n in execution if n in EXITS)
        if ENTRIES[en]==EXITS[ex]:raise Blocked('SAME_DIRECTION_EXIT_ENTRY_NOT_SUPPORTED')
    at=p.get('decision_timestamp') or p.get('cutoff_timestamp');t=aware(at).astimezone(IST)
    at=t.isoformat()
    if t.second or t.microsecond or t.minute%5:raise Blocked('COMPLETED_FIVE_MINUTE_BOUNDARY_REQUIRED')
    if record['stage']=='DIRECTIONAL_SESSION_CUTOFF' and any(n in ENTRIES for n in execution):raise Blocked('CUTOFF_CANNOT_OPEN_ENTRY')
    details=p.get('event_details')
    if not isinstance(details,list):raise Blocked('CONFIRMED_EVENT_DETAILS_REQUIRED')
    result=[]
    for name in sorted(execution,key=lambda n:0 if n in EXITS else 1):
        ds=[d for d in details if isinstance(d,dict) and d.get('event_type')==name]
        if len(ds)!=1 or aware(ds[0].get('event_time'))!=t:raise Blocked('EVENT_DETAIL_TIME_OR_IDENTITY_MISMATCH')
        if name in ENTRIES and aware(ds[0].get('entry_time'))!=t:raise Blocked('ENTRY_CONFIRMATION_TIME_MISMATCH')
        role='ENTRY' if name in ENTRIES else 'EXIT';side=(ENTRIES if role=='ENTRY' else EXITS)[name]
        eid=key([POLICY,VERSION,at,name])
        result.append(dict(id=eid,role=role,direction=side,event_at=at,source_event=name,
            qualified_at=ds[0].get('qualified_signal_time'),entry_reference_at=ds[0].get('entry_time') if role=='EXIT' else None,exit_reason=ds[0].get('exit_reason'),
            source_record_hash=record.get('record_hash'),source_sequence=record.get('sequence')))
    return result

class Bridge:
    def __init__(self,service,ownership_path,*,simulation_price='100',quantity=65,auto_fill_entries=False):
        if type(service) is not Service or type(service.broker) is not SimBroker:raise Blocked('SIMULATOR_ONLY_BRIDGE')
        positive_int(quantity)
        if type(auto_fill_entries) is not bool:raise Blocked('EXPLICIT_SIMULATION_AUTOFILL_FLAG_REQUIRED')
        if money(simulation_price)<=0:raise Blocked('SIMULATION_PRICE_REQUIRED')
        self.s=service;self.quantity=quantity;self.price=str(money(simulation_price));self.auto=auto_fill_entries
        self.scope='SIMULATOR:'+key([str(service.store.path.resolve())])
        if Path(ownership_path).resolve()==service.store.path.resolve():raise Blocked('OWNERSHIP_DB_MUST_BE_SEPARATE')
        self.ledger=Ledger(ownership_path,self.scope)
        with self.s.store.db() as d:d.execute('CREATE TABLE IF NOT EXISTS sim_bridge_events(id TEXT PRIMARY KEY,data TEXT NOT NULL)')
    @contextmanager
    def lock(self):
        fd=os.open(str(self.s.store.path)+'.bridge.lock',os.O_CREAT|os.O_RDWR,0o600)
        with os.fdopen(fd,'a') as f:
            fcntl.flock(f,fcntl.LOCK_EX)
            try:yield
            finally:fcntl.flock(f,fcntl.LOCK_UN)
    def rows(self):
        with self.s.store.db() as d:return [json.loads(r[0]) for r in d.execute('SELECT data FROM sim_bridge_events ORDER BY rowid')]
    def put(self,row):
        with self.s.store.db() as d:d.execute('INSERT OR REPLACE INTO sim_bridge_events VALUES(?,?)',(row['id'],encode(row)))
    def audit(self,kind,**kw):self.s.store.event(kind,self.s.now().isoformat(),**kw,production_execution_enabled=False)
    def stop(self,reason):
        with self.s.store.lock():self.s._block(reason)
    def _active(self,direction=None):
        intents={r['id']:r for r in self.s.store.intents()}
        for e in self.rows():
            row=intents.get(e.get('intent_id'))
            if e['role']!='ENTRY' or not row or direction and e['direction']!=direction:continue
            remaining,exits=self.s._remaining(row)
            if remaining or row['status'] not in TERMINAL or any(x['status'] not in TERMINAL for x in exits):return row
        return None
    def sync_ownership(self):
        with self.s.store.lock():
            self.s._session()
            if not self.s._reconcile():return dict(status='REVIEW_REQUIRED',reason='SIMULATOR_RECONCILIATION_REQUIRED')
            intents=self.s.store.intents();orders=self.s.broker.orders();fills=self.s.broker.fills();positions=self.s.broker.positions()
            captured=self.s.now()
        by_id={r['id']:r for r in intents};owned={}
        for event in self.rows():
            row=by_id.get(event.get('intent_id'))
            if event['role']!='ENTRY' or row is None:continue
            if row['instrument']!=event['instrument'] or row['quantity']!=self.quantity:raise Blocked('SIMULATOR_INTENT_MAPPING_MISMATCH')
            if not row.get('created_at'):raise Blocked('LEGACY_SIM_INTENT_PROVENANCE_MISSING')
            own=self.ledger.register_entry(signal_id=event['id'],signal_at=event['event_at'],intent_at=row['created_at'],
                direction=event['direction'],instrument=row['instrument'],product='SIM',quantity_=row['quantity'],policy_id=POLICY,strategy_version=VERSION)
            if not row.get('order_id'):return dict(status='REVIEW_REQUIRED',reason='SIM_ORDER_ACCEPTANCE_UNKNOWN')
            self.ledger.bind_order(intent_id=own,order_id=row['order_id'],at=row['created_at']);owned[row['id']]=own
        for row in intents:
            if row.get('parent') not in owned:continue
            if not row.get('created_at') or not row.get('order_id'):return dict(status='REVIEW_REQUIRED',reason='SIM_EXIT_EVIDENCE_UNAVAILABLE')
            own=self.ledger.register_exit(entry_id=owned[row['parent']],exit_key=row['id'],intent_at=row['created_at'],
                quantity_=row['quantity'],reason='SIMULATOR_EXIT')
            self.ledger.bind_order(intent_id=own,order_id=row['order_id'],at=row['created_at'])
        today=captured.date().isoformat();order_rows=[];trade_rows=[]
        for o in orders:
            if not o.get('created_at'):return dict(status='REVIEW_REQUIRED',reason='LEGACY_SIM_ORDER_PROVENANCE_MISSING')
            if aware(o['created_at']).astimezone(captured.tzinfo).date().isoformat()!=today:continue
            order_rows.append(dict(order_id=o['order_id'],instrument=o['instrument'],product='SIM',side=o['side'],quantity=o['quantity'],
                filled=o['filled'],pending=o['quantity']-o['filled'] if o['status'] not in TERMINAL else 0,status=o['status']))
        for f in fills:
            if f.get('evidence_mode')!='SIMULATOR_GENERATED':raise Blocked('NON_SIMULATOR_EXECUTION_REJECTED')
            if aware(f['filled_at']).astimezone(captured.tzinfo).date().isoformat()!=today:continue
            trade_rows.append(dict(order_id=f['order_id'],trade_id=f['trade_id'],instrument=f['instrument'],product='SIM',side=f['side'],
                quantity=f['quantity'],price=f['price'],filled_at=f['filled_at']))
        snapshot=dict(snapshot_id=uuid.uuid4().hex,account_scope=self.scope,evidence_mode='OFFLINE_FIXTURE',
            execution_origin='SIMULATOR_GENERATED',observed_at=captured.isoformat(),complete=True,
            orders=order_rows,trades=trade_rows,positions=[dict(instrument=k,product='SIM',quantity=q) for k,q in positions.items()])
        return self.ledger.reconcile(snapshot,as_of=captured.isoformat())
    def _exit(self,row):
        if row.get('position_id'):
            active=next((i for i in self.s.store.intents() if i['id']==row['position_id']),None)
        else:
            age=(self.s.now()-aware(row['event_at'])).total_seconds()
            if not 0<=age<=60 or aware(row['event_at']).astimezone(self.s.now().tzinfo).date()!=self.s.now().date():
                row.update(state='BLOCKED',reason='EXIT_SIGNAL_STALE_OR_FUTURE');self.put(row);return
            active=self._active(row['direction'])
            if active is not None and (not row.get('entry_reference_at') or aware(row['entry_reference_at'])!=aware(active['signal_at'])):
                row.update(state='BLOCKED',reason='EXIT_POSITION_REFERENCE_MISMATCH');self.put(row);self.stop(row['reason']);return
            if active is not None:row['position_id']=active['id'];self.put(row)
        if active is None:row.update(state='EXIT_FINISHED',reason='NO_OPEN_SIMULATOR_POSITION');self.put(row);return
        try:
            result=self.s.strategy_exit(position_id=active['id'],exit_id=key([row['id'],active['id'],'SELL']),price=self.price)
            row.update(state='EXIT_FINISHED' if result['status']=='FLAT_CONFIRMED' else 'WAIT_EXIT',reason=result['status'])
            self.put(row);self.audit('SIM_BRIDGE_STRATEGY_EXIT',event_id=row['id'],state=row['state'],remaining=result['remaining'])
        except Blocked as exc:
            row.update(state='WAIT_EXIT',reason=str(exc));self.put(row)
            self.audit('SIM_BRIDGE_EXIT_REQUIRES_RECONCILIATION',event_id=row['id'],reason=str(exc))
    def _entry(self,row):
        c=self.s.status()['control'];age=(self.s.now()-aware(row['event_at'])).total_seconds()
        if c['version']!=row['control_version'] or c['mode']!='ARMED':row.update(state='BLOCKED',reason='PAUSED_OR_CONTROL_VERSION_CHANGED')
        elif not 0<=age<=60 or aware(row['event_at']).astimezone(self.s.now().tzinfo).date()!=self.s.now().date():row.update(state='BLOCKED',reason='ENTRY_SIGNAL_STALE_OR_FUTURE')
        elif self._active():row.update(state='WAIT_EXIT' if row.get('paired_exit') else 'BLOCKED',reason='EXISTING_SIM_EXPOSURE_OR_ORDER')
        else:
            proof=self.sync_ownership()
            if proof['status']!='RECONCILED_OFFLINE_FIXTURE':row.update(state='BLOCKED',reason='OWNERSHIP_RECONCILIATION_REQUIRED');self.stop('SIM_BRIDGE_OWNERSHIP_REVIEW')
            else:
                row['state']='SUBMITTING';self.put(row) # durable before central submission gate
                try:
                    result=self.s.submit_entry(signal_id=row['id'],signal_at=row['event_at'],instrument=row['instrument'],quantity=self.quantity,price=self.price)
                    row.update(state='SUBMITTED',intent_id=result['id'],reason=result['status'])
                    self.put(row)
                    if self.auto and result['status']=='OPEN':
                        self.s.broker.fill(result['id'],self.quantity,self.price)
                except Blocked as exc:row.update(state='BLOCKED',reason=str(exc))
        self.put(row);self.audit('SIM_BRIDGE_ENTRY_DECISION',event_id=row['id'],state=row['state'],reason=row['reason'])
    def _poll(self):
        for row in self.rows():
            if row['state']=='SUBMITTING':
                expected=hashlib.sha256((aware(row['event_at']).astimezone(self.s.now().tzinfo).date().isoformat()+'|'+row['id']).encode()).hexdigest()
                found=next((i for i in self.s.store.intents() if i['id']==expected),None)
                if found:row.update(state='SUBMITTED',intent_id=found['id'],reason='RECOVERED_DURABLE_SIM_INTENT')
                else:row.update(state='BLOCKED',reason='INTERRUPTED_SUBMISSION_REQUIRES_REVIEW');self.stop(row['reason'])
                self.put(row)
            if row['state']=='WAIT_EXIT' and row['role']=='EXIT':self._exit(row)
        for row in self.rows():
            if row['state']=='WAIT_EXIT' and row['role']=='ENTRY':self._entry(row)
    def process(self,record):
        try:events=accepted(record)
        except Exception:
            self.stop('SIM_BRIDGE_SOURCE_REJECTED');raise
        with self.lock():
            self._poll()
            for e in events:
                old=next((x for x in self.rows() if x['id']==e['id']),None)
                fingerprint=key([{k:v for k,v in e.items() if k not in {'source_record_hash','source_sequence'}},self.quantity,self.price])
                if old:
                    if old['fingerprint']!=fingerprint:self.stop('SIM_BRIDGE_EVENT_CONFLICT');raise Blocked('SIM_BRIDGE_EVENT_CONFLICT')
                    continue
                control=self.s.status()['control'];e.update(fingerprint=fingerprint,state='NEW',control_version=control['version'],
                    paired_exit=any(x['role']=='EXIT' for x in events),instrument='SIMULATOR|'+('CE' if e['direction']=='BULLISH' else 'PE'))
                self.put(e)
                if e['role']=='EXIT':self._exit(e)
                else:self._entry(e)
            proof=self.sync_ownership()
            return dict(model=MODEL,events=self.rows(),ownership_status=proof,simulation_only=True,
                execution_prices='SYNTHETIC_CONFIGURED_PRICE',orders_sent_to_upstox=False,production_execution_enabled=False)
    def poll(self):
        with self.lock():self._poll();return self.sync_ownership()

    def run_source_once(self,path):
        """Read live strategy journal into SIMULATOR only, baseline on first use."""
        lock_path=str(self.s.store.path)+'.source.lock'
        fd=os.open(lock_path,os.O_CREAT|os.O_RDWR,0o600)
        with os.fdopen(fd,'a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            try:
                records=verified_records(path)
                source=str(Path(path).resolve())
                with self.s.store.db() as d:
                    d.execute('CREATE TABLE IF NOT EXISTS sim_bridge_source(id INTEGER PRIMARY KEY,data TEXT NOT NULL)')
                    previous=d.execute('SELECT data FROM sim_bridge_source WHERE id=1').fetchone()
                    previous=json.loads(previous[0]) if previous else None
                    if previous is None:
                        cursor=dict(path=source,sequence=len(records),hash=records[-1]['record_hash'] if records else None)
                        d.execute('INSERT INTO sim_bridge_source VALUES(1,?)',(encode(cursor),))
                        return dict(status='BASELINED_WAIT_NEXT_FRESH_SIGNAL',source_sequence=len(records),production_execution_enabled=False)
                if previous['path']!=source or previous['sequence']>len(records):raise Blocked('SOURCE_CHANGED_OR_TRUNCATED')
                if previous['sequence'] and records[previous['sequence']-1]['record_hash']!=previous['hash']:raise Blocked('SOURCE_PREFIX_REPLACED')
                count=0
                self.poll()
                for row in records[previous['sequence']:]:
                    p=row.get('payload') or {}
                    # Old policy versions and old sessions remain audit history, not executable input.
                    stamp=p.get('decision_timestamp') or p.get('cutoff_timestamp')
                    relevant=row.get('stage') in {'DIRECTIONAL_DECISION','DIRECTIONAL_SESSION_CUTOFF'} and p.get('policy_id')==POLICY and stamp is not None
                    if relevant and aware(stamp).astimezone(IST).date()==self.s.now().date() and p.get('strategy_version')!=VERSION:raise Blocked('SOURCE_POLICY_OR_VERSION_MISMATCH')
                    if relevant and aware(stamp).astimezone(IST).date()==self.s.now().date():
                        self.process(row);count+=1
                    cursor=dict(path=source,sequence=row['sequence'],hash=row['record_hash'])
                    with self.s.store.db() as d:d.execute('UPDATE sim_bridge_source SET data=? WHERE id=1',(encode(cursor),))
                return dict(status='SIMULATOR_SOURCE_PROCESSED',processed_records=count,source_sequence=len(records),
                            production_execution_enabled=False,orders_sent_to_upstox=False)
            except Exception:
                self.stop('SIM_BRIDGE_SOURCE_RECONCILIATION_REQUIRED');raise
            finally:fcntl.flock(lock,fcntl.LOCK_UN)
