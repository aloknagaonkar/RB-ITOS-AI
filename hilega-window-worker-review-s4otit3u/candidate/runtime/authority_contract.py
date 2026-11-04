"""Offline authority-grant verification candidate; no issuer, key generation or execution permission."""
from datetime import datetime
import hashlib
import hmac
import json
import re

BINDING_FIELDS={'account_scope','release_sha256','policy_sha256','private_context_sha256','authority_id',
                'authority_key_sha256','owner_row_sha256','seed_request_id','bridge_run_id'}
GRANT_FIELDS={'model','issuer_id','grant_id','binding','issued_at','expires_at','production_execution_enabled','signature'}


def need(ok,reason):
    if not ok:raise ValueError(reason)


def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def digest(raw):return hashlib.sha256(raw).hexdigest()


def aware(value):
    try:dt=datetime.fromisoformat(value)
    except (TypeError,ValueError):raise ValueError('AWARE_GRANT_TIMESTAMP_REQUIRED') from None
    need(dt.tzinfo is not None and dt.utcoffset() is not None,'AWARE_GRANT_TIMESTAMP_REQUIRED')
    return dt


def binding(value):
    need(type(value) is dict and set(value)==BINDING_FIELDS,'EXACT_AUTHORITY_BINDING_REQUIRED')
    need(isinstance(value['account_scope'],str) and re.fullmatch(r'UPSTOX:[0-9a-f]{64}',value['account_scope']),'EXACT_ACCOUNT_SCOPE_REQUIRED')
    for key in ('release_sha256','policy_sha256','private_context_sha256','authority_key_sha256','owner_row_sha256'):
        need(isinstance(value[key],str) and re.fullmatch(r'[0-9a-f]{64}',value[key]),'EXACT_AUTHORITY_DIGEST_REQUIRED')
    for key in ('authority_id','seed_request_id','bridge_run_id'):
        need(isinstance(value[key],str) and 0<len(value[key])<=200,'EXACT_AUTHORITY_IDENTITY_REQUIRED')
    return dict(value)


def verify(grant,expected,trusted_roots,now):
    expected=binding(expected)
    need(type(grant) is dict,'EXACT_AUTHORITY_GRANT_REQUIRED')
    grant=json.loads(canonical(grant))  # Stable detached value, not a mutable caller-owned grant.
    need(type(grant) is dict and set(grant)==GRANT_FIELDS,'EXACT_AUTHORITY_GRANT_REQUIRED')
    need(grant['model']=='HILEGA_OFFLINE_AUTHORITY_GRANT_CANDIDATE_V1' and grant['production_execution_enabled'] is False,'CANDIDATE_GRANT_CANNOT_ENABLE_EXECUTION')
    need(binding(grant['binding'])==expected,'AUTHORITY_BINDING_CHANGED')
    issuer=grant['issuer_id']
    need(isinstance(issuer,str) and isinstance(trusted_roots,dict) and issuer in trusted_roots,'UNTRUSTED_AUTHORITY_ISSUER')
    key=trusted_roots[issuer]
    need(type(key) is bytes and len(key)>=32 and digest(key)!=expected['authority_key_sha256'],'INDEPENDENT_TRUST_ROOT_REQUIRED')
    need(isinstance(grant['grant_id'],str) and 0<len(grant['grant_id'])<=200,'GRANT_ID_REQUIRED')
    payload={k:v for k,v in grant.items() if k!='signature'}
    signature=grant['signature']
    need(isinstance(signature,str) and re.fullmatch(r'[0-9a-f]{64}',signature)
         and hmac.compare_digest(signature,hmac.new(key,canonical(payload),hashlib.sha256).hexdigest()),'AUTHORITY_GRANT_SIGNATURE_INVALID')
    start,end=aware(grant['issued_at']),aware(grant['expires_at'])
    need(now.tzinfo is not None and now.utcoffset() is not None and 0<(end-start).total_seconds()<=86400 and start<=now<end,'AUTHORITY_GRANT_EXPIRED_OR_FUTURE')
    return dict(status='CANDIDATE_AUTHORITY_BINDING_VERIFIED',grant_id=grant['grant_id'],
                binding_sha256=digest(canonical(expected)),issuer_key_sha256=digest(key),
                production_trust_provisioned=False,execution_permission=False)
