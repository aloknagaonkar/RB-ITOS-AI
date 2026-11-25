#!/usr/bin/env python3
"""Contextual staging, leased installation and rollback for simulation-only integration."""
import argparse
import ast
from datetime import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen
import companion_bindings as companion

HERE=Path(__file__).resolve().parent
API='hilega-api.service';REFERENCE='hilega-lifecycle-reference.service'
NEW='hilega-rsi-two-route-shadow.service'
PROTECTED=('hilega-worker.service','hilega-production-source-worker.service',
           'hilega-observation-analytics.service','hilega-observation-readiness.service')


def sha(raw):return hashlib.sha256(raw).hexdigest()
def regular(path):return companion.regular(path)
def write_json(path,value):path.write_text(json.dumps(value,indent=2)+'\n')
def ctl(*args):return subprocess.run(['systemctl','--user',*args],capture_output=True,text=True,timeout=60,check=True)
def unit(name):
    r=subprocess.run(['systemctl','--user','show',name,'-p','ActiveState,SubState,MainPID,WorkingDirectory'],capture_output=True,text=True,timeout=30)
    if r.returncode and name!=NEW:raise ValueError('SYSTEMD_QUERY_FAILED:'+name)
    return dict(line.split('=',1) for line in r.stdout.splitlines() if '=' in line)
def protected():return {name:unit(name) for name in PROTECTED}
def check_protected(before):
    if protected()!=before:raise ValueError('PROTECTED_SERVICE_CHANGED')
def run(args,log,cwd=None,env=None):
    with log.open('w') as out:
        r=subprocess.run(args,cwd=cwd,env=env,stdout=out,stderr=subprocess.STDOUT,timeout=600)
    if r.returncode:raise ValueError('CHECK_FAILED_SEE_LOG:'+str(log))
def one_replace(text,old,new):
    if text.count(old)!=1:raise ValueError('SOURCE_ANCHOR_CHANGED:'+old)
    return text.replace(old,new,1)


def patches(repo):
    updates={}
    for path in sorted((HERE/'files').rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts and path.suffix not in ('.pyc',):
            relative=str(path.relative_to(HERE/'files'))
            if (repo/relative).exists():raise ValueError('NEW_MODULE_ALREADY_EXISTS:'+relative)
            updates[relative]=regular(path)
    rel='backend/market_lab/api.py';text=regular(repo/rel).decode()
    tree=ast.parse(text)
    funcs=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='create_app']
    if len(funcs)!=1:raise ValueError('API_FACTORY_CHANGED')
    lines=text.splitlines(keepends=True)
    prefix=[n for n in tree.body if (isinstance(n,ast.ImportFrom) and n.module=='__future__')]
    insert_after=max([n.end_lineno for n in prefix]+([tree.body[0].end_lineno] if tree.body and isinstance(tree.body[0],ast.Expr) and isinstance(tree.body[0].value,ast.Constant) and isinstance(tree.body[0].value.value,str) else [0]))
    lines.insert(insert_after,'from .hilega_rsi_two_route_v1.api import router as hilega_rsi_two_route_router\n')
    text=''.join(lines)
    text=one_replace(text,'    app.include_router(hilega_historical_router)',
        '    app.include_router(hilega_historical_router)\n    app.include_router(hilega_rsi_two_route_router)')
    ast.parse(text);updates[rel]=text.encode()
    for filename,name,mode in [('hilegaHistoricalReplay.tsx','HilegaHistoricalReplay','historical'),('hilegaMilegaShadow.tsx','HilegaMilegaShadow','live')]:
        rel='frontend/src/'+filename;text=regular(repo/rel).decode()
        if 'useState' not in text:raise ValueError('FRONTEND_HOOK_IMPORT_CHANGED')
        import re
        pattern=r'export default function '+name+r'\s*\(\s*\)\s*\{'
        if len(re.findall(pattern,text))!=1:raise ValueError('FRONTEND_COMPONENT_ANCHOR_CHANGED:'+filename)
        text=re.sub(pattern,'function Legacy'+name+'(){',text,count=1)
        text="import HilegaRsiTwoRouteWorkspace from './hilegaRsiTwoRouteWorkspace'\n"+text
        text+='\nexport default function '+name+'''() {
  const [strategy, setStrategy] = useState<'legacy' | 'rsi'>('legacy')
  return <section>
    <label>Strategy workspace <select value={strategy} onChange={event => setStrategy(event.target.value as 'legacy' | 'rsi')}>
      <option value="legacy">Existing Hilega strategies</option>
      <option value="rsi">RSI Two Route — Confirmed Midpoint · simulation</option>
    </select></label>
    {strategy === 'rsi' ? <HilegaRsiTwoRouteWorkspace mode="'''+mode+'''" /> : <Legacy'''+name+''' />}
  </section>
}
'''
        updates[rel]=text.encode()
    return updates


def assert_package():
    manifest=json.loads(regular(HERE/'package-manifest.json'))
    for rel,expected in manifest['files'].items():
        if sha(regular(HERE/rel))!=expected:raise ValueError('PACKAGE_FILE_CHANGED:'+rel)


def prepare(args):
    repo=args.repo.resolve();assert_package()
    if not (repo/'.venv/bin/python').is_file():raise ValueError('APPLICATION_PYTHON_MISSING')
    states=protected()
    for name in (API,REFERENCE):
        u=unit(name)
        if u.get('ActiveState')!='active' or Path(u.get('WorkingDirectory','')).resolve()!=repo:
            raise ValueError('EXPECTED_APPLICATION_SERVICE_NOT_RUNNING:'+name)
    check=subprocess.run([str(repo/'.venv/bin/python'),'-B',str(repo/companion.PACKAGE/'cli.py'),'check','--repo',str(repo)],capture_output=True,text=True,timeout=60)
    if check.returncode or json.loads(check.stdout).get('status')!='PACKAGE_AND_RUNTIME_CHECK_PASS':raise ValueError('CURRENT_COMPANION_CHECK_FAILED')
    updates=patches(repo)
    originals={rel:regular(repo/rel) for rel in (str(companion.PACKAGE/'manifest.json'),str(companion.PACKAGE/'cli.py'),str(companion.SERVICE))}
    binding=companion.rebind(originals,updates);updates.update(binding['files'])
    stage=Path(tempfile.mkdtemp(prefix='hilega-rsi-integration-',dir=args.stage_parent)).resolve()
    # Copy source, never credentials, databases, trade journals or old data.
    for directory in ('backend','frontend'):
        shutil.copytree(repo/directory,stage/directory,ignore=shutil.ignore_patterns('node_modules','dist','__pycache__','.env','*.db','*.sqlite*'))
    for rel,raw in updates.items():
        target=stage/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    # Companion module integrity is validated before hashing the changed runtime.
    old=json.loads(originals[str(companion.PACKAGE/'manifest.json')])
    for rel,expected in old['modules'].items():
        raw=regular(repo/companion.PACKAGE/rel)
        if sha(raw)!=expected:raise ValueError('COMPANION_MODULE_CHANGED:'+rel)
        dest=stage/companion.PACKAGE/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(raw)
    companion.check_candidate(stage,stage/companion.PACKAGE,stage/companion.SERVICE,companion.current_service_args(repo))
    python=str(repo/'.venv/bin/python')
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=str(stage/'backend'),HILEGA_RSI_TEST_MODULE_ROOT=str(stage/'backend/market_lab'))
    run([python,'-B','-m','unittest','discover','-s',str(HERE/'tests'),'-v'],stage/'integration-tests.log',env=env)
    run([python,'-B','-c','from market_lab.api import app; assert any(r.path == "/api/live-shadow/hilega-rsi-two-route/rules" for r in app.routes)'],stage/'api-import.log',cwd=stage,env=env)
    run(['node',str(HERE/'tests/ui_contract.js'),str(stage/'backend/market_lab/hilega_rsi_two_route_v1/workspace.html')],stage/'audit-ui-contract.log')
    deps=repo/'frontend/node_modules'
    if not deps.is_dir():raise ValueError('VM_FRONTEND_DEPENDENCIES_MISSING')
    (stage/'frontend/node_modules').symlink_to(deps,target_is_directory=True)
    run(['npm','run','build'],stage/'frontend-build.log',cwd=stage/'frontend')
    import difflib
    diff=[]
    for rel,raw in sorted(updates.items()):
        original=regular(repo/rel).decode() if (repo/rel).exists() else ''
        diff.extend(difflib.unified_diff(original.splitlines(keepends=True),raw.decode().splitlines(keepends=True),fromfile='installed/'+rel,tofile='candidate/'+rel))
    (stage/'changes.diff').write_text(''.join(diff))
    files={}
    for rel,raw in updates.items():
        current=repo/rel
        files[rel]=dict(before=sha(regular(current)) if current.exists() else None,after=sha(raw))
    # Retain old hashed assets to support already-open clients; index is installed last.
    assets={str(p.relative_to(stage)):sha(regular(p)) for p in (stage/'frontend/dist').rglob('*') if p.is_file()}
    receipt=dict(status='PREPARED_NOT_INSTALLED',repo=str(repo),stage=str(stage),files=files,assets=assets,
        package_sha256=sha(regular(HERE/'package-manifest.json')),protected_services=states,
        companion_check=True,checks=['integration-tests','audit UI JavaScript contract','full application import','frontend TypeScript/Vite build','companion runtime pins'],
        strategy_id='HILEGA_RSI_TWO_ROUTE_CONFIRMED_MIDPOINT',strategy_version='1.0.0',execution_mode='SIMULATION_ONLY',
        installed_files_modified=False,services_restarted=False,broker_orders_sent=False)
    write_json(stage/'prepared.json',receipt);check_protected(states)
    print(json.dumps(receipt,indent=2),flush=True)
    return receipt


def put(path,raw):
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile('wb',dir=path.parent,delete=False) as f:
        tmp=Path(f.name);f.write(raw);f.flush();os.fsync(f.fileno())
    try:os.chmod(tmp,0o644);os.replace(tmp,path)
    finally:tmp.unlink(missing_ok=True)


def verify_url(base):
    last=None
    for _ in range(20):
        try:
            with urlopen(base.rstrip('/')+'/api/live-shadow/hilega-rsi-two-route/rules',timeout=5) as response:r=json.load(response)
            if r.get('strategy_version')=='1.0.0' and r.get('execution_mode')=='SIMULATION_ONLY':return r
        except Exception as exc:last=type(exc).__name__
        time.sleep(1)
    raise ValueError('API_HEALTH_CHECK_FAILED:'+str(last))


def apply(args):
    assert_package();stage=args.stage.resolve();r=json.loads(regular(stage/'prepared.json'));repo=args.repo.resolve()
    if r['repo']!=str(repo) or r['stage']!=str(stage):raise ValueError('STAGE_IDENTITY_MISMATCH')
    if r['package_sha256']!=sha(regular(HERE/'package-manifest.json')):raise ValueError('STAGE_PACKAGE_CHANGED')
    states=protected();unit_path=Path.home()/'.config/systemd/user'/NEW
    if unit_path.exists() or unit(NEW).get('ActiveState')=='active':raise ValueError('NEW_SERVICE_ALREADY_EXISTS')
    for rel,item in r['files'].items():
        path=repo/rel
        current=sha(regular(path)) if path.exists() else None
        if current!=item['before'] or sha(regular(stage/rel))!=item['after']:raise ValueError('SOURCE_LEASE_CHANGED:'+rel)
    for rel,expected in r['assets'].items():
        if sha(regular(stage/rel))!=expected:raise ValueError('BUILT_ASSET_CHANGED:'+rel)
    backup=repo/'data/recovery'/('hilega-rsi-install-'+datetime.now().strftime('%Y%m%dT%H%M%S%f'));backup.mkdir(parents=True)
    transaction=dict(repo=str(repo),stage=str(stage),unit_path=str(unit_path),files={},protected_services=states,new_service_preexisting=False,status='INSTALLING')
    all_files=list(r['files'])+sorted(r['assets'],key=lambda n:n.endswith('/index.html'))
    for rel in all_files:
        path=repo/rel;old=regular(path) if path.exists() else None
        if old is not None:
            dest=backup/'original'/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(old)
        transaction['files'][rel]=dict(before=sha(old) if old is not None else None,after=sha(regular(stage/rel)))
    write_json(backup/'receipt.json',transaction)
    try:
        # Package-protected services must keep their exact identity throughout.
        check_protected(states)
        for rel in all_files:put(repo/rel,regular(stage/rel))
        repo_string=str(repo)
        if any(c in repo_string for c in ('\n','\r','"','%','\\')):raise ValueError('UNSUPPORTED_SERVICE_PATH')
        unit_body=f'''[Unit]
Description=Hilega RSI Two Route independent simulation shadow
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
WorkingDirectory={repo}
Environment="PYTHONPATH={repo}/backend"
Environment="PYTHONUNBUFFERED=1"
ExecStart="{repo}/.venv/bin/python" -B -m market_lab.hilega_rsi_two_route_v1.worker --repo "{repo}"
Restart=on-failure
RestartSec=15
UMask=0077
[Install]
WantedBy=default.target
'''
        put(unit_path,unit_body.encode());transaction['unit_sha256']=sha(unit_body.encode());write_json(backup/'receipt.json',transaction)
        ctl('daemon-reload');ctl('restart',API,REFERENCE)
        verify_url(args.api_url)
        for name in (API,REFERENCE):
            first=unit(name)
            time.sleep(2)
            second=unit(name)
            if first.get('ActiveState')!='active' or second.get('ActiveState')!='active' or first.get('MainPID')!=second.get('MainPID'):
                raise ValueError('RESTART_FAILED_OR_FLAPPING:'+name)
        ctl('enable','--now',NEW)
        if unit(NEW).get('ActiveState')!='active':raise ValueError('SIMULATION_WORKER_START_FAILED')
        check_protected(states)
        transaction.update(status='INSTALLED_SIMULATION_ONLY',installed_at=datetime.now().isoformat(),broker_orders_sent=False,
                           remaining='Inspect live worker health and rendered strategy selector on VM')
        write_json(backup/'receipt.json',transaction)
        print(json.dumps(dict(status=transaction['status'],receipt=str(backup/'receipt.json'),
                              new_service=NEW,broker_orders_sent=False,protected_services_unchanged=True),indent=2))
    except BaseException:
        print('Installation failed. Attempting exact-file rollback.',file=sys.stderr)
        rollback_files(backup,transaction)
        raise


def rollback_files(backup,r):
    repo=Path(r['repo']);unit_path=Path(r['unit_path'])
    # Do not overwrite post-install user changes during rollback.
    for rel,item in r['files'].items():
        path=repo/rel
        current=sha(regular(path)) if path.exists() else None
        if current not in (item['before'],item['after']):raise ValueError('ROLLBACK_FILE_CHANGED:'+rel)
    if unit_path.exists() and (not r.get('unit_sha256') or sha(regular(unit_path))!=r['unit_sha256']):
        raise ValueError('ROLLBACK_UNIT_CHANGED')
    if r.get('unit_sha256'):
        ctl('disable','--now',NEW)
        unit_path.unlink(missing_ok=True);ctl('daemon-reload')
    for rel,item in reversed(list(r['files'].items())):
        path=repo/rel
        if item['before'] is None:path.unlink(missing_ok=True)
        else:put(path,regular(backup/'original'/rel))
    ctl('restart',API,REFERENCE)
    r['status']='ROLLED_BACK';write_json(backup/'receipt.json',r)


def main():
    p=argparse.ArgumentParser();g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare',action='store_true');g.add_argument('--install',action='store_true',help='prepare, validate, then apply automatically on success');g.add_argument('--apply',action='store_true');g.add_argument('--rollback',type=Path)
    p.add_argument('--repo',type=Path,default=Path.cwd());p.add_argument('--stage',type=Path)
    p.add_argument('--stage-parent',type=Path,default=Path('/tmp'));p.add_argument('--api-url',default='http://127.0.0.1:8123')
    args=p.parse_args()
    lockdir=args.repo.resolve()/'data/recovery';lockdir.mkdir(parents=True,exist_ok=True)
    with (lockdir/'hilega-rsi-install.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if args.prepare:prepare(args)
        elif args.install:
            receipt=prepare(args);args.stage=Path(receipt['stage']);apply(args)
        elif args.apply:
            if args.stage is None:p.error('--apply requires --stage from PREPARED_NOT_INSTALLED')
            apply(args)
        else:
            receipt=args.rollback.resolve();r=json.loads(regular(receipt))
            if r['repo']!=str(args.repo.resolve()):raise ValueError('ROLLBACK_REPO_MISMATCH')
            states=protected();rollback_files(receipt.parent,r);check_protected(states)
            print(json.dumps({'status':'ROLLED_BACK','receipt':str(receipt)}))
if __name__=='__main__':main()
