"""Stage explicit worker boundary hook and rehearse native managed windows on disposable state."""
import argparse,ast,hashlib,stat,importlib.util,json,os,subprocess,sys,tempfile
from pathlib import Path
sys.dont_write_bytecode=True
def need(ok,reason):
    if not ok:raise ValueError(reason)
def raw(p):
    need(p.is_absolute() and p.is_file() and not any(q.is_symlink() for q in (p,*p.parents)),'REGULAR_INPUT_REQUIRED');return p.read_bytes()
def sha(b):return hashlib.sha256(b).hexdigest()
def load(p):return json.loads(raw(p))
def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--repo',type=Path,required=True);ap.add_argument('--active-plan',type=Path,required=True);ap.add_argument('--active-plan-sha256',required=True);ap.add_argument('--integration-review',type=Path,required=True);a=ap.parse_args()
    root=a.repo.absolute();here=Path(__file__).absolute().parent;path=a.active_plan.absolute();review=a.integration_review.absolute()
    for n,h in load(here/'MANIFEST.json').items():need(sha(raw(here/n))==h,'WINDOW_PACKAGE_CHANGED')
    for n,h in load(here/'BASELINE-PINS.json').items():need(sha(raw(root/n))==h,'WINDOW_BASELINE_CHANGED')
    need(sha(raw(path))==a.active_plan_sha256,'ACTIVE_PLAN_CHANGED');plan=load(path);need(plan['model']=='HILEGA_WARMUP_PREVENTION_INSTALL_V1' and plan['repo']==str(root) and plan['production_execution_enabled'] is False,'CLOSED_SUCCESSOR_REQUIRED')
    need(review.parent==root and review.name.startswith('hilega-admission-enrollment-review-'),'EXPECTED_NATIVE_INTEGRATION_REVIEW_REQUIRED');prior=load(review/'RESULT.json')
    need(prior['status']=='NATIVE_DISABLED_ADMISSION_ENROLLMENT_INTEGRATION_CANDIDATE_PASS' and prior['new_cases']==8 and prior['hard_order_gate_overridden'] is False,'PASSING_EIGHT_CASE_INTEGRATION_REQUIRED')
    out=Path(tempfile.mkdtemp(prefix='hilega-window-worker-review-',dir=root));out.chmod(0o700)
    def save(name,v):
        fd=os.open(out/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as f:json.dump(v,f,indent=2);f.write('\n')
    def status(label):
        r=subprocess.run([sys.executable,'-B',str(root/'hilega-warmup-prevention-deploy-v1/manage.py'),'--repo',str(root),'--action','status','--plan',str(path),'--approve-plan-sha256',a.active_plan_sha256],capture_output=True,text=True,timeout=110);save(label+'.json',dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr));need(r.returncode==0 and json.loads(r.stdout)['phase']=='CLOSED_WARMUP_PREVENTION_RUNNING','CLOSED_RUNTIME_CHECK_FAILED')
    status('BEFORE');source=review/'candidate';old=load(source/'RELEASE-MANIFEST.json');need(sha(raw(source/'RELEASE-MANIFEST.json'))==prior['candidate_release_sha256'],'INTEGRATION_RELEASE_CHANGED')
    for n,h in old['files'].items():need(sha(raw(source/n))==h,'INTEGRATION_FILE_CHANGED')
    candidate=out/'candidate';candidate.mkdir(mode=0o700);files=dict(old['files'])
    for n in files:
        rel=Path(n);need(not rel.is_absolute() and '..' not in rel.parts,'SAFE_CANDIDATE_PATH_REQUIRED');p=candidate/rel;p.parent.mkdir(mode=0o700,parents=True,exist_ok=True);p.write_bytes(raw(source/rel))
    name='runtime/window_worker_bridge.py';need(name not in files,'WINDOW_HOOK_ALREADY_PRESENT');(candidate/name).write_bytes(raw(here/'window_worker_bridge.py'));files[name]=sha(raw(candidate/name))
    worker='runtime/worker_binding.py';text=(candidate/worker).read_text();anchor='def default_worker_poll(source,journal):';need(text.count(anchor)==1,'EXACT_WORKER_DISPATCH_REQUIRED')
    changed=text.replace(anchor,'def _default_worker_poll_without_window(source,journal):',1)+'''\n\ndef default_worker_poll(source,journal):
    from window_worker_bridge import before_poll
    if not before_poll(source,journal):
        return dict(status='WINDOW_GUARD_REJECTED_PAUSED',production_execution_enabled=False)
    result=_default_worker_poll_without_window(source,journal)
    from window_worker_bridge import observe
    return observe(source,journal,result)
'''
    compile(changed,worker,'exec');(candidate/worker).write_text(changed);files[worker]=sha(raw(candidate/worker))
    dep='backend/market_lab/hilega_preparation_runtime_v1/dependencies.json';deps=load(candidate/dep);need(deps[worker]==old['files'][worker],'ORIGINAL_WORKER_DEPENDENCY_CHANGED');deps[worker]=files[worker];deps[name]=files[name];(candidate/dep).write_text(json.dumps(deps,indent=2)+'\n');files[dep]=sha(raw(candidate/dep))
    for n,h in deps.items():need(sha(raw(candidate/n))==h,'STAGED_WINDOW_DEPENDENCY_CHANGED')
    for n in ['backend/market_lab/hilega_execution_port_v1/adapter.py','runtime/FACTORY-REGISTRATION.json','runtime/POSITION-POLICY.json','closed_worker_launcher.py','scripts/hilega_production_simulator_bridge.py']:
        need(files[n]==old['files'][n],'PROTECTED_COMPONENT_CHANGED')
    (candidate/'RELEASE-MANIFEST.json').write_text(json.dumps(dict(old,files=files,disabled_window_boundary_candidate=True),indent=2)+'\n');digest=sha(raw(candidate/'RELEASE-MANIFEST.json'))
    # Registration private_bytes requires owner-only file and parent permissions.
    # Copying immutable source bytes must not silently restore the process umask's 0644 default.
    for entry in candidate.rglob('*'):
        if entry.is_file():entry.chmod(0o400)
    for directory in sorted((x for x in candidate.rglob('*') if x.is_dir()),key=lambda x:len(x.parts),reverse=True):directory.chmod(0o500)
    candidate.chmod(0o500)
    registration=candidate/'runtime/FACTORY-REGISTRATION.json'
    info=registration.stat();parent=registration.parent.stat()
    need(info.st_uid==os.getuid() and info.st_nlink==1 and stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode)&0o077==0 and stat.S_IMODE(parent.st_mode)&0o077==0,'CANDIDATE_PRIVATE_REGISTRATION_METADATA_INVALID')
    code='import sys,json;from pathlib import Path;sys.path[:0]=[sys.argv[1],sys.argv[2]];from worker_binding import registration;v=registration(Path(sys.argv[3]),sys.argv[4]);assert v["enabled"] is False and v["production_execution_enabled"] is False;print(json.dumps({"status":"NATIVE_PRIVATE_REGISTRATION_PREFLIGHT_PASS","factory_enabled":False}))'
    check=subprocess.run([sys.executable,'-B','-c',code,str(candidate/'backend'),str(candidate/'runtime'),str(registration),files['runtime/FACTORY-REGISTRATION.json']],cwd=out,env=dict(PATH=os.defpath,LANG='C.UTF-8',HOME=str(out),PYTHONDONTWRITEBYTECODE='1'),capture_output=True,text=True,timeout=30)
    save('REGISTRATION-PREFLIGHT.json',dict(exit_code=check.returncode,stdout=check.stdout,stderr=check.stderr))
    need(check.returncode==0,'NATIVE_PRIVATE_REGISTRATION_PREFLIGHT_FAILED');print(check.stdout,flush=True)
    # No token or credential environment is forwarded to process rehearsals.
    clean=dict(PATH=os.defpath,LANG='C.UTF-8',HOME=str(out),PYTHONDONTWRITEBYTECODE='1');results=[]
    for scenario in ('fresh-signal','dead-guard-fresh-signal','normal-timeout','initiator-loss','managed-guard-loss'):
        print('Disposable worker/window scenario: '+scenario,flush=True)
        workspace=out/scenario
        r=subprocess.run([sys.executable,'-B',str(here/'run_rehearsal.py'),'--bundle',str(candidate),'--workspace',str(workspace),'--scenario',scenario],cwd=out,env=clean,capture_output=True,text=True,timeout=110)
        save(scenario+'-PROCESS.json',dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr))
        if r.returncode!=0:
            diag=workspace/'WORKER-STARTUP-DIAGNOSTIC.json'
            if diag.is_file():
                diagnostic=load(diag);save(scenario+'-STARTUP-DIAGNOSTIC.json',diagnostic);print(json.dumps(dict(scenario=scenario,startup_diagnostic=diagnostic),indent=2),flush=True)
            print(json.dumps(dict(failed_scenario=scenario,audit_folder=str(out),process_record=str(out/(scenario+'-PROCESS.json')))),flush=True)
        need(r.returncode==0,'PROCESS_SCENARIO_FAILED_'+scenario.replace('-','_').upper());results.append(load(workspace/'SCENARIO-RESULT.json'))
    for n,h in files.items():need(sha(raw(candidate/n))==h,'CANDIDATE_CHANGED_DURING_REHEARSAL')
    status('AFTER')
    report=dict(status='WORKER_BOUNDARY_AND_MANAGED_WINDOW_CANDIDATE_PASS',scenarios=results,prior_eight_native_enrollment_cases_reexecuted=False,candidate_files_sealed_owner_read_only=True,native_private_registration_preflight_passed=True,explicit_worker_hook_staged=True,source_worker_outer_cli_executed=True,signed_disabled_seed_boundary_verified=True,independent_deadline_and_exec_stop_post_recovery_rehearsed=True,arm_pause_lock_serialization_implemented=True,guard_death_exact_pre_resume_race_injection_tested=False,dead_guard_before_worker_poll_rejection_tested=True,guard_death_during_preparation_transaction_qualified=False,gate_overridden=False,live_window_arm_available=False,live_apply_available=False,live_enrollment_automated=False,worker_hook_does_not_sign_enrollment_grants=True,actual_vm_reboot_tested=False,installed_sources_modified=False,application_services_changed=False,live_databases_mutated=False,live_controller_resumed=False,orders_sent=False,production_execution_enabled=False,production_ready=False,candidate=str(candidate),candidate_release_sha256=digest,audit_folder=str(out))
    save('RESULT.json',report);(out/'MILESTONES.md').write_text('# Window/worker milestone\n\n- [x] Explicit default-off worker boundary hook staged.\n- [x] Exact outer CLI consumed fresh synthetic signal and produced signed paused boundary.\n- [x] Native managed timeout, initiator-loss and guard-loss recovery passed on disposable state.\n- [ ] Exact pre-resume guard-kill race injection and live adapter/plan qualification.\n- [ ] Real-session seed, signed ownership enrollment and final activation.\n\nNo live arming or deployment occurred.\n');(out/'MILESTONES.md').chmod(0o600);print(json.dumps(report,indent=2))
if __name__=='__main__':
    try:main()
    except Exception as exc:
        import re,traceback
        text=str(exc).split(':',1)[0];print(json.dumps(dict(status='WINDOW_WORKER_INTEGRATION_BLOCKED',reason=text if re.fullmatch('[A-Z][A-Z0-9_]*',text) else 'INSPECT_WINDOW_REVIEW_AUDIT',error_type=type(exc).__name__,location=[dict(file=Path(f.filename).name,line=f.lineno) for f in traceback.extract_tb(exc.__traceback__)[-3:]],live_apply_available=False)));raise SystemExit(2)
