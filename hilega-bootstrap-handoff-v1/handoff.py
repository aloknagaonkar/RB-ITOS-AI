"""Signed disabled-context handoff/rebinding with durable owner/file commit recovery."""
from copy import deepcopy
from datetime import datetime
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from zoneinfo import ZoneInfo
from local_admission import closed_transport,canonical,sha,need,aware

MODEL='HILEGA_DISABLED_HANDOFF_APPROVAL_V1'
FIELDS={'account_scope','release_sha256','policy_sha256','context_path','application_db','adapter_db','journal',
        'seed_request_id','from_run_id','to_run_id','old_context_sha256','new_context_sha256','old_owner_sha256',
        'new_owner_sha256','state_fingerprint','transaction_id'}


def encode(value):return (json.dumps(value,sort_keys=True,indent=2)+'\n').encode()


def atomic(path,raw):
    p=Path(path);need(not any(q.is_symlink() for q in (p,*p.parents)),'HANDOFF_SYMLINK_FORBIDDEN')
    temp=p.with_name(p.name+'.handoff-new')
    fd=os.open(temp,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    try:
        with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
        os.replace(temp,p);fd=os.open(p.parent,os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
    finally:
        if temp.exists():temp.unlink()


def seal(value,pin):
    value=deepcopy(value);value.pop('signature',None)
    value['signature']=hmac.new(bytes.fromhex(pin['key']),canonical(value),hashlib.sha256).hexdigest();return value


def unseal(value,pin):
    row=dict(value);signature=row.pop('signature',None)
    need(isinstance(signature,str) and hmac.compare_digest(hmac.new(bytes.fromhex(pin['key']),canonical(row),hashlib.sha256).hexdigest(),signature),'HANDOFF_INTENT_SIGNATURE_INVALID')
    return row


class Approval:
    def __init__(self,grant,expected,roots,clock):
        need(type(expected) is dict and set(expected)==FIELDS,'EXACT_HANDOFF_BINDING_REQUIRED')
        need(all(isinstance(expected[k],str) and expected[k] for k in FIELDS),'HANDOFF_BINDING_VALUES_REQUIRED')
        self.expected=deepcopy(expected);self.grant=json.loads(canonical(grant));self.roots=roots
        self.check(clock())

    def check(self,now,*,ignore_expiry=False):
        closed_transport();g=self.grant
        need(set(g)=={'model','operation','issuer_id','binding','issued_at','expires_at','order_transport_permission','production_execution_enabled','signature'}
             and g['model']==MODEL and g['operation'] in {'ATTACH_DISABLED_CONTEXT','REBIND_DISABLED_LEASE','RECOVER_DISABLED_REBIND'},'EXACT_HANDOFF_GRANT_REQUIRED')
        need(g['order_transport_permission'] is False and g['production_execution_enabled'] is False,'HANDOFF_CANNOT_AUTHORIZE_TRANSPORT')
        need(g['binding']==self.expected,'HANDOFF_GRANT_BINDING_CHANGED')
        roots=self.roots();need(g['issuer_id'] in roots,'HANDOFF_ISSUER_NOT_TRUSTED');key=roots[g['issuer_id']]
        need(type(key) is bytes and len(key)>=32,'HANDOFF_TRUST_ROOT_REQUIRED')
        payload={k:v for k,v in g.items() if k!='signature'}
        need(isinstance(g['signature'],str) and hmac.compare_digest(hmac.new(key,canonical(payload),hashlib.sha256).hexdigest(),g['signature']),'HANDOFF_GRANT_SIGNATURE_INVALID')
        start,end=aware(g['issued_at']),aware(g['expires_at'])
        need(0<(end-start).total_seconds()<=60,'BOUNDED_HANDOFF_GRANT_REQUIRED')
        if not ignore_expiry:need(now.tzinfo is not None and start<=now<end,'HANDOFF_GRANT_EXPIRED_OR_FUTURE')
        return roots


def snapshot(source,store,pin,journal,context_path,context_sha,clock,*,fresh=True):
    closed_transport()
    from market_lab.hilega_private_context_v1 import private_read,MODEL as CONTEXT_MODEL,FIELDS as CONTEXT_FIELDS
    from market_lab.hilega_exclusive_closed_route_v1 import _verify,_guarded_source,TABLE
    from market_lab.hilega_execution_port_v1 import adapter as port
    _guarded_source(source);need(type(store) is port.Store and store.scope==pin['scope'] and store.mode=='LIVE_CLOSED','EXACT_HANDOFF_STORE_REQUIRED')
    raw=private_read(context_path);need(sha(raw)==context_sha,'HANDOFF_CONTEXT_CHANGED');cfg=json.loads(raw)
    need(set(cfg)==CONTEXT_FIELDS and cfg['model']==CONTEXT_MODEL and cfg['production_execution_enabled'] is False,'EXACT_HANDOFF_CONTEXT_REQUIRED')
    need(aware(cfg['issued_at'])<=clock()<aware(cfg['expires_at']),'HANDOFF_CONTEXT_EXPIRED')
    need(cfg['application_db']==str(source.s.store.path.resolve()) and cfg['adapter_db']==str(store.path.resolve())
         and cfg['journal']==str(Path(journal).resolve()),'HANDOFF_SOURCE_PATH_CHANGED')
    protected={}
    for stem in ['pin','authority','broker_token']:
        data=private_read(Path(cfg[stem+'_file']));need(sha(data)==cfg[stem+'_sha256'],'HANDOFF_PRIVATE_IDENTITY_CHANGED');protected[stem]=data
    need(json.loads(protected['pin'])==pin,'HANDOFF_ACCOUNT_PIN_CHANGED');authority=json.loads(protected['authority'])
    from existing_request_attempt_v1 import authority_check
    authority_check(authority,pin)
    with source.s.store.db() as db:
        control=json.loads(db.execute('SELECT data FROM control WHERE id=1').fetchone()[0])
        stop=db.execute('SELECT generation,handled FROM sim_stop_state WHERE id=1').fetchone()
        health=json.loads(db.execute('SELECT data FROM sim_bridge_health WHERE id=1').fetchone()[0])
        owner_raw=db.execute('SELECT data FROM '+TABLE+' WHERE id=1').fetchone()
        cursor=db.execute('SELECT data FROM preparation_source WHERE id=1').fetchone()[0]
    need(control['mode']=='PAUSED' and stop[0]==stop[1],'PAUSED_HANDOFF_REQUIRED')
    need(health['run_id']==source.run_id and health['phase'] in {'STARTING','RUNNING'}
         and 0<=(clock()-aware(health['heartbeat_at'])).total_seconds()<=15,'CURRENT_HANDOFF_SOURCE_LEASE_REQUIRED')
    need(owner_raw is not None,'SIGNED_HANDOFF_OWNER_REQUIRED');owner=json.loads(owner_raw[0])
    proxy=SimpleNamespace(app=source.s.store,adapter=port.Adapter(store,port.HttpTransport(lambda:(_ for _ in ()).throw(AssertionError('No transport')))),
                          journal=Path(journal),pin=pin,authority=authority,seed=cfg['seed_request_id'],bridge=cfg['bridge_run_id'])
    _verify(proxy,owner)
    with sqlite3.connect(store.path.resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.execute('PRAGMA query_only=ON')
        need(db.execute('SELECT COUNT(*) FROM requests').fetchone()[0]==1 and db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0]==0
             and db.execute('SELECT COUNT(*) FROM receipts').fetchone()[0]==0,'UNSENT_HANDOFF_ONLY')
        request=json.loads(db.execute('SELECT data FROM requests WHERE id=?',(cfg['seed_request_id'],)).fetchone()[0])
        need(request['state']=='PREPARED' and not request.get('order_id'),'DISABLED_HANDOFF_REQUEST_REQUIRED')
    if fresh:
        signal=aware(request['signal_at']);need(0<=(clock()-signal).total_seconds()<=60 and signal.astimezone(ZoneInfo('Asia/Kolkata')).date()==clock().astimezone(ZoneInfo('Asia/Kolkata')).date(),'FRESH_DISABLED_HANDOFF_SEED_REQUIRED')
    from market_lab.hilega_production_simulator_bridge_v1 import verified_records
    records=verified_records(journal);cur=json.loads(cursor)
    need(cur['path']==str(Path(journal).resolve()) and 0<=cur['sequence']<=len(records)
         and (cur['sequence']==0 or records[cur['sequence']-1]['record_hash']==cur['hash']),'HANDOFF_CURSOR_PREFIX_CHANGED')
    return dict(config=cfg,context_raw=raw.decode(),owner=owner,owner_raw=owner_raw[0],cursor=cursor,
                control=control,stop=list(stop),request=request,authority=authority,protected={k:sha(v) for k,v in protected.items()})


def propose(source,store,pin,journal,context_path,context_sha,release,release_sha,transaction_id,clock):
    need(isinstance(transaction_id,str) and len(transaction_id)==32 and all(c in '0123456789abcdef' for c in transaction_id),'HANDOFF_TRANSACTION_ID_REQUIRED')
    release=Path(release);need(sha((release/'RELEASE-MANIFEST.json').read_bytes())==release_sha,'HANDOFF_RELEASE_CHANGED')
    policy=(release/'runtime/POSITION-POLICY.json').read_bytes();p=json.loads(policy)
    need(p['max_simultaneous_positions']==1 and p['max_premium_per_entry_cents'] is None and p['daily_loss_cutoff_cents'] is None,'HANDOFF_POLICY_CHANGED')
    state=snapshot(source,store,pin,journal,context_path,context_sha,clock)
    cfg=deepcopy(state['config']);cfg['bridge_run_id']=source.run_id
    owner=deepcopy(state['owner']);owner['binding']['bridge_run_id']=source.run_id;owner.pop('signature',None)
    from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import sign
    owner['signature']=sign(owner,pin)
    # Preserve the existing owner format and its native signature contract.
    new_cfg=encode(cfg).decode();new_owner=json.dumps(owner,sort_keys=True)
    bind=dict(account_scope=pin['scope'],release_sha256=release_sha,policy_sha256=sha(policy),context_path=str(Path(context_path).absolute()),
              application_db=str(source.s.store.path.resolve()),adapter_db=str(store.path.resolve()),journal=str(Path(journal).resolve()),
              seed_request_id=cfg['seed_request_id'],from_run_id=state['config']['bridge_run_id'],to_run_id=source.run_id,
              old_context_sha256=sha(state['context_raw'].encode()),new_context_sha256=sha(new_cfg.encode()),
              old_owner_sha256=sha(state['owner_raw'].encode()),new_owner_sha256=sha(new_owner.encode()),
              state_fingerprint=sha(canonical({k:state[k] for k in ['control','stop','cursor','request','protected']})),transaction_id=transaction_id)
    return dict(binding=bind,old_context=state['context_raw'],new_context=new_cfg,old_owner=state['owner_raw'],new_owner=new_owner,
                cursor=state['cursor'],control=state['control'],stop=state['stop'],request=state['request'],protected=state['protected'],authority_key_sha256=sha(bytes.fromhex(state['authority']['key'])),
                phase='PREPARED')


def intent_path(proposal):return Path(proposal['binding']['context_path']).parent/('handoff-'+proposal['binding']['transaction_id']+'.json')


def store_intent(path,value,pin):atomic(path,encode(seal(value,pin)))


def validate_record(record,pin):
    b=record['binding']
    for label in ['old_context','new_context','old_owner','new_owner']:
        need(sha(record[label].encode())==b[label+'_sha256'],'HANDOFF_INTENT_PAYLOAD_CHANGED')
    cfg=json.loads(record['old_context']);new_cfg=deepcopy(cfg);new_cfg['bridge_run_id']=b['to_run_id']
    need(encode(new_cfg).decode()==record['new_context'],'HANDOFF_CONTEXT_CHANGE_EXCEEDS_LEASE')
    owner=json.loads(record['old_owner']);new_owner=deepcopy(owner);new_owner['binding']['bridge_run_id']=b['to_run_id'];new_owner.pop('signature',None)
    from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import sign
    new_owner['signature']=sign(new_owner,pin)
    need(json.dumps(new_owner,sort_keys=True)==record['new_owner'],'HANDOFF_OWNER_CHANGE_EXCEEDS_LEASE')
    need(cfg['bridge_run_id']==owner['binding']['bridge_run_id']==b['from_run_id'],'HANDOFF_ORIGINAL_LEASE_CHANGED')
    need(sha(canonical({k:record[k] for k in ['control','stop','cursor','request','protected']}))==b['state_fingerprint'],'HANDOFF_RECORDED_STATE_CHANGED')


def bound_files(record,pin,roots):
    from market_lab.hilega_private_context_v1 import private_read
    b=record['binding'];release=Path(__file__).absolute().parent.parent
    need(sha((release/'RELEASE-MANIFEST.json').read_bytes())==b['release_sha256']
         and sha((release/'runtime/POSITION-POLICY.json').read_bytes())==b['policy_sha256'],'HANDOFF_RELEASE_OR_POLICY_CHANGED')
    cfg=json.loads(record['old_context'])
    for stem in ['pin','authority','broker_token']:
        need(sha(private_read(Path(cfg[stem+'_file'])))==record['protected'][stem]==cfg[stem+'_sha256'],'HANDOFF_PRIVATE_IDENTITY_CHANGED')
    authority=json.loads(private_read(Path(cfg['authority_file'])))
    need(sha(bytes.fromhex(authority['key']))==record['authority_key_sha256'],'HANDOFF_AUTHORITY_CHANGED')
    need(all(sha(key) not in {sha(bytes.fromhex(pin['key'])),record['authority_key_sha256'],record['protected']['broker_token']} for key in roots.values()),'HANDOFF_ROOT_MUST_BE_INDEPENDENT')


def guarded_database(db,store,record):
    db.execute('ATTACH DATABASE ? AS handoff_broker',(str(store.path.resolve()),))
    db.execute('BEGIN IMMEDIATE')
    control=json.loads(db.execute('SELECT data FROM control WHERE id=1').fetchone()[0])
    stop=list(db.execute('SELECT generation,handled FROM sim_stop_state WHERE id=1').fetchone())
    cursor=db.execute('SELECT data FROM preparation_source WHERE id=1').fetchone()[0]
    need(control==record['control'] and stop==record['stop'] and stop[0]==stop[1] and cursor==record['cursor'],'HANDOFF_CONTROL_OR_CURSOR_CHANGED')
    need(db.execute('SELECT COUNT(*) FROM handoff_broker.requests').fetchone()[0]==1
         and db.execute('SELECT COUNT(*) FROM handoff_broker.attempts').fetchone()[0]==0
         and db.execute('SELECT COUNT(*) FROM handoff_broker.receipts').fetchone()[0]==0,'HANDOFF_BROKER_STATE_CHANGED')
    request=json.loads(db.execute('SELECT data FROM handoff_broker.requests WHERE id=?',(record['binding']['seed_request_id'],)).fetchone()[0])
    need(request==record['request'],'HANDOFF_SEED_CHANGED')


def verify_done(source,store,pin,journal,record,clock):
    b=record['binding'];need(source.run_id==b['to_run_id'],'HANDOFF_RECOVERY_SOURCE_LEASE_CHANGED')
    state=snapshot(source,store,pin,journal,b['context_path'],b['new_context_sha256'],clock,fresh=False)
    need(sha(state['owner_raw'].encode())==b['new_owner_sha256'] and state['cursor']==record['cursor'],'HANDOFF_RESULT_OR_CURSOR_CHANGED')
    need(state['protected']==record['protected'],'HANDOFF_CHANGED_PRIVATE_IDENTITY')
    return state


def receipt(source,store,pin,journal,record,clock):
    verify_done(source,store,pin,journal,record,clock);b=record['binding']
    value=seal(dict(model='HILEGA_DISABLED_WORKER_HANDOFF_V1',binding=b,ready_for_local_review=True,
        execution_permission=False,production_execution_enabled=False,controller_resumed=False,keys_rotated=False),pin)
    p=intent_path(record).with_suffix('.receipt.json');atomic(p,encode(value))
    return dict(status='SIGNED_DISABLED_WORKER_HANDOFF_READY',receipt=str(p),receipt_sha256=sha(p.read_bytes()),
                context_sha256=b['new_context_sha256'],owner_sha256=b['new_owner_sha256'],new_key_created=False,
                controller_resumed=False,production_execution_enabled=False)


def apply(source,store,pin,journal,proposal,approval,clock,checkpoint=lambda at:None):
    from market_lab.hilega_exclusive_closed_route_v1 import route_lock,TABLE
    need(approval.expected==proposal['binding'],'HANDOFF_PROPOSAL_APPROVAL_CHANGED')
    operation='ATTACH_DISABLED_CONTEXT' if proposal['binding']['from_run_id']==proposal['binding']['to_run_id'] else 'REBIND_DISABLED_LEASE'
    need(approval.grant['operation']==operation,'EXACT_HANDOFF_OPERATION_REQUIRED')
    with route_lock(source.s.store.path),source.s.store.lock():
        roots=approval.check(clock());b=proposal['binding']
        need(all(sha(key) not in {sha(bytes.fromhex(pin['key'])),proposal['authority_key_sha256'],proposal['protected']['broker_token']} for key in roots.values()),'HANDOFF_ROOT_MUST_BE_INDEPENDENT')
        current=propose(source,store,pin,journal,b['context_path'],b['old_context_sha256'],Path(__file__).absolute().parent.parent,b['release_sha256'],b['transaction_id'],clock)
        need(current==proposal,'HANDOFF_PREPARED_STATE_CHANGED')
        path=intent_path(proposal);need(not path.exists() and not path.is_symlink(),'EXISTING_HANDOFF_INTENT_USE_RECOVERY')
        record=dict(proposal,initial_grant=deepcopy(approval.grant));store_intent(path,record,pin);checkpoint('AFTER_INTENT')
        validate_record(record,pin)
        approval.check(clock())
        with source.s.store.db() as db:
            guarded_database(db,store,record);row=db.execute('SELECT data FROM '+TABLE+' WHERE id=1').fetchone()
            need(row is not None and sha(row[0].encode())==b['old_owner_sha256'],'HANDOFF_OWNER_CHANGED')
            db.execute('UPDATE '+TABLE+' SET data=? WHERE id=1',(record['new_owner'],))
            checkpoint('BEFORE_OWNER_COMMIT');approval.check(clock())
        record['phase']='OWNER_COMMITTED';store_intent(path,record,pin);checkpoint('AFTER_OWNER_COMMIT')
        approval.check(clock());atomic(Path(b['context_path']),record['new_context'].encode())
        record['phase']='FILES_COMMITTED';store_intent(path,record,pin);checkpoint('AFTER_CONTEXT_REPLACE')
        approval.check(clock());out=receipt(source,store,pin,journal,record,clock)
        record['phase']='DONE';store_intent(path,record,pin);return out


def recover(source,store,pin,journal,path,approval,clock):
    from market_lab.hilega_private_context_v1 import private_read
    from market_lab.hilega_exclusive_closed_route_v1 import route_lock,TABLE
    with route_lock(source.s.store.path),source.s.store.lock():
        record=unseal(json.loads(private_read(path,limit=131072)),pin);b=record['binding']
        validate_record(record,pin)
        need(approval.grant['operation']=='RECOVER_DISABLED_REBIND' and approval.expected==b,'EXACT_HANDOFF_RECOVERY_APPROVAL_REQUIRED')
        roots=approval.check(clock());bound_files(record,pin,roots);need(source.run_id==b['to_run_id'],'HANDOFF_RECOVERY_SOURCE_LEASE_CHANGED')
        need(str(source.s.store.path.resolve())==b['application_db'] and str(store.path.resolve())==b['adapter_db']
             and str(Path(journal).resolve())==b['journal'] and pin['scope']==b['account_scope'],'HANDOFF_RECOVERY_PATH_OR_SCOPE_CHANGED')
        original=Approval.__new__(Approval);original.expected=deepcopy(b);original.grant=record['initial_grant'];original.roots=approval.roots
        original.check(clock(),ignore_expiry=True)
        need(original.grant['operation']==('ATTACH_DISABLED_CONTEXT' if b['from_run_id']==b['to_run_id'] else 'REBIND_DISABLED_LEASE'),'HANDOFF_ORIGINAL_OPERATION_CHANGED')
        need(Path(path)==intent_path(record),'HANDOFF_INTENT_PATH_CHANGED')
        current_cfg=private_read(Path(b['context_path']));current_cfg_sha=sha(current_cfg)
        with source.s.store.db() as db:row=db.execute('SELECT data FROM '+TABLE+' WHERE id=1').fetchone()
        need(row is not None,'HANDOFF_OWNER_MISSING');current_owner_sha=sha(row[0].encode())
        need(current_cfg_sha in {b['old_context_sha256'],b['new_context_sha256']} and current_owner_sha in {b['old_owner_sha256'],b['new_owner_sha256']},'EXTERNAL_HANDOFF_CHANGE_REQUIRES_REVIEW')
        if current_owner_sha==b['old_owner_sha256'] and b['old_owner_sha256']!=b['new_owner_sha256']:
            need(current_cfg_sha==b['old_context_sha256'],'HANDOFF_COMMIT_ORDER_INVALID')
            state=snapshot(source,store,pin,journal,b['context_path'],b['old_context_sha256'],clock)
            need(state['cursor']==record['cursor'] and state['protected']==record['protected'],'HANDOFF_RECOVERY_STATE_CHANGED')
            with source.s.store.db() as db:
                guarded_database(db,store,record);fresh=db.execute('SELECT data FROM '+TABLE+' WHERE id=1').fetchone()[0]
                need(sha(fresh.encode())==b['old_owner_sha256'],'RECOVERY_OWNER_CHANGED')
                db.execute('UPDATE '+TABLE+' SET data=? WHERE id=1',(record['new_owner'],));approval.check(clock())
        approval.check(clock())
        if current_cfg_sha!=b['new_context_sha256']:atomic(Path(b['context_path']),record['new_context'].encode())
        out=receipt(source,store,pin,journal,record,clock);record['phase']='DONE';store_intent(Path(path),record,pin);return out


def read_handoff(source,store,pin,journal,path,digest,clock):
    """Read-only consumer; this receipt never enables an execution factory."""
    from market_lab.hilega_private_context_v1 import private_read
    from market_lab.hilega_exclusive_closed_route_v1 import route_lock
    with route_lock(source.s.store.path),source.s.store.lock():
        raw=private_read(Path(path));need(sha(raw)==digest,'HANDOFF_RECEIPT_CHANGED')
        value=unseal(json.loads(raw),pin)
        need(value['model']=='HILEGA_DISABLED_WORKER_HANDOFF_V1' and value['execution_permission'] is False
             and value['production_execution_enabled'] is False and value['controller_resumed'] is False,'EXACT_DISABLED_HANDOFF_RECEIPT_REQUIRED')
        b=value['binding'];record_path=Path(b['context_path']).parent/('handoff-'+b['transaction_id']+'.json')
        record=unseal(json.loads(private_read(record_path,limit=131072)),pin)
        need(record['binding']==b and record['phase']=='DONE','COMPLETED_HANDOFF_REQUIRED')
        validate_record(record,pin);bound_files(record,pin,{})
        verify_done(source,store,pin,journal,record,clock)
        return value
