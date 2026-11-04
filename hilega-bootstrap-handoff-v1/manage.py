"""One managed synthetic handoff/recovery validation batch. No live apply action."""
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
    old=verify(source,'682aaac7c9ed323c34ede05942d18e56ede71c55c0ac92c8189acc39db7f01ce');target.mkdir(mode=0o700);files=dict(old['files'])
    for name in files:
        p=target/name;p.parent.mkdir(mode=0o700,parents=True,exist_ok=True);p.write_bytes(regular(source/name))
    name='runtime/handoff.py';need(name not in files,'HANDOFF_ALREADY_PRESENT');(target/name).write_bytes(regular(here/'handoff.py'));files[name]=sha((target/name).read_bytes())
    dep='backend/market_lab/hilega_preparation_runtime_v1/dependencies.json';p=target/dep;deps=json.loads(p.read_text());deps[name]=files[name]
    p.write_text(json.dumps(deps,indent=2)+'\n');files[dep]=sha(p.read_bytes())
    for name,h in deps.items():need(sha(regular(target/name))==h,'STAGED_DEPENDENCY_CHANGED')
    m=dict(old,files=files,disabled_signed_handoff_candidate=True);save(target/'RELEASE-MANIFEST.json',m)
    verify(target)
    for p in target.rglob('*'):
        if p.is_file():p.chmod(0o400)
    for p in sorted((p for p in target.rglob('*') if p.is_dir()),key=lambda p:len(p.parts),reverse=True):p.chmod(0o500)
    target.chmod(0o500)
    return sha((target/'RELEASE-MANIFEST.json').read_bytes())


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--repo',type=Path,required=True)
    ap.add_argument('--current-plan',type=Path,required=True);ap.add_argument('--current-plan-sha256',required=True)
    ap.add_argument('--bootstrap-review',type=Path,required=True);a=ap.parse_args()
    root=a.repo.absolute();here=Path(__file__).absolute().parent;planpath=a.current_plan.absolute();review=a.bootstrap_review.absolute()
    for name,h in json.loads(regular(here/'MANIFEST.json')).items():need(sha(regular(here/name))==h,'HANDOFF_PACKAGE_CHANGED')
    for name,h in json.loads(regular(here/'BASELINE-PINS.json')).items():need(sha(regular(root/name))==h,'BASELINE_PACKAGE_CHANGED: '+name)
    need(sha(regular(planpath))==a.current_plan_sha256,'CURRENT_PLAN_CHANGED');plan=json.loads(regular(planpath))
    need(plan['repo']==str(root) and plan['production_execution_enabled'] is False,'CLOSED_CURRENT_PLAN_REQUIRED')
    installed=Path(plan['destination']);verify(installed,plan['release_sha256'])
    prior=json.loads(regular(review/'RESULT.json'))
    need(prior['status']=='SIGNED_LOCAL_BOOTSTRAP_AND_COMMIT_RECOVERY_CANDIDATE_PASS' and Path(prior['candidate'])==review/'candidate','PASSED_LOCAL_BOOTSTRAP_REVIEW_REQUIRED')
    out=Path(tempfile.mkdtemp(prefix='hilega-bootstrap-handoff-review-',dir=root));out.chmod(0o700);(out/'.gitignore').write_text('*\n')
    def status(label):
        r=subprocess.run([sys.executable,'-B',str(root/'hilega-worker-qualification-v1/manage.py'),'--repo',str(root),'--action','status','--plan',str(planpath),'--approve-plan-sha256',a.current_plan_sha256],capture_output=True,text=True,timeout=100)
        save(out/(label+'.json'),dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr))
        need(r.returncode==0 and json.loads(r.stdout)['phase']=='CLOSED_GROUP2_CANDIDATE_RUNNING','CURRENT_CLOSED_STATUS_FAILED; inspect '+str(out/(label+'.json')))
    status('STATUS-BEFORE');candidate=out/'candidate';digest=stage(review/'candidate',candidate,here)
    combined=root/'hilega-group2-combined-v2';bootstrap=root/'hilega-local-bootstrap-candidate-v2'
    paths=[candidate/'backend',candidate/'runtime',here/'tests',bootstrap/'tests',combined/'tests',combined/'fixtures']
    envargs=['PATH='+os.defpath,'LANG=C.UTF-8','HOME='+str(out),'PYTHONDONTWRITEBYTECODE=1','PYTEST_DISABLE_PLUGIN_AUTOLOAD=1',
        'HILEGA_PACKAGE_B_BUNDLE='+str(candidate),'PYTHONPATH='+os.pathsep.join(map(str,paths))]
    unit='hilega-disposable-handoff-'+uuid.uuid4().hex+'.service'
    junit=out/'TESTS.xml'
    # All database/file changes below belong to pytest's disposable basetemp.
    cmd=['systemd-run','--user','--wait','--collect','--unit='+unit,'--property=Type=oneshot','--property=NoNewPrivileges=yes',
        '--property=RestrictAddressFamilies=AF_UNIX','--property=RuntimeMaxSec=240','--property=UMask=0077','--working-directory='+str(out),
        '/usr/bin/env','-i',*envargs,sys.executable,'-B','-m','pytest','-q','-p','no:cacheprovider','--rootdir='+str(here),'--confcutdir='+str(here),
        str(here/'tests'),'--basetemp='+str(out/'synthetic'),'--junitxml='+str(junit)]
    print('Combined managed synthetic validation: signed handoff, lease rebind, interrupted commit and actor SIGKILL recovery',flush=True)
    r=subprocess.run(cmd,capture_output=True,text=True,timeout=255)
    save(out/'MANAGED-PROCESS.json',dict(unit=unit,exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr))
    status('STATUS-AFTER')
    cases=list(ET.parse(junit).getroot().iter('testcase')) if junit.is_file() else []
    need(r.returncode==0 and len(cases)==13 and all(all(c.find(t) is None for t in ['failure','error','skipped']) for c in cases),'MANAGED_HANDOFF_VALIDATION_FAILED; inspect '+str(out/'MANAGED-PROCESS.json')+' and '+str(junit))
    verify(installed,plan['release_sha256']);verify(candidate,digest)
    report=dict(status='MANAGED_DISABLED_HANDOFF_AND_LEASE_RECOVERY_CANDIDATE_PASS',new_handoff_cases=len(cases),
        synthetic_bootstrap_real_gate_closed=True,signed_same_lease_receipt_consumer_tested=True,explicit_signed_new_lease_rebinding_tested=True,
        owner_and_context_commit_recovery_tested=True,actor_sigkill_scenarios=2,managed_disposable_unit_used=True,
        source_worker_cli_end_to_end_qualified=False,automatic_live_boot_rebinding_installed=False,actual_vm_reboot_tested=False,
        authority_keys_preserved=True,source_cursor_preserved=True,production_gate_patched=False,
        prior_19_bootstrap_cases_reexecuted=False,broker_requests_issued=False,live_apply_available=False,
        live_secret_material_created=False,live_database_mutations_issued=False,installed_sources_modified=False,
        application_services_changed=False,controller_resumed=False,production_execution_enabled=False,production_ready=False,group2_complete=False,
        candidate=str(candidate),candidate_release_sha256=digest,audit_folder=str(out))
    save(out/'RESULT.json',report)
    (out/'MILESTONES.md').write_text('# Hilega readiness — evidence-based checklist\n\n'
        '- [x] Closed live worker, one-position policy and pause recovery deployed (prior VM results).\n'
        '- [x] Signed disabled bootstrap and commit recovery: prior 19 + 1 seed cases passed.\n'
        '- [x] This run: signed receipt consumer, explicit lease rebind, transaction recovery and two actor SIGKILL cases under disposable systemd.\n'
        '- [ ] Integrate/qualify configured source-worker CLI dispatch and matching startup recovery; candidate is not deployed.\n'
        '- [ ] Provision real independent trust root and exact private bindings after review.\n'
        '- [ ] Resolve broker timestamp contract and final per-trade fees/ownership evidence.\n'
        '- [ ] Market-session fresh disabled seed and signed owner enrollment.\n'
        '- [ ] Final release regression, operational recovery and controlled live activation.\n\n'
        'Execution remains disabled. Premium and daily-loss caps remain unconfigured; capacity stays one.\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
