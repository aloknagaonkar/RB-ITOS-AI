"""Exact candidate outer CLI qualification using synthetic inputs only; no live changes."""
import argparse,hashlib,json,os,subprocess,sys,tempfile,uuid
from pathlib import Path
import xml.etree.ElementTree as ET


def need(ok,reason):
    if not ok:raise ValueError(reason)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def regular(p):
    need(p.is_absolute() and p.is_file() and not any(q.is_symlink() for q in (p,*p.parents)),'REGULAR_CLI_INPUT_REQUIRED')
    return p.read_bytes()
def save(p,v):
    fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:json.dump(v,f,indent=2);f.write('\n')


def verify(bundle,digest):
    need(sha(regular(bundle/'RELEASE-MANIFEST.json'))==digest,'CLI_RELEASE_MANIFEST_CHANGED')
    manifest=json.loads(regular(bundle/'RELEASE-MANIFEST.json'))
    for name,h in manifest['files'].items():
        rel=Path(name);need(not rel.is_absolute() and '..' not in rel.parts,'SAFE_CLI_RELEASE_PATH_REQUIRED')
        need(sha(regular(bundle/rel))==h,'CLI_RELEASE_SOURCE_CHANGED: '+name)
    actual={p.relative_to(bundle).as_posix() for p in bundle.rglob('*') if p.is_file()}
    need(actual==set(manifest['files'])|{'RELEASE-MANIFEST.json'},'UNMANIFESTED_CLI_RELEASE_FILE')
    return manifest


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--repo',type=Path,required=True)
    ap.add_argument('--current-plan',type=Path,required=True);ap.add_argument('--current-plan-sha256',required=True)
    ap.add_argument('--factory-review',type=Path,required=True);a=ap.parse_args()
    root=a.repo.absolute();here=Path(__file__).absolute().parent;path=a.current_plan.absolute();review=a.factory_review.absolute()
    for name,h in json.loads(regular(here/'MANIFEST.json')).items():need(sha(regular(here/name))==h,'CLI_PACKAGE_CHANGED')
    for name,h in json.loads(regular(here/'BASELINE-PINS.json')).items():need(sha(regular(root/name))==h,'CLI_BASELINE_CHANGED: '+name)
    need(sha(regular(path))==a.current_plan_sha256,'CURRENT_CLI_PLAN_CHANGED');plan=json.loads(regular(path))
    need(plan['repo']==str(root) and plan['execution_factory_configured'] is False and plan['production_execution_enabled'] is False,'CLOSED_CURRENT_CLI_PLAN_REQUIRED')
    previous=json.loads(regular(review/'RESULT.json'));candidate=review/'candidate'
    need(previous['status']=='REGISTERED_FACTORY_BRIDGE_SYNTHETIC_PROCESS_CANDIDATE_PASS' and previous['reexecuted_cases']==30
         and Path(previous['candidate'])==candidate,'PASSED_REGISTERED_FACTORY_REVIEW_REQUIRED')
    digest='48b68578e1d83bb654662e3d077383e05025adabd363efb7b271f65f4d71ec4a'
    need(previous['candidate_release_sha256']==digest,'EXPECTED_FACTORY_CANDIDATE_REQUIRED')
    manifest=verify(candidate,digest);live=verify(Path(plan['destination']),plan['release_sha256'])
    for name in ['backend/market_lab/hilega_execution_port_v1/adapter.py','runtime/FACTORY-REGISTRATION.json','runtime/POSITION-POLICY.json']:
        need(manifest['files'][name]==live['files'][name],'GATE_DEFAULT_REGISTRATION_OR_POLICY_CHANGED')
    out=Path(tempfile.mkdtemp(prefix='hilega-factory-cli-review-',dir=root));out.chmod(0o700);(out/'.gitignore').write_text('*\n')
    save(out/'INPUTS.json',dict(current_plan=str(path),current_plan_sha256=a.current_plan_sha256,factory_review=str(review),
        factory_receipt_sha256=sha(regular(review/'RESULT.json')),candidate=str(candidate),candidate_release_sha256=digest))
    def status(label):
        r=subprocess.run([sys.executable,'-B',str(root/'hilega-bootstrap-deploy-v1/manage.py'),'--repo',str(root),'--action','status',
            '--plan',str(path),'--approve-plan-sha256',a.current_plan_sha256],capture_output=True,text=True,timeout=100)
        save(out/(label+'.json'),dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr))
        need(r.returncode==0 and json.loads(r.stdout)['phase']=='CLOSED_GROUP2_CANDIDATE_RUNNING','CURRENT_CLI_STATUS_FAILED; inspect '+str(out/(label+'.json')))
    status('STATUS-BEFORE')
    combined=root/'hilega-group2-combined-v2';trust=root/'hilega-trust-worker-batch-v2';authority=root/'hilega-authority-factory-candidate-v1';qualification=root/'hilega-worker-qualification-v1';factory=root/'hilega-factory-process-v1'
    paths=[candidate/'backend',candidate/'runtime',here/'tests',factory/'tests',trust/'tests',authority/'tests',combined/'tests',combined/'fixtures']
    envargs=['PATH='+os.defpath,'LANG=C.UTF-8','HOME='+str(out),'PYTHONDONTWRITEBYTECODE=1','PYTEST_DISABLE_PLUGIN_AUTOLOAD=1',
        'HILEGA_PACKAGE_B_BUNDLE='+str(candidate),'PYTHONPATH='+os.pathsep.join(map(str,paths))]
    junit=out/'TESTS.xml';unit='hilega-disposable-factory-cli-'+uuid.uuid4().hex+'.service'
    cmd=['systemd-run','--user','--wait','--collect','--unit='+unit,'--property=Type=oneshot','--property=NoNewPrivileges=yes',
        '--property=RestrictAddressFamilies=AF_UNIX','--property=RuntimeMaxSec=300','--property=UMask=0077','--working-directory='+str(out),
        '/usr/bin/env','-i',*envargs,sys.executable,'-B','-m','pytest','-q','-p','no:cacheprovider','--rootdir='+str(here),'--confcutdir='+str(here),
        str(here/'tests'),str(factory/'tests'),str(trust/'tests/test_worker_files.py'),str(qualification/'tests/test_qualification.py'),str(combined/'seed_preflight.py'),
        '--basetemp='+str(out/'synthetic'),'--junitxml='+str(junit)]
    print('Managed exact outer CLI batch: native startup, fresh synthetic bootstrap, factory cycles, new-process stale lease and root-change rejection',flush=True)
    r=subprocess.run(cmd,capture_output=True,text=True,timeout=315)
    save(out/'MANAGED-PROCESS.json',dict(unit=unit,exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr));status('STATUS-AFTER')
    cases=list(ET.parse(junit).getroot().iter('testcase')) if junit.is_file() else []
    need(r.returncode==0 and len(cases)==32 and all(all(c.find(t) is None for t in ['failure','error','skipped']) for c in cases),'FACTORY_CLI_TESTS_FAILED; inspect '+str(out/'MANAGED-PROCESS.json')+' and '+str(junit))
    verify(candidate,digest);verify(Path(plan['destination']),plan['release_sha256'])
    report=dict(status='EXACT_OUTER_CLI_SYNTHETIC_FACTORY_LIFECYCLE_PASS',reexecuted_cases=32,new_outer_cli_cases=2,
        prior_registered_factory_cases_reexecuted=30,exact_bundled_launcher_and_outer_loop_executed=True,
        native_startup_lease_claim_used=True,fresh_synthetic_seed_created_after_native_resume=True,
        durable_closed_seed_handoff_recorded_before_bootstrap=True,durable_seed_handoff_replay_verified=True,
        signed_disabled_bootstrap_used_before_test_gate_override=True,synthetic_factory_two_cycles_completed=True,
        successful_cycle_intercepted_sends=4,new_process_stale_authority_pauses_without_send=True,
        cached_root_change_pauses_before_second_send=True,native_finish_leaves_controller_paused=True,
        test_clock_and_poll_cadence_substituted=True,test_registration_file_location_substituted=True,
        original_registration_parser_and_hash_checks_used=True,positive_factory_gate_overridden_in_child_only=True,
        synthetic_evidence_and_intercepted_transport_only=True,real_network_denied=True,
        actual_production_registration_activation_qualified=False,production_transport_validated=False,
        automatic_live_lease_migration_implemented=False,actual_vm_reboot_tested=False,
        candidate_release_unchanged=True,candidate=str(candidate),candidate_release_sha256=digest,
        live_apply_available=False,installed_sources_modified=False,application_services_changed=False,
        live_database_mutations_issued=False,live_secret_material_created=False,broker_requests_issued=False,
        production_trust_provisioned=False,live_database_enrolled=False,controller_resumed=False,
        production_execution_enabled=False,production_ready=False,group2_complete=False,audit_folder=str(out))
    save(out/'RESULT.json',report)
    (out/'MILESTONES.md').write_text('# Hilega flow after synthetic outer CLI validation\n\n'
        '- [x] Integrated closed bootstrap/worker release deployed (prior VM apply/status).\n'
        '- [x] Registered-factory Bridge candidate and file/lease regression rechecked.\n'
        '- [x] This run: exact outer CLI from native startup through fresh synthetic preparation, durable signed evidence handoff, signed bootstrap and two intercepted cycles.\n'
        '- [x] New-process stale-authority rejection and cached root-change pause verified in synthetic CLI tests.\n'
        '- [ ] Reviewed production registration/activation binding design and real independent trust provisioning.\n'
        '- [ ] Broker timestamp contract, actual fees and ownership evidence.\n'
        '- [ ] Fresh real disabled enrollment and final operational qualification.\n'
        '- [ ] Controlled live activation.\n\n'
        'Synthetic qualification does not certify production activation or order transport. No automatic live lease migration is implemented.\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
