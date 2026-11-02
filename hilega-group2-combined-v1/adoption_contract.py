"""Public closed-only authority/seed handoff contracts. No private key generation or enrollment."""
from datetime import datetime
import re


def need(ok,reason):
    if not ok:raise ValueError(reason)
def aware(value):
    dt=datetime.fromisoformat(value);need(dt.tzinfo is not None,'AWARE_CONTEXT_TIMESTAMP_REQUIRED');return dt

def authority_request(scope,release_sha,descriptor=None):
    need(isinstance(scope,str) and re.fullmatch(r'UPSTOX:[0-9a-f]{64}',scope),'EXACT_ACCOUNT_SCOPE_REQUIRED')
    need(isinstance(release_sha,str) and re.fullmatch(r'[0-9a-f]{64}',release_sha),'EXACT_RELEASE_DIGEST_REQUIRED')
    if descriptor is not None:
        need(type(descriptor) is dict and set(descriptor)=={'authority_id','account_scope','public_fingerprint','approved_for_production'},'PUBLIC_AUTHORITY_DESCRIPTOR_ONLY')
        need(descriptor['account_scope']==scope,'AUTHORITY_ACCOUNT_SCOPE_CHANGED')
        need(isinstance(descriptor['public_fingerprint'],str) and re.fullmatch(r'[0-9a-f]{64}',descriptor['public_fingerprint']),'AUTHORITY_FINGERPRINT_REQUIRED')
        need(descriptor['approved_for_production'] is False,'CANDIDATE_CANNOT_SELF_APPROVE_PRODUCTION_AUTHORITY')
    return dict(model='HILEGA_CLOSED_AUTHORITY_REVIEW_REQUEST_V1',account_scope=scope,release_sha256=release_sha,
        public_descriptor=descriptor,status='INDEPENDENT_TRUST_AND_POLICY_APPROVAL_REQUIRED',
        authority_created=False,production_authority_provisioned=False,live_arming_permitted=False)

def seed_handoff(intent,seed,*,now):
    need(intent['model']=='HILEGA_CLOSED_AUTHORITY_REVIEW_REQUEST_V1','EXACT_REVIEW_INTENT_REQUIRED')
    required={'account_scope','release_sha256','signal_at','resumed_at','state','order_id','attempt_count','receipt_count','owner_exists','binding_verified','cash_signature_verified','source_cursor_verified','context_digest','seed_request_id','bridge_run_id','source_sequence','source_record_hash'}
    need(type(seed) is dict and set(seed)==required,'EXACT_DISABLED_SEED_HANDOFF_REQUIRED')
    need(seed['account_scope']==intent['account_scope'] and seed['release_sha256']==intent['release_sha256'],'SEED_ACCOUNT_OR_RELEASE_CHANGED')
    need(all(isinstance(seed[k],str) and 0<len(seed[k])<=200 for k in ('seed_request_id','bridge_run_id')),'EXACT_SEED_AND_LEASE_ID_REQUIRED')
    need(type(seed['source_sequence']) is int and seed['source_sequence']>0 and isinstance(seed['source_record_hash'],str) and re.fullmatch(r'[0-9a-f]{64}',seed['source_record_hash']),'EXACT_SOURCE_CURSOR_BINDING_REQUIRED')
    stamp=aware(seed['signal_at']);resumed=aware(seed['resumed_at'])
    need(now.tzinfo is not None and stamp.date()==now.astimezone(stamp.tzinfo).date() and 0<=(now-stamp).total_seconds()<=60 and stamp>resumed,'FRESH_POST_RESUME_SEED_REQUIRED')
    need(seed['state']=='PREPARED' and seed['order_id'] is None and type(seed['attempt_count']) is int and type(seed['receipt_count']) is int and seed['attempt_count']==seed['receipt_count']==0,'UNSENT_DISABLED_REQUEST_REQUIRED')
    need(seed['owner_exists'] is False and all(seed[k] is True for k in ('binding_verified','cash_signature_verified','source_cursor_verified')),'SIGNED_BOUND_UNOWNED_SEED_REQUIRED')
    need(isinstance(seed['context_digest'],str) and re.fullmatch(r'[0-9a-f]{64}',seed['context_digest']),'EXACT_PRIVATE_CONTEXT_DIGEST_REQUIRED')
    return dict(status='CANDIDATE_SEED_CONTRACT_PASS_REVIEW_ONLY',context_digest=seed['context_digest'],
        owner_commit_permitted=False,production_execution_enabled=False,trust_approval_still_required=True)
