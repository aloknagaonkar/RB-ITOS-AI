"""Explicit local-only worker handoff admission. Never dispatches an execution factory."""
from datetime import datetime,timezone
import hashlib,hmac,json,os,re,sqlite3
from pathlib import Path
from local_admission import need,sha,canonical,aware,closed_transport
from handoff import read_handoff,Approval,unseal,bound_files,validate_record

FIELDS={'model','release_sha256','application_db','adapter_db','journal','pin_file','pin_sha256',
        'trust_key_file','trust_key_sha256','issuer_id','mailbox','production_execution_enabled'}
SLOT={'model','receipt_file','receipt_sha256','source_lease','release_sha256','application_db','adapter_db','journal',
      'issued_at','expires_at','issuer_id','production_execution_enabled','signature'}


def read_private(path,digest=None,limit=131072):
    from market_lab.hilega_private_context_v1 import private_read
    raw=private_read(Path(path),limit=limit)
    if digest is not None:need(sha(raw)==digest,'WORKER_PRIVATE_FILE_CHANGED')
    return raw


def verify_slot(value,config,key,source,journal,now):
    need(type(value) is dict and set(value)==SLOT and value['model']=='HILEGA_DISABLED_WORKER_MAILBOX_V1'
         and value['production_execution_enabled'] is False,'EXACT_DISABLED_WORKER_MAILBOX_REQUIRED')
    need(value['issuer_id']==config['issuer_id'],'WORKER_ISSUER_CHANGED')
    payload={k:v for k,v in value.items() if k!='signature'}
    need(isinstance(value['signature'],str) and hmac.compare_digest(hmac.new(key,canonical(payload),hashlib.sha256).hexdigest(),value['signature']),'WORKER_MAILBOX_SIGNATURE_INVALID')
    need(value['source_lease']==source.run_id,'WORKER_LEASE_REQUIRES_SIGNED_REBIND')
    for field in ['release_sha256','application_db','adapter_db','journal']:need(value[field]==config[field],'WORKER_MAILBOX_BINDING_CHANGED')
    start,end=aware(value['issued_at']),aware(value['expires_at'])
    need(0<(end-start).total_seconds()<=60 and start<=now<end,'WORKER_MAILBOX_EXPIRED_OR_FUTURE')


def source_time(journal):
    from market_lab.hilega_production_simulator_bridge_v1 import verified_records,POLICY,VERSION
    from market_lab.hilega_production_bridge_health_v1 import source_timestamp
    return source_timestamp(verified_records(journal),POLICY,VERSION)


def configured_poll(source,journal,*,clock=None):
    """None selects the unchanged legacy dispatch. Explicit opt-in is local review only."""
    path=os.environ.get('HILEGA_DISABLED_HANDOFF_CONFIG');digest=os.environ.get('HILEGA_DISABLED_HANDOFF_CONFIG_SHA256')
    if path is None and digest is None:return None
    from worker_binding import ensure_paused
    ensure_paused(source.s)
    now=clock or source.s.now
    try:
        closed_transport();need(path and digest,'EXACT_WORKER_HANDOFF_CONFIG_REQUIRED')
        from market_lab.hilega_preparation_runtime_v1.source import Source
        from market_lab.hilega_production_simulator_bridge_v1 import Bridge
        need(type(source) in {Source,Bridge},'EXACT_WORKER_SOURCE_REQUIRED')
        if type(source) is Bridge:
            # The real CLI supplies Bridge. Reopen only an already prepared
            # application source; never baseline or collect evidence here.
            with source.s.store.db() as db:
                names={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                need({'preparation_source','preparation_plans','preparation_request_bindings','preparation_cash_reservations'}<=names,'EXISTING_PREPARED_APPLICATION_REQUIRED')
            def forbidden():raise AssertionError('No evidence collection during handoff admission')
            source=Source(source.s,run_id=source.run_id,provider=forbidden)
        cfg=json.loads(read_private(path,digest))
        need(type(cfg) is dict and set(cfg)==FIELDS and cfg['model']=='HILEGA_DISABLED_WORKER_CONFIG_V1'
             and cfg['production_execution_enabled'] is False,'EXACT_DISABLED_WORKER_CONFIG_REQUIRED')
        release=Path(__file__).absolute().parent.parent
        need(sha((release/'RELEASE-MANIFEST.json').read_bytes())==cfg['release_sha256'],'WORKER_RELEASE_CHANGED')
        need(cfg['application_db']==str(source.s.store.path.resolve()) and cfg['journal']==str(Path(journal).resolve()),'WORKER_SOURCE_PATH_CHANGED')
        key=read_private(cfg['trust_key_file'],cfg['trust_key_sha256']);need(len(key)>=32,'WORKER_INDEPENDENT_ROOT_REQUIRED')
        pin=json.loads(read_private(cfg['pin_file'],cfg['pin_sha256']))
        need(sha(key)!=sha(bytes.fromhex(pin['key'])),'WORKER_CAPTURE_KEY_IS_NOT_AUTHORITY')
        mailbox=Path(cfg['mailbox']);need(mailbox.is_absolute() and not any(p.is_symlink() for p in (mailbox,*mailbox.parents)),'PRIVATE_MAILBOX_PATH_REQUIRED')
        if not mailbox.exists():
            return dict(status='DISABLED_HANDOFF_WAITING_SIGNED_MAILBOX',source_at=source_time(journal),orders_sent=False,production_execution_enabled=False)
        slot=json.loads(read_private(mailbox));verify_slot(slot,cfg,key,source,journal,now())
        receipt_path=Path(slot['receipt_file']);receipt_value=unseal(json.loads(read_private(receipt_path,slot['receipt_sha256'])),pin)
        b=receipt_value['binding'];record_path=Path(b['context_path']).parent/('handoff-'+b['transaction_id']+'.json')
        record=unseal(json.loads(read_private(record_path)),pin);validate_record(record,pin);bound_files(record,pin,{cfg['issuer_id']:key})
        need(b['to_run_id']==source.run_id and b['account_scope']==pin['scope'] and b['adapter_db']==cfg['adapter_db'],'WORKER_HANDOFF_BINDING_CHANGED')
        original=Approval.__new__(Approval);original.expected=b;original.grant=record['initial_grant'];original.roots=lambda:{cfg['issuer_id']:key}
        original.check(now(),ignore_expiry=True)
        need(original.grant['operation'] in {'ATTACH_DISABLED_CONTEXT','REBIND_DISABLED_LEASE'},'WORKER_ORIGINAL_APPROVAL_REQUIRED')
        from market_lab.hilega_execution_port_v1 import adapter as port
        adapter=Path(cfg['adapter_db'])
        need(adapter.is_absolute() and adapter.is_file() and not any(p.is_symlink() for p in (adapter,*adapter.parents)),'EXISTING_WORKER_ADAPTER_REQUIRED')
        with sqlite3.connect(adapter.as_uri()+'?mode=ro',uri=True) as db:
            db.execute('PRAGMA query_only=ON')
            names={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            need({'meta','requests','attempts','receipts','events','fixture_orders'}<=names,'COMPLETE_WORKER_ADAPTER_REQUIRED')
            meta=json.loads(db.execute('SELECT data FROM meta WHERE id=1').fetchone()[0])
            need(meta==dict(scope=pin['scope'],mode='LIVE_CLOSED'),'WORKER_ADAPTER_SCOPE_CHANGED')
        store=port.Store(adapter,pin['scope'],'LIVE_CLOSED')
        result=read_handoff(source,store,pin,journal,receipt_path,slot['receipt_sha256'],now)
        return dict(status='DISABLED_BOOTSTRAP_HANDOFF_WORKER_VERIFIED',source_at=source_time(journal),
            handoff_transaction=b['transaction_id'],bridge_run_id=source.run_id,controller_resumed=False,
            execution_factory_dispatched=False,execution_permission=False,orders_sent=False,production_execution_enabled=False)
    except Exception as exc:
        ensure_paused(source.s)
        # Fixed reason labels avoid exporting paths, keys, tokens or private contents.
        reason=str(exc) if re.fullmatch(r'[A-Z][A-Z0-9_]{0,99}',str(exc)) else 'WORKER_HANDOFF_VALIDATION_FAILED'
        return dict(status='DISABLED_HANDOFF_REVIEW_REQUIRED',reason=reason,error_type=type(exc).__name__,source_at=None,
                    controller_resumed=False,execution_factory_dispatched=False,orders_sent=False,production_execution_enabled=False)
