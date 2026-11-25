"""Durable simulation state. Writes only this strategy's private SQLite journal."""
from datetime import date, datetime, time, timedelta
from contextlib import closing
from pathlib import Path
import json
import sqlite3
from . import STRATEGY_ID, VERSION
from .calendar import IST, SPECIAL, session_day, validate_rows
from .data import OWN_ROOT, aggregate, digest, seed, code_hash
from .engine import Engine


def normalize_prefix(raw, day, now):
    # Reuse strict OHLC/time/volume validation by extending only the validation
    # envelope; padded rows are never fed into indicators, marks or journal.
    start=datetime.combine(day,time(14,20) if day==SPECIAL else time(9,15),IST)
    count=70 if day==SPECIAL else 375
    if not raw:return [],[]
    if len(raw)>count:raise ValueError('EXCESS_MINUTES')
    raw=sorted(raw,key=lambda r:r['timestamp'])
    for i,r in enumerate(raw):
        at=datetime.fromisoformat(r['timestamp'])
        if at.tzinfo is None or at.astimezone(IST)!=start+timedelta(minutes=i):
            raise ValueError('LIVE_MINUTE_COVERAGE_INVALID')
        if at>now:raise ValueError('FUTURE_MINUTE')
    tail=raw[-1]
    padded=raw+[dict(tail,timestamp=(start+timedelta(minutes=i)).isoformat()) for i in range(len(raw),count)]
    checked=validate_rows(padded,day)[:len(raw)]
    completed=[r for r in checked if datetime.fromisoformat(r['timestamp'])+timedelta(minutes=1)<=now]
    # The next minute open is a modeled reference; no forming high/low/close may
    # affect indicators or extrema. Incomplete rows are not durably committed.
    references=[dict(timestamp=r['timestamp'],open=r['open']) for r in checked[len(completed):]]
    return completed,references


class Store:
    def __init__(self, repo):
        self.repo=Path(repo)
        self.path=self.repo/OWN_ROOT/'live.sqlite3'
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with closing(self.connect()) as db:
            db.execute('CREATE TABLE IF NOT EXISTS sessions(day TEXT PRIMARY KEY, identity TEXT NOT NULL, state TEXT NOT NULL, minutes TEXT NOT NULL, observed TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS health(id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL)')

    def connect(self):
        db=sqlite3.connect(self.path,timeout=30,isolation_level=None)
        db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA synchronous=FULL')
        return db

    def health(self, status, **details):
        payload=dict(status=status,observed_at=datetime.now(IST).isoformat(),**details)
        with closing(self.connect()) as db:db.execute('INSERT OR REPLACE INTO health VALUES(1,?)',(json.dumps(payload),))

    def ingest(self, day, raw, now, warmup=None, evidence=None):
        if now.tzinfo is None:raise ValueError('OBSERVATION_TIMEZONE_REQUIRED')
        now=now.astimezone(IST)
        if not session_day(day) or now.date()<day:raise ValueError('INVALID_LIVE_SESSION')
        complete,forming=normalize_prefix(raw,day,now)
        if warmup is None:warmup,evidence=seed(self.repo,day)
        identity=dict(strategy_id=STRATEGY_ID,version=VERSION,code_sha256=code_hash(),seed=evidence)
        db=self.connect()
        try:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT identity,state,minutes FROM sessions WHERE day=?',(str(day),)).fetchone()
            if row:
                if json.loads(row[0])!=identity:raise ValueError('LIVE_RULES_OR_SEED_CHANGED_REVIEW_REQUIRED')
                state=json.loads(row[1]);old=json.loads(row[2]);engine=Engine.restore(state)
                if len(complete)<len(old) or complete[:len(old)]!=old:
                    raise ValueError('SOURCE_REVISION_OR_REGRESSION_REQUIRES_REVIEW')
                old_count=len(engine.audits)
                # A modeled reference open already used by a committed event is immutable.
                opens={r['timestamp']:r['open'] for r in complete+forming}
                for audit in engine.audits:
                    if audit['decision_time'].endswith('T15:30:00+05:30'):continue
                    if audit['decision_time'] not in opens or opens[audit['decision_time']]!=audit['modeled_reference_price']:
                        raise ValueError('REFERENCE_OPEN_REVISION_REQUIRES_REVIEW')
            else:
                engine=Engine(str(day),warmup);old_count=0
            grid=complete[1:] if day==SPECIAL else complete
            ready=aggregate(grid[:len(grid)//3*3]);references=complete+forming
            available={r['timestamp'] for r in references};pending=None
            for bar in ready[len(engine.audits):]:
                boundary=datetime.fromisoformat(bar['start'])+timedelta(minutes=3)
                if boundary.time()!=time(15,30) and boundary.isoformat() not in available:
                    pending=boundary.isoformat();break
                audit=engine.advance(bar,references)
                audit.update(observed_at=now.isoformat(),latency_seconds=(now-boundary).total_seconds(),
                    recovered=(not row or (now-boundary).total_seconds()>180),
                    modeled_reference_price=next(r['close'] for r in complete if r['timestamp']==(boundary-timedelta(minutes=1)).isoformat()) if boundary.time()==time(15,30) else next(r['open'] for r in references if r['timestamp']==boundary.isoformat()),
                    mark_basis='EXACT_1529_CLOSE_MODELED' if boundary.time()==time(15,30) else 'NEXT_1M_OPEN_MODELED',
                    execution_mode='SIMULATION_ONLY')
            db.execute('INSERT OR REPLACE INTO sessions VALUES(?,?,?,?,?)',
                (str(day),json.dumps(identity),json.dumps(engine.snapshot(),allow_nan=False),json.dumps(complete),now.isoformat()))
            last_boundary=datetime.fromisoformat(engine.audits[-1]['decision_time']) if engine.audits else None
            age=(now-last_boundary).total_seconds() if last_boundary else None
            status=('SESSION_COMPLETE' if len(engine.audits)==(23 if day==SPECIAL else 125) else
                    'PENDING_REFERENCE_OPEN' if pending else 'WAITING_FOR_COMPLETED_3M_BAR' if not engine.audits else
                    'STALE_CANDLE_DATA' if age>240 else 'OK')
            health=dict(status=status,completed_bar_age_seconds=age,
                        data_through=(datetime.fromisoformat(complete[-1]['timestamp'])+timedelta(minutes=1)).isoformat() if complete else None,
                        observed_at=now.isoformat(),
                        session_date=str(day),last_completed_bar=engine.audits[-1]['decision_time'] if engine.audits else None,
                        pending_boundary=pending,new_audits=len(engine.audits)-old_count)
            db.execute('INSERT OR REPLACE INTO health VALUES(1,?)',(json.dumps(health),))
            db.commit()
            return dict(engine.result(),health=health,status='LIVE_SIMULATION')
        except BaseException:
            db.rollback();raise
        finally:db.close()

    def view(self, day):
        with closing(self.connect()) as db:
            row=db.execute('SELECT state,observed FROM sessions WHERE day=?',(str(day),)).fetchone()
            h=db.execute('SELECT body FROM health WHERE id=1').fetchone()
        health=json.loads(h[0]) if h else {'status':'WORKER_NOT_OBSERVED'}
        if not row:return dict(strategy_id=STRATEGY_ID,strategy_version=VERSION,status='NOT_PROCESSED',
                               session_date=str(day),audit=[],trades=[],owner=None,health=health)
        result=Engine.restore(json.loads(row[0])).result()
        result.update(status='LIVE_SIMULATION',health=health,last_ingested_at=row[1])
        result['observation_age_seconds']=(datetime.now(IST)-datetime.fromisoformat(row[1])).total_seconds()
        return result
