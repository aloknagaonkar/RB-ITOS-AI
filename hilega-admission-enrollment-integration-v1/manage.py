"""Stage and validate native disabled admission/enrollment integration; no live apply action."""
import argparse,hashlib,importlib.util,json,os,subprocess,sys,tempfile
from pathlib import Path
import xml.etree.ElementTree as ET
sys.dont_write_bytecode=True
def need(ok,reason):
    if not ok:raise ValueError(reason)
def raw(p):
    need(p.is_absolute() and p.is_file() and not any(q.is_symlink() for q in (p,*p.parents)),'REGULAR_INPUT_REQUIRED');return p.read_bytes()
def sha(b):return hashlib.sha256(b).hexdigest()
def load(p):return json.loads(raw(p))
def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--repo',type=Path,required=True);ap.add_argument('--active-plan',type=Path,required=True);ap.add_argument('--active-plan-sha256',required=True);a=ap.parse_args()
    root=a.repo.absolute();here=Path(__file__).absolute().parent;path=a.active_plan.absolute()
    for n,h in load(here/'MANIFEST.json').items():need(sha(raw(here/n))==h,'INTEGRATION_PACKAGE_CHANGED')
    for n,h in load(here/'BASELINE-PINS.json').items():need(sha(raw(root/n))==h,'INTEGRATION_BASELINE_CHANGED')
    need(sha(raw(path))==a.active_plan_sha256,'ACTIVE_PLAN_CHANGED');plan=load(path);need(plan['model']=='HILEGA_WARMUP_PREVENTION_INSTALL_V1' and plan['repo']==str(root) and plan['production_execution_enabled'] is False,'CLOSED_SUCCESSOR_PLAN_REQUIRED')
    out=Path(tempfile.mkdtemp(prefix='hilega-admission-enrollment-review-',dir=root));out.chmod(0o700)
    def save(name,value):
        p=out/name;fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as f:json.dump(value,f,indent=2);f.write('\n')
    def status(label):
        r=subprocess.run([sys.executable,'-B',str(root/'hilega-warmup-prevention-deploy-v1/manage.py'),'--repo',str(root),'--action','status','--plan',str(path),'--approve-plan-sha256',a.active_plan_sha256],capture_output=True,text=True,timeout=110);save(label+'.json',dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr));need(r.returncode==0 and json.loads(r.stdout)['phase']=='CLOSED_WARMUP_PREVENTION_RUNNING','CLOSED_RUNTIME_CHECK_FAILED')
    status('BEFORE')
    folder=root/'hilega-issuer-provision-v1';sys.path.insert(0,str(folder));spec=importlib.util.spec_from_file_location('flow_release_reader',folder/'manage.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);source=m.verify_release(plan);manifest=load(source/'RELEASE-MANIFEST.json')
    candidate=out/'candidate';candidate.mkdir(mode=0o700);files=dict(manifest['files'])
    for n,digest in files.items():
        rel=Path(n);need(not rel.is_absolute() and '..' not in rel.parts,'SAFE_RELEASE_PATH_REQUIRED');data=raw(source/rel);need(sha(data)==digest,'SOURCE_RELEASE_CHANGED');target=candidate/rel;target.parent.mkdir(mode=0o700,parents=True,exist_ok=True);target.write_bytes(data)
    name='runtime/admission_enrollment_flow.py';need(name not in files,'INTEGRATION_ALREADY_PRESENT');(candidate/name).write_bytes(raw(here/'admission_enrollment_flow.py'));files[name]=sha(raw(candidate/name))
    dep='backend/market_lab/hilega_preparation_runtime_v1/dependencies.json';deps=load(candidate/dep);deps[name]=files[name];(candidate/dep).write_text(json.dumps(deps,indent=2)+'\n');files[dep]=sha(raw(candidate/dep))
    for n,digest in deps.items():need(sha(raw(candidate/n))==digest,'CANDIDATE_DEPENDENCY_MISMATCH')
    newmanifest=dict(manifest,files=files,disabled_enrollment_integration_candidate=True);(candidate/'RELEASE-MANIFEST.json').write_text(json.dumps(newmanifest,indent=2)+'\n');release_sha=sha(raw(candidate/'RELEASE-MANIFEST.json'))
    protected=['backend/market_lab/hilega_execution_port_v1/adapter.py','runtime/POSITION-POLICY.json','runtime/FACTORY-REGISTRATION.json','runtime/worker_binding.py','closed_worker_launcher.py','scripts/hilega_production_simulator_bridge.py']
    for n in protected:need(files[n]==manifest['files'][n],'PROTECTED_RELEASE_COMPONENT_CHANGED')
    combined=root/'hilega-group2-combined-v2';bootstrap=root/'hilega-local-bootstrap-candidate-v2'
    paths=[candidate/'backend',candidate/'runtime',here/'tests',bootstrap/'tests',combined/'tests',combined/'fixtures']
    env=dict(PATH=os.defpath,LANG='C.UTF-8',HOME=str(out),PYTHONDONTWRITEBYTECODE='1',PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',HILEGA_PACKAGE_B_BUNDLE=str(candidate),PYTHONPATH=os.pathsep.join(map(str,paths)))
    junit=out/'TESTS.xml'
    r=subprocess.run([sys.executable,'-B','-m','pytest','-q','-p','no:cacheprovider','--rootdir='+str(here),'--confcutdir='+str(here),str(here/'tests'),'--basetemp='+str(out/'synthetic'),'--junitxml='+str(junit)],cwd=out,env=env,capture_output=True,text=True,timeout=150)
    save('PROCESS.json',dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr));print(r.stdout,flush=True)
    cases=list(ET.parse(junit).getroot().iter('testcase')) if junit.is_file() else []
    need(r.returncode==0 and len(cases)==8 and all(all(c.find(t) is None for t in ('failure','error','skipped')) for c in cases),'NATIVE_INTEGRATION_CASES_FAILED')
    for n,digest in files.items():need(sha(raw(candidate/n))==digest,'CANDIDATE_CHANGED_DURING_TESTS')
    m.verify_release(plan);status('AFTER')
    report=dict(status='NATIVE_DISABLED_ADMISSION_ENROLLMENT_INTEGRATION_CANDIDATE_PASS',new_cases=8,native_fresh_seed_scan_and_binding_used=True,native_signed_local_provisioner_used=True,native_postcommit_same_key_recovery_used=True,hard_order_gate_overridden=False,real_network_denied_in_tests=True,test_transport_is_intercepted_and_no_send_expected=True,disposable_databases_and_private_files_only=True,final_activation_stays_blocked=True,candidate=str(candidate),candidate_release_sha256=release_sha,changed_modules=[name],changed_dependency_manifest=dep,existing_worker_dispatch_bytes_unchanged=True,source_worker_cli_assembly_for_live_bounded_window_implemented=False,live_window_guard_and_reload_plan_available=False,live_enrollment_apply_available=False,production_contract_admission_live_qualified=False,activation_apply_available=False,installed_sources_modified=False,services_changed=False,live_database_mutations_issued=False,live_authority_keys_created=False,broker_requests_issued=False,controller_resumed=False,production_execution_enabled=False,production_ready=False,remaining=['LIVE_BOUNDED_PREPARATION_WINDOW_ASSEMBLY_AND_INDEPENDENT_GUARD','OPEN_SESSION_V4_AND_REAL_FRESH_SEED_QUALIFICATION','EXACT_SIGNED_LIVE_DISABLED_ENROLLMENT_PLAN','BROKER_TIMESTAMP_FINAL_FEE_AND_FULL_CONTRACT_EVIDENCE','REGISTRY_ATTACHMENT_RECOVERY_AND_SEPARATE_FINAL_GATE_RELEASE'],audit_folder=str(out))
    save('RESULT.json',report)
    text='''# Implementation milestone update\n\n- [x] Candidate integration source written for native admission request, signed disabled enrollment and recovery.\n- [x] Eight disposable native integration cases passed in this VM run.\n- [x] Real order gate remained closed; no live deployment or secret material creation.\n- [ ] Live bounded window assembly and independent guard.\n- [ ] Real fresh seed, signed approval and disabled ownership enrollment.\n- [ ] Production admission and final activation qualification.\n- [ ] Broker external evidence and open-session v4 run (reminders retained).\n\nThis package implements an integration API and candidate tests; it does not implement live window arming, enable registry or release the hard order gate.\n'''
    (out/'MILESTONES.md').write_text(text);(out/'MILESTONES.md').chmod(0o600);print(json.dumps(report,indent=2))
if __name__=='__main__':
    try:main()
    except Exception as exc:
        import re,traceback
        code=str(exc).split(':',1)[0];print(json.dumps(dict(status='ADMISSION_ENROLLMENT_INTEGRATION_BLOCKED',reason=code if re.fullmatch('[A-Z][A-Z0-9_]*',code) else 'INSPECT_INTEGRATION_AUDIT',error_type=type(exc).__name__,location=[dict(file=Path(f.filename).name,line=f.lineno) for f in traceback.extract_tb(exc.__traceback__)[-3:]],live_apply_available=False)));raise SystemExit(2)
