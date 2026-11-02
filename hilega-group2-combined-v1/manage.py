"""Combined Group 2 candidate validation, staged timestamp guard and GET-only evidence review."""
import argparse,hashlib,json,os,sqlite3,subprocess,sys,tempfile
from pathlib import Path
from datetime import datetime,timezone
import xml.etree.ElementTree as ET
from adoption_contract import authority_request
from stage_candidate import stage

def need(ok,reason):
    if not ok:raise ValueError(reason)
def regular(p):
    need(p.is_file() and not any(x.is_symlink() for x in [p,*p.absolute().parents]),'REGULAR_PACKAGE_B_INPUT_REQUIRED');return p.read_bytes()
def sha(raw):return hashlib.sha256(raw).hexdigest()
def save(p,value):
    fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:json.dump(value,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--repo',type=Path,required=True);ap.add_argument('--broker-read',action='store_true',help='Validate current source-provider signed market/cash evidence with GETs only');args=ap.parse_args()
    root=args.repo.absolute();here=Path(__file__).absolute().parent
    for name,digest in json.loads(regular(here/'MANIFEST.json')).items():need(sha(regular(here/name))==digest,'PACKAGE_B_SOURCE_CHANGED')
    for name,digest in json.loads(regular(here/'BASELINE-PINS.json')).items():need(sha(regular(root/name))==digest,'VERIFIED_RECOVERY_OR_VALIDATION_CODE_CHANGED')
    installed_raw=regular(root/'hilega-recovery-install-v1/VM-VALIDATION.json');installed=json.loads(installed_raw)
    need(installed['status']=='CLOSED_RECOVERY_INSTALL_PLAN_PASS','RECOVERY_INSTALL_PLAN_REQUIRED')
    installed_path=Path(installed['plan']);need(sha(regular(installed_path))==installed['plan_sha256'],'APPROVED_RECOVERY_PLAN_CHANGED')
    tx=json.loads(regular(installed_path.parent/'TRANSACTION.json'));need(tx['phase']=='CLOSED_RECOVERY_INSTALLED_RUNNING','INSTALLED_RUNNING_CLOSED_RECOVERY_REQUIRED')
    output=Path(tempfile.mkdtemp(prefix='hilega-group2-combined-review-',dir=root));output.chmod(0o700);(output/'.gitignore').write_text('*\n')
    def health(label):
        r=subprocess.run([sys.executable,'-B',str(root/'hilega-recovery-install-v1/manage.py'),'--repo',str(root),'--action','status','--plan',str(installed_path),'--approve-plan-sha256',installed['plan_sha256']],cwd=root,capture_output=True,text=True,timeout=90)
        save(output/(label+'.json'),dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr));need(r.returncode==0,'INSTALLED_CLOSED_RECOVERY_REQUIRES_REVIEW')
        need(json.loads(r.stdout)['phase']=='CLOSED_RECOVERY_INSTALLED_RUNNING','CURRENT_CLOSED_RECOVERY_REQUIRED')
    health('CLOSED-STATUS-BEFORE')
    recovery_plan=json.loads(regular(installed_path));active_path=Path(recovery_plan['active_plan']);active_raw=regular(active_path)
    need(sha(active_raw)==recovery_plan['active_plan_sha256'],'ACTIVE_RUNTIME_PLAN_CHANGED');active=json.loads(active_raw);bundle=Path(active['destination'])
    manifest_raw=regular(bundle/'RELEASE-MANIFEST.json');need(sha(manifest_raw)==active['release_manifest_sha256'],'CLOSED_RELEASE_CHANGED')
    manifest=json.loads(manifest_raw)
    modules=['backend/market_lab/hilega_execution_session_factory_v1.py','backend/market_lab/hilega_private_context_v1.py','backend/market_lab/hilega_provisioning_workflow_v1.py','backend/market_lab/hilega_exclusive_closed_route_v1.py','backend/market_lab/hilega_execution_port_v1/adapter.py']
    for name in modules:need(name in manifest['files'] and sha(regular(bundle/name))==manifest['files'][name],'REQUIRED_BUNDLED_CONTEXT_MODULE_CHANGED: '+name)
    registration=json.loads(regular(bundle/'CLOSED-REGISTRATION.json'));need(registration['execution_factory_configured'] is False and registration['production_execution_enabled'] is False,'FACTORY_DISABLED_RUNTIME_REQUIRED')
    original_bundle=bundle;original_manifest=manifest
    candidate_info=stage(original_bundle,output/'candidate',regular(here/'timestamp_policy.py'))
    save(output/'CANDIDATE-CHANGES.json',candidate_info)
    bundle=output/'candidate';manifest_raw=regular(bundle/'RELEASE-MANIFEST.json');manifest=json.loads(manifest_raw)
    modules.append('backend/market_lab/hilega_broker_time_consistency_v1.py')
    environment=dict(PATH=os.defpath,LANG='C.UTF-8',HOME=str(output),PYTHONDONTWRITEBYTECODE='1',PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',
        HILEGA_PACKAGE_B_BUNDLE=str(bundle),PYTHONPATH=os.pathsep.join(map(str,[here,bundle/'backend',bundle/'runtime',here/'fixtures'])))
    junit=output/'TESTS.xml'
    cmd=[sys.executable,'-B','-m','pytest','-q','-p','no:cacheprovider','--rootdir='+str(here),'--confcutdir='+str(here),
        '--basetemp='+str(output/'synthetic-tests'),str(here/'tests'),'--junitxml='+str(junit)]
    code=subprocess.run(cmd,cwd=output,env=environment).returncode
    cases=list(ET.parse(junit).getroot().iter('testcase')) if junit.is_file() else []
    failed=sum(c.find('failure') is not None or c.find('error') is not None for c in cases);skipped=sum(c.find('skipped') is not None for c in cases)
    need(code==0 and len(cases)==74 and failed==skipped==0,'COMBINED_GROUP2_TESTS_FAILED; inspect TESTS.xml')
    app=Path(active['application_db']);adapter=Path(active['adapter_db'])
    with sqlite3.connect(adapter.as_uri()+'?mode=ro',uri=True) as db:
        db.execute('PRAGMA query_only=ON');meta=json.loads(db.execute('SELECT data FROM meta WHERE id=1').fetchone()[0]);need(meta['mode']=='LIVE_CLOSED','LIVE_CLOSED_ADAPTER_REQUIRED');scope=meta['scope']
    intent=authority_request(scope,sha(manifest_raw));save(output/'AUTHORITY-REVIEW-REQUEST.json',intent)
    source_summary=None
    if args.broker_read:
        pid=int(subprocess.check_output(['systemctl','--user','show','hilega-production-source-worker.service','--property=MainPID','--value'],text=True).strip());need(pid>0,'RUNNING_SOURCE_WORKER_REQUIRED')
        env=dict(PATH=os.defpath,LANG='C.UTF-8',HOME=str(Path.home()),PYTHONDONTWRITEBYTECODE='1')
        r=subprocess.run([sys.executable,'-B',str(here/'source_preflight.py'),'--repo',str(root),'--bundle',str(bundle),'--application',str(app),'--adapter',str(adapter),'--pid',str(pid),'--output',str(output)],cwd=root,env=env,capture_output=True,text=True,timeout=90)
        # The helper emits only a deliberately limited public summary; raw errors stay private.
        try:source_summary=json.loads(r.stdout)
        except ValueError:source_summary=dict(status='SOURCE_PROVIDER_PREFLIGHT_BLOCKED',reason='SOURCE_PREFLIGHT_PROCESS_FAILED')
        if r.stderr:save(output/'SOURCE-PREFLIGHT-PRIVATE-DIAGNOSTIC.json',dict(stderr=r.stderr))
        if r.returncode!=0:source_summary['status']='SOURCE_PROVIDER_PREFLIGHT_BLOCKED'
        current_pid=int(subprocess.check_output(['systemctl','--user','show','hilega-production-source-worker.service','--property=MainPID','--value'],text=True).strip())
        if current_pid!=pid:source_summary=dict(status='SOURCE_PROVIDER_PREFLIGHT_BLOCKED',reason='SOURCE_LEASE_CHANGED_DURING_CAPTURE')
    if source_summary and source_summary.get('timestamp_review'):
        save(output/'BROKER-TIMESTAMP-REVIEW.json',source_summary['timestamp_review'])
    health('CLOSED-STATUS-AFTER')
    for name in modules:need(sha(regular(bundle/name))==manifest['files'][name],'STAGED_MODULE_CHANGED_DURING_TESTS')
    for name in modules[:-1]:need(sha(regular(original_bundle/name))==original_manifest['files'][name],'INSTALLED_MODULE_CHANGED_DURING_TESTS')
    context_plan=dict(model='HILEGA_PACKAGE_B_CONTEXT_ADOPTION_REVIEW_V1',release_manifest_sha256=sha(manifest_raw),active_recovery_plan_sha256=installed['plan_sha256'],
        authority_review_request_sha256=sha(regular(output/'AUTHORITY-REVIEW-REQUEST.json')),
        live_arming_permitted=False,live_enrollment_permitted=False,hard_gate_change_available=False,
        seed_requirements=dict(max_age_seconds=60,new_post_resume_signal=True,exact_source_cursor=True,disabled_request_only=True,signed_cash_binding=True,owner_absent=True),
        private_context_requirements=['ACCOUNT_PIN','INDEPENDENT_APPROVED_AUTHORITY','BROKER_READ_TOKEN_FILE','EXACT_CONTEXT_PUBLIC_DIGEST','SOURCE_LEASE_AND_SEED_BINDING','OWNER_COMMIT_RECOVERY_RECEIPT'],
        required_before_live_seed=['TRUST_AND_ORDER_POLICY_APPROVAL','CLOSED_CONTEXT_REGISTRATION_AND_RECOVERY_BINDING_REVIEW','FEE_AND_CASH_HANDLING_RELEASE_REVIEW','SINGLE_BOUNDED_SEED_TO_OWNER_HANDOFF_REHEARSED'],
        production_authority_provisioned=False,production_execution_enabled=False)
    save(output/'CONTEXT-ADOPTION-PLAN.json',context_plan)
    report=dict(status='GROUP2_COMBINED_CANDIDATE_VALIDATION_PASS' if source_summary is None or source_summary.get('status')=='RUNNING_SOURCE_GET_EVIDENCE_PREFLIGHT_PASS' else 'GROUP2_COMBINED_CANDIDATE_PASS_BROKER_REVIEW_REQUIRED',
        targeted_cases=74,failed=0,skipped=0,prior_full_regression_reexecuted=False,
        candidate_factory_private_context_and_provisioning_modules_tested=True,
        synthetic_authority_and_owner_commit_recovery_tested=True,
        positive_paths_use_in_memory_test_gate_override=True,real_network_denied_in_tests=True,
        installed_production_gate_bytes_unchanged=True,actual_production_gate_opened=False,
        source_preflight_requested=args.broker_read,source_preflight=source_summary,
        read_only_timestamp_guard_staged=True,timestamps_automatically_shifted=False,
        candidate_changes=candidate_info,candidate_folder=str(bundle),
        factory_context_and_owner_recovery_cases=40,reservation_and_fee_candidate_cases=12,
        broker_readiness_candidate_cases=12,timestamp_regression_cases=10,
        broker_timezone_contract_independently_confirmed=False,
        context_adoption_plan_created=True,context_adoption_plan_sha256=sha(regular(output/'CONTEXT-ADOPTION-PLAN.json')),
        public_authority_review_request_created=True,live_secret_material_created=False,
        production_authority_provisioned=False,live_database_enrolled=False,execution_factory_configured=False,
        controller_resumed=False,live_preparation_created=False,application_services_changed=False,
        installed_sources_modified=False,live_database_mutations_issued=False,
        candidate_test_batch_complete=True,
        remaining_live_group2=['BROKER_TIMESTAMP_CONTRACT_AND_EXISTING_ACCOUNT_ACTIVITY_REVIEW',
            'INDEPENDENT_PRODUCTION_AUTHORITY_AND_ORDER_POLICY_APPROVAL',
            'STAGED_CONTEXT_AND_RECOVERY_BINDINGS_DEPLOYMENT_REVIEW',
            'BOUNDED_FRESH_SEED_TO_SIGNED_OWNER_ENROLLMENT',
            'ACTUAL_FEE_RECONCILIATION_AND_DEPLOYED_CASH_RELEASE'],
        group2_complete=False,production_execution_enabled=False,production_ready=False,audit_folder=str(output))
    save(output/'RESULT.json',report);(here/'VM-VALIDATION.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2));return 0 if report['status']=='GROUP2_COMBINED_CANDIDATE_VALIDATION_PASS' else 2
if __name__=='__main__':raise SystemExit(main())
