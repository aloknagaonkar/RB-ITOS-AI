"""After-hours public authority/context binding packet. Never reads keys or activates a factory."""
import argparse
import ast
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile


def need(ok,reason):
    if not ok:raise ValueError(reason)


def regular(p):
    need(p.is_absolute() and p.is_file() and not any(q.is_symlink() for q in (p,*p.parents)),'REGULAR_PUBLIC_INPUT_REQUIRED')
    return p.read_bytes()


def sha(raw):return hashlib.sha256(raw).hexdigest()


def save(p,value):
    fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:json.dump(value,f,indent=2);f.write('\n')


def readonly(path,kind):
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
        db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        names=['preparation_plans','preparation_request_bindings','preparation_cash_reservations','preparation_candidate_exclusive_source_owner_v1'] if kind=='application' else ['requests','attempts','receipts']
        counts={name:db.execute('SELECT COUNT(*) FROM '+name).fetchone()[0] if name in tables else None for name in names}
        if kind=='application':
            c=json.loads(db.execute('SELECT data FROM control WHERE id=1').fetchone()[0])
            need(c['mode']=='PAUSED','PAUSED_CONTROLLER_REQUIRED')
            return dict(mode=c['mode'],version=c['version'],session_date=c['session_date'],counts=counts)
        meta=json.loads(db.execute('SELECT data FROM meta WHERE id=1').fetchone()[0])
        need(meta['mode']=='LIVE_CLOSED','CLOSED_ADAPTER_REQUIRED')
        return dict(scope=meta['scope'],mode=meta['mode'],counts=counts)


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--repo',type=Path,required=True)
    ap.add_argument('--active-plan',type=Path,required=True);ap.add_argument('--active-plan-sha256',required=True)
    a=ap.parse_args();root=a.repo.absolute();here=Path(__file__).absolute().parent
    for name,digest in json.loads(regular(here/'MANIFEST.json')).items():need(sha(regular(here/name))==digest,'REVIEW_PACKAGE_CHANGED')
    for name,digest in json.loads(regular(here/'BASELINE-PINS.json')).items():need(sha(regular(root/name))==digest,'UPGRADE_TOOL_CHANGED')
    path=a.active_plan.absolute();need(sha(regular(path))==a.active_plan_sha256,'ACTIVE_POLICY_PLAN_CHANGED')
    plan=json.loads(regular(path))
    need(plan['repo']==str(root) and plan['model']=='HILEGA_GROUP2_CLOSED_UPGRADE_V1' and plan['production_execution_enabled'] is False,'CLOSED_POLICY_PLAN_REQUIRED')
    output=Path(tempfile.mkdtemp(prefix='hilega-authority-context-review-',dir=root));output.chmod(0o700)
    (output/'.gitignore').write_text('*\n')
    def status(label):
        r=subprocess.run([sys.executable,'-B',str(root/'hilega-position-policy-upgrade-v1/manage.py'),'--repo',str(root),'--action','status','--plan',str(path),'--approve-plan-sha256',a.active_plan_sha256],capture_output=True,text=True,timeout=100)
        save(output/(label+'.json'),dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr))
        need(r.returncode==0 and json.loads(r.stdout)['phase']=='CLOSED_GROUP2_CANDIDATE_RUNNING','INSTALLED_POLICY_STATUS_FAILED')
    status('STATUS-BEFORE')
    bundle=Path(plan['destination']);raw=regular(bundle/'RELEASE-MANIFEST.json')
    need(sha(raw)==plan['release_sha256'],'DEPLOYED_RELEASE_CHANGED');manifest=json.loads(raw)
    required=['backend/market_lab/hilega_private_context_v1.py','backend/market_lab/hilega_provisioning_workflow_v1.py',
              'backend/market_lab/hilega_execution_session_factory_v1.py','backend/market_lab/hilega_execution_port_v1/adapter.py',
              'runtime/existing_request_attempt_v1.py','runtime/history_aware_attempt_v1.py',
              'runtime/hilega_position_policy_v1.py','runtime/POSITION-POLICY.json','CLOSED-REGISTRATION.json']
    bindings={}
    for name in required:
        need(name in manifest['files'] and sha(regular(bundle/name))==manifest['files'][name],'DEPLOYED_CONTEXT_MODULE_CHANGED')
        bindings[name]=manifest['files'][name]
    policy=json.loads(regular(bundle/'runtime/POSITION-POLICY.json'))
    need(policy['max_simultaneous_positions']==1 and policy['max_premium_per_entry_cents'] is None and policy['daily_loss_cutoff_cents'] is None,'USER_POLICY_CHANGED')
    registration=json.loads(regular(bundle/'CLOSED-REGISTRATION.json'))
    need(registration['execution_factory_configured'] is False and registration['production_execution_enabled'] is False,'FACTORY_DISABLED_REGISTRATION_REQUIRED')
    tree=ast.parse(regular(bundle/'backend/market_lab/hilega_private_context_v1.py'))
    assignments=[n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='FIELDS' for t in n.targets)]
    need(len(assignments)==1,'EXACT_CONTEXT_FIELD_CONTRACT_REQUIRED');fields=sorted(ast.literal_eval(assignments[0].value))
    gate_tree=ast.parse(regular(bundle/'backend/market_lab/hilega_execution_port_v1/adapter.py'))
    gates=[n for n in gate_tree.body if isinstance(n,ast.FunctionDef) and n.name=='require_live_clearance']
    need(len(gates)==1 and len(gates[0].body)==1 and isinstance(gates[0].body[0],ast.Raise),'UNCONDITIONAL_CLOSED_GATE_REQUIRED')
    app=readonly(Path(plan['application_db']),'application');adapter=readonly(Path(plan['adapter_db']),'adapter')
    need(all(value in (None,0) for value in app['counts'].values()) and all(value==0 for value in adapter['counts'].values()),'EMPTY_UNENROLLED_BASELINE_REQUIRED')
    packet=dict(model='HILEGA_DEPLOYED_AUTHORITY_CONTEXT_REVIEW_V1',created_at=datetime.now(timezone.utc).isoformat(),
        operating_context='AFTER_HOURS_PREPARATION_REQUESTED',account_scope=adapter['scope'],release_sha256=plan['release_sha256'],
        active_plan_sha256=a.active_plan_sha256,source_bindings=bindings,position_policy=policy,
        application_db=plan['application_db'],adapter_db=plan['adapter_db'],context_field_contract=fields,
        unresolved_context_values=['EXACT_FRESH_SEED_REQUEST','CURRENT_SOURCE_LEASE','JOURNAL_BINDING','INDEPENDENT_APPROVED_AUTHORITY',
            'PRIVATE_TOKEN_AND_PIN_FILE_HASH_BINDINGS','AWARE_ISSUED_AND_EXPIRY_TIMES'],
        broker_prerequisites=['CONFIRMED_TIMESTAMP_INTERPRETATION','COMPLETE_FEE_AND_OWNERSHIP_RECONCILIATION'],
        engineering_prerequisites=['PRODUCTION_AUTHORITY_TRUST_PATH_REVIEW','FACTORY_ACTIVATION_AND_RECOVERY_BINDING_IMPLEMENTATION_REVIEW',
            'BOUNDED_REAL_FRESH_SEED_TO_OWNER_WORKFLOW'],
        candidate_provisioner_is_not_a_production_trust_issuer=True,
        authority_approved=False,secret_material_created=False,live_arming_permitted=False,
        live_enrollment_permitted=False,execution_gate_change_available=False,production_execution_enabled=False)
    save(output/'AUTHORITY-CONTEXT-REVIEW.json',packet)
    status('STATUS-AFTER')
    after_app=readonly(Path(plan['application_db']),'application');after_adapter=readonly(Path(plan['adapter_db']),'adapter')
    need(after_app==app and after_adapter==adapter,'REVIEW_STATE_CHANGED')
    report=dict(status='AFTER_HOURS_AUTHORITY_CONTEXT_BINDINGS_PREPARED',
        release_sha256=plan['release_sha256'],context_fields_discovered=len(fields),module_bindings_verified=len(bindings),
        factory_disabled=True,hard_gate_unconditionally_closed=True,controller_paused=True,
        application_counts=app['counts'],adapter_counts=adapter['counts'],
        review_packet=str(output/'AUTHORITY-CONTEXT-REVIEW.json'),review_packet_sha256=sha(regular(output/'AUTHORITY-CONTEXT-REVIEW.json')),
        previous_tests_reexecuted=False,broker_requests_issued=False,authority_or_broker_token_loaded_for_context=False,secret_material_created=False,
        production_authority_provisioned=False,live_database_enrolled=False,application_sql_mutations_issued=False,
        application_services_changed=False,controller_resumed=False,production_execution_enabled=False,group2_complete=False,audit_folder=str(output))
    save(output/'RESULT.json',report)
    tracker=regular(path.parent/'MILESTONES.md').decode()
    tracker+='\n## Authority/context bindings after policy deployment\n- [x] Current deployed release and public private-context field contract bound into one review packet.\n'
    tracker+='- [x] Paused, empty, factory-disabled baseline verified before/after.\n'
    tracker+='- [ ] Production trust issuer/path and factory activation implementation reviewed.\n- [ ] Broker timestamp/fee prerequisites resolved.\n- [ ] Real fresh-signal seed and signed owner enrollment during an eligible session.\n'
    (output/'MILESTONES.md').write_text(tracker);(output/'MILESTONES.md').chmod(0o600)
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
