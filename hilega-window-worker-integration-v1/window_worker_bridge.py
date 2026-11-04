"""Explicit disabled-window seed boundary observer. Never arms, enrolls or submits an order."""
import hashlib,json,os,sqlite3,time,uuid
from pathlib import Path
FIELDS={'model','release_sha256','application_db','adapter_db','journal','pin_file','window_state','receipt_file','production_execution_enabled'}
def need(ok,reason):
    if not ok:raise ValueError(reason)
def sha(b):return hashlib.sha256(b).hexdigest()
def pause(source):
    c=source.s.store.control();source.s.command('pause',request_id=uuid.uuid4().hex,expected_version=c['version'],session_date=c['session_date'],actor='DISABLED_WINDOW_BOUNDARY')
def observe(source,journal,result):
    config=os.environ.get('HILEGA_DISABLED_WINDOW_CONFIG');digest=os.environ.get('HILEGA_DISABLED_WINDOW_CONFIG_SHA256')
    if config is None and digest is None:return result
    base=result if isinstance(result,dict) else {}
    try:
        from market_lab.hilega_execution_port_v1 import adapter as port
        from market_lab.hilega_preparation_runtime_v1.source import Source
        from market_lab.hilega_production_simulator_bridge_v1 import Bridge
        need(type(source) in {Source,Bridge},'EXACT_NATIVE_WINDOW_SOURCE_REQUIRED')
        try:port.require_live_clearance()
        except port.GateClosed:pass
        else:raise ValueError('WINDOW_OBSERVER_REQUIRES_ORDER_GATE_CLOSED')
        need(config and digest,'EXACT_WINDOW_CONFIG_REQUIRED')
        from market_lab.hilega_private_context_v1 import private_read
        from market_lab.hilega_production_account_adapter_v1 import read_pin,sign
        raw=private_read(Path(config));need(sha(raw)==digest,'WINDOW_CONFIG_CHANGED');cfg=json.loads(raw)
        need(set(cfg)==FIELDS and cfg['model']=='HILEGA_DISABLED_WINDOW_OBSERVER_V1' and cfg['production_execution_enabled'] is False,'EXACT_CLOSED_WINDOW_CONFIG_REQUIRED')
        release=Path(__file__).absolute().parent.parent
        need(sha((release/'RELEASE-MANIFEST.json').read_bytes())==cfg['release_sha256'],'WINDOW_RELEASE_CHANGED')
        need(cfg['application_db']==str(source.s.store.path.resolve()) and cfg['journal']==str(Path(journal).resolve()),'WINDOW_SOURCE_PATH_CHANGED')
        window_path=Path(cfg['window_state']);receipt=Path(cfg['receipt_file'])
        need(window_path.is_absolute() and receipt.is_absolute() and not any(p.is_symlink() for p in (window_path,receipt,*window_path.parents,*receipt.parents)),'REGULAR_WINDOW_PATHS_REQUIRED')
        if not window_path.exists():return result
        window=json.loads(private_read(window_path));need(window['production_execution_enabled'] is False,'CLOSED_WINDOW_REQUIRED')
        if window.get('phase') not in {'ARM_REQUESTED','CLOSED'}:return result
        if window.get('source_lease')!=source.run_id:
            pause(source);return dict(base,window_boundary_status='LEASE_CHANGED_PAUSED',production_execution_enabled=False)
        with source.s.store.db() as db:
            rows=db.execute('SELECT data FROM preparation_plans').fetchall()
            if not rows:return result
            need(len(rows)==1,'EXACTLY_ONE_DISABLED_PREPARATION_REQUIRED');plan=json.loads(rows[0][0])
        need(plan['source_sequence']>window['source_sequence'],'POST_WINDOW_SOURCE_RECORD_REQUIRED')
        need(window['created_at']<=time.time()<window['deadline'],'WINDOW_BOUNDARY_EXPIRED_OR_CLOCK_REWOUND')
        pause(source)
        need(source.s.store.control()['mode']=='PAUSED','WINDOW_BOUNDARY_PAUSE_FAILED')
        p=Path(cfg['adapter_db']);need(p.is_absolute() and p.is_file() and not any(x.is_symlink() for x in (p,*p.parents)),'REGULAR_WINDOW_ADAPTER_REQUIRED')
        pin=read_pin(Path(cfg['pin_file']))
        with sqlite3.connect(p.as_uri()+'?mode=ro',uri=True) as db:
            db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
            meta=json.loads(db.execute('SELECT data FROM meta WHERE id=1').fetchone()[0]);need(meta==dict(scope=pin['scope'],mode='LIVE_CLOSED'),'EXACT_WINDOW_ACCOUNT_SCOPE_REQUIRED')
            need(all(db.execute('SELECT 1 FROM '+t+' LIMIT 1').fetchone() is None for t in ('attempts','receipts')),'WINDOW_MUST_HAVE_NO_ORDER_ATTEMPT')
            requests=db.execute('SELECT data FROM requests').fetchall();need(len(requests)==1,'ONE_DISABLED_REQUEST_REQUIRED');request=json.loads(requests[0][0])
            need(request['state']=='PREPARED' and request['order_id'] is None,'UNSENT_PREPARED_REQUEST_REQUIRED')
        value=dict(model='HILEGA_DISABLED_WINDOW_SEED_BOUNDARY_V1',window_created_at=window['created_at'],account_scope=pin['scope'],release_sha256=cfg['release_sha256'],application_db=cfg['application_db'],adapter_db=cfg['adapter_db'],journal=cfg['journal'],source_lease=source.run_id,seed_request_id=request['request_id'],source_sequence=plan['source_sequence'],source_record_hash=plan['source_record_hash'],controller_paused=True,owner_enrolled=False,admission_request_created=False,orders_sent=False,production_execution_enabled=False)
        value['signature']=sign(value,pin)
        if receipt.exists():
            existing=json.loads(private_read(receipt));need(existing==value,'WINDOW_BOUNDARY_RECEIPT_CHANGED')
        else:
            data=(json.dumps(value,sort_keys=True,indent=2)+'\n').encode();temp=receipt.with_name(receipt.name+'.new-'+uuid.uuid4().hex)
            try:
                fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
                with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
                need(not receipt.exists(),'WINDOW_RECEIPT_CONCURRENT_WRITER');os.replace(temp,receipt)
            finally:
                if temp.exists():temp.unlink()
        return dict(base,window_boundary_status='FRESH_DISABLED_SEED_RECORDED_PAUSED',seed_request_id=request['request_id'],production_execution_enabled=False)
    except Exception as exc:
        pause(source)
        import re
        text=str(exc);return dict(base,window_boundary_status='REVIEW_REQUIRED_PAUSED',window_boundary_reason=text if re.fullmatch('[A-Z][A-Z0-9_]*',text) else 'WINDOW_BOUNDARY_VALIDATION_FAILED',production_execution_enabled=False)
