"""Combined exact-CLI worker handoff and closed startup/restart qualification. No live apply action."""
import argparse,hashlib,json,os,subprocess,sys,tempfile,uuid
from pathlib import Path
import xml.etree.ElementTree as ET


def need(ok,reason):
    if not ok:raise ValueError(reason)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def regular(p):
    need(p.is_absolute() and p.is_file() and not any(q.is_symlink() for q in (p,*p.parents)),'REGULAR_INPUT_REQUIRED: '+str(p))
    return p.read_bytes()
def save(p,v):
    fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:json.dump(v,f,indent=2);f.write('\n')


def verify(bundle,digest=None):
    raw=regular(bundle/'RELEASE-MANIFEST.json')
    if digest:need(sha(raw)==digest,'RELEASE_MANIFEST_CHANGED')
    m=json.loads(raw)
    for name,h in m['files'].items():
        rel=Path(name);need(not rel.is_absolute() and '..' not in rel.parts,'SAFE_MANIFEST_PATH_REQUIRED')
        need(sha(regular(bundle/rel))==h,'RELEASE_FILE_CHANGED: '+name)
    return m


def stage(source,target,here):
    old=verify(source,'240f50de3b2b638f34f3e0162a84510c0c13d79e91e4d82b80406995343a217e');target.mkdir(mode=0o700);files=dict(old['files'])
    for name in files:
        p=target/name;p.parent.mkdir(mode=0o700,parents=True,exist_ok=True);p.write_bytes(regular(source/name))
    name='runtime/bootstrap_worker.py';need(name not in files,'WORKER_HANDOFF_ALREADY_PRESENT')
    (target/name).write_bytes(regular(here/'bootstrap_worker.py'));files[name]=sha((target/name).read_bytes())
    worker='runtime/worker_binding.py';text=(target/worker).read_text()
    anchor='def default_worker_poll(source,journal):\n    global _DEFAULT'
    need(text.count(anchor)==1,'EXACT_DEFAULT_WORKER_DISPATCH_REQUIRED')
    changed=text.replace(anchor,'def default_worker_poll(source,journal):\n    from bootstrap_worker import configured_poll\n    local_result=configured_poll(source,journal)\n    if local_result is not None:return local_result\n    global _DEFAULT')
    compile(changed,worker,'exec');(target/worker).write_text(changed);files[worker]=sha((target/worker).read_bytes())
    dep='backend/market_lab/hilega_preparation_runtime_v1/dependencies.json';p=target/dep;deps=json.loads(p.read_text())
    need(deps[worker]==old['files'][worker],'OLD_WORKER_DEPENDENCY_CHANGED')
    for name in ['runtime/bootstrap_worker.py',worker]:deps[name]=files[name]
    p.write_text(json.dumps(deps,indent=2)+'\n');files[dep]=sha(p.read_bytes())
    for name,h in deps.items():need(sha(regular(target/name))==h,'STAGED_DEPENDENCY_CHANGED')
    for name in ['backend/market_lab/hilega_execution_port_v1/adapter.py','runtime/FACTORY-REGISTRATION.json','runtime/POSITION-POLICY.json','closed_worker_launcher.py','scripts/hilega_production_simulator_bridge.py']:
        need(files[name]==old['files'][name],'PROTECTED_RUNTIME_CHANGED')
    m=dict(old,files=files,closed_worker_handoff_candidate=True);save(target/'RELEASE-MANIFEST.json',m);verify(target)
    for p in target.rglob('*'):
        if p.is_file():p.chmod(0o400)
    for p in sorted((p for p in target.rglob('*') if p.is_dir()),key=lambda p:len(p.parts),reverse=True):p.chmod(0o500)
    target.chmod(0o500)
    return sha((target/'RELEASE-MANIFEST.json').read_bytes())


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--repo',type=Path,required=True)
    ap.add_argument('--current-plan',type=Path,required=True);ap.add_argument('--current-plan-sha256',required=True)
    ap.add_argument('--handoff-review',type=Path,required=True);a=ap.parse_args()
    root=a.repo.absolute();here=Path(__file__).absolute().parent;planpath=a.current_plan.absolute();review=a.handoff_review.absolute()
    for name,h in json.loads(regular(here/'MANIFEST.json')).items():need(sha(regular(here/name))==h,'HANDOFF_PACKAGE_CHANGED')
    for name,h in json.loads(regular(here/'BASELINE-PINS.json')).items():need(sha(regular(root/name))==h,'BASELINE_PACKAGE_CHANGED: '+name)
    need(sha(regular(planpath))==a.current_plan_sha256,'CURRENT_PLAN_CHANGED');plan=json.loads(regular(planpath))
    need(plan['repo']==str(root) and plan['production_execution_enabled'] is False,'CLOSED_CURRENT_PLAN_REQUIRED')
    installed=Path(plan['destination']);verify(installed,plan['release_sha256'])
    prior=json.loads(regular(review/'RESULT.json'))
    need(prior['status']=='MANAGED_DISABLED_HANDOFF_AND_LEASE_RECOVERY_CANDIDATE_PASS' and Path(prior['candidate'])==review/'candidate','PASSED_MANAGED_HANDOFF_REVIEW_REQUIRED')
    out=Path(tempfile.mkdtemp(prefix='hilega-bootstrap-worker-review-',dir=root));out.chmod(0o700);(out/'.gitignore').write_text('*\n')
    def status(label):
        r=subprocess.run([sys.executable,'-B',str(root/'hilega-worker-qualification-v1/manage.py'),'--repo',str(root),'--action','status','--plan',str(planpath),'--approve-plan-sha256',a.current_plan_sha256],capture_output=True,text=True,timeout=100)
        save(out/(label+'.json'),dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr))
        need(r.returncode==0 and json.loads(r.stdout)['phase']=='CLOSED_GROUP2_CANDIDATE_RUNNING','CURRENT_CLOSED_STATUS_FAILED; inspect '+str(out/(label+'.json')))
    status('STATUS-BEFORE');candidate=out/'candidate';digest=stage(review/'candidate',candidate,here)
    combined=root/'hilega-group2-combined-v2';bootstrap=root/'hilega-local-bootstrap-candidate-v2';handoff=root/'hilega-bootstrap-handoff-v1'
    paths=[candidate/'backend',candidate/'runtime',here/'tests',handoff/'tests',bootstrap/'tests',combined/'tests',combined/'fixtures']
    envargs=['PATH='+os.defpath,'LANG=C.UTF-8','HOME='+str(out),'PYTHONDONTWRITEBYTECODE=1','PYTEST_DISABLE_PLUGIN_AUTOLOAD=1',
        'HILEGA_WORKER_FIXTURE_HELPER='+str(here/'fixture_worker.py'),'HILEGA_PACKAGE_B_BUNDLE='+str(candidate),'PYTHONPATH='+os.pathsep.join(map(str,paths))]
    unit='hilega-disposable-bootstrap-worker-'+uuid.uuid4().hex+'.service'
    junit=out/'TESTS.xml'
    # All database/file changes below belong to pytest's disposable basetemp.
    cmd=['systemd-run','--user','--wait','--collect','--unit='+unit,'--property=Type=oneshot','--property=NoNewPrivileges=yes',
        '--property=RestrictAddressFamilies=AF_UNIX','--property=RuntimeMaxSec=240','--property=UMask=0077','--working-directory='+str(out),
        '/usr/bin/env','-i',*envargs,sys.executable,'-B','-m','pytest','-q','-p','no:cacheprovider','--rootdir='+str(here),'--confcutdir='+str(here),
        str(here/'tests'),str(handoff/'tests'),str(bootstrap/'tests'),str(combined/'seed_preflight.py'),'--basetemp='+str(out/'synthetic'),'--junitxml='+str(junit)]
    print('Combined managed validation: exact worker CLI, signed admission, restart rebinding and bootstrap/handoff regression',flush=True)
    r=subprocess.run(cmd,capture_output=True,text=True,timeout=255)
    save(out/'MANAGED-PROCESS.json',dict(unit=unit,exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr))
    status('STATUS-AFTER')
    cases=list(ET.parse(junit).getroot().iter('testcase')) if junit.is_file() else []
    need(r.returncode==0 and len(cases)==36 and all(all(c.find(t) is None for t in ['failure','error','skipped']) for c in cases),'MANAGED_WORKER_VALIDATION_FAILED; inspect '+str(out/'MANAGED-PROCESS.json')+' and '+str(junit))
    verify(installed,plan['release_sha256']);verify(candidate,digest)
    proposal=dict(model='HILEGA_CLOSED_WORKER_DEPLOYMENT_PROPOSAL_V1',repo=str(root),candidate=str(candidate),candidate_release_sha256=digest,
        predecessor_plan=str(planpath),predecessor_plan_sha256=a.current_plan_sha256,rollback_release_sha256=plan['release_sha256'],
        target_destination=str(root/'data/runtime/hilega-closed-releases'/digest),factory_enabled=False,
        local_handoff_config_deployed=False,production_execution_enabled=False,live_apply_available=False,
        required_before_apply=['EXACT_WRAPPER_AND_RECOVERY_BINDING_PLAN','QUIESCENT_CODE_DATABASE_AND_CONFIGURATION_BACKUPS','STATE_RECHECK_AND_ROLLBACK_BINDINGS'])
    save(out/'DEPLOYMENT-PROPOSAL.json',proposal)
    report=dict(status='CLOSED_WORKER_CLI_HANDOFF_AND_RESTART_CANDIDATE_PASS',reexecuted_cases=len(cases),
        new_worker_cases=3,prior_handoff_cases_reexecuted=13,prior_bootstrap_cases_reexecuted=19,seed_preflight_cases=1,
        exact_bundled_launcher_executed=True,synthetic_clock_injected=True,real_order_gate_unchanged=True,
        current_lease_signed_handoff_consumed=True,worker_sigkill_restart_requires_new_signed_rebind=True,
        stale_mailbox_and_tampering_stay_paused=True,source_cursor_and_authority_bytes_preserved=True,
        execution_factory_process_qualified=False,closed_handoff_process_qualified=True,
        automatic_live_boot_rebinding_installed=False,actual_vm_reboot_tested=False,
        production_trust_provisioned=False,live_database_enrolled=False,broker_requests_issued=False,
        live_apply_available=False,live_secret_material_created=False,live_database_mutations_issued=False,
        installed_sources_modified=False,application_services_changed=False,controller_resumed=False,
        production_execution_enabled=False,production_ready=False,group2_complete=False,
        candidate=str(candidate),candidate_release_sha256=digest,deployment_proposal=str(out/'DEPLOYMENT-PROPOSAL.json'),
        deployment_proposal_sha256=sha((out/'DEPLOYMENT-PROPOSAL.json').read_bytes()),audit_folder=str(out))
    save(out/'RESULT.json',report)
    (out/'MILESTONES.md').write_text('# Hilega readiness — after combined VM validation\n\n'
        '- [x] Closed live worker, one-position policy and pause recovery deployed (prior VM results).\n'
        '- [x] This run: 19 bootstrap, 13 handoff, 3 worker checks plus one seed preflight.\n'
        '- [x] Exact bundled closed worker CLI consumes a signed handoff; restart blocks stale lease until explicitly rebound.\n'
        '- [x] Deployment proposal created with current release as rollback target.\n'
        '- [ ] Exact installation/recovery binding plan, backups and reviewed deployment.\n'
        '- [ ] Production trust provisioning and configured execution-factory qualification.\n'
        '- [ ] Broker timestamp contract, final fees and ownership evidence.\n'
        '- [ ] Market-session fresh disabled seed/enrollment and final operational qualification.\n'
        '- [ ] Controlled live activation.\n\nExecution disabled; max one position; premium/daily caps remain null.\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
