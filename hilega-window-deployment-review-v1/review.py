"""Read-only deployment impact and recovery proposal; no live apply operation."""
import argparse, hashlib, json, os, stat, subprocess, sys, tempfile
from pathlib import Path

def need(ok, reason):
    if not ok: raise ValueError(reason)
def raw(p):
    need(p.is_absolute() and p.is_file() and not any(q.is_symlink() for q in (p,*p.parents)), 'REGULAR_INPUT_REQUIRED')
    return p.read_bytes()
def sha(b): return hashlib.sha256(b).hexdigest()
def load(p): return json.loads(raw(p))
def bundle(p, digest):
    manifest=load(p/'RELEASE-MANIFEST.json')
    need(sha(raw(p/'RELEASE-MANIFEST.json'))==digest,'RELEASE_MANIFEST_CHANGED')
    for name,h in manifest['files'].items():
        rel=Path(name)
        need(not rel.is_absolute() and '..' not in rel.parts,'SAFE_RELEASE_PATH_REQUIRED')
        need(sha(raw(p/rel))==h,'RELEASE_FILE_CHANGED')
    return manifest

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for key in ('repo','active-plan','window-review'): ap.add_argument('--'+key,type=Path,required=True)
    ap.add_argument('--active-plan-sha256',required=True)
    a=ap.parse_args(); root=a.repo.absolute(); planpath=a.active_plan.absolute(); review=a.window_review.absolute(); here=Path(__file__).absolute().parent
    for n,h in load(here/'MANIFEST.json').items(): need(sha(raw(here/n))==h,'TOOL_CHANGED')
    for n,h in load(here/'BASELINE-PINS.json').items(): need(sha(raw(root/n))==h,'REVIEW_BASELINE_CHANGED')
    need(sha(raw(planpath))==a.active_plan_sha256,'ACTIVE_PLAN_CHANGED'); plan=load(planpath)
    need(plan['model']=='HILEGA_WARMUP_PREVENTION_INSTALL_V1' and plan['repo']==str(root) and plan['production_execution_enabled'] is False,'CLOSED_SUCCESSOR_REQUIRED')
    need(review.parent==root and review.name.startswith('hilega-window-worker-review-'),'EXPECTED_WINDOW_REVIEW_REQUIRED')
    receipt=load(review/'RESULT.json')
    need(receipt['status']=='WORKER_BOUNDARY_AND_MANAGED_WINDOW_CANDIDATE_PASS' and receipt['gate_overridden'] is False and receipt['live_controller_resumed'] is False,'PASSED_CLOSED_REHEARSAL_REQUIRED')
    need({s['scenario'] for s in receipt['scenarios']}=={'fresh-signal','normal-timeout','initiator-loss','managed-guard-loss'},'FOUR_SCENARIOS_REQUIRED')
    for s in receipt['scenarios']: need(s['disposable_databases_only'] is True,'DISPOSABLE_RECEIPT_REQUIRED')
    candidate=review/'candidate'; need(receipt['candidate']==str(candidate),'EXACT_CANDIDATE_REQUIRED')
    need(receipt['candidate_release_sha256']=='a23ddba83ca884366a1007da3c3bee0edb3e356bd635b9dfcaffb192db264ce9','EXPECTED_VM_RELEASE_REQUIRED')
    old=bundle(Path(plan['destination']),plan['release_sha256']); new=bundle(candidate,receipt['candidate_release_sha256'])
    need(set(old['files'])<=set(new['files']),'RELEASE_FILE_REMOVAL_FORBIDDEN')
    protected=['backend/market_lab/hilega_execution_port_v1/adapter.py','runtime/FACTORY-REGISTRATION.json','runtime/POSITION-POLICY.json','closed_worker_launcher.py','scripts/hilega_production_simulator_bridge.py']
    for n in protected: need(old['files'][n]==new['files'][n],'PROTECTED_COMPONENT_CHANGED')
    changed=[dict(path=n,installed_sha256=old['files'].get(n),candidate_sha256=h) for n,h in sorted(new['files'].items()) if old['files'].get(n)!=h]
    expected={'runtime/admission_enrollment_flow.py','runtime/window_worker_bridge.py','runtime/worker_binding.py','backend/market_lab/hilega_preparation_runtime_v1/dependencies.json'}
    need({x['path'] for x in changed}==expected,'UNEXPECTED_DEPLOYMENT_SCOPE')
    deps=load(candidate/'backend/market_lab/hilega_preparation_runtime_v1/dependencies.json')
    for n,h in deps.items(): need(new['files'].get(n)==h,'DEPENDENCY_BINDING_CHANGED')
    for n in new['files']:
        info=(candidate/n).stat(); need(info.st_uid==os.getuid() and info.st_nlink==1 and stat.S_IMODE(info.st_mode)&0o077==0,'PRIVATE_CANDIDATE_REQUIRED')
    out=Path(tempfile.mkdtemp(prefix='hilega-window-deployment-review-',dir=root));out.chmod(0o700)
    def save(name,v):
        fd=os.open(out/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as f: json.dump(v,f,indent=2);f.write('\n')
    def status(label):
        r=subprocess.run([sys.executable,'-B',str(root/'hilega-warmup-prevention-deploy-v1/manage.py'),'--repo',str(root),'--action','status','--plan',str(planpath),'--approve-plan-sha256',a.active_plan_sha256],capture_output=True,text=True,timeout=110)
        save(label+'.json',dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr))
        need(r.returncode==0 and json.loads(r.stdout)['phase']=='CLOSED_WARMUP_PREVENTION_RUNNING','INSTALLED_CLOSED_RUNTIME_REQUIRED')
    status('STATUS-BEFORE')
    proposal=dict(model='HILEGA_WINDOW_CLOSED_DEPLOYMENT_PROPOSAL_V1',active_plan=str(planpath),active_plan_sha256=a.active_plan_sha256,window_receipt=str(review/'RESULT.json'),window_receipt_sha256=sha(raw(review/'RESULT.json')),installed_release_sha256=plan['release_sha256'],candidate=str(candidate),candidate_release_sha256=receipt['candidate_release_sha256'],changes=changed,protected_files=protected,apply_available=False,live_window_arm_available=False,production_execution_enabled=False,
      required_installation_checks=['Rehearse exact guard-death-before-resume interleavings on disposable state','Qualify successor wrapper and startup recovery against candidate release','Prepare quiescent file and database backups with no automatic database restore','Install closed release with window configuration absent and factory disabled','Verify heartbeat, paused controller and warmup using successor status driver'],
      recovery_contract=dict(default_window_configuration='ABSENT',startup_controller='PAUSED',factory_registration_enabled=False,lease_migration='EXPLICIT_SIGNED_REBIND_ONLY',database_restore='NEVER_AUTOMATIC',rollback_target=plan['release_sha256']),
      pending_reminders=['Open-session v4 WebSocket and native contract coverage validation','Upstox timestamp reply and final November 2 contract note/fee reconciliation','Real fresh disabled seed and ownership enrollment, then separate final activation'])
    save('DEPLOYMENT-PROPOSAL.json',proposal)
    bundle(candidate,receipt['candidate_release_sha256']);status('STATUS-AFTER')
    report=dict(status='CLOSED_WINDOW_DEPLOYMENT_IMPACT_REVIEW_PASS',changed_file_count=len(changed),four_prior_scenarios_receipt_verified=True,prior_scenarios_reexecuted=False,guard_race_qualified=False,proposal=str(out/'DEPLOYMENT-PROPOSAL.json'),proposal_sha256=sha(raw(out/'DEPLOYMENT-PROPOSAL.json')),live_apply_available=False,installed_sources_modified=False,controller_resumed=False,production_execution_enabled=False,production_ready=False)
    save('RESULT.json',report);print(json.dumps(report,indent=2))
if __name__=='__main__':
    try: main()
    except Exception as exc:
        import re
        reason=str(exc);print(json.dumps(dict(status='WINDOW_DEPLOYMENT_REVIEW_BLOCKED',reason=reason if re.fullmatch('[A-Z][A-Z0-9_]*',reason) else 'INSPECT_REVIEW_INPUTS',error_type=type(exc).__name__,live_apply_available=False)));raise SystemExit(2)
