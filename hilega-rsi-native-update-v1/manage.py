#!/usr/bin/env python3
"""Replace strategy inside native Hilega screens/worker; keep execution configuration."""
import argparse,ast,fcntl,hashlib,json,os,shutil,signal,subprocess,sys,tempfile,time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from urllib.request import urlopen
import companion_bindings as pins

HERE=Path(__file__).resolve().parent;IST=ZoneInfo('Asia/Kolkata')
OLD='HILEGA_V2_ALIGNMENT_DUAL_EXIT';NEW='HILEGA_RSI_TWO_ROUTE_CONFIRMED_MIDPOINT'
VERSION='rsi-two-route-1.0.0-3m-native-confirmed-midpoint';POLICY='RSI_TWO_ROUTE_CONFIRMED_MIDPOINT'
RELOAD=('hilega-api.service','hilega-lifecycle-reference.service','hilega-observation-analytics.service','hilega-observation-readiness.service')
PROTECTED=('hilega-worker.service','hilega-production-source-worker.service')
SEPARATE='hilega-rsi-two-route-shadow.service'
CONTROL='data/live-observation/hilega-upstox-sandbox-v2/control.json'
ACTIVATION='data/live-observation/hilega-rsi-native-v1/activation.json'

def digest(b):return hashlib.sha256(b).hexdigest()
def raw(p):return pins.regular(p)
def write_json(p,value):
    p.write_text(json.dumps(value,indent=2)+'\n');os.chmod(p,0o600)
def put(p,b):
    p.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile('wb',dir=p.parent,delete=False) as f:
        t=Path(f.name);f.write(b);f.flush();os.fsync(f.fileno())
    try:os.chmod(t,0o600 if p.name=='.env' else 0o644);os.replace(t,p)
    finally:t.unlink(missing_ok=True)
def ctl(*args):return subprocess.run(['systemctl','--user',*args],capture_output=True,text=True,check=True,timeout=60)
def unit(name):
    r=subprocess.run(['systemctl','--user','show',name,'-p','ActiveState,SubState,MainPID,WorkingDirectory'],capture_output=True,text=True,timeout=20)
    if r.returncode:raise ValueError('SERVICE_QUERY_FAILED:'+name)
    return dict(l.split('=',1) for l in r.stdout.splitlines() if '=' in l)
def protected():return {n:unit(n) for n in PROTECTED}
def check_protected(p):
    if protected()!=p:raise ValueError('UNRELATED_SERVICE_CHANGED')
def run(args,log,cwd=None,env=None):
    with log.open('w') as f:r=subprocess.run(args,cwd=cwd,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=600)
    if r.returncode:raise ValueError('CHECK_FAILED_SEE_LOG:'+str(log))
def inventory():
    m=json.loads(raw(HERE/'manifest.json'))
    for rel,h in m['package_files'].items():
        if digest(raw(HERE/rel))!=h:raise ValueError('PACKAGE_CHANGED:'+rel)
    return m

def selected_env(b):
    lines=b.decode().splitlines();matches=[]
    for i,line in enumerate(lines):
        key,sep,value=line.partition('=')
        if sep and key.strip()=='LIVE_SHADOW_STRATEGY':matches.append((i,value.strip().strip('"\'')))
    if len(matches)!=1:raise ValueError('EXPECTED_ONE_LIVE_SHADOW_STRATEGY_SETTING')
    i,current=matches[0]
    if current!=OLD:raise ValueError('CURRENT_STRATEGY_DIFFERS_FROM_REVIEW')
    lines[i]='LIVE_SHADOW_STRATEGY='+NEW
    return ('\n'.join(lines)+'\n').encode()

def flat(repo,stage):
    env=dict(os.environ,PYTHONPATH=str(repo/'backend'),PYTHONDONTWRITEBYTECODE='1')
    result=subprocess.run([str(repo/'.venv/bin/python'),'-B',str(HERE/'check_flat.py')],cwd=repo,env=env,capture_output=True,text=True,timeout=60)
    if result.returncode:raise ValueError('LOCAL_LEDGER_CHECK_FAILED_NO_INSTALLATION')
    p=json.loads(result.stdout)
    if p.get('status')!='LOCAL_LEDGERS_FLAT' or any(p['counts'].values()):
        write_json(stage/'flat-check.json',p)
        raise ValueError('EXISTING_OPEN_OR_PENDING_TRADES_REQUIRES_RECONCILIATION:'+str(stage/'flat-check.json'))
    write_json(stage/'flat-check.json',p);return p

def prepare(a):
    repo=a.repo.resolve();m=inventory();states=protected()
    if unit(SEPARATE)['ActiveState']!='inactive':raise ValueError('STOP_SEPARATE_RSI_WORKER_FIRST')
    for name in RELOAD:
        info=unit(name)
        if info['ActiveState']!='active' or Path(info.get('WorkingDirectory','')).resolve()!=repo:raise ValueError('EXPECTED_RUNNING_NATIVE_SERVICE:'+name)
        import shlex
        configured=ctl('show',name,'-p','Environment','--value').stdout
        for setting in shlex.split(configured):
            if setting.startswith('LIVE_SHADOW_STRATEGY=') and setting.split('=',1)[1]!=NEW:
                raise ValueError('SYSTEMD_STRATEGY_OVERRIDE_REQUIRES_REVIEW:'+name)
    for rel,before in m['installed_before'].items():
        current=digest(raw(repo/rel)) if (repo/rel).exists() else None
        if current!=before:raise ValueError('VM_SOURCE_CHANGED:'+rel)
    selected_env(raw(repo/'.env'))
    old_check=subprocess.run([str(repo/'.venv/bin/python'),'-B',str(repo/pins.PACKAGE/'cli.py'),'check','--repo',str(repo)],capture_output=True,text=True,timeout=60)
    if old_check.returncode or json.loads(old_check.stdout).get('status')!='PACKAGE_AND_RUNTIME_CHECK_PASS':raise ValueError('CURRENT_COMPANION_CHECK_FAILED')
    stage=Path(tempfile.mkdtemp(prefix='hilega-rsi-native-',dir=a.stage_parent)).resolve()
    for name in ('backend','frontend'):
        shutil.copytree(repo/name,stage/name,ignore=shutil.ignore_patterns('node_modules','dist','__pycache__','.env','*.db','*.sqlite*'))
    updates={rel:raw(HERE/'files'/rel) for rel in m['installed_before']}
    original={rel:raw(repo/rel) for rel in (str(pins.PACKAGE/'manifest.json'),str(pins.PACKAGE/'cli.py'),str(pins.SERVICE))}
    binding=pins.rebind(original,updates);updates.update(binding['files'])
    for rel,b in updates.items():put(stage/rel,b)
    old_manifest=json.loads(original[str(pins.PACKAGE/'manifest.json')])
    for name,h in old_manifest['modules'].items():
        b=raw(repo/pins.PACKAGE/name)
        if digest(b)!=h:raise ValueError('COMPANION_MODULE_CHANGED:'+name)
        put(stage/pins.PACKAGE/name,b)
    pins.check_candidate(stage,stage/pins.PACKAGE,stage/pins.SERVICE,pins.current_service_args(repo))
    env=dict(os.environ,PYTHONPATH=str(stage/'backend'),HILEGA_NATIVE_TEST_ROOT=str(stage/'backend'),
             LIVE_SHADOW_STRATEGY=NEW,PYTHONDONTWRITEBYTECODE='1')
    python=str(repo/'.venv/bin/python')
    run([python,'-B','-m','unittest','discover','-s',str(HERE/'tests'),'-v'],stage/'native-tests.log',env=env)
    run([python,'-B',str(HERE/'check_api.py')],stage/'native-api.log',cwd=stage,env=env)
    deps=repo/'frontend/node_modules'
    if not deps.is_dir():raise ValueError('FRONTEND_NODE_MODULES_REQUIRED')
    (stage/'frontend/node_modules').symlink_to(deps,target_is_directory=True)
    run(['npm','run','build'],stage/'frontend-build.log',cwd=stage/'frontend')
    flat(repo,stage)
    import difflib
    differences=[]
    for rel,b in sorted(updates.items()):
        before=raw(repo/rel).decode() if (repo/rel).exists() else ''
        differences.extend(difflib.unified_diff(before.splitlines(keepends=True),b.decode().splitlines(keepends=True),fromfile='installed/'+rel,tofile='native/'+rel))
    (stage/'changes.diff').write_text(''.join(differences))
    files={rel:dict(before=digest(raw(repo/rel)) if (repo/rel).exists() else None,after=digest(b)) for rel,b in updates.items()}
    assets={str(p.relative_to(stage)):digest(raw(p)) for p in (stage/'frontend/dist').rglob('*') if p.is_file()}
    lease={rel:digest(raw(repo/rel)) if (repo/rel).exists() else None for rel in ('.env',CONTROL,ACTIVATION)}
    receipt=dict(status='NATIVE_UPDATE_PREPARED',repo=str(repo),stage=str(stage),files=files,assets=assets,
        configuration_lease=lease,package_sha256=digest(raw(HERE/'manifest.json')),protected=states,
        strategy_id=NEW,strategy_version=VERSION,execution_mode_change=False,broker_orders_sent=False,
        checks=['native signal/event/lifecycle tests','existing application HTTP routes','TypeScript/Vite build','companion startup pins','local flat/pending/manual-exit guards'])
    write_json(stage/'prepared.json',receipt);check_protected(states)
    print(json.dumps(receipt,indent=2),flush=True);return receipt


def basket_pid(repo):
    p=repo/'data/hilega-upstox-sandbox-worker.pid'
    if not p.exists():return None
    try:pid=int(p.read_text().strip());args=Path('/proc',str(pid),'cmdline').read_bytes().split(b'\0')
    except (ValueError,OSError):return None
    if b'market_lab.hilega_upstox_sandbox_basket_v2' not in args or Path('/proc',str(pid),'cwd').resolve()!=repo:
        raise ValueError('BASKET_WORKER_PID_IDENTITY_MISMATCH')
    return pid

def stop_basket(repo,pid):
    if pid is None:return
    if basket_pid(repo)!=pid:raise ValueError('BASKET_WORKER_CHANGED')
    os.kill(pid,signal.SIGTERM)
    for _ in range(50):
        if not Path('/proc',str(pid)).exists():return
        time.sleep(.1)
    raise ValueError('BASKET_WORKER_DID_NOT_STOP_NO_KILL_ATTEMPTED')

def start_basket(repo):
    script=repo/'scripts/start_hilega_upstox_sandbox_worker.sh'
    if not script.is_file():raise ValueError('EXISTING_BASKET_START_SCRIPT_MISSING')
    env=dict(os.environ);env.pop('LIVE_SHADOW_STRATEGY',None)
    r=subprocess.run(['bash',str(script)],cwd=repo,env=env,capture_output=True,text=True,timeout=30)
    if r.returncode:raise ValueError('EXISTING_BASKET_WORKER_RESTART_FAILED')
    for _ in range(30):
        pid=basket_pid(repo)
        if pid is not None:return
        time.sleep(.1)
    raise ValueError('EXISTING_BASKET_WORKER_RESTART_FAILED')

def http_check(base):
    for _ in range(25):
        try:
            with urlopen(base.rstrip('/')+'/api/live-shadow/hilega-directional/status?fast=true',timeout=5) as r:p=json.load(r)
            if p.get('active_strategy_id')==NEW and p.get('strategy_version')==VERSION:return
        except Exception:pass
        time.sleep(1)
    raise ValueError('NATIVE_API_HEALTH_CHECK_FAILED')

def rollback(backup,r):
    repo=Path(r['repo'])
    for rel,v in r['files'].items():
        p=repo/rel;h=digest(raw(p)) if p.exists() else None
        if h not in (v['before'],v['after'],*v.get('intermediate',[])):raise ValueError('ROLLBACK_SOURCE_CHANGED:'+rel)
    for name in RELOAD:ctl('stop',name)
    pid=basket_pid(repo)
    if pid:stop_basket(repo,pid)
    for rel,v in reversed(list(r['files'].items())):
        p=repo/rel
        if v['before'] is None:p.unlink(missing_ok=True)
        else:put(p,raw(backup/'original'/rel))
    for name in RELOAD:ctl('start',name)
    if r['basket_was_running']:start_basket(repo)
    r['status']='NATIVE_UPDATE_ROLLED_BACK';write_json(backup/'receipt.json',r)


def cutover_boundary(now):
    from datetime import timedelta
    from math import ceil
    start=now.replace(hour=9,minute=15,second=0,microsecond=0)
    return start+timedelta(minutes=3*ceil(max(0,(now-start).total_seconds())/180))

def apply(a):
    repo=a.repo.resolve();stage=a.stage.resolve();m=inventory();r=json.loads(raw(stage/'prepared.json'))
    if r['repo']!=str(repo) or r['stage']!=str(stage) or r['package_sha256']!=digest(raw(HERE/'manifest.json')):raise ValueError('STAGE_IDENTITY_MISMATCH')
    for rel,v in r['files'].items():
        h=digest(raw(repo/rel)) if (repo/rel).exists() else None
        if h!=v['before'] or digest(raw(stage/rel))!=v['after']:raise ValueError('SOURCE_LEASE_CHANGED:'+rel)
    for rel,h in r['assets'].items():
        if digest(raw(stage/rel))!=h:raise ValueError('BUILT_ASSET_CHANGED:'+rel)
    for rel,h in r['configuration_lease'].items():
        current=digest(raw(repo/rel)) if (repo/rel).exists() else None
        if current!=h:raise ValueError('EXECUTION_CONFIGURATION_CHANGED:'+rel)
    # Same OS lock used by basket submission and manual exit. An existing basket
    # is never changed or closed as part of a rule replacement.
    lock=repo/'data/live-observation/hilega-upstox-sandbox-v2/basket-events.jsonl.worker.lock';lock.parent.mkdir(parents=True,exist_ok=True)
    with lock.open('a') as execution_lock:
        fcntl.flock(execution_lock,fcntl.LOCK_EX)
        flat(repo,stage);states=protected()
        control=json.loads(raw(repo/CONTROL)) if (repo/CONTROL).exists() else None
        if control and control.get('strategy_id')!=OLD:raise ValueError('CONTROL_STRATEGY_CHANGED')
        if control and control.get('execution_mode') in ('RANKED_ONE_LEG_SANDBOX','RANKED_OBSERVATION_ONLY'):
            raise ValueError('RANKED_STRIKE_POLICY_VERSION_REVIEW_REQUIRED')
        pid=basket_pid(repo)
        if pid and not (repo/'scripts/start_hilega_upstox_sandbox_worker.sh').is_file():raise ValueError('BASKET_RESTART_SCRIPT_MISSING')
        # Halt only components that import the changed Hilega code. Unrelated
        # preparation/failed production services keep their current states.
        backup=repo/'data/recovery'/('hilega-rsi-native-install-'+datetime.now().strftime('%Y%m%dT%H%M%S%f'));backup.mkdir(mode=0o700,parents=True)
        updates={rel:raw(stage/rel) for rel in r['files']}
        updates['.env']=selected_env(raw(repo/'.env'))
        if control:
            control.update(strategy_id=NEW,strategy_version=VERSION,policy_id=POLICY)
            updates[CONTROL]=(json.dumps(control,indent=2)+'\n').encode()
        updates[ACTIVATION]=(json.dumps(dict(strategy_id=NEW,strategy_version=VERSION,
            activated_at=datetime.now(IST).isoformat(),committed=False,old_strategy_id=OLD,existing_execution_settings_preserved=True),indent=2)+'\n').encode()
        for rel in sorted(r['assets'],key=lambda n:n.endswith('/index.html')):updates[rel]=raw(stage/rel)
        transaction=dict(repo=str(repo),files={},basket_was_running=pid is not None,status='INSTALLING',protected=states)
        for rel,b in updates.items():
            p=repo/rel;old=raw(p) if p.exists() else None
            if old is not None:put(backup/'original'/rel,old)
            transaction['files'][rel]=dict(before=digest(old) if old is not None else None,after=digest(b))
        write_json(backup/'receipt.json',transaction)
        try:
            for name in RELOAD:ctl('stop',name)
            stop_basket(repo,pid)
            # Recheck under the shared execution lock after source writers stop.
            for rel,v in transaction['files'].items():
                current=digest(raw(repo/rel)) if (repo/rel).exists() else None
                if current!=v['before']:raise ValueError('SOURCE_CHANGED_DURING_CUTOVER:'+rel)
            for rel,b in updates.items():put(repo/rel,b)
            # Mark the lease-backed source/config transaction durable before reload.
            transaction['status']='FILES_INSTALLED';write_json(backup/'receipt.json',transaction)
            for name in RELOAD:ctl('start',name)
            http_check(a.api_url)
            for name in RELOAD:
                first=unit(name);time.sleep(1);second=unit(name)
                if first['ActiveState']!='active' or second['ActiveState']!='active' or first['MainPID']!=second['MainPID']:
                    raise ValueError('NATIVE_SERVICE_NOT_STABLE:'+name)
            if pid:start_basket(repo)
            check_protected(states)
            # Only full candles after readiness may create a new native entry.
            now=datetime.now(IST)
            cutoff=cutover_boundary(now)
            activation=json.loads(raw(repo/ACTIVATION));activation.update(committed=True,activated_at=cutoff.isoformat(),committed_at=now.isoformat())
            committed=(json.dumps(activation,indent=2)+'\n').encode()
            lease=transaction['files'][ACTIVATION];lease['intermediate']=[lease['after']];lease['after']=digest(committed)
            write_json(backup/'receipt.json',transaction)
            put(repo/ACTIVATION,committed)

            transaction['status']='NATIVE_HILEGA_STRATEGY_UPDATED';write_json(backup/'receipt.json',transaction)
            print(json.dumps(dict(status=transaction['status'],receipt=str(backup/'receipt.json'),strategy_id=NEW,
                strategy_version=VERSION,existing_execution_settings_preserved=True,broker_orders_sent=False,
                separate_rsi_workspace_removed=True,basket_worker_restarted=pid is not None,entry_cutover_boundary=cutoff.isoformat()),indent=2))
        except BaseException:
            rollback(backup,transaction);raise


def main():
    p=argparse.ArgumentParser();g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare',action='store_true');g.add_argument('--install',action='store_true');g.add_argument('--apply',action='store_true');g.add_argument('--rollback',type=Path)
    p.add_argument('--repo',type=Path,default=Path.cwd());p.add_argument('--stage',type=Path);p.add_argument('--stage-parent',type=Path,default=Path('/tmp'));p.add_argument('--api-url',default='http://127.0.0.1:8123');a=p.parse_args()
    lock=a.repo.resolve()/'data/recovery/hilega-rsi-native-install.lock';lock.parent.mkdir(parents=True,exist_ok=True)
    with lock.open('a') as f:
        fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if a.prepare:prepare(a)
        elif a.install:r=prepare(a);a.stage=Path(r['stage']);apply(a)
        elif a.apply:
            if not a.stage:p.error('--stage is required')
            apply(a)
        else:
            r=json.loads(raw(a.rollback));
            if r['repo']!=str(a.repo.resolve()):raise ValueError('ROLLBACK_REPO_MISMATCH')
            execution_path=a.repo.resolve()/'data/live-observation/hilega-upstox-sandbox-v2/basket-events.jsonl.worker.lock'
            with execution_path.open('a') as execution_lock:
                fcntl.flock(execution_lock,fcntl.LOCK_EX)
                flat(a.repo.resolve(),a.rollback.parent);rollback(a.rollback.parent,r)
            print(json.dumps({'status':r['status']}))
if __name__=='__main__':main()
