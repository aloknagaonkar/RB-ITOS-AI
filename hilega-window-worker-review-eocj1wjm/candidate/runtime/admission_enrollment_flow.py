"""Native disabled-seed admission/enrollment integration. No controller arm or order transport."""
import json,sqlite3
from pathlib import Path
from local_admission import LocalApproval,expected,closed_transport,need,sha
from market_lab.hilega_provisioning_workflow_v1 import _scan,provision_disabled_owner
from local_context import recover_disabled_context

def _closed(source,store):
    closed_transport()
    from market_lab.hilega_execution_port_v1 import adapter as port
    from market_lab.hilega_exclusive_closed_route_v1 import _guarded_source
    _guarded_source(source)
    need(type(store) is port.Store and store.mode=='LIVE_CLOSED','EXACT_CLOSED_ADAPTER_REQUIRED')
    need(source.s.store.control()['mode']=='PAUSED' and not source.s.store.stop_state()['pending'],'PAUSED_FLOW_REQUIRED')
    with sqlite3.connect(Path(store.path).as_uri()+'?mode=ro',uri=True) as db:
        db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
        need(all(db.execute('SELECT 1 FROM '+name+' LIMIT 1').fetchone() is None for name in ('attempts','receipts')),'EXISTING_EXECUTION_REQUIRES_REVIEW')

class DisabledEnrollmentFlow:
    """Calls existing native state/freshness/approval checks; never replaces them with booleans."""
    def __init__(self,source,store,pin,journal,seed,private_parent,release,release_sha256,*,clock):
        self.source=source;self.store=store;self.pin=pin;self.journal=Path(journal);self.seed=seed
        self.parent=Path(private_parent);self.release=Path(release);self.release_sha256=release_sha256;self.clock=clock
        _closed(source,store)
    def admission_request(self):
        """Read existing disabled state. Does not collect a signal, arm control or generate a key."""
        _closed(self.source,self.store)
        fingerprint=_scan(self.source,self.store,self.pin,self.journal,self.seed,self.clock)
        binding=expected(self.source,self.store,self.pin,self.journal,self.seed,self.release,self.release_sha256,private_parent=self.parent,state_fingerprint=fingerprint)
        requests=[r for r in self.store.requests() if r['request_id']==self.seed]
        need(len(requests)==1,'EXACT_EXISTING_SEED_REQUEST_REQUIRED')
        return dict(model='HILEGA_DISABLED_ENROLLMENT_FLOW_REQUEST_V1',operation='ENROLL_DISABLED_OWNER',binding=binding,
                    approval_required=True,approval_created=False,admission_basis='NATIVE_SCAN_OF_FRESH_BOUND_DISABLED_SEED',
                    production_contract_admission_certified=False,controller_resumed=False,orders_sent=False,production_execution_enabled=False)
    def enroll(self,approval,secret_provider,*,checkpoint=lambda point:None):
        need(type(approval) is LocalApproval and approval.operation=='ENROLL_DISABLED_OWNER','EXACT_SIGNED_LOCAL_ENROLLMENT_APPROVAL_REQUIRED')
        request=self.admission_request()
        need(approval.expected==request['binding'],'ENROLLMENT_REQUEST_BINDING_CHANGED')
        # Native provisioner rechecks grant freshness, source lease, signature, state and key separation at commit boundaries.
        result=provision_disabled_owner(self.source,self.store,self.pin,self.journal,self.seed,self.parent,secret_provider,
            local_approval=approval,clock=self.clock,checkpoint=checkpoint)
        _closed(self.source,self.store)
        need(result.get('status')=='CANDIDATE_PRIVATE_CONTEXT_AND_OWNER_READY','NATIVE_ENROLLMENT_NOT_VERIFIED')
        return dict(result,integration_model='HILEGA_DISABLED_ENROLLMENT_FLOW_V1',controller_resumed=False,
                    order_transport_permission=False,production_execution_enabled=False,final_activation_available=False)
    def recover(self,context_path,context_sha256,approval):
        _closed(self.source,self.store)
        need(type(approval) is LocalApproval and approval.operation=='RECOVER_DISABLED_CONTEXT','EXACT_SIGNED_LOCAL_RECOVERY_APPROVAL_REQUIRED')
        result=recover_disabled_context(self.source,self.store,self.journal,Path(context_path),context_sha256,self.pin,approval,clock=self.clock)
        _closed(self.source,self.store)
        need(result.get('new_key_created') is False,'RECOVERY_MUST_PRESERVE_AUTHORITY_KEY')
        return dict(result,controller_resumed=False,order_transport_permission=False,production_execution_enabled=False,final_activation_available=False)
    def final_activation_review(self):
        _closed(self.source,self.store)
        # A disabled owner is NOT a production execution authority. This integration has no grant issuer or gate-release action.
        return dict(status='FINAL_ACTIVATION_BLOCKED',hard_order_gate_closed=True,controller_paused=True,
            remaining=['FRESH_PRODUCTION_CONTRACT_AND_CASH_ADMISSION','BROKER_TIMESTAMP_AND_FINAL_FEE_EVIDENCE',
                       'REAL_SESSION_DISABLED_SEED_AND_OWNERSHIP_VERIFICATION','EXACT_REGISTRY_ATTACHMENT_WRAPPER_RECOVERY_REVIEW',
                       'SEPARATE_HARD_GATE_RELEASE_AND_ACTIVATION_APPROVAL'],
            activation_available=False,registry_enable_available=False,order_transport_permission=False,production_execution_enabled=False)
