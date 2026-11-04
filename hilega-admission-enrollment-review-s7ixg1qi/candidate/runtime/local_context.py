"""Read-only validation/recovery of a committed local context with hard order gate closed."""
import json
from pathlib import Path
from types import SimpleNamespace
import sqlite3
from local_admission import need,sha,closed_transport


def validate_created_context(session,path,digest,approval,clock):
    from market_lab.hilega_private_context_v1 import private_read,MODEL,FIELDS
    from market_lab.hilega_exclusive_closed_route_v1 import _verify,TABLE
    closed_transport();approval.check_time(clock())
    raw=private_read(path);need(sha(raw)==digest,'LOCAL_CONTEXT_HASH_CHANGED');config=json.loads(raw)
    need(set(config)==FIELDS and config['model']==MODEL and config['production_execution_enabled'] is False,'EXACT_DISABLED_LOCAL_CONTEXT_REQUIRED')
    from market_lab.hilega_preparation_runtime_v1.evidence import aware
    need(aware(config['issued_at'])<=clock()<aware(config['expires_at']),'LOCAL_CONTEXT_EXPIRED_OR_FUTURE')
    expected=dict(application_db=str(session.app.path.resolve()),adapter_db=str(session.adapter.store.path.resolve()),journal=str(session.journal.resolve()),seed_request_id=session.seed,bridge_run_id=session.bridge)
    need(all(config[k]==v for k,v in expected.items()),'LOCAL_CONTEXT_SOURCE_BINDING_CHANGED')
    for stem in ['pin','authority','broker_token']:
        need(sha(private_read(Path(config[stem+'_file'])))==config[stem+'_sha256'],'LOCAL_PRIVATE_FILE_CHANGED')
    pin=json.loads(private_read(Path(config['pin_file'])));authority=json.loads(private_read(Path(config['authority_file'])))
    need(pin==session.pin and authority==session.authority,'LOCAL_IDENTITY_FILE_CHANGED')
    from existing_request_attempt_v1 import authority_check
    authority_check(authority,pin)
    with sqlite3.connect(session.adapter.store.path.resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.execute('PRAGMA query_only=ON')
        need(db.execute('SELECT COUNT(*) FROM requests').fetchone()[0]==1 and db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0]==0
             and db.execute('SELECT COUNT(*) FROM receipts').fetchone()[0]==0,'DISABLED_UNSENT_RECOVERY_ONLY')
        request=db.execute('SELECT data FROM requests WHERE id=?',(session.seed,)).fetchone()
        need(request is not None and json.loads(request[0])['state']=='PREPARED' and not json.loads(request[0]).get('order_id'),'UNSENT_LOCAL_SEED_REQUIRED')
    with sqlite3.connect(session.app.path.resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.execute('PRAGMA query_only=ON');row=db.execute('SELECT data FROM '+TABLE+' WHERE id=1').fetchone()
    need(row is not None,'COMMITTED_SIGNED_LOCAL_OWNER_REQUIRED');_verify(session,json.loads(row[0]))
    return dict(status='DISABLED_LOCAL_CONTEXT_VERIFIED',seed_request_id=session.seed,new_key_created=False,production_execution_enabled=False)


def recover_disabled_context(source,store,journal,path,digest,pin,approval,*,clock):
    need(approval.operation=='RECOVER_DISABLED_CONTEXT','RECOVERY_ONLY_LOCAL_APPROVAL_REQUIRED')
    approval.check(source,store,pin,journal,approval.expected['seed_request_id'],clock,Path(path).parent.parent)
    need(digest==approval.expected['state_fingerprint'],'RECOVERY_CONTEXT_DIGEST_CHANGED')
    from market_lab.hilega_private_context_v1 import private_read
    from market_lab.hilega_execution_port_v1 import adapter as port
    raw=private_read(path);need(sha(raw)==digest,'RECOVERY_CONTEXT_CHANGED');config=json.loads(raw)
    authority=json.loads(private_read(Path(config['authority_file'])))
    def forbidden():raise AssertionError('No transport or token callback in local recovery')
    session=SimpleNamespace(app=source.s.store,adapter=port.Adapter(store,port.HttpTransport(forbidden)),journal=Path(journal),pin=pin,authority=authority,seed=config['seed_request_id'],bridge=source.run_id)
    return validate_created_context(session,path,digest,approval,clock)
