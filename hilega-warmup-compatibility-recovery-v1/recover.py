"""Restore the reviewed writer binding, retain repaired candles, recover closed companion."""
import argparse,fcntl,hashlib,importlib.util,json,os,stat,subprocess,sys,tempfile
from pathlib import Path
sys.dont_write_bytecode=True
OLD='c5d640d66285f5e6b908b036b20bf57a909437b247d38757918dc8728c687319'
NEW='2bd6ae98e40a7b76b6e492f641feef5fc933ab27cefe48e369d2c9b38afc7b8f'
CACHE='39c08d06ff71e08d0119ae9944a6ce1879ff36aafe91fe708e6c048d5758c733'
APPROVED='4dc497c053d41c136559b3c4ef9918598ddc6bb1b3f5447fe89032a79456c7f5'
UNIT='hilega-lifecycle-reference.service'
def need(ok,reason):
    if not ok:raise ValueError(reason)
def read(p):
    need(p.is_absolute() and p.is_file() and not any(x.is_symlink() for x in (p,*p.parents)),'REGULAR_INPUT_REQUIRED')
    return p.read_bytes()
def sha(b):return hashlib.sha256(b).hexdigest()
def module(p,name):
    spec=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--repo',type=Path,required=True);ap.add_argument('--apply',action='store_true');a=ap.parse_args()
    root=a.repo.absolute();here=Path(__file__).absolute().parent
    for n,h in json.loads(read(here/'MANIFEST.json')).items():need(sha(read(here/n))==h,'RECOVERY_PACKAGE_CHANGED')
    for n,h in json.loads(read(here/'BASELINE-PINS.json')).items():need(sha(read(root/n))==h,'RECOVERY_BASELINE_CHANGED')
    planpath=root/'hilega-group2-upgrade-plan-qfgbdwft/PLAN.json';need(sha(read(planpath))==APPROVED,'ACTIVE_PLAN_CHANGED');plan=json.loads(read(planpath))
    need(plan['repo']==str(root) and plan['production_execution_enabled'] is False,'CLOSED_PLAN_REQUIRED')
    package=root/'hilega-operational-lifecycle-tools-6cexrur_';cli=package/'cli.py'
    target=root/'backend/market_lab/hilega_milega_historical_replay_v1.py'
    original=root/'hilega-warmup-repair-atpjt7r6/original-cache-writer.py'
    original_raw=read(original);need(sha(original_raw)==OLD,'ORIGINAL_WRITER_BACKUP_CHANGED')
    need(sha(read(target)) in {OLD,NEW},'WRITER_NOT_EXACT_REVIEWED_VERSION')
    cache=root/'data/historical-evidence/hilega-milega-underlying-cache-v1/2026-10-30.json'
    need(sha(read(cache))==CACHE,'REPAIRED_CACHE_CHANGED_REQUIRES_REVIEW')
    folder=root/'hilega-group1-rollout-v1';sys.path.insert(0,str(folder))
    import maintenance_primitives as m
    issuer=root/'hilega-issuer-provision-v1';sys.path.insert(0,str(issuer))
    module(issuer/'manage.py','compatibility_release_reader').verify_release(plan)
    manager=m.Systemd();before=manager.state(UNIT)
    need(before['active'] in {'failed','inactive'} and before['pid']==0,'COMPANION_MUST_BE_STOPPED')
    m.require_empty_closed_baseline(Path(plan['application_db']),Path(plan['adapter_db']))
    manifest=json.loads(read(package/'manifest.json'))
    need(manifest['runtime'].get(str(target.relative_to(root)))==OLD,'EXPECTED_WRITER_BINDING_REQUIRED')
    if not a.apply:
        print(json.dumps(dict(status='COMPATIBILITY_RECOVERY_CHECK_PASS',restore_original_writer=True,repaired_cache_retained=True,prevention_deployment_pending=True,companion_start_planned=True,production_execution_enabled=False),indent=2));return
    lock=root/'.hilega-closed-rollout.lock'
    need(not lock.is_symlink(),'REGULAR_MAINTENANCE_LOCK_REQUIRED')
    fd=os.open(lock,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'r+') as locked:
        fcntl.flock(locked,fcntl.LOCK_EX|fcntl.LOCK_NB)
        m.require_empty_closed_baseline(Path(plan['application_db']),Path(plan['adapter_db']))
        need(manager.state(UNIT)['pid']==0,'COMPANION_CHANGED')
        out=Path(tempfile.mkdtemp(prefix='hilega-warmup-compatibility-recovery-',dir=root));out.chmod(0o700)
        def save(name,data):
            f=os.open(out/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            with os.fdopen(f,'wb') as s:s.write(data);s.flush();os.fsync(s.fileno())
        before_raw=read(target);need(sha(before_raw) in {OLD,NEW},'WRITER_CHANGED')
        save('writer-before-recovery.py',before_raw)
        if sha(before_raw)==NEW:
            need(sha(read(cache))==CACHE,'CACHE_CHANGED')
            # Restore exact approved bytes; immutable release, manifests and plans are untouched.
            m.atomic(target,original_raw,stat.S_IMODE(target.stat().st_mode))
        need(sha(read(target))==OLD,'RESTORED_WRITER_VERIFICATION_FAILED')
        def check(label,command,timeout=45):
            r=subprocess.run(command,capture_output=True,text=True,timeout=timeout)
            save(label+'.json',(json.dumps(dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr),indent=2)+'\n').encode())
            need(r.returncode==0,'RECOVERY_CHECK_FAILED_'+label)
            return r
        check('PACKAGE', [sys.executable,'-B',str(cli),'check','--repo',str(root)])
        m.require_empty_closed_baseline(Path(plan['application_db']),Path(plan['adapter_db']))
        need(sha(read(cache))==CACHE,'REPAIRED_CACHE_CHANGED')
        manager.control('start',UNIT)
        r=check('CLOSED-STATUS',[sys.executable,'-B',str(root/'hilega-registration-rollout-v1/manage.py'),'--repo',str(root),'--action','status','--plan',str(planpath),'--approve-plan-sha256',APPROVED],timeout=110)
        need(json.loads(r.stdout)['phase']=='CLOSED_GROUP2_CANDIDATE_RUNNING','CLOSED_STATUS_NOT_VERIFIED')
        need(sha(read(cache))==CACHE,'CACHE_CHANGED_DURING_RECOVERY')
        report=dict(status='ORIGINAL_WRITER_COMPATIBILITY_AND_CLOSED_RUNTIME_RESTORED',repaired_cache_retained=True,original_writer_restored=True,prevention_patch_rolled_back=True,prevention_deployment_pending=True,companion_started=True,controller_resumed=False,production_execution_enabled=False,production_ready=False,orders_sent_by_recovery=False,audit_folder=str(out))
        save('RESULT.json',(json.dumps(report,indent=2)+'\n').encode());print(json.dumps(report,indent=2))
if __name__=='__main__':
    try:main()
    except Exception as exc:
        import re
        reason=str(exc);safe=reason if re.fullmatch('[A-Z][A-Z0-9_]*',reason) else 'RECOVERY_STOPPED_REVIEW_AUDIT'
        print(json.dumps(dict(status='RECOVERY_BLOCKED',reason=safe,error_type=type(exc).__name__,automatic_retry=False)));raise SystemExit(2)
