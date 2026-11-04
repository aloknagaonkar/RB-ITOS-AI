"""Exact plan for private issuer material and disabled registry; no grants or activation."""
import argparse,fcntl,hmac,json,os,re,sqlite3,stat,subprocess,sys,tempfile
from datetime import datetime,timedelta,timezone
from pathlib import Path
import xml.etree.ElementTree as ET
from storage import need,sha,encode,create,private,provision,status as issuer_status


def regular(p):
    p=Path(p);need(p.is_absolute() and p.is_file() and not any(q.is_symlink() for q in (p,*p.parents)),'REGULAR_PROVISION_INPUT_REQUIRED')
    return p.read_bytes()
def save(p,v):create(p,encode(v),0o600)
def load(p):return json.loads(regular(p))
def owned(p):
    p=Path(p);regular(p);s=p.stat()
    need(s.st_uid==os.getuid() and s.st_nlink==1 and stat.S_IMODE(s.st_mode)&0o077==0,'OWNED_PRIVATE_CONFIGURATION_REQUIRED')
    return p.read_bytes()


def verify_release(plan):
    bundle=Path(plan['destination']);raw=regular(bundle/'RELEASE-MANIFEST.json');need(sha(raw)==plan['release_sha256'],'ISSUER_RELEASE_CHANGED')
    manifest=json.loads(raw)
    for name,digest in manifest['files'].items():
        rel=Path(name);need(not rel.is_absolute() and '..' not in rel.parts,'SAFE_ISSUER_RELEASE_PATH_REQUIRED')
        need(sha(regular(bundle/rel))==digest,'BOUND_ISSUER_RELEASE_FILE_CHANGED')
    need(plan['execution_factory_configured'] is False and plan['production_execution_enabled'] is False,'CLOSED_ISSUER_RELEASE_REQUIRED')
    return bundle


def identity(root,active):
    bundle=verify_release(active)
    r=subprocess.run(['systemctl','--user','show','hilega-production-source-worker.service','--property=MainPID','--value'],capture_output=True,text=True,timeout=10)
    need(r.returncode==0 and r.stdout.strip().isdigit(),'ISSUER_SOURCE_PID_UNAVAILABLE');pid=int(r.stdout.strip());need(pid>0,'RUNNING_ISSUER_SOURCE_REQUIRED')
    proc=Path('/proc')/str(pid);need(proc.stat().st_uid==os.getuid() and (proc/'cwd').resolve()==root,'EXACT_ISSUER_SOURCE_PROCESS_REQUIRED')
    env={k.decode():v.decode() for item in (proc/'environ').read_bytes().split(b'\0') if b'=' in item for k,v in [item.split(b'=',1)]}
    need(env.get('HILEGA_PRODUCTION_EXECUTION_ROUTE')=='PREPARATION_ONLY','CLOSED_ISSUER_SOURCE_ROUTE_REQUIRED')
    home=Path(env.get('HOME',str(Path.home())));selected=Path(env.get('HILEGA_PREPARATION_ENV_FILE','.env'));envfile=selected if selected.is_absolute() else root/selected
    pinfile=Path(env.get('HILEGA_PREPARATION_PIN_FILE',str(home/'hilega-private/upstox-account-pin.json')))
    env_raw=owned(envfile);pin_raw=owned(pinfile)
    from dotenv import dotenv_values
    settings=dotenv_values(envfile)
    def setting(name):
        a,b=env.get(name),settings.get(name);need(not(a and b and a!=b),'ISSUER_READ_CONTEXT_CONFLICT');return a or b
    token=(setting('HILEGA_PRODUCTION_BROKER_READ_TOKEN') or setting('UPSTOX_ACCESS_TOKEN') or '').strip();need(bool(token),'ISSUER_READ_CONTEXT_TOKEN_MISSING')
    sys.dont_write_bytecode=True;sys.path[:0]=[str(bundle/'backend'),str(bundle/'runtime')]
    from market_lab import hilega_production_account_adapter_v1 as api
    from market_lab.hilega_execution_port_v1 import adapter as port
    try:port.require_live_clearance()
    except port.GateClosed:pass
    else:raise ValueError('ISSUER_PROVISION_REQUIRES_REAL_GATE_CLOSED')
    pin=api.read_pin(pinfile)
    return dict(pid=pid,pin=pin,forbidden=(bytes.fromhex(pin['key']),token.encode()),api=api,
        bindings={str(envfile):sha(env_raw),str(pinfile):sha(pin_raw)})


def baseline(active):
    for key,tables in [('application_db',['preparation_plans','preparation_shadow_holds','preparation_outbox','preparation_request_bindings','preparation_cash_reservations','preparation_candidate_exclusive_source_owner_v1','intents']),('adapter_db',['requests','attempts','receipts'])]:
        path=Path(active[key]);regular(path)
        with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
            db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
            if key=='application_db':
                need(json.loads(db.execute('SELECT data FROM control WHERE id=1').fetchone()[0])['mode']=='PAUSED','ISSUER_CONTROLLER_MUST_REMAIN_PAUSED')
                row=db.execute('SELECT generation,handled FROM sim_stop_state WHERE id=1').fetchone();need(row and row[0]==row[1],'ISSUER_STOP_PENDING')
            for name in tables:
                if db.execute('SELECT 1 FROM sqlite_master WHERE type=\'table\' AND name=?',(name,)).fetchone():
                    need(db.execute('SELECT COUNT(*) FROM '+name).fetchone()[0]==0,'ISSUER_REQUIRES_EMPTY_DISABLED_BASELINE')


def closed_status(root,path,digest,folder,label):
    r=subprocess.run([sys.executable,'-B',str(root/'hilega-registration-rollout-v1/manage.py'),'--repo',str(root),'--action','status','--plan',str(path),'--approve-plan-sha256',digest],capture_output=True,text=True,timeout=100)
    save(folder/(label+'.json'),dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr))
    need(r.returncode==0 and json.loads(r.stdout)['phase']=='CLOSED_GROUP2_CANDIDATE_RUNNING','CURRENT_ISSUER_RUNTIME_STATUS_FAILED')


def tracker(folder,material):
    mark='x' if material else ' '
    text='# Issuer provisioning milestone\n\n'
    text+='- [x] Exact account/release/configuration-bound plan and ten synthetic storage checks completed.\n'
    text+='- ['+mark+'] One real private issuer key and disabled registry prepared and verified.\n'
    text+='- [ ] Registry enablement and exact registration/supervisor/recovery activation approval.\n'
    text+='- [ ] Broker timestamp semantics, final fees and strategy ownership resolved.\n'
    text+='- [ ] Fresh real disabled seed, durable handoff and signed enrollment.\n'
    text+='- [ ] Final operational qualification and controlled execution activation.\n\nRegistry remains disabled; no grant, live enrollment or controller resume is performed.\n'
    path=folder/'MILESTONES.md';need(not path.is_symlink(),'ISSUER_CHECKLIST_SYMLINK_FORBIDDEN')
    temporary=folder/'MILESTONES.new';create(temporary,text.encode(),0o600);os.replace(temporary,path)


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--repo',type=Path,required=True)
    ap.add_argument('--action',choices=['check','apply','recover','status'],default='check')
    ap.add_argument('--active-plan',type=Path);ap.add_argument('--active-plan-sha256')
    ap.add_argument('--evidence-review',type=Path);ap.add_argument('--requirements-sha256')
    ap.add_argument('--plan',type=Path);ap.add_argument('--approve-plan-sha256');a=ap.parse_args()
    root=a.repo.absolute();here=Path(__file__).absolute().parent
    for name,digest in load(here/'MANIFEST.json').items():need(sha(regular(here/name))==digest,'ISSUER_TOOL_CHANGED')
    for name,digest in load(here/'BASELINE-PINS.json').items():need(sha(regular(root/name))==digest,'ISSUER_PINNED_TOOL_CHANGED')
    if a.action=='check':
        need(a.active_plan and a.active_plan_sha256 and a.evidence_review and a.requirements_sha256,'EXACT_ISSUER_PREPARATION_INPUTS_REQUIRED')
        active_path=a.active_plan.absolute();need(sha(regular(active_path))==a.active_plan_sha256,'ACTIVE_ISSUER_PLAN_CHANGED');active=load(active_path)
        need(active['repo']==str(root),'EXACT_ISSUER_REPO_REQUIRED')
        review=a.evidence_review.absolute();requirements=review/'ISSUER-PROVISIONING-REQUIREMENTS.json'
        need(sha(regular(requirements))==a.requirements_sha256,'ISSUER_REQUIREMENTS_CHANGED');req=load(requirements);prior=load(review/'RESULT.json')
        need(prior['historical_capture_completed'] is True and prior['finance_review']['historical_trade_capture_complete'] is True
             and req['active_plan']==str(active_path) and req['active_plan_sha256']==a.active_plan_sha256 and req['release_sha256']==active['release_sha256'],'VERIFIED_SCOPE_REQUIREMENTS_REQUIRED')
        folder=Path(tempfile.mkdtemp(prefix='hilega-issuer-provision-plan-',dir=root));folder.chmod(0o700);(folder/'.gitignore').write_text('*\n')
        closed_status(root,active_path,a.active_plan_sha256,folder,'STATUS-BEFORE');idn=identity(root,active);baseline(active)
        proof_path=review/'PRIVATE-POSTTRADE-EVIDENCE.json';proof=json.loads(owned(proof_path));sig=proof.pop('signature',None)
        need(isinstance(sig,str) and hmac.compare_digest(sig,idn['api'].sign(proof,idn['pin'])) and proof['account_scope']==idn['pin']['scope']==req['account_scope'],'ISSUER_ACCOUNT_EVIDENCE_SIGNATURE_CHANGED')
        at=datetime.fromisoformat(proof['completed_at']);need(at.tzinfo is not None and 0<=(datetime.now(timezone.utc)-at).total_seconds()<=86400,'RECENT_SIGNED_ACCOUNT_EVIDENCE_REQUIRED')
        parent=Path.home()/'hilega-private/production-issuers'/idn['pin']['scope'].split(':',1)[1]
        need(str(parent)==req['proposed_private_parent'] and not parent.exists() and not any(p.is_symlink() for p in (parent,*parent.parents)),'NEW_EXACT_PRIVATE_ISSUER_DESTINATION_REQUIRED')
        junit=folder/'TESTS.xml';env=dict(PATH=os.defpath,LANG='C.UTF-8',HOME=str(folder),PYTHONDONTWRITEBYTECODE='1',PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
        r=subprocess.run([sys.executable,'-B','-m','pytest','-q','-p','no:cacheprovider','--rootdir='+str(here),'--confcutdir='+str(here),str(here/'test_storage.py'),'--basetemp='+str(folder/'synthetic'),'--junitxml='+str(junit)],cwd=here,env=env,capture_output=True,text=True,timeout=60)
        save(folder/'TEST-PROCESS.json',dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr));cases=list(ET.parse(junit).getroot().iter('testcase')) if junit.is_file() else []
        need(r.returncode==0 and len(cases)==10 and all(all(c.find(t) is None for t in ['failure','error','skipped']) for c in cases),'ISSUER_STORAGE_TESTS_FAILED; inspect '+str(folder/'TEST-PROCESS.json'))
        now=datetime.now(timezone.utc)
        plan=dict(model='HILEGA_REAL_ISSUER_MATERIAL_PLAN_V1',repo=str(root),uid=os.getuid(),home=str(Path.home()),
            tool_manifest_sha256=sha(regular(here/'MANIFEST.json')),created_at=now.isoformat(),apply_before=(now+timedelta(minutes=30)).isoformat(),
            active_plan=str(active_path),active_plan_sha256=a.active_plan_sha256,release_sha256=active['release_sha256'],position_policy=active['position_policy'],
            account_scope=idn['pin']['scope'],issuer_id=req['proposed_issuer_id'],private_parent=str(parent),key_file=str(parent/'issuer.key'),
            registry_file=str(parent/(active['release_sha256']+'.registry.json')),registry_enabled=False,production_execution_enabled=False,
            source_pid=idn['pid'],source_configuration_bindings=idn['bindings'],evidence_file=str(proof_path),evidence_sha256=sha(regular(proof_path)),
            requirements=str(requirements),requirements_sha256=a.requirements_sha256,real_key_bytes=32,registration_activation_available=False,
            live_enrollment_available=False,controller_resume_available=False)
        closed_status(root,active_path,a.active_plan_sha256,folder,'STATUS-AFTER');baseline(active)
        save(folder/'PLAN.json',plan);digest=sha(regular(folder/'PLAN.json'))
        save(folder/'CHECK-VALIDATION.json',dict(status='REAL_ISSUER_DISABLED_REGISTRY_PLAN_PASS',plan_sha256=digest,storage_cases_passed=10))
        report=dict(status='REAL_ISSUER_DISABLED_REGISTRY_PLAN_PASS',storage_cases_passed=10,plan=str(folder/'PLAN.json'),plan_sha256=digest,
            apply_before=plan['apply_before'],key_file=plan['key_file'],registry_file=plan['registry_file'],apply_creates_one_real_key=True,
            real_key_created=False,registry_enabled=False,production_registration_activated=False,live_database_enrolled=False,
            controller_resumed=False,production_execution_enabled=False,production_ready=False,group2_complete=False)
        save(folder/'RESULT.json',report);tracker(folder,False);print(json.dumps(report,indent=2));return
    need(a.plan and a.approve_plan_sha256,'EXACT_ISSUER_PLAN_APPROVAL_REQUIRED');path=a.plan.absolute();digest=a.approve_plan_sha256
    need(sha(regular(path))==digest,'ISSUER_PLAN_APPROVAL_CHANGED');plan=load(path);folder=path.parent
    need(path.name=='PLAN.json' and folder.parent==root and folder.name.startswith('hilega-issuer-provision-plan-'),'EXACT_ISSUER_PLAN_FOLDER_REQUIRED')
    need(plan['model']=='HILEGA_REAL_ISSUER_MATERIAL_PLAN_V1' and plan['repo']==str(root) and plan['uid']==os.getuid() and plan['home']==str(Path.home())
         and plan['tool_manifest_sha256']==sha(regular(here/'MANIFEST.json')),'ISSUER_PLAN_SCOPE_CHANGED')
    check=load(folder/'CHECK-VALIDATION.json');need(check['status']=='REAL_ISSUER_DISABLED_REGISTRY_PLAN_PASS' and check['plan_sha256']==digest,'PASSING_EXACT_ISSUER_PLAN_REQUIRED')
    active_path=Path(plan['active_plan']);need(sha(regular(active_path))==plan['active_plan_sha256'],'ISSUER_ACTIVE_PLAN_CHANGED');active=load(active_path)
    label=a.action+'-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
    closed_status(root,active_path,plan['active_plan_sha256'],folder,label+'-BEFORE')
    fd=os.open(root/'.hilega-closed-rollout.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        lock_info=os.fstat(fd);need(stat.S_ISREG(lock_info.st_mode) and lock_info.st_uid==os.getuid() and stat.S_IMODE(lock_info.st_mode)&0o077==0,'PRIVATE_ISSUER_MAINTENANCE_LOCK_REQUIRED')
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        idn=identity(root,active);baseline(active)
        need(idn['pin']['scope']==plan['account_scope'] and idn['bindings']==plan['source_configuration_bindings'],'ISSUER_ACCOUNT_OR_CONFIGURATION_CHANGED')
        need(str(Path.home()/'hilega-private/production-issuers'/plan['account_scope'].split(':',1)[1])==plan['private_parent'],'ISSUER_DESTINATION_CHANGED')
        need(sha(regular(Path(plan['evidence_file'])))==plan['evidence_sha256'] and sha(regular(Path(plan['requirements'])))==plan['requirements_sha256'],'ISSUER_EVIDENCE_OR_REQUIREMENTS_CHANGED')
        if a.action=='apply':
            need(datetime.now(timezone.utc)<=datetime.fromisoformat(plan['apply_before']) and idn['pid']==plan['source_pid'],'ISSUER_PLAN_EXPIRED_OR_SOURCE_RESTARTED_RECHECK')
            result=provision(plan,digest,forbidden=idn['forbidden'])
        elif a.action=='recover':result=provision(plan,digest,recover=True,forbidden=idn['forbidden'])
        else:result=issuer_status(plan,digest)
    finally:os.close(fd)
    closed_status(root,active_path,plan['active_plan_sha256'],folder,label+'-AFTER');save(folder/(label+'-RESULT.json'),result);tracker(folder,True)
    print(json.dumps(dict(result,production_ready=False,group2_complete=False),indent=2))


if __name__=='__main__':
    try:main()
    except Exception as exc:
        reason=str(exc);safe=reason if re.fullmatch(r'[A-Z][A-Z0-9_]{0,159}',reason) else 'ISSUER_OPERATION_BLOCKED_INSPECT_PRIVATE_PLAN_LOGS'
        print(json.dumps(dict(status='ISSUER_OPERATION_BLOCKED',reason=safe,error_type=type(exc).__name__,production_execution_enabled=False)));raise SystemExit(2)
