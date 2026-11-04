"""Pinned external registration and trust-binding candidate; no real provisioning or live activation."""
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


def stage(source,target,base_sha,here):
    old=verify(source,base_sha);target.mkdir(mode=0o700);files=dict(old['files'])
    for name in files:
        path=target/name;path.parent.mkdir(mode=0o700,parents=True,exist_ok=True);path.write_bytes(regular(source/name))
    added='runtime/factory_attachment.py';need(added not in files,'ATTACHMENT_ALREADY_PRESENT')
    (target/added).write_bytes(regular(here/'factory_attachment.py'));files[added]=sha((target/added).read_bytes())
    name='runtime/worker_binding.py';text=(target/name).read_text()
    anchor='def default_worker_poll(source,journal):\n    from bootstrap_worker import configured_poll'
    need(text.count(anchor)==1,'EXACT_CLOSED_DISPATCH_ANCHOR_REQUIRED')
    text=text.replace(anchor,'def default_worker_poll(source,journal):\n    from factory_attachment import attachment_poll\n    attached=attachment_poll(source,journal)\n    if attached is not None:return attached\n    from bootstrap_worker import configured_poll')
    compile(text,name,'exec');(target/name).write_text(text);files[name]=sha((target/name).read_bytes())
    dep='backend/market_lab/hilega_preparation_runtime_v1/dependencies.json';path=target/dep;deps=json.loads(path.read_text())
    need(deps[name]==old['files'][name],'ATTACHMENT_BASE_DEPENDENCY_CHANGED')
    for name in [name,added]:deps[name]=files[name]
    path.write_text(json.dumps(deps,indent=2)+'\n');files[dep]=sha(path.read_bytes())
    for name,h in deps.items():need(sha(regular(target/name))==h,'ATTACHMENT_DEPENDENCY_CHANGED')
    for name in ['backend/market_lab/hilega_execution_port_v1/adapter.py','runtime/FACTORY-REGISTRATION.json','runtime/POSITION-POLICY.json']:
        need(files[name]==old['files'][name],'ATTACHMENT_CHANGED_GATE_DEFAULT_OR_POLICY')
    save(target/'RELEASE-MANIFEST.json',dict(old,files=files,pinned_external_attachment_candidate=True))
    digest=sha(regular(target/'RELEASE-MANIFEST.json'));verify(target,digest)
    for path in target.rglob('*'):
        if path.is_file():path.chmod(0o400)
    for path in sorted((path for path in target.rglob('*') if path.is_dir()),key=lambda path:len(path.parts),reverse=True):path.chmod(0o500)
    target.chmod(0o500);return digest


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--repo',type=Path,required=True)
    ap.add_argument('--current-plan',type=Path,required=True);ap.add_argument('--current-plan-sha256',required=True)
    ap.add_argument('--cli-review',type=Path,required=True);a=ap.parse_args()
    root=a.repo.absolute();here=Path(__file__).absolute().parent;path=a.current_plan.absolute();review=a.cli_review.absolute()
    for name,h in json.loads(regular(here/'MANIFEST.json')).items():need(sha(regular(here/name))==h,'CLI_PACKAGE_CHANGED')
    for name,h in json.loads(regular(here/'BASELINE-PINS.json')).items():need(sha(regular(root/name))==h,'CLI_BASELINE_CHANGED: '+name)
    need(sha(regular(path))==a.current_plan_sha256,'CURRENT_CLI_PLAN_CHANGED');plan=json.loads(regular(path))
    need(plan['repo']==str(root) and plan['execution_factory_configured'] is False and plan['production_execution_enabled'] is False,'CLOSED_CURRENT_CLI_PLAN_REQUIRED')
    previous=json.loads(regular(review/'RESULT.json'));source=Path(previous['candidate'])
    need(previous['status']=='EXACT_OUTER_CLI_SYNTHETIC_FACTORY_LIFECYCLE_PASS' and previous['reexecuted_cases']==32
         and source.parent.parent==root and source.name=='candidate','PASSED_REGISTERED_FACTORY_REVIEW_REQUIRED')
    digest='48b68578e1d83bb654662e3d077383e05025adabd363efb7b271f65f4d71ec4a'
    need(previous['candidate_release_sha256']==digest,'EXPECTED_FACTORY_CANDIDATE_REQUIRED')
    manifest=verify(source,digest);live=verify(Path(plan['destination']),plan['release_sha256'])
    for name in ['backend/market_lab/hilega_execution_port_v1/adapter.py','runtime/FACTORY-REGISTRATION.json','runtime/POSITION-POLICY.json']:
        need(manifest['files'][name]==live['files'][name],'GATE_DEFAULT_REGISTRATION_OR_POLICY_CHANGED')
    out=Path(tempfile.mkdtemp(prefix='hilega-registration-bindings-review-',dir=root));out.chmod(0o700);(out/'.gitignore').write_text('*\n')
    save(out/'INPUTS.json',dict(current_plan=str(path),current_plan_sha256=a.current_plan_sha256,factory_review=str(review),
        factory_receipt_sha256=sha(regular(review/'RESULT.json')),candidate=str(source),candidate_release_sha256=digest))
    def status(label):
        r=subprocess.run([sys.executable,'-B',str(root/'hilega-bootstrap-deploy-v1/manage.py'),'--repo',str(root),'--action','status',
            '--plan',str(path),'--approve-plan-sha256',a.current_plan_sha256],capture_output=True,text=True,timeout=100)
        save(out/(label+'.json'),dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr))
        need(r.returncode==0 and json.loads(r.stdout)['phase']=='CLOSED_GROUP2_CANDIDATE_RUNNING','CURRENT_CLI_STATUS_FAILED; inspect '+str(out/(label+'.json')))
    status('STATUS-BEFORE')
    candidate=out/'candidate';digest=stage(source,candidate,digest,here)
    combined=root/'hilega-group2-combined-v2';trust=root/'hilega-trust-worker-batch-v2';authority=root/'hilega-authority-factory-candidate-v1';qualification=root/'hilega-worker-qualification-v1';factory=root/'hilega-factory-process-v1'
    paths=[candidate/'backend',candidate/'runtime',here/'tests',factory/'tests',trust/'tests',authority/'tests',combined/'tests',combined/'fixtures']
    envargs=['PATH='+os.defpath,'LANG=C.UTF-8','HOME='+str(out),'PYTHONDONTWRITEBYTECODE=1','PYTEST_DISABLE_PLUGIN_AUTOLOAD=1',
        'HILEGA_PACKAGE_B_BUNDLE='+str(candidate),'PYTHONPATH='+os.pathsep.join(map(str,paths))]
    junit=out/'TESTS.xml';unit='hilega-disposable-registration-bindings-'+uuid.uuid4().hex+'.service'
    cmd=['systemd-run','--user','--wait','--collect','--unit='+unit,'--property=Type=oneshot','--property=NoNewPrivileges=yes',
        '--property=RestrictAddressFamilies=AF_UNIX','--property=RuntimeMaxSec=300','--property=UMask=0077','--working-directory='+str(out),
        '/usr/bin/env','-i',*envargs,sys.executable,'-B','-m','pytest','-q','-p','no:cacheprovider','--rootdir='+str(here),'--confcutdir='+str(here),
        str(here/'tests'),str(factory/'tests'),str(trust/'tests/test_worker_files.py'),str(qualification/'tests/test_qualification.py'),str(combined/'seed_preflight.py'),
        '--basetemp='+str(out/'synthetic'),'--junitxml='+str(junit)]
    print('Managed registration/trust-binding batch: real attachment dispatch, full synthetic CLI, expiry and no-downgrade checks',flush=True)
    r=subprocess.run(cmd,capture_output=True,text=True,timeout=315)
    save(out/'MANAGED-PROCESS.json',dict(unit=unit,exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr));status('STATUS-AFTER')
    cases=list(ET.parse(junit).getroot().iter('testcase')) if junit.is_file() else []
    need(r.returncode==0 and len(cases)==38 and all(all(c.find(t) is None for t in ['failure','error','skipped']) for c in cases),'REGISTRATION_BINDING_TESTS_FAILED; inspect '+str(out/'MANAGED-PROCESS.json')+' and '+str(junit))
    verify(candidate,digest);verify(Path(plan['destination']),plan['release_sha256'])
    request=dict(model='HILEGA_TRUST_AND_ATTACHMENT_REVIEW_REQUEST_V1',candidate_release_sha256=digest,
        position_policy_sha256=sha(regular(candidate/'runtime/POSITION-POLICY.json')),
        max_simultaneous_positions=1,max_premium_per_entry_cents=None,daily_loss_cutoff_cents=None,
        application_db=plan['application_db'],adapter_db=plan['adapter_db'],current_plan=str(path),current_plan_sha256=a.current_plan_sha256,
        attachment_pointer_names=['HILEGA_FACTORY_ATTACHMENT_FILE','HILEGA_FACTORY_ATTACHMENT_SHA256'],
        attachment_file_requires_exact_release_policy_paths_lease_and_expiry=True,
        trust_registry_requires_independent_issuer_and_pinned_private_key=True,
        account_scope=None,issuer_id=None,issuer_key_sha256=None,private_context_sha256=None,owner_row_sha256=None,
        seed_request_id=None,bridge_run_id=None,attachment_sha256=None,
        unresolved_live_requirements=['EXACT_SUPERVISOR_WRAPPER_AND_RECOVERY_ACTIVATION_PLAN','INDEPENDENT_REAL_ISSUER_AND_PRIVATE_FILE_BINDINGS',
            'BROKER_TIMESTAMP_CONTRACT','FINAL_FEES_AND_STRATEGY_OWNERSHIP','ONE_FRESH_REAL_DISABLED_SEED_AND_DURABLE_HANDOFF',
            'REVIEWED_LIVE_ENROLLMENT_AND_FINAL_READINESS'],
        live_approval_granted=False,live_apply_available=False,production_execution_enabled=False)
    save(out/'TRUST-BINDINGS-REQUEST.json',request)
    report=dict(status='PINNED_EXTERNAL_REGISTRATION_AND_TRUST_BINDINGS_CANDIDATE_PASS',reexecuted_cases=38,
        new_attachment_contract_cases=6,outer_cli_cases=2,prior_registered_factory_cases=30,
        cli_registration_reader_substitution_removed=True,actual_external_attachment_dispatch_tested=True,
        real_gate_precedes_private_attachment_reads=True,release_policy_and_source_lease_bindings_tested=True,
        descriptor_expiry_pointer_changes_and_removal_pause=True,full_synthetic_cli_two_cycles_verified=True,
        new_process_stale_attachment_pauses_without_send=True,cached_root_change_pauses_before_second_send=True,
        positive_factory_gate_overridden_in_child_only=True,test_clock_evidence_and_intercepted_transport=True,real_network_denied=True,
        factory_registration_default_bytes_unchanged=True,installed_gate_source_unchanged=True,
        trust_binding_request=str(out/'TRUST-BINDINGS-REQUEST.json'),trust_binding_request_sha256=sha(regular(out/'TRUST-BINDINGS-REQUEST.json')),
        real_trust_root_created=False,production_trust_provisioned=False,production_registration_activated=False,
        broker_timestamp_contract_confirmed=False,actual_fees_reconciled=False,strategy_ownership_verified=False,
        live_database_enrolled=False,live_apply_available=False,installed_sources_modified=False,application_services_changed=False,
        live_database_mutations_issued=False,live_secret_material_created=False,broker_requests_issued=False,
        controller_resumed=False,production_execution_enabled=False,production_ready=False,group2_complete=False,
        candidate=str(candidate),candidate_release_sha256=digest,audit_folder=str(out))
    save(out/'RESULT.json',report)
    (out/'MILESTONES.md').write_text('# Hilega registration and trust-binding flow\n\n'
        '- [x] Integrated closed bootstrap/worker release deployed (prior VM status).\n'
        '- [x] Prior registered-factory and outer CLI synthetic lifecycle qualified.\n'
        '- [x] This run: real external attachment-file dispatch and 38-case candidate qualification.\n'
        '- [x] Exact release/policy-bound trust review request created; unresolved live fields remain null.\n'
        '- [ ] Reviewed closed deployment and exact supervisor/wrapper/recovery activation bindings.\n'
        '- [ ] Real independent issuer/private files provisioned and approved.\n'
        '- [ ] Broker timestamps, actual fees and account ownership resolved.\n'
        '- [ ] Fresh real disabled seed, durable handoff, signed enrollment and final readiness.\n'
        '- [ ] Controlled execution activation.\n\nNo real trust, registration activation or live enrollment was performed.\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
