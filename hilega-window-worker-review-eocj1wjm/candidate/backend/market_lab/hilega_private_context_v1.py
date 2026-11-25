"""Pinned private candidate context and GET-only providers. No key provisioning or enrollment."""
from contextlib import closing
from copy import deepcopy
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
from types import SimpleNamespace

MODEL='HILEGA_PINNED_PRIVATE_CANDIDATE_CONTEXT_V1'
FIELDS={'model','production_execution_enabled','application_db','adapter_db','journal','seed_request_id','bridge_run_id',
    'pin_file','pin_sha256','authority_file','authority_sha256','broker_token_file','broker_token_sha256','issued_at','expires_at'}
CONTRACT_FIELDS=('instrument_key','underlying_key','instrument_type','segment','exchange','expiry',
    'strike_price','lot_size','minimum_lot','freeze_quantity','tick_size')


def need(ok,reason):
    if not ok:raise ValueError(reason)


def sha(raw):return hashlib.sha256(raw).hexdigest()


def private_read(path,limit=16384):
    p=Path(path);need(p.is_absolute() and not any(q.is_symlink() for q in [p,*p.parents]),'PRIVATE_ABSOLUTE_REGULAR_PATH_REQUIRED')
    parent=p.parent.stat();need(parent.st_uid==os.getuid() and stat.S_IMODE(parent.st_mode)&0o077==0,'PRIVATE_PARENT_REQUIRED')
    fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as stream:
        info=os.fstat(stream.fileno())
        need(stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid() and stat.S_IMODE(info.st_mode)&0o077==0
             and info.st_nlink==1 and info.st_size<=limit,'PRIVATE_OWNER_ONLY_FILE_REQUIRED')
        return stream.read(limit+1)


def capture_owned(token,pin,contract,quantity,clock):
    from market_lab.hilega_preparation_runtime_v1.collect import collectors
    from market_lab.hilega_preparation_runtime_v1.evidence import MODEL as BUNDLE_MODEL,MODE,FLAGS,fresh_window
    from market_lab.hilega_production_account_adapter_v1 import Client,matches,sign,day
    from owned_exit_pricing_candidate import review_owned_quote
    rules,market_module,_,_=collectors()
    account=Client(token);market=market_module.MarketClient(token);start=clock()
    matches(account.get('profile'),pin);opening=market.get('market')
    rows=market.get('contracts');key=contract['instrument_key']
    selected=[{k:r[k] for k in CONTRACT_FIELDS} for r in rows if isinstance(r,dict) and r.get('instrument_key')==key]
    need(len(selected)==1 and selected[0]==contract,'EXACT_OWNED_CONTRACT_REQUIRED')
    quote=rules.quote_map(market.get('quotes',[key]),[key])[key]
    safe={k:quote[k] for k in ('instrument_token','last_price','timestamp','last_trade_time','volume')}
    safe['depth']={side:[{k:d[k] for k in ('price','quantity')} for d in quote['depth'][side]] for side in ('buy','sell')}
    closing_market=market.get('market');matches(account.get('profile'),pin);end=clock()
    fresh_window(start.isoformat(),end.isoformat(),end.isoformat())
    value=dict(model=BUNDLE_MODEL,evidence_mode=MODE,account_scope=pin['scope'],
        snapshot_id='OWNED-'+os.urandom(16).hex(),started_at=start.isoformat(),completed_at=end.isoformat(),session_date=day(end),
        profile_verified_before_and_after=True,market_before={k:opening[k] for k in ('exchange','status')},
        market_after={k:closing_market[k] for k in ('exchange','status')},contracts=selected,quotes={key:safe},**FLAGS)
    value['signature']=sign(value,pin)
    review_owned_quote(value,pin,contract,quantity=quantity,as_of=end.isoformat())
    return value


class LiveProviders:
    def __init__(self,source,pin,token,clock,check):
        self.source,self.pin,self.token,self.clock,self.check=source,deepcopy(pin),token,clock,check

    def account(self):
        self.check()
        from market_lab.hilega_production_account_adapter_v1 import Client,capture
        return capture(Client(self.token()),self.pin,clock=self.clock)

    def entry_market(self):
        self.check()
        from market_lab.hilega_preparation_runtime_v1.collect import capture
        return capture(self.token(),self.pin)

    def entry(self,kind):
        self.check();need(kind in {'first','history'},'EXACT_ENTRY_CAPTURE_KIND_REQUIRED')
        if kind=='first':return self.entry_market()
        return dict(account=self.account(),market=self.entry_market())

    def exit(self):
        self.check();path=self.source.s.store.path
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=3)) as db:
            db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
            rows=db.execute('SELECT data FROM preparation_plans LIMIT 2').fetchall()
            need(len(rows)==1,'SINGLE_ACTIVE_OWNED_PLAN_REQUIRED');plan=json.loads(rows[0][0])
            need(plan['account_scope']==self.pin['scope'],'OWNED_PLAN_ACCOUNT_CHANGED')
            contract=deepcopy(plan['evidence']['contract']);quantity=plan['quantity'];db.rollback()
        return dict(account=self.account(),market=capture_owned(self.token(),self.pin,contract,quantity,self.clock))

    def next(self,event):
        self.check();need(isinstance(event,dict) and event.get('role')=='ENTRY','FRESH_ENTRY_EVENT_REQUIRED')
        return dict(account=self.account(),market=self.entry_market())


class PrivateContextLoader:
    def __init__(self,source,adapter_store,journal,config_path,expected_config_sha256,*,clock=lambda:datetime.now(timezone.utc)):
        self.source,self.store,self.journal=source,adapter_store,journal
        self.config_path,self.expected=Path(config_path),expected_config_sha256;self.clock=clock

    def __call__(self):
        from market_lab.hilega_execution_port_v1 import adapter as port
        port.require_live_clearance() # Direct loader invocation is also closed before private I/O.
        raw=private_read(self.config_path);need(sha(raw)==self.expected,'APPROVED_PRIVATE_CONFIG_CHANGED')
        config=json.loads(raw);need(type(config) is dict and set(config)==FIELDS
            and config['model']==MODEL and config['production_execution_enabled'] is False,'EXACT_CANDIDATE_PRIVATE_CONFIG_REQUIRED')
        from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import aware
        def check():
            need(sha(private_read(self.config_path))==self.expected,'APPROVED_PRIVATE_CONFIG_CHANGED')
            now=self.clock();issued=aware(config['issued_at']);expires=aware(config['expires_at'])
            need(issued<=now<expires and 0<(expires-issued).total_seconds()<=86400,'PRIVATE_CONTEXT_EXPIRED_OR_FUTURE')
            for stem in ('pin','authority'):
                need(sha(private_read(Path(config[stem+'_file'])))==config[stem+'_sha256'],'PRIVATE_IDENTITY_FILE_CHANGED')
        check()
        from market_lab.hilega_production_account_adapter_v1 import read_pin
        from existing_request_attempt_v1 import authority_check
        from market_lab.hilega_exclusive_closed_route_v1 import _guarded_source,_verify,TABLE
        _guarded_source(self.source)
        for name in ('application_db','adapter_db','journal'):
            path=Path(config[name])
            need(path.is_absolute() and path.is_file() and not any(p.is_symlink() for p in [path,*path.parents]),'REGULAR_ABSOLUTE_CONTEXT_BINDING_REQUIRED')
        need(type(self.store) is port.Store and self.store.mode=='LIVE_CLOSED'
            and self.store.path.resolve()==Path(config['adapter_db']).resolve()
            and self.source.s.store.path.resolve()==Path(config['application_db']).resolve()
            and Path(self.journal).resolve()==Path(config['journal']).resolve()
            and self.source.run_id==config['bridge_run_id'],'CONTEXT_SOURCE_STORE_OR_LEASE_CHANGED')
        pin=read_pin(Path(config['pin_file']));authority=json.loads(private_read(Path(config['authority_file'])))
        need(type(authority) is dict and set(authority)=={'account_scope','authority_id','key'},'EXACT_LOCAL_AUTHORITY_CONTEXT_REQUIRED')
        authority_check(authority,pin);need(self.store.scope==pin['scope'],'CONTEXT_ACCOUNT_SCOPE_CHANGED')
        with closing(sqlite3.connect(self.store.path.resolve().as_uri()+'?mode=ro',uri=True,timeout=3)) as db:
            db.execute('PRAGMA query_only=ON')
            meta=db.execute('SELECT data FROM meta WHERE id=1').fetchone()
            need(meta is not None and json.loads(meta[0])==dict(scope=pin['scope'],mode='LIVE_CLOSED'),'CURRENT_ADAPTER_META_CHANGED')
        def token():
            check();value=private_read(Path(config['broker_token_file']),4096)
            need(sha(value)==config['broker_token_sha256'],'BROKER_TOKEN_FILE_CHANGED')
            text=value.decode().strip();need(text and '\n' not in text and '\r' not in text,'SINGLE_BROKER_TOKEN_REQUIRED');return text
        adapter=port.Adapter(self.store,port.HttpTransport(token))
        with closing(sqlite3.connect(self.source.s.store.path.resolve().as_uri()+'?mode=ro',uri=True,timeout=3)) as db:
            db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
            need(db.execute("SELECT 1 FROM sqlite_master WHERE name=?",(TABLE,)).fetchone() is not None,'EXPLICIT_ROUTE_ENROLLMENT_REQUIRED')
            row=db.execute('SELECT data FROM '+TABLE+' WHERE id=1').fetchone();need(row is not None,'SIGNED_ROUTE_OWNER_REQUIRED')
            context=SimpleNamespace(app=self.source.s.store,adapter=adapter,pin=pin,authority=authority,journal=Path(self.journal),
                seed=config['seed_request_id'],bridge=config['bridge_run_id'])
            _verify(context,json.loads(row[0]));db.rollback()
        providers=LiveProviders(self.source,pin,token,self.clock,check)
        return dict(adapter=adapter,pin=pin,authority=authority,seed_request_id=config['seed_request_id'],
            bridge_run_id=config['bridge_run_id'],providers=dict(entry=providers.entry,account=providers.account,exit=providers.exit,next=providers.next),clock=self.clock)
