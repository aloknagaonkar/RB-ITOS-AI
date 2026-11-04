"""Prepare a four-file warmup prevention compatibility proposal; never applies live changes."""
import argparse,ast,json,os,subprocess,sys,tempfile
from pathlib import Path
from bindings import need,sha,chain
sys.dont_write_bytecode=True
SOURCE='backend/market_lab/hilega_milega_historical_replay_v1.py'
PACKAGE='hilega-operational-lifecycle-tools-6cexrur_'
SERVICE='hilega-reference-service-stage-yup3_wr1/lifecycle_reference_service.py'
def regular(p):
    need(p.is_absolute() and p.is_file() and not any(q.is_symlink() for q in (p,*p.parents)),'REGULAR_SOURCE_REQUIRED');return p.read_bytes()
def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--repo',type=Path,required=True);ap.add_argument('--active-plan',type=Path,required=True);ap.add_argument('--active-plan-sha256',required=True);a=ap.parse_args()
    root=a.repo.absolute();here=Path(__file__).absolute().parent;path=a.active_plan.absolute()
    for n,h in json.loads(regular(here/'MANIFEST.json')).items():need(sha(regular(here/n))==h,'PREVENTION_PLAN_PACKAGE_CHANGED')
    for n,h in json.loads(regular(here/'BASELINE-PINS.json')).items():need(sha(regular(root/n))==h,'PREVENTION_BASELINE_CHANGED')
    need(sha(regular(path))==a.active_plan_sha256,'ACTIVE_PLAN_CHANGED');active=json.loads(regular(path));need(active['repo']==str(root) and active['production_execution_enabled'] is False,'CLOSED_PLAN_REQUIRED')
    out=Path(tempfile.mkdtemp(prefix='hilega-warmup-prevention-plan-',dir=root));out.chmod(0o700)
    def save(name,value):
        p=out/name;p.parent.mkdir(parents=True,exist_ok=True)
        fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        data=value if isinstance(value,bytes) else (json.dumps(value,indent=2)+'\n').encode()
        with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
    def run(label,command,timeout=110):
        r=subprocess.run(command,capture_output=True,text=True,timeout=timeout);save(label+'.json',dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr));need(r.returncode==0,'CHECK_FAILED_'+label);return r
    def status(label):
        r=run(label,[sys.executable,'-B',str(root/'hilega-registration-rollout-v1/manage.py'),'--repo',str(root),'--action','status','--plan',str(path),'--approve-plan-sha256',a.active_plan_sha256]);need(json.loads(r.stdout)['phase']=='CLOSED_GROUP2_CANDIDATE_RUNNING','CLOSED_RUNTIME_REQUIRED')
    status('BEFORE')
    test=run('BINDING_TESTS',[sys.executable,'-B','-m','pytest','-q','-p','no:cacheprovider',str(here/'test_bindings.py')],timeout=60);print(test.stdout,flush=True)
    pins=json.loads(regular(here/'WRITER-PINS.json'));old=regular(root/SOURCE);candidate=regular(here/'writer-candidate.py.txt')
    need(sha(old)==pins['original'] and sha(candidate)==pins['candidate'],'EXACT_OLD_AND_REVIEWED_WRITER_REQUIRED')
    # Only the cache writer function may differ from the deployed original.
    trees=[ast.parse(old),ast.parse(candidate)]
    for t in trees:
        nodes=[n for n in t.body if isinstance(n,ast.FunctionDef) and n.name=='_write_cache'];need(len(nodes)==1,'EXACT_WRITER_FUNCTION_REQUIRED');t.body.remove(nodes[0])
    need(ast.dump(trees[0])==ast.dump(trees[1]),'UNRELATED_APPLICATION_CODE_CHANGED')
    compile(candidate,SOURCE,'exec')
    manifest_raw=regular(root/PACKAGE/'manifest.json');cli_raw=regular(root/PACKAGE/'cli.py');service_raw=regular(root/SERVICE)
    proposed=chain(manifest_raw,cli_raw,service_raw,SOURCE,pins['original'],pins['candidate'])
    manifest=json.loads(manifest_raw);observed={};overlay=out/'candidate-repo';overlay.mkdir(mode=0o700)
    def capture(relative,base):
        rel=Path(relative);need(not rel.is_absolute() and '..' not in rel.parts,'SAFE_MANIFEST_PATH_REQUIRED');original=regular(base/rel);return original
    for n,h in manifest['runtime'].items():
        data=capture(n,root);need(sha(data)==h,'UNRELATED_RUNTIME_SOURCE_CHANGED');observed[str(root/n)]=h
        save('candidate-repo/'+n,candidate if n==SOURCE else data)
    for n,h in manifest['modules'].items():
        need(Path(n).name==n and n.endswith('.py'),'SAFE_PACKAGE_MODULE_REQUIRED');data=capture(n,root/PACKAGE);need(sha(data)==h,'PACKAGE_MODULE_CHANGED');observed[str(root/PACKAGE/n)]=h
        save('candidate-repo/'+PACKAGE+'/'+n,data)
    changes={SOURCE:(old,candidate),PACKAGE+'/manifest.json':(manifest_raw,proposed[0]),PACKAGE+'/cli.py':(cli_raw,proposed[1]),SERVICE:(service_raw,proposed[2])}
    for n,(before,after) in changes.items():
        dest=out/'candidate-repo'/n
        # Manifest modules are not expected to include their own CLI.
        need(not dest.exists() or n==SOURCE,'UNEXPECTED_CANDIDATE_PATH_COLLISION')
        if n==SOURCE:need(regular(dest)==after,'CANDIDATE_WRITER_CHANGED')
        else:save('candidate-repo/'+n,after)
        save('originals/'+n,before);observed[str(root/n)]=sha(before)
    # Execute only the candidate CLI's hash check, with a disposable source overlay.
    r=run('CANDIDATE_PACKAGE_CHECK',[sys.executable,'-B',str(overlay/PACKAGE/'cli.py'),'check','--repo',str(overlay)],timeout=35)
    need(json.loads(r.stdout)['status']=='PACKAGE_AND_RUNTIME_CHECK_PASS','CANDIDATE_CHAIN_CHECK_REQUIRED')
    expected_bindings=dict(active['observed_bindings'])
    for e in [*active['files'],*active['new_recovery_files']]:expected_bindings[e['destination']]=e['new_sha256']
    impact=[]
    for n,(before,after) in changes.items():
        full=str(root/n);bound=full in expected_bindings
        if bound:need(expected_bindings[full]==sha(before),'CURRENT_PLAN_BINDING_DISAGREES')
        impact.append(dict(path=full,original_sha256=sha(before),candidate_sha256=sha(after),current_plan_direct_binding=bound,candidate=str(overlay/n),original_backup=str(out/'originals'/n)))
    for filename,digest in observed.items():need(sha(regular(Path(filename)))==digest,'SOURCE_CHANGED_DURING_REVIEW')
    status('AFTER')
    proposal=dict(model='HILEGA_WARMUP_PREVENTION_COMPATIBILITY_PROPOSAL_V1',active_plan=str(path),active_plan_sha256=a.active_plan_sha256,files=impact,observed_source_hashes=observed,required_work=['SUCCESSOR_ROLLOUT_BINDING_AND_ROLLBACK_PLAN','QUIESCENT_COMPATIBILITY_CHAIN_INSTALL','RELOAD_IDENTIFIED_WARMUP_CONSUMERS','VERIFY_COMPANION_HEALTH_AND_WARMUP_AFTER_RELOAD'],candidate_cli_check_passed=True,writer_changes_limited_to_cache_writer=True,services_to_review=['hilega-production-source-worker.service','hilega-worker.service','hilega-api.service','hilega-lifecycle-reference.service','hilega-observation-analytics.service','hilega-observation-readiness.service'],independent_cache_or_source_changes_allowed=False,apply_available=False,production_execution_enabled=False)
    save('DEPLOYMENT-PROPOSAL.json',proposal)
    report=dict(status='COORDINATED_WARMUP_PREVENTION_PROPOSAL_PASS',binding_tests=6,candidate_writer_and_three_dependency_bindings_prepared=True,candidate_package_runtime_check_passed=True,prior_18_repair_writer_tests_reexecuted=False,current_runtime_checked_before_and_after=True,current_plan_binding_impact=impact,proposal=str(out/'DEPLOYMENT-PROPOSAL.json'),proposal_sha256=sha(regular(out/'DEPLOYMENT-PROPOSAL.json')),apply_available=False,prevention_deployed=False,application_sources_modified=False,services_changed=False,controller_resumed=False,broker_requests_issued=False,production_execution_enabled=False,production_ready=False,audit_folder=str(out))
    save('RESULT.json',report);print(json.dumps(report,indent=2))
if __name__=='__main__':
    try:main()
    except Exception as exc:
        import re,traceback
        text=str(exc).split(':',1)[0];print(json.dumps(dict(status='PREVENTION_PLAN_BLOCKED',reason=text if re.fullmatch('[A-Z][A-Z0-9_]*',text) else 'PREVENTION_PLAN_REQUIRES_REVIEW',error_type=type(exc).__name__,location=[dict(file=Path(f.filename).name,line=f.lineno) for f in traceback.extract_tb(exc.__traceback__)[-3:]],live_apply_available=False)));raise SystemExit(2)
