"""Managed synthetic registered-factory Bridge qualification; no live deployment."""
import argparse,hashlib,json,os,subprocess,sys,tempfile,uuid
from pathlib import Path
import xml.etree.ElementTree as ET


def need(ok,reason):
    if not ok:raise ValueError(reason)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def regular(p):
    need(p.is_absolute() and p.is_file() and not any(q.is_symlink() for q in (p,*p.parents)),'REGULAR_FACTORY_INPUT_REQUIRED')
    return p.read_bytes()
def save(p,v):
    fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:json.dump(v,f,indent=2);f.write('\n')


def verify(source,digest):
    need(sha(regular(source/'RELEASE-MANIFEST.json'))==digest,'FACTORY_BASE_MANIFEST_CHANGED')
    m=json.loads(regular(source/'RELEASE-MANIFEST.json'))
    for name,h in m['files'].items():
        p=Path(name);need(not p.is_absolute() and '..' not in p.parts,'SAFE_FACTORY_RELEASE_PATH_REQUIRED')
        need(sha(regular(source/p))==h,'FACTORY_BASE_SOURCE_CHANGED: '+name)
    actual={p.relative_to(source).as_posix() for p in source.rglob('*') if p.is_file()}
    need(actual==set(m['files'])|{'RELEASE-MANIFEST.json'},'UNMANIFESTED_FACTORY_BASE_FILE')
    return m


def stage(source,target,digest,here):
    old=verify(source,digest);target.mkdir(mode=0o700);files=dict(old['files'])
    for name in files:
        p=target/name;p.parent.mkdir(mode=0o700,parents=True,exist_ok=True);p.write_bytes(regular(source/name))
    added='runtime/factory_source.py';need(added not in files,'FACTORY_ADAPTER_ALREADY_PRESENT')
    (target/added).write_bytes(regular(here/'factory_source.py'));files[added]=sha((target/added).read_bytes())
    name='runtime/worker_binding.py';text=(target/name).read_text()
    anchor="        try:\n            bind=value['expected_binding']"
    need(text.count(anchor)==1,'EXACT_REGISTERED_FACTORY_GATE_ANCHOR_REQUIRED')
    text=text.replace(anchor,"        try:\n            from factory_source import prepare_factory_source\n            source=prepare_factory_source(self,source,journal)\n            bind=value['expected_binding']")
    compile(text,name,'exec');(target/name).write_text(text);files[name]=sha((target/name).read_bytes())
    dep='backend/market_lab/hilega_preparation_runtime_v1/dependencies.json';p=target/dep;deps=json.loads(p.read_text())
    need(deps[name]==old['files'][name],'FACTORY_WORKER_DEPENDENCY_CHANGED')
    for name in [name,added]:deps[name]=files[name]
    p.write_text(json.dumps(deps,indent=2)+'\n');files[dep]=sha(p.read_bytes())
    for name,h in deps.items():need(sha(regular(target/name))==h,'FACTORY_DEPENDENCY_CHAIN_CHANGED')
    for name in ['backend/market_lab/hilega_execution_port_v1/adapter.py','runtime/FACTORY-REGISTRATION.json','runtime/POSITION-POLICY.json']:
        need(files[name]==old['files'][name],'FACTORY_GATE_OR_DEFAULT_POLICY_CHANGED')
    save(target/'RELEASE-MANIFEST.json',dict(old,files=files,registered_factory_bridge_candidate=True))
    newsha=sha(regular(target/'RELEASE-MANIFEST.json'));verify(target,newsha)
    for p in target.rglob('*'):
        if p.is_file():p.chmod(0o400)
    for p in sorted((p for p in target.rglob('*') if p.is_dir()),key=lambda p:len(p.parts),reverse=True):p.chmod(0o500)
    target.chmod(0o500);return newsha


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--repo',type=Path,required=True)
    ap.add_argument('--current-plan',type=Path,required=True);ap.add_argument('--current-plan-sha256',required=True);a=ap.parse_args()
    root=a.repo.absolute();here=Path(__file__).absolute().parent;path=a.current_plan.absolute()
    for name,h in json.loads(regular(here/'MANIFEST.json')).items():need(sha(regular(here/name))==h,'FACTORY_PACKAGE_CHANGED')
    for name,h in json.loads(regular(here/'BASELINE-PINS.json')).items():need(sha(regular(root/name))==h,'FACTORY_BASELINE_TOOL_CHANGED: '+name)
    need(sha(regular(path))==a.current_plan_sha256,'CURRENT_FACTORY_PLAN_CHANGED');plan=json.loads(regular(path))
    need(plan['repo']==str(root) and plan['production_execution_enabled'] is False and plan['execution_factory_configured'] is False,'CLOSED_FACTORY_PLAN_REQUIRED')
    source=Path(plan['destination']);need(plan['release_sha256']=='7ff8f3e672b68a58945cb400aae278028e65dd7d5494d2454376ea795581235b','EXPECTED_DEPLOYED_BOOTSTRAP_RELEASE_REQUIRED')
    out=Path(tempfile.mkdtemp(prefix='hilega-factory-process-review-',dir=root));out.chmod(0o700);(out/'.gitignore').write_text('*\n')
    def status(label):
        r=subprocess.run([sys.executable,'-B',str(root/'hilega-bootstrap-deploy-v1/manage.py'),'--repo',str(root),'--action','status','--plan',str(path),'--approve-plan-sha256',a.current_plan_sha256],capture_output=True,text=True,timeout=100)
        save(out/(label+'.json'),dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr))
        need(r.returncode==0 and json.loads(r.stdout)['phase']=='CLOSED_GROUP2_CANDIDATE_RUNNING','CURRENT_FACTORY_STATUS_FAILED; inspect '+str(out/(label+'.json')))
    status('STATUS-BEFORE');candidate=out/'candidate';digest=stage(source,candidate,plan['release_sha256'],here)
    combined=root/'hilega-group2-combined-v2';trust=root/'hilega-trust-worker-batch-v2';authority=root/'hilega-authority-factory-candidate-v1';qualification=root/'hilega-worker-qualification-v1'
    paths=[candidate/'backend',candidate/'runtime',here/'tests',trust/'tests',authority/'tests',combined/'tests',combined/'fixtures']
    envargs=['PATH='+os.defpath,'LANG=C.UTF-8','HOME='+str(out),'PYTHONDONTWRITEBYTECODE=1','PYTEST_DISABLE_PLUGIN_AUTOLOAD=1',
             'HILEGA_PACKAGE_B_BUNDLE='+str(candidate),'PYTHONPATH='+os.pathsep.join(map(str,paths))]
    junit=out/'TESTS.xml';unit='hilega-disposable-factory-process-'+uuid.uuid4().hex+'.service'
    cmd=['systemd-run','--user','--wait','--collect','--unit='+unit,'--property=Type=oneshot','--property=NoNewPrivileges=yes',
         '--property=RestrictAddressFamilies=AF_UNIX','--property=RuntimeMaxSec=240','--property=UMask=0077','--working-directory='+str(out),
         '/usr/bin/env','-i',*envargs,sys.executable,'-B','-m','pytest','-q','-p','no:cacheprovider','--rootdir='+str(here),'--confcutdir='+str(here),
         str(here/'tests'),str(trust/'tests/test_worker_files.py'),str(qualification/'tests/test_qualification.py'),str(combined/'seed_preflight.py'),
         '--basetemp='+str(out/'synthetic'),'--junitxml='+str(junit)]
    print('Managed synthetic factory qualification: Bridge attachment, child-process cycles, registry, gate and lease regressions',flush=True)
    r=subprocess.run(cmd,capture_output=True,text=True,timeout=255)
    save(out/'MANAGED-PROCESS.json',dict(unit=unit,exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr));status('STATUS-AFTER')
    cases=list(ET.parse(junit).getroot().iter('testcase')) if junit.is_file() else []
    need(r.returncode==0 and len(cases)==30 and all(all(c.find(t) is None for t in ['failure','error','skipped']) for c in cases),'FACTORY_PROCESS_TESTS_FAILED; inspect '+str(out/'MANAGED-PROCESS.json')+' and '+str(junit))
    verify(source,plan['release_sha256']);verify(candidate,digest)
    report=dict(status='REGISTERED_FACTORY_BRIDGE_SYNTHETIC_PROCESS_CANDIDATE_PASS',reexecuted_cases=30,new_bridge_cases=5,
        file_registration_cases_reexecuted=16,worker_lease_cases_reexecuted=8,seed_preflight_cases=1,
        registered_factory_child_process_two_cycles_verified=True,synthetic_intercepted_sends=4,
        managed_unit_used=True,positive_paths_use_in_memory_gate_override=True,real_network_denied=True,
        real_parent_gate_remained_closed=True,installed_gate_source_unchanged=True,
        bridge_source_identity_and_lease_rejection_tested=True,missing_preparation_tables_not_created=True,
        full_source_worker_cli_positive_factory_branch_verified=False,production_transport_validated=False,
        factory_registration_enabled_on_live=False,production_trust_provisioned=False,live_database_enrolled=False,
        live_apply_available=False,installed_sources_modified=False,application_services_changed=False,
        live_database_mutations_issued=False,live_secret_material_created=False,broker_requests_issued=False,
        controller_resumed=False,production_execution_enabled=False,production_ready=False,group2_complete=False,
        candidate=str(candidate),candidate_release_sha256=digest,audit_folder=str(out))
    save(out/'RESULT.json',report)
    (out/'MILESTONES.md').write_text('# Hilega progress after registered-factory qualification\n\n'
        '- [x] Integrated closed bootstrap/worker release deployed (prior apply/status).\n'
        '- [x] This run: registered factory Bridge attachment, two synthetic child-process cycles and gate/lease/file regressions.\n'
        '- [ ] Positive factory branch through the full outer CLI and startup-recovery lifecycle, using intercepted transport.\n'
        '- [ ] Real independent trust provisioning and reviewed activation bindings.\n'
        '- [ ] Broker timestamp contract, actual fees and account ownership evidence.\n'
        '- [ ] Fresh real disabled enrollment, final qualification and controlled live activation.\n\n'
        'This candidate is not deployed. Test gate overrides are process-local; real execution remains disabled.\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
