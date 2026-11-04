"""Signed local-only bootstrap authorization. Never grants broker transport permission."""
from copy import deepcopy
from datetime import datetime
import hashlib
import hmac
import json
from pathlib import Path
import re

MODEL='HILEGA_LOCAL_BOOTSTRAP_APPROVAL_CANDIDATE_V1'
FIELDS={'account_scope','release_sha256','policy_sha256','application_db','adapter_db','journal','private_parent','seed_request_id','bridge_run_id','state_fingerprint'}


def need(ok,reason):
    if not ok:raise ValueError(reason)


def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def sha(raw):return hashlib.sha256(raw).hexdigest()


def aware(value):
    result=datetime.fromisoformat(value);need(result.tzinfo is not None and result.utcoffset() is not None,'AWARE_LOCAL_GRANT_TIME_REQUIRED');return result


def closed_transport():
    from market_lab.hilega_execution_port_v1 import adapter as port
    try:port.require_live_clearance()
    except port.GateClosed:return
    raise ValueError('LOCAL_BOOTSTRAP_REQUIRES_HARD_ORDER_GATE_CLOSED')


def expected(source,store,pin,journal,seed,release,release_sha256,*,private_parent,state_fingerprint):
    release=Path(release);raw=(release/'RELEASE-MANIFEST.json').read_bytes()
    need(sha(raw)==release_sha256,'BOOTSTRAP_RELEASE_CHANGED')
    policy=release/'runtime/POSITION-POLICY.json';p=json.loads(policy.read_text())
    need(p['max_simultaneous_positions']==1 and p['max_premium_per_entry_cents'] is None and p['daily_loss_cutoff_cents'] is None,'EXACT_USER_POLICY_REQUIRED')
    return dict(account_scope=pin['scope'],release_sha256=release_sha256,policy_sha256=sha(policy.read_bytes()),
                application_db=str(source.s.store.path.resolve()),adapter_db=str(store.path.resolve()),journal=str(Path(journal).resolve()),
                private_parent=str(Path(private_parent).resolve()),seed_request_id=seed,bridge_run_id=source.run_id,state_fingerprint=state_fingerprint)


class LocalApproval:
    """Verification result/provider, not a production authority issuer."""
    def __init__(self,grant,expected_binding,trust_provider,*,operation,clock):
        need(operation in {'ENROLL_DISABLED_OWNER','RECOVER_DISABLED_CONTEXT'},'LOCAL_OPERATION_REQUIRED')
        need(type(expected_binding) is dict and set(expected_binding)==FIELDS,'EXACT_LOCAL_BINDING_REQUIRED')
        for key in ('release_sha256','policy_sha256','state_fingerprint'):
            need(isinstance(expected_binding[key],str) and re.fullmatch(r'[0-9a-f]{64}',expected_binding[key]),'EXACT_LOCAL_DIGEST_REQUIRED')
        self.grant=json.loads(canonical(grant));self.expected=deepcopy(expected_binding);self.trust=trust_provider;self.operation=operation
        self.check_time(clock())

    def check_time(self,now):
        closed_transport()
        value=self.grant;fields={'model','operation','issuer_id','grant_id','binding','issued_at','expires_at','order_transport_permission','production_execution_enabled','signature'}
        need(type(value) is dict and set(value)==fields and value['model']==MODEL and value['operation']==self.operation,'EXACT_LOCAL_APPROVAL_REQUIRED')
        need(value['order_transport_permission'] is False and value['production_execution_enabled'] is False,'LOCAL_GRANT_CANNOT_ENABLE_ORDERS')
        need(isinstance(value['grant_id'],str) and 0<len(value['grant_id'])<=200,'LOCAL_GRANT_ID_REQUIRED')
        need(value['binding']==self.expected,'LOCAL_APPROVAL_BINDING_CHANGED')
        roots=self.trust();issuer=value['issuer_id'];need(isinstance(issuer,str) and issuer in roots,'LOCAL_ISSUER_NOT_TRUSTED')
        key=roots[issuer];need(type(key) is bytes and len(key)>=32,'EXPLICIT_LOCAL_TRUST_ROOT_REQUIRED')
        payload={k:v for k,v in value.items() if k!='signature'}
        need(isinstance(value['signature'],str) and hmac.compare_digest(hmac.new(key,canonical(payload),hashlib.sha256).hexdigest(),value['signature']),'LOCAL_APPROVAL_SIGNATURE_INVALID')
        start,end=aware(value['issued_at']),aware(value['expires_at'])
        need(now.tzinfo is not None and now.utcoffset() is not None and 0<(end-start).total_seconds()<=60 and start<=now<end,'LOCAL_APPROVAL_EXPIRED_OR_FUTURE')
        return roots

    def check(self,source,store,pin,journal,seed,clock,private_parent):
        closed_transport();roots=self.check_time(clock())
        from market_lab.hilega_exclusive_closed_route_v1 import _guarded_source
        from market_lab.hilega_execution_port_v1 import adapter as port
        _guarded_source(source)
        need(type(store) is port.Store and store.mode=='LIVE_CLOSED' and store.scope==pin['scope'],'EXACT_CLOSED_LOCAL_STORE_REQUIRED')
        need(source.s.store.control()['mode']=='PAUSED' and not source.s.store.stop_state()['pending'],'PAUSED_LOCAL_BOOTSTRAP_REQUIRED')
        need(all(sha(key)!=sha(bytes.fromhex(pin['key'])) for key in roots.values()),'CAPTURE_KEY_CANNOT_AUTHORIZE_LOCAL_BOOTSTRAP')
        actual=dict(account_scope=pin['scope'],application_db=str(source.s.store.path.resolve()),adapter_db=str(store.path.resolve()),
                    journal=str(Path(journal).resolve()),private_parent=str(Path(private_parent).resolve()),seed_request_id=seed,bridge_run_id=source.run_id)
        need(all(self.expected[k]==v for k,v in actual.items()),'LOCAL_BOOTSTRAP_SOURCE_BINDING_CHANGED')
        if self.operation=='ENROLL_DISABLED_OWNER':
            from market_lab.hilega_provisioning_workflow_v1 import _scan
            need(_scan(source,store,pin,journal,seed,clock)==self.expected['state_fingerprint'],'LOCAL_PREPARATION_FINGERPRINT_CHANGED')
        return roots

    def independent_authority_key(self,key,pin,clock):
        roots=self.check_time(clock())
        return key!=pin['key'] and all(sha(bytes.fromhex(key))!=sha(root) for root in roots.values())

    def check_token_separation(self,token,clock):
        roots=self.check_time(clock())
        need(all(sha(root) not in {sha(token),sha(token.strip())} for root in roots.values()),'BROKER_TOKEN_CANNOT_AUTHORIZE_LOCAL_BOOTSTRAP')

    def audit_record(self,clock):
        roots=self.check_time(clock())
        return dict(model='HILEGA_LOCAL_BOOTSTRAP_APPROVAL_AUDIT_V1',grant=deepcopy(self.grant),
                    verified_at=clock().isoformat(),issuer_key_fingerprints={issuer:sha(key) for issuer,key in roots.items()},
                    production_execution_enabled=False,order_transport_permission=False)
