"""Existing-request adoption candidate. Installed HTTP gate remains mandatory."""
from copy import deepcopy
from datetime import timedelta
import hashlib
import hmac
import json
from pathlib import Path
import re
import uuid

from authenticated_handoff_v1 import need
from history_prepared_proof_v1 import review_prepared as review, admission_as_handoff as existing, current_history
from cycle_scope_v1 import cycle_transaction, recover_entry_only
from durable_closed_handoff_v1 import one
from market_lab.hilega_preparation_runtime_v1.evidence import digest, aware
from market_lab.hilega_execution_port_v1 import adapter as port

EXPECTED_PORT_SHA='d2d8146cf8cc3334ce1d7d4715d73285d7755bc93201651be2d1798b34ee9e27'
ADOPTIONS='preparation_execution_adoption_candidates_v1'
CLAIMS='candidate_existing_request_claims_v1'
MODEL='HILEGA_EXISTING_REQUEST_ATTEMPT_CANDIDATE_V1'


def signature(value,authority):
    return hmac.new(bytes.fromhex(authority['key']),port.encode(value).encode(),hashlib.sha256).hexdigest()


def authority_check(authority,pin):
    need(isinstance(authority,dict) and authority.get('account_scope')==pin['scope']
         and isinstance(authority.get('authority_id'),str) and bool(authority['authority_id'])
         and isinstance(authority.get('key'),str)
         and re.fullmatch(r'[0-9a-f]{64}',authority['key']) is not None
         and authority['key']!=pin['key'],'INDEPENDENT_CANDIDATE_AUTHORITY_REQUIRED')


def signed(value,authority):
    row=deepcopy(value);row['signature']=signature(row,authority)
    return row


def checked(row,authority):
    payload=dict(row);sig=payload.pop('signature',None)
    need(isinstance(sig,str) and hmac.compare_digest(signature(payload,authority),sig),
         'ADOPTION_SIGNATURE_INVALID')
    return row


def request_and_attempts(db,key):
    found=db.execute('SELECT fingerprint,data FROM broker.requests WHERE id=?',(key,)).fetchone()
    need(found is not None,'EXISTING_PREPARED_REQUEST_REQUIRED')
    row=json.loads(found[1]);stable={k:row[k] for k in (
        'request_id','draft','signal_id','signal_at','direction','reservation_reference')}
    need(port.sha(stable)==found[0],'EXISTING_REQUEST_FINGERPRINT_CHANGED')
    attempts=db.execute('SELECT id,request_id,operation,data FROM broker.attempts WHERE request_id=?',(key,)).fetchall()
    return row,found[0],attempts


def recovery(db,adapter,pin,authority,key,request,fp,attempts):
    need(len(attempts)==1,'SINGLE_EXISTING_ATTEMPT_REQUIRED')
    aid,rid,operation,raw=attempts[0];attempt=json.loads(raw)
    need(rid==key and operation=='PLACE' and attempt['attempt_id']==aid
         and attempt['request_id']==key and attempt['operation']=='PLACE'
         and attempt['wire']==adapter._wire(request,'PLACE'),'ADOPTION_RECOVERY_ATTEMPT_CHANGED')
    adoption=checked(one(db,ADOPTIONS,key),authority)
    claim=checked(one(db,'broker.'+CLAIMS,key),authority)
    need(adoption==claim and adoption['model']==MODEL and adoption['account_scope']==pin['scope']
         and adoption['authority_id']==authority['authority_id']
         and adoption['request_id']==key and adoption['request_fingerprint']==fp
         and adoption['attempt_id']==aid and adoption['wire_fingerprint']==port.sha(attempt['wire'])
         and adoption['production_execution_enabled'] is False
         and adoption['live_clearance_granted'] is False,'ADOPTION_RECOVERY_BINDING_CHANGED')
    need(db.execute('SELECT COUNT(*) FROM broker.attempts WHERE request_id=?',(key,)).fetchone()[0]==1,
         'UNRELATED_ATTEMPT_REQUIRES_REVIEW')
    return attempt


def submit_existing_candidate(app_store,adapter,pin,authority,*,journal,request_id,
                              capture_provider,clock,expected_version,bridge_run_id,
                              checkpoint=lambda point:None):
    path=Path(port.__file__)
    need(path.is_file() and not path.is_symlink()
         and hashlib.sha256(path.read_bytes()).hexdigest()==EXPECTED_PORT_SHA,'PINNED_INSTALLED_PORT_REQUIRED')
    need(type(adapter) is port.Adapter and type(adapter.store) is port.Store
         and type(adapter.transport) is port.HttpTransport
         and adapter.store.mode=='LIVE_CLOSED' and adapter.store.scope==pin['scope'],
         'EXACT_CLOSED_INSTALLED_ADAPTER_REQUIRED')
    authority_check(authority,pin)
    need(app_store.path.stat().st_dev==adapter.store.path.stat().st_dev,'SAME_FILESYSTEM_REQUIRED')
    recovered=None
    with cycle_transaction(app_store,adapter.store.path,request_id) as db:
        request,fp,attempts=request_and_attempts(db,request_id)
        if attempts:recovered=recovery(db,adapter,pin,authority,request_id,request,fp,attempts)
    if recovered is not None:
        recover_entry_only(adapter,request_id)  # Bind durable receipts or mark UNKNOWN; never send.
        return dict(status='EXISTING_ADOPTED_ATTEMPT_RECOVERED_NO_SUBMISSION',
                    recovery_only=True,new_attempt_created=False,account_capture_requested=False,
                    production_execution_enabled=False)
    # No provider, authorizer claim, or attempt is reached with the actual gate.
    try:adapter.transport.check()
    except port.GateClosed:
        return dict(status='PRODUCTION_MUTATIONS_CLOSED_IN_CODE',recovery_only=False,
                    new_attempt_created=False,account_capture_requested=False,
                    production_execution_enabled=False)
    supplied=deepcopy(capture_provider())
    need(isinstance(supplied,dict) and set(supplied)=={'account','market'},'HISTORY_EXACT_CURRENT_CAPTURES_REQUIRED')
    bundle=supplied['market'];account=supplied['account']
    issued=aware(clock().isoformat());expires=issued+timedelta(seconds=10)
    grant=signed(dict(authorization_id=uuid.uuid4().hex,authority_id=authority['authority_id'],
        account_scope=pin['scope'],request_id=request_id,fresh_bundle_fingerprint=digest(bundle),fresh_account_fingerprint=digest(account),
        issued_at=issued.isoformat(),expires_at=expires.isoformat(),
        live_clearance_granted=False,production_execution_enabled=False),authority)
    checkpoint('AFTER_CANDIDATE_GRANT')
    raced=None
    with cycle_transaction(app_store,adapter.store.path,request_id) as db:
        request,fp,attempts=request_and_attempts(db,request_id)
        if attempts:raced=recovery(db,adapter,pin,authority,request_id,request,fp,attempts)
        else:
            provenance=review(db,pin,journal=journal,request_id=request_id)
            handoff=existing(db,pin,request_id,provenance)
            need(handoff is not None,'DURABLE_CLOSED_HANDOFF_REQUIRED')
            now=clock();need(issued<=now<expires,'CANDIDATE_GRANT_EXPIRED_OR_FUTURE')
            checked(grant,authority)
            context=current_history(db,pin,request_id,account,bundle,now,expected_version,bridge_run_id)
            from hilega_position_policy_v1 import enforce as _enforce_position_policy
            _enforce_position_policy(db,pin,request_id)
            wire=adapter._wire(request,'PLACE');aid=uuid.uuid4().hex
            attempt=dict(attempt_id=aid,request_id=request_id,operation='PLACE',wire=wire,
                         state='IN_FLIGHT',retry_allowed=False)
            adoption=signed(dict(model=MODEL,authority_id=authority['authority_id'],
                authorization_id=grant['authorization_id'],account_scope=pin['scope'],
                request_id=request_id,request_fingerprint=fp,attempt_id=aid,
                wire_fingerprint=port.sha(wire),handoff_fingerprint=digest(handoff),
                historical_provenance=provenance,current_review=context,
                candidate_grant=grant,live_clearance_granted=False,
                production_execution_enabled=False),authority)
            db.execute('CREATE TABLE IF NOT EXISTS '+ADOPTIONS+'(id TEXT PRIMARY KEY,data TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS broker.'+CLAIMS+'(id TEXT PRIMARY KEY,data TEXT NOT NULL)')
            db.execute('INSERT INTO '+ADOPTIONS+' VALUES(?,?)',(request_id,port.encode(adoption)))
            db.execute('INSERT INTO broker.'+CLAIMS+' VALUES(?,?)',(request_id,port.encode(adoption)))
            checkpoint('AFTER_AUTHORIZATION_CLAIM')
            # Recheck before this transaction creates the attempt. The same
            # attached transaction owns application adoption and broker claim.
            final_now=clock();need(issued<=final_now<expires,'CANDIDATE_GRANT_EXPIRED_OR_FUTURE')
            final=current_history(db,pin,request_id,account,bundle,final_now,expected_version,bridge_run_id)
            need({k:v for k,v in final.items() if k!='reviewed_at'}==
                 {k:v for k,v in context.items() if k!='reviewed_at'},'ADOPTION_CURRENT_CONTEXT_CHANGED')
            need(review(db,pin,journal=journal,request_id=request_id)==provenance,
                 'ADOPTION_PROVENANCE_CHANGED')
            db.execute('INSERT INTO broker.attempts VALUES(?,?,?,?)',(aid,request_id,'PLACE',port.encode(attempt)))
            request['state']='IN_FLIGHT'
            db.execute('UPDATE broker.requests SET data=? WHERE id=?',(port.encode(request),request_id))
            db.execute('INSERT INTO broker.events(data) VALUES(?)',
                (port.encode(dict(type='EXISTING_REQUEST_CANDIDATE_ADOPTED',attempt_id=aid,request_id=request_id)),))
            checkpoint('AFTER_ATTEMPT_INSERT')
            commit_at=clock();need(issued<=commit_at<expires,'CANDIDATE_GRANT_EXPIRED_OR_FUTURE')
            committed_context=current_history(db,pin,request_id,account,bundle,commit_at,
                expected_version,bridge_run_id,_pending_attempt=attempt)
            need({k:v for k,v in committed_context.items() if k!='reviewed_at'}==
                 {k:v for k,v in context.items() if k!='reviewed_at'},
                 'ADOPTION_CURRENT_CONTEXT_CHANGED_BEFORE_COMMIT')
    if raced is not None:
        recover_entry_only(adapter,request_id)
        return dict(status='EXISTING_ADOPTED_ATTEMPT_RECOVERED_NO_SUBMISSION',recovery_only=True,
                    new_attempt_created=False,account_capture_requested=True,production_execution_enabled=False)
    checkpoint('AFTER_ATTEMPT_COMMIT')
    try:receipt=adapter.transport.send(aid,wire)
    except Exception:
        with adapter.store.tx() as db:
            attempt['state']='UNKNOWN';request['state']='UNKNOWN'
            db.execute('UPDATE attempts SET data=? WHERE id=?',(port.encode(attempt),aid))
            db.execute('UPDATE requests SET data=? WHERE id=?',(port.encode(request),request_id))
        return dict(status='ADOPTED_BUY_UNKNOWN_NO_RESUBMISSION',adapter_result=attempt,
                    recovery_only=False,new_attempt_created=True,production_execution_enabled=False)
    checkpoint('AFTER_TRANSPORT_BEFORE_RECEIPT')
    adapter._persist_receipt(attempt,receipt)
    checkpoint('AFTER_RECEIPT_COMMIT')
    result=adapter._bind_receipt(attempt,receipt)
    return dict(status='EXISTING_REQUEST_CANDIDATE_ATTEMPT_RECORDED',adapter_result=result,
                recovery_only=False,new_attempt_created=True,production_execution_enabled=False)
