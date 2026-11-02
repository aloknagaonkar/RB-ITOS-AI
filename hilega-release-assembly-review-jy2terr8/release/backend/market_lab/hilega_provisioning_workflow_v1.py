"""Gated first-seed provisioning/enrollment workflow candidate. No CLI activation or order sends."""
from contextlib import closing
from datetime import timedelta
import json
import os
from pathlib import Path
import secrets
import sqlite3
import tempfile


def need(ok,reason):
    if not ok:raise ValueError(reason)


def _scan_db(db,source,store,pin,journal,seed,clock,*,allow_pending_owner=False):
    from authenticated_handoff_v1 import review
    from market_lab.hilega_execution_port_v1 import adapter as port
    from market_lab.hilega_preparation_runtime_v1.limit_candidate import fresh_plan
    from market_lab.hilega_nifty_option_price_grid_v1 import PROFILE
    from market_lab.hilega_preparation_runtime_v1.evidence import aware,day
    from market_lab.hilega_preparation_runtime_v1.source import entry_clock_open
    from market_lab.hilega_production_bridge_health_v1 import effective
    need(db.in_transaction,'ACTIVE_ATTACHED_TRANSACTION_REQUIRED');tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not allow_pending_owner:need('preparation_candidate_exclusive_source_owner_v1' not in tables,'EXISTING_OWNER_REQUIRES_RECOVERY')
    need(db.execute('SELECT COUNT(*) FROM preparation_plans').fetchone()[0]==1,'SINGLE_FRESH_PREPARATION_REQUIRED')
    provenance=review(db,pin,journal=journal,request_id=seed)
    row=json.loads(db.execute('SELECT data FROM broker.requests WHERE id=?',(seed,)).fetchone()[0])
    need(row['state']=='PREPARED' and not row.get('order_id')
        and db.execute('SELECT COUNT(*) FROM broker.requests').fetchone()[0]==1
        and db.execute('SELECT COUNT(*) FROM broker.attempts').fetchone()[0]==0
        and db.execute('SELECT COUNT(*) FROM broker.receipts').fetchone()[0]==0,'UNSENT_FIRST_SEED_REQUIRED')
    now=clock();signal=aware(row['signal_at'])
    need(entry_clock_open(now) and entry_clock_open(signal),'ENROLLMENT_ENTRY_WINDOW_CLOSED')
    need(day(now)==day(signal) and 0<=(now-signal).total_seconds()<=60,'FRESH_FIRST_SEED_REQUIRED')
    port.validated_request(row['draft'],signal_id=row['signal_id'],signal_at=row['signal_at'],direction=row['direction'],
        reservation_reference=row['reservation_reference'],as_of=now.isoformat())
    c=json.loads(db.execute('SELECT data FROM control WHERE id=1').fetchone()[0])
    stop=db.execute('SELECT generation,handled FROM sim_stop_state WHERE id=1').fetchone()
    need(c['mode']=='PAUSED' and c['reason']=='APPLICATION_UNSENT_PREPARATION_REQUIRES_REVIEW'
         and stop and stop[0]==stop[1],'PAUSED_PREPARATION_AND_NO_STOP_REQUIRED')
    health=json.loads(db.execute('SELECT data FROM sim_bridge_health WHERE id=1').fetchone()[0])
    need(health.get('run_id')==source.run_id and effective(health,now)['healthy'],'CURRENT_SOURCE_LEASE_REQUIRED')
    plan_row=json.loads(db.execute('SELECT data FROM preparation_plans WHERE id=?',(seed,)).fetchone()[0])
    cursor=json.loads(db.execute('SELECT data FROM preparation_source WHERE id=1').fetchone()[0])
    need(cursor['sequence']==plan_row['source_sequence'] and cursor['hash']==plan_row['source_record_hash'],
         'EXACT_FIRST_SEED_SOURCE_CURSOR_REQUIRED')
    binding=json.loads(db.execute('SELECT data FROM preparation_request_bindings WHERE id=?',(seed,)).fetchone()[0])
    need(binding['model']=='HILEGA_ATOMIC_DISABLED_REQUEST_BINDING_V1','FIRST_CYCLE_BINDING_REQUIRED')
    bundle=json.loads(db.execute('SELECT data FROM preparation_evidence WHERE digest=?',(binding['bundle_fingerprint'],)).fetchone()[0])
    fresh_plan(bundle,pin,row['direction'],now,PROFILE)
    # Heartbeat timestamps are allowed to advance; lifecycle/control identity must not change.
    stable=dict(provenance=provenance,control=c,stop=stop,
        cursor=db.execute('SELECT data FROM preparation_source WHERE id=1').fetchone()[0],
        active={t:list(db.execute('SELECT id,data FROM '+t+' ORDER BY id')) for t in (
            'preparation_plans','preparation_shadow_holds','preparation_outbox','preparation_request_bindings','preparation_cash_reservations')},
        requests=list(db.execute('SELECT id,fingerprint,data FROM broker.requests ORDER BY id')))
    return port.sha(stable)


def _scan(source,store,pin,journal,seed,clock):
    from durable_closed_handoff_v1 import transaction
    with transaction(source.s.store,store.path) as db:
        return _scan_db(db,source,store,pin,journal,seed,clock)

def _write(path,value):
    raw=value if isinstance(value,bytes) else (json.dumps(value,sort_keys=True,indent=2)+'\n').encode()
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())


def provision_and_enroll_candidate(source,store,pin,journal,seed,private_parent,secret_provider,*,clock,checkpoint=lambda at:None):
    from market_lab.hilega_execution_port_v1 import adapter as port
    port.require_live_clearance() # No seed reads, file creation, keys or tokens behind the real closed gate.
    from market_lab.hilega_exclusive_closed_route_v1 import route_lock,_guarded_source,_binding,_verify,TABLE,MODEL as OWNER_MODEL
    from market_lab.hilega_private_context_v1 import MODEL,private_read,sha,PrivateContextLoader
    from existing_request_attempt_v1 import authority_check
    from closed_application_coordinator_v1 import CandidateSession
    import stat
    _guarded_source(source);need(type(store) is port.Store and store.mode=='LIVE_CLOSED' and store.scope==pin['scope'],'EXACT_CLOSED_ACCOUNT_STORE_REQUIRED')
    need(set(pin)=={'model','broker','scope','key','approved_at'},'VALIDATED_COMPLETE_ACCOUNT_PIN_REQUIRED')
    from market_lab.hilega_production_account_adapter_v1 import PIN_MODEL,aware
    import re
    need(pin['model']==PIN_MODEL and pin['broker']=='UPSTOX' and isinstance(pin['scope'],str)
         and re.fullmatch(r'UPSTOX:[0-9a-f]{64}',pin['scope']) and isinstance(pin['key'],str)
         and re.fullmatch(r'[0-9a-f]{64}',pin['key']) and aware(pin['approved_at'])<=clock(),'VALIDATED_ACCOUNT_PIN_REQUIRED')
    parent=Path(private_parent)
    need(parent.is_absolute() and parent.is_dir() and not any(p.is_symlink() for p in [parent,*parent.parents]),'EXPLICIT_PRIVATE_PARENT_REQUIRED')
    info=parent.stat();need(info.st_uid==os.getuid() and stat.S_IMODE(info.st_mode)&0o077==0,'OWNER_ONLY_PRIVATE_PARENT_REQUIRED')
    with route_lock(source.s.store.path):
        fingerprint=_scan(source,store,pin,journal,seed,clock)
        token=secret_provider();token=token.encode() if isinstance(token,str) else token
        need(isinstance(token,bytes) and token.strip() and b'\n' not in token.strip() and b'\r' not in token.strip(),'EXPLICIT_SINGLE_BROKER_TOKEN_REQUIRED')
        key=secrets.token_hex(32)
        while key==pin['key']:key=secrets.token_hex(32)
        authority=dict(account_scope=pin['scope'],authority_id='candidate-'+secrets.token_hex(16),key=key)
        authority_check(authority,pin)
        folder=Path(tempfile.mkdtemp(prefix='candidate-context-',dir=parent));folder.chmod(0o700)
        _write(folder/'pin.json',pin);_write(folder/'authority.json',authority);_write(folder/'broker-token',token)
        now=clock()
        config=dict(model=MODEL,production_execution_enabled=False,application_db=str(source.s.store.path.resolve()),adapter_db=str(store.path.resolve()),
            journal=str(Path(journal).resolve()),seed_request_id=seed,bridge_run_id=source.run_id,
            pin_file=str(folder/'pin.json'),pin_sha256=sha(private_read(folder/'pin.json')),
            authority_file=str(folder/'authority.json'),authority_sha256=sha(private_read(folder/'authority.json')),
            broker_token_file=str(folder/'broker-token'),broker_token_sha256=sha(token),
            issued_at=now.isoformat(),expires_at=(now+timedelta(hours=1)).isoformat())
        _write(folder/'context.json',config);digest=sha(private_read(folder/'context.json'))
        _write(folder/'INTENT.json',dict(model='HILEGA_CANDIDATE_CONTEXT_ENROLLMENT_INTENT_V1',config_sha256=digest,
            lifecycle_fingerprint=fingerprint,production_authority_provisioned=False,production_execution_enabled=False))
        fd=os.open(folder,os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
        def blocked(*args,**kwargs):raise ValueError('NO_CAPTURE_DURING_PROVISIONING')
        session=CandidateSession(source.s.store,port.Adapter(store,port.HttpTransport(blocked)),source,pin,authority,
            journal=journal,seed_request_id=seed,bridge_run_id=source.run_id,
            providers={k:blocked for k in ('entry','account','exit','next')},clock=clock)
        session._runtime()
        try:
            checkpoint('AFTER_PRIVATE_FILES_BEFORE_ENROLLMENT')
            from durable_closed_handoff_v1 import transaction
            from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import sign
            with transaction(source.s.store,store.path) as db:
                need(_scan_db(db,source,store,pin,journal,seed,clock)==fingerprint,'PREPARATION_CHANGED_BEFORE_ENROLLMENT')
                cursor=json.loads(db.execute('SELECT data FROM preparation_source WHERE id=1').fetchone()[0])
                owner=dict(model=OWNER_MODEL,binding=_binding(session),enrolled_cursor=cursor,entry_permission=False,
                    orders_sent_to_upstox=False,reservation_release_permission=False,production_execution_enabled=False)
                owner['signature']=sign(owner,pin)
                db.execute('CREATE TABLE '+TABLE+'(id INTEGER PRIMARY KEY,data TEXT NOT NULL)')
                db.execute('INSERT INTO '+TABLE+' VALUES(1,?)',(json.dumps(owner,sort_keys=True),))
                checkpoint('BEFORE_OWNER_COMMIT')
                need(_scan_db(db,source,store,pin,journal,seed,clock,allow_pending_owner=True)==fingerprint,
                    'PREPARATION_CHANGED_OR_STALE_BEFORE_OWNER_COMMIT')
                _verify(session,owner)
            checkpoint('AFTER_OWNER_COMMIT_BEFORE_RECEIPT')
            context=PrivateContextLoader(source,store,journal,folder/'context.json',digest,clock=clock)()
            need(context['seed_request_id']==seed,'PROVISIONED_CONTEXT_VALIDATION_FAILED')
            _write(folder/'RECEIPT.json',dict(status='CANDIDATE_PRIVATE_CONTEXT_AND_OWNER_READY',config_sha256=digest,
                orders_sent=False,production_authority_provisioned=False,production_execution_enabled=False))
        except BaseException:
            # Keep private intent/identity files. Commit uncertainty must never create a second owner/key.
            if not (folder/'REVIEW_REQUIRED.json').exists():_write(folder/'REVIEW_REQUIRED.json',dict(status='INSPECT_OWNER_AND_INTENT_BEFORE_RETRY',production_execution_enabled=False))
            raise
        return dict(status='CANDIDATE_PRIVATE_CONTEXT_AND_OWNER_READY',private_folder=str(folder),config_sha256=digest,
            orders_sent=False,production_authority_provisioned=False,production_execution_enabled=False)


def recover_committed_context(source,store,journal,config_path,expected_sha256,*,clock):
    from market_lab.hilega_execution_port_v1 import adapter as port
    port.require_live_clearance()
    from market_lab.hilega_private_context_v1 import PrivateContextLoader
    context=PrivateContextLoader(source,store,journal,config_path,expected_sha256,clock=clock)()
    return dict(status='EXISTING_CANDIDATE_CONTEXT_VERIFIED_NO_REENROLLMENT',seed_request_id=context['seed_request_id'],
        new_key_created=False,orders_sent=False,production_execution_enabled=False)
