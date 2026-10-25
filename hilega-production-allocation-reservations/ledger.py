"""Offline allocation reservations. No broker transport or production permission."""
import hashlib,json,os,sqlite3
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal,InvalidOperation,ROUND_DOWN,ROUND_UP
from pathlib import Path
from zoneinfo import ZoneInfo
IST=ZoneInfo('Asia/Kolkata')
class Blocked(ValueError):pass

def canonical(v):return json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False)
def money(v):
    if isinstance(v,bool) or not isinstance(v,(str,int,float,Decimal)):raise Blocked('INVALID_AMOUNT')
    try:d=Decimal(str(v))
    except InvalidOperation:raise Blocked('INVALID_AMOUNT') from None
    if not d.is_finite() or d<0:raise Blocked('INVALID_AMOUNT')
    return d

def cents(v,up=False):
    return int((money(v)*100).to_integral_value(rounding=ROUND_UP if up else ROUND_DOWN))
def display(v):return str((Decimal(v)/100).quantize(Decimal('.01')))
def aware(v):
    try:t=datetime.fromisoformat(v)
    except (ValueError,TypeError):raise Blocked('INVALID_TIMESTAMP') from None
    if t.tzinfo is None:raise Blocked('AWARE_TIMESTAMP_REQUIRED')
    return t.astimezone(IST)
def identity(v):
    if not isinstance(v,str) or not 1<=len(v)<=200 or any(ord(c)<32 for c in v):raise Blocked('INVALID_IDENTITY')
    return v

def cost(legs):
    if not isinstance(legs,list) or not 1<=len(legs)<=5:raise Blocked('ONE_TO_FIVE_LEGS_REQUIRED')
    seen=set();offsets=set();sides=set();total=0
    for leg in legs:
        if not isinstance(leg,dict):raise Blocked('LEG_SCHEMA_INVALID')
        key=identity(leg.get('instrument'))
        if key in seen:raise Blocked('DUPLICATE_INSTRUMENT')
        seen.add(key);side=leg.get('side');sides.add(side)
        offset=leg.get('offset')
        if type(offset)is not int or offset not in range(-2,3) or offset in offsets:raise Blocked('INVALID_OR_DUPLICATE_OFFSET')
        offsets.add(offset)
        lot=leg.get('lot_size');lots=leg.get('lots');qty=leg.get('quantity')
        if any(type(x)is not int or x<=0 for x in (lot,lots,qty)) or qty!=lot*lots:raise Blocked('LOT_QUANTITY_MISMATCH')
        ask=money(leg.get('ask'));buffer=money(leg.get('buffer'))
        if ask<=0:raise Blocked('POSITIVE_ASK_REQUIRED')
        total+=cents(ask*qty+buffer,up=True)
    if len(sides)!=1 or not sides<= {'CE','PE'}:raise Blocked('ONE_DIRECTIONAL_BASKET_ONLY')
    return total

class Ledger:
    """One account per isolated SQLite DB. BEGIN IMMEDIATE serializes writers."""
    def __init__(self,path,account):
        self.path=Path(path);self.account=identity(account);self.path.parent.mkdir(parents=True,exist_ok=True)
        fd=os.open(self.path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600);os.close(fd)
        if self.path.is_symlink():raise Blocked('DB_SYMLINK_REJECTED')
        with self.tx() as d:
            d.executescript('''CREATE TABLE IF NOT EXISTS allocation_account(id INTEGER PRIMARY KEY,data TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS allocation_snapshots(id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,data TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS allocation_reservations(id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,data TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS allocation_evidence(id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,data TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS allocation_events(seq INTEGER PRIMARY KEY AUTOINCREMENT,data TEXT NOT NULL);''')
            row=d.execute('SELECT data FROM allocation_account WHERE id=1').fetchone()
            if row and json.loads(row[0])['account']!=self.account:raise Blocked('ACCOUNT_SCOPE_MISMATCH')
            if not row:d.execute('INSERT INTO allocation_account VALUES(1,?)',(canonical(dict(account=self.account)),))
    @contextmanager
    def tx(self):
        d=sqlite3.connect(self.path,timeout=15);d.execute('PRAGMA synchronous=FULL');d.execute('BEGIN IMMEDIATE')
        try:yield d;d.commit()
        except BaseException:d.rollback();raise
        finally:d.close()
    def _event(self,d,kind,at,**kw):d.execute('INSERT INTO allocation_events(data) VALUES(?)',(canonical(dict(type=kind,at=at,**kw)),))
    def _rows(self,d):return [json.loads(r[0]) for r in d.execute('SELECT data FROM allocation_reservations ORDER BY rowid')]
    def snapshot(self,snapshot_id,*,cash,observed_at,as_of,session_date):
        identity(snapshot_id);at=aware(as_of);observed=aware(observed_at)
        if at.date().isoformat()!=session_date or observed.date()!=at.date() or not 0<=(at-observed).total_seconds()<=30:raise Blocked('FUNDS_STALE_OR_WRONG_SESSION')
        payload=dict(account=self.account,cash=str(money(cash)),observed_at=observed.isoformat(),session_date=session_date,
                     evidence_mode='OFFLINE_FIXTURE',production_execution_enabled=False)
        fp=hashlib.sha256(canonical(payload).encode()).hexdigest()
        with self.tx() as d:
            old=d.execute('SELECT fingerprint FROM allocation_snapshots WHERE id=?',(snapshot_id,)).fetchone()
            if old and old[0]!=fp:raise Blocked('SNAPSHOT_ID_REUSED_WITH_DIFFERENT_DATA')
            latest=d.execute('SELECT data FROM allocation_snapshots ORDER BY rowid DESC LIMIT 1').fetchone()
            if latest and observed<aware(json.loads(latest[0])['observed_at']):raise Blocked('FUNDS_TIME_REGRESSION')
            if not old:
                d.execute('INSERT INTO allocation_snapshots VALUES(?,?,?)',(snapshot_id,fp,canonical(payload)))
                self._event(d,'FUNDS_FIXTURE_RECORDED',at.isoformat(),snapshot_id=snapshot_id)
        return dict(snapshot_id=snapshot_id,**payload)
    def reserve(self,reservation_id,*,signal_id,snapshot_id,legs,as_of,session_date):
        identity(reservation_id);identity(signal_id);at=aware(as_of)
        if at.date().isoformat()!=session_date:raise Blocked('SESSION_MISMATCH')
        requested=cost(legs)
        payload=dict(signal_id=signal_id,snapshot_id=snapshot_id,legs=legs,session_date=session_date)
        fp=hashlib.sha256(canonical(payload).encode()).hexdigest()
        with self.tx() as d:
            old=d.execute('SELECT fingerprint,data FROM allocation_reservations WHERE id=?',(reservation_id,)).fetchone()
            if old:
                if old[0]!=fp:raise Blocked('RESERVATION_ID_REUSED_WITH_DIFFERENT_PLAN')
                return dict(json.loads(old[1]),idempotent_replay=True)
            rows=self._rows(d)
            if any(r['signal_id']==signal_id and r['session_date']==session_date for r in rows):raise Blocked('SIGNAL_ALREADY_CONSUMED')
            latest=d.execute('SELECT id,data FROM allocation_snapshots ORDER BY rowid DESC LIMIT 1').fetchone()
            if not latest or latest[0]!=snapshot_id:raise Blocked('LATEST_FUNDS_SNAPSHOT_REQUIRED')
            funds=json.loads(latest[1]);observed=aware(funds['observed_at'])
            if funds['session_date']!=session_date or not 0<=(at-observed).total_seconds()<=30:raise Blocked('FUNDS_STALE_OR_WRONG_SESSION')
            if any(r['state']=='UNKNOWN' for r in rows):raise Blocked('UNKNOWN_ORDER_OUTCOME_REQUIRES_REVIEW')
            # Whole holds across sessions remain until explicit terminal evidence.
            held=sum(r['held_cents'] for r in rows)
            cap=cents(money(funds['cash'])*Decimal('.50'))
            if requested<=0 or requested+held>cap:raise Blocked('HALF_CASH_CAP_EXCEEDED')
            row=dict(id=reservation_id,account=self.account,signal_id=signal_id,session_date=session_date,snapshot_id=snapshot_id,
                legs=legs,amount_cents=requested,held_cents=requested,state='RESERVED',created_at=at.isoformat(),
                production_execution_enabled=False,evidence_mode='OFFLINE_FIXTURE')
            d.execute('INSERT INTO allocation_reservations VALUES(?,?,?)',(reservation_id,fp,canonical(row)))
            self._event(d,'BASKET_RESERVED',at.isoformat(),reservation_id=reservation_id,amount=display(requested),cap=display(cap),prior_holds=display(held))
            return row
    def evidence(self,evidence_id,reservation_id,*,state,as_of,terminal_no_exposure=False):
        """Explicit OFFLINE aggregate evidence; NEVER call with unverified live rows.
        No filled/partial/unknown order releases funds. RELEASED requires trusted
        aggregate terminal/no-exposure confirmation supplied by offline fixture.
        """
        identity(evidence_id);identity(reservation_id);at=aware(as_of)
        valid={'RESERVED','SUBMITTED','PARTIAL','FILLED','UNKNOWN','RELEASED'}
        if state not in valid or type(terminal_no_exposure)is not bool:raise Blocked('INVALID_EVIDENCE_STATE')
        if state=='RELEASED' and not terminal_no_exposure:raise Blocked('TERMINAL_NO_EXPOSURE_PROOF_REQUIRED')
        payload=dict(reservation_id=reservation_id,state=state,terminal_no_exposure=terminal_no_exposure,at=at.isoformat())
        fp=hashlib.sha256(canonical(payload).encode()).hexdigest()
        with self.tx() as d:
            old=d.execute('SELECT fingerprint,data FROM allocation_evidence WHERE id=?',(evidence_id,)).fetchone()
            if old:
                if old[0]!=fp:raise Blocked('EVIDENCE_ID_CONFLICT')
                current=d.execute('SELECT data FROM allocation_reservations WHERE id=?',(reservation_id,)).fetchone()
                return dict(json.loads(old[1]),idempotent_replay=True,current_state=json.loads(current[0])['state'])
            found=d.execute('SELECT data FROM allocation_reservations WHERE id=?',(reservation_id,)).fetchone()
            if not found:raise Blocked('RESERVATION_NOT_FOUND')
            row=json.loads(found[0]);prior=row['state'];previous_at=aware(row.get('updated_at',row['created_at']))
            if at<previous_at:raise Blocked('EVIDENCE_TIME_REGRESSION')
            allowed={'RESERVED':{'SUBMITTED','UNKNOWN','RELEASED'},'SUBMITTED':{'PARTIAL','FILLED','UNKNOWN','RELEASED'},
                     'PARTIAL':{'PARTIAL','FILLED','UNKNOWN','RELEASED'},'FILLED':{'UNKNOWN','RELEASED'},
                     'UNKNOWN':{'SUBMITTED','PARTIAL','FILLED','UNKNOWN','RELEASED'},'RELEASED':set()}
            if state not in allowed[prior]:raise Blocked('EVIDENCE_STATE_REGRESSION_OR_TERMINAL')
            row.update(state=state,updated_at=at.isoformat(),held_cents=0 if state=='RELEASED' else row['amount_cents'])
            d.execute('UPDATE allocation_reservations SET data=? WHERE id=?',(canonical(row),reservation_id))
            d.execute('INSERT INTO allocation_evidence VALUES(?,?,?)',(evidence_id,fp,canonical(row)))
            self._event(d,'RESERVATION_EVIDENCE',at.isoformat(),reservation_id=reservation_id,before=prior,after=state,held=display(row['held_cents']))
            return row
    def status(self):
        with self.tx() as d:
            rows=self._rows(d);events=[json.loads(x[0]) for x in d.execute('SELECT data FROM allocation_events ORDER BY seq')]
        return dict(model='HILEGA_OFFLINE_ALLOCATION_RESERVATIONS_V1',reservations=rows,held_total=display(sum(x['held_cents'] for x in rows)),
            events=events,entry_permission=False,production_execution_enabled=False,orders_sent=False,
            integration_status='NOT_WIRED_TO_EXECUTION',evidence_mode='OFFLINE_FIXTURE')
