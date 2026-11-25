#!/usr/bin/env python3
"""Install the exact VM-validated UI candidate; no strategy or journal edits."""
import argparse
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
from urllib.parse import urlparse
from urllib.request import urlopen
from zoneinfo import ZoneInfo

HERE=Path(__file__).resolve().parent
IST=ZoneInfo('Asia/Kolkata')
API='hilega-api.service'
REFERENCE='hilega-lifecycle-reference.service'
RESTART=(API,REFERENCE)
PROTECTED=('hilega-worker.service','hilega-production-source-worker.service',
           'hilega-observation-analytics.service','hilega-observation-readiness.service')
COMPANION=Path('hilega-operational-lifecycle-tools-6cexrur_')
SERVICE=Path('hilega-reference-service-stage-yup3_wr1/lifecycle_reference_service.py')


def digest(raw):return hashlib.sha256(raw).hexdigest()


def raw(path):
    if path.is_symlink() or not path.is_file() or any(p.is_symlink() for p in path.absolute().parents):
        raise ValueError('REGULAR_SOURCE_REQUIRED:'+str(path))
    return path.read_bytes()


def sha(path):return digest(raw(path))


def write_json(path,value):
    path.write_text(json.dumps(value,indent=2)+'\n')


def systemctl(*args):
    return subprocess.run(['systemctl','--user',*args],capture_output=True,text=True,timeout=45,check=True)


def unit(name):
    result=systemctl('show',name,'--property=ActiveState,SubState,MainPID,WorkingDirectory,NRestarts')
    return dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)


def protected_states():return {name:unit(name) for name in PROTECTED}


def protected_check(before):
    after=protected_states()
    if after!=before:raise ValueError('PROTECTED_SERVICE_CHANGED_NO_RESTART_ATTEMPTED')
    return after


def read_url(base,path):
    with urlopen(base.rstrip('/')+path,timeout=20) as response:return response.read()


def status(base,version):
    value=json.loads(read_url(base,'/api/live-shadow/hilega-directional/status?fast=true'))
    if (value.get('strategy_version')!=version or
        value.get('selected_live_shadow_strategy')!='HILEGA_V2_ALIGNMENT_DUAL_EXIT' or
        value.get('observation_only') is not True or value.get('execution_enabled') is not False):
        raise ValueError('EXPECTED_OBSERVATION_POLICY_REQUIRED')
    return value


def command_json(command,repo):
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=str(repo/'backend'))
    p=subprocess.run(command,cwd=repo,env=env,capture_output=True,text=True,timeout=60)
    if p.returncode:raise ValueError('READ_ONLY_CHECK_FAILED:'+Path(command[2] if len(command)>2 else command[0]).name)
    return json.loads(p.stdout)


def package_check(repo):
    value=command_json([sys.executable,'-B',str(repo/COMPANION/'cli.py'),'check','--repo',str(repo)],repo)
    if value.get('status')!='PACKAGE_AND_RUNTIME_CHECK_PASS':raise ValueError('RUNTIME_PIN_CHECK_FAILED')
    for name in ['database_access_performed','credentials_opened','broker_reads_performed','order_actions_available','production_execution_enabled']:
        if value.get(name) is not False:raise ValueError('PACKAGE_CHECK_SCOPE_CHANGED:'+name)
    return value


def reference_arguments(repo):
    state=unit(REFERENCE);pid=state.get('MainPID','0')
    if state.get('ActiveState')!='active' or not pid.isdigit() or pid=='0':
        raise ValueError('REFERENCE_SERVICE_NOT_RUNNING')
    cwd=Path('/proc',pid,'cwd').resolve()
    args=Path('/proc',pid,'cmdline').read_bytes().decode().split('\0')
    candidates=[i for i,arg in enumerate(args) if arg.endswith('.py') and
        (Path(arg) if Path(arg).is_absolute() else cwd/arg).resolve()==repo/SERVICE]
    if len(candidates)!=1:raise ValueError('REFERENCE_ENTRYPOINT_CHANGED')
    tail=[arg for arg in args[candidates[0]+1:] if arg]
    if [arg for arg in tail if arg in ('--watch','--once','--check')]!=['--watch']:
        raise ValueError('REFERENCE_WATCH_MODE_REQUIRED')
    for option in ['--repo','--package','--application','--adapter','--pin-file','--env-file','--journal']:
        if tail.count(option)!=1:raise ValueError('REFERENCE_ARGUMENT_CHANGED:'+option)
        index=tail.index(option)+1
        value=Path(tail[index]);tail[index]=str(value if value.is_absolute() else cwd/value)
    if Path(tail[tail.index('--repo')+1]).resolve()!=repo or Path(tail[tail.index('--package')+1]).resolve()!=repo/COMPANION:
        raise ValueError('REFERENCE_SOURCE_PATH_CHANGED')
    return tail


def reference_check(repo,arguments):
    args=list(arguments);args[args.index('--watch')]='--check'
    args[args.index('--repo')+1]=str(repo)
    args[args.index('--package')+1]=str(repo/COMPANION)
    value=command_json([sys.executable,'-B',str(repo/SERVICE),*args],repo)
    if (value.get('status')!='SERVICE_STARTUP_CHECK_PASS' or value.get('database_opened') is not False or
        value.get('token_loaded') is not False or value.get('production_execution_enabled') is not False):
        raise ValueError('REFERENCE_STARTUP_CHECK_FAILED')
    return value


def verify_prepared(repo,stage,manifest):
    prepared=json.loads(raw(stage/'preparation.json'))
    if (prepared.get('status')!='UI_POLICY_FIX_PREPARED_NOT_INSTALLED' or
        Path(prepared.get('repo','')).resolve()!=repo or Path(prepared.get('stage','')).resolve()!=stage or
        prepared.get('strategy_version')!=manifest['strategy_version'] or
        prepared.get('files')!=manifest['files'] or
        prepared.get('built_asset_sha256')!=manifest['built_asset_sha256']):
        raise ValueError('PREPARED_BUILD_DIFFERS_FROM_REVIEWED_VM_RESULT')
    expected={rel:item['after'] for rel,item in manifest['files'].items()}
    expected.update({'frontend/dist/'+rel:value for rel,value in manifest['built_asset_sha256'].items()})
    for rel,value in expected.items():
        if sha(stage/rel)!=value:raise ValueError('PREPARED_FILE_CHANGED:'+rel)
    actual={str(p.relative_to(stage/'frontend/dist')) for p in (stage/'frontend/dist').rglob('*') if p.is_file()}
    if actual!=set(manifest['built_asset_sha256']):raise ValueError('UNEXPECTED_PREPARED_ASSET_SET')
    return expected


def source_check(repo,manifest,side='before'):
    for rel,item in manifest['files'].items():
        if sha(repo/rel)!=item[side]:raise ValueError('SOURCE_CHANGED:'+rel)


def atomic_file(path,content,mode=0o644):
    if any(p.is_symlink() for p in path.absolute().parents) or path.is_symlink():
        raise ValueError('SYMLINK_TARGET_NOT_ALLOWED:'+str(path))
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile('wb',dir=path.parent,delete=False,prefix='.hilega-ui-') as f:
        temp=Path(f.name)
        try:
            f.write(content);f.flush();os.fsync(f.fileno());os.chmod(temp,mode)
        except BaseException:
            temp.unlink(missing_ok=True);raise
    try:os.replace(temp,path)
    finally:temp.unlink(missing_ok=True)


def invalidate(repo,files):
    for rel in files:
        p=repo/rel
        if p.suffix=='.py':
            cache=p.parent/'__pycache__'
            if cache.is_symlink():raise ValueError('CACHE_SYMLINK_NOT_ALLOWED')
            if cache.is_dir():
                for bytecode in cache.glob(p.stem+'.*.pyc'):
                    if not bytecode.is_symlink():bytecode.unlink()


def make_backup(repo,backup,expected):
    before={};modes={}
    for rel in expected:
        p=repo/rel
        if p.exists() or p.is_symlink():
            data=raw(p);before[rel]=digest(data);modes[rel]=p.stat().st_mode&0o777
            target=backup/'files'/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
        else:before[rel]=None;modes[rel]=0o644
    return before,modes


def restore(repo,backup,receipt):
    # Restore only files attempted by this deployment, never unrelated assets.
    for rel in reversed(receipt['touched']):
        if rel not in receipt['after']:raise ValueError('UNEXPECTED_ROLLBACK_PATH')
        p=repo/rel;current=sha(p) if p.exists() or p.is_symlink() else None
        old=receipt['before'][rel]
        if current==old:continue
        if current!=receipt['after'][rel]:raise ValueError('ROLLBACK_SOURCE_LEASE_CHANGED:'+rel)
        if old is None:p.unlink()
        else:
            content=raw(backup/'files'/rel)
            if digest(content)!=old:raise ValueError('BACKUP_CHANGED:'+rel)
            atomic_file(p,content,receipt['modes'][rel])
    invalidate(repo,receipt['before'])
    for rel,old in receipt['before'].items():
        p=repo/rel;current=sha(p) if p.exists() or p.is_symlink() else None
        if current!=old:raise ValueError('ROLLBACK_VERIFICATION_FAILED:'+rel)


def verify_api(base,version,assets,protected):
    deadline=time.monotonic()+180;last='not ready';next_update=0
    while time.monotonic()<deadline:
        try:
            value=status(base,version);current=value.get('current') or {}
            if current.get('state_available') is not True:raise ValueError('CURRENT_STATE_NOT_READY')
            day=current.get('session_date')
            if day!=datetime.now(IST).date().isoformat():raise ValueError('CURRENT_SESSION_MISMATCH')
            data=json.loads(read_url(base,'/api/live-shadow/hilega-directional-candles/live?audit_only=true&session_date='+day))
            rows=data.get('rows') or []
            if data.get('display_strategy_version')!=version or not rows:raise ValueError('CANDLE_VIEW_NOT_READY')
            if any(r.get('strategy_version')!=version for r in rows):raise ValueError('CANDLE_VIEW_VERSION_MIX')
            if any(r.get('audit_status')=='RECOVERED' and r.get('reconstructed') is not True for r in rows):
                raise ValueError('RECONSTRUCTION_PROVENANCE_MISSING')
            if digest(read_url(base,'/'))!=assets['index.html']:raise ValueError('SERVED_UI_INDEX_MISMATCH')
            for rel,expected in assets.items():
                if rel!='index.html' and digest(read_url(base,'/'+rel))!=expected:raise ValueError('SERVED_ASSET_MISMATCH:'+rel)
            for name in RESTART:
                state=unit(name)
                if state.get('ActiveState')!='active' or state.get('SubState')!='running':raise ValueError('SERVICE_NOT_RUNNING:'+name)
            protected_check(protected)
            return dict(strategy_version=version,current={k:current.get(k) for k in
                ['session_date','state_available','trade_owner','bullish_state','bearish_state','last_completed_bar']},
                candle_rows=len(rows),candle_versions=sorted({r['strategy_version'] for r in rows}),
                reconstructed_rows=sum(r.get('reconstructed') is True for r in rows),
                served_assets_verified=len(assets),services={name:unit(name) for name in RESTART},
                browser_display_verified=False)
        except Exception as exc:
            last=type(exc).__name__+': '+str(exc)
            if time.monotonic()>=next_update:
                print('Waiting for API/UI verification:',last,flush=True);next_update=time.monotonic()+15
            time.sleep(3)
    raise ValueError('POST_INSTALL_VERIFICATION_FAILED:'+last)


def install(repo,stage,base,manifest):
    expected=verify_prepared(repo,stage,manifest)
    source_check(repo,manifest)
    before_status=status(base,manifest['strategy_version'])
    protected=protected_states();arguments=reference_arguments(repo)
    for name in RESTART:
        state=unit(name)
        if state.get('ActiveState')!='active' or Path(state.get('WorkingDirectory','')).resolve()!=repo:
            raise ValueError('EXPECTED_SERVICE_IDENTITY_REQUIRED:'+name)
    package_check(repo);package_check(stage);reference_check(stage,arguments)
    env_sha=sha(repo/'.env')
    backup=repo/'data/deployments'/('hilega-ui-policy-fix-'+datetime.now(IST).strftime('%Y%m%dT%H%M%S%f'))
    backup.mkdir(parents=True,exist_ok=False)
    before,modes=make_backup(repo,backup,expected)
    receipt=dict(model='HILEGA_UI_POLICY_INSTALL_RECEIPT_V1',status='BACKUP_CREATED',repo=str(repo),stage=str(stage),
        before=before,after=expected,modes=modes,touched=[],protected_services=protected,
        services_restarted=list(RESTART),strategy_version=manifest['strategy_version'],
        strategy_rules_changed=False,journals_rewritten=False,broker_requests_sent_by_installer=False,
        databases_edited_by_installer=False,browser_display_verified=False)
    write_json(backup/'receipt.json',receipt);print('Backup:',backup,flush=True)
    stopping=False
    try:
        stopping=True;systemctl('stop',*RESTART)
        for name in RESTART:
            if unit(name).get('ActiveState')!='inactive':raise ValueError('SERVICE_DID_NOT_STOP:'+name)
        source_check(repo,manifest);protected_check(protected);package_check(repo)
        if sha(repo/'.env')!=env_sha:raise ValueError('ENV_CHANGED_DURING_INSTALL')
        # Index last. Existing hashed assets remain for already-open browser tabs.
        order=[rel for rel in expected if rel!='frontend/dist/index.html']+['frontend/dist/index.html']
        for rel in order:
            p=repo/rel;current=sha(p) if p.exists() or p.is_symlink() else None
            if current!=before[rel]:raise ValueError('TARGET_CHANGED_DURING_INSTALL:'+rel)
            content=raw(stage/rel)
            if digest(content)!=expected[rel]:raise ValueError('CANDIDATE_CHANGED_DURING_INSTALL:'+rel)
            receipt['touched'].append(rel);write_json(backup/'receipt.json',receipt)
            atomic_file(p,content,modes[rel])
        invalidate(repo,expected);source_check(repo,manifest,'after')
        for rel,wanted in expected.items():
            if sha(repo/rel)!=wanted:raise ValueError('INSTALLED_HASH_MISMATCH:'+rel)
        package_check(repo);reference_check(repo,arguments)
        protected_check(protected)
        systemctl('start',*RESTART)
        verified=verify_api(base,manifest['strategy_version'],manifest['built_asset_sha256'],protected)
        if sha(repo/'.env')!=env_sha:raise ValueError('ENV_CHANGED_AFTER_INSTALL')
        receipt.update(status='UI_POLICY_FIX_DEPLOYED_API_VERIFIED',verification=verified,
            installed_files_modified=True,backup=str(backup))
        write_json(backup/'receipt.json',receipt);print(json.dumps(receipt,indent=2))
    except BaseException as exc:
        receipt.update(status='INSTALL_FAILED',error=type(exc).__name__+': '+str(exc))
        try:
            if stopping:systemctl('stop',*RESTART)
            restore(repo,backup,receipt);package_check(repo);reference_check(repo,arguments)
            if stopping:systemctl('start',*RESTART)
            receipt['status']='ROLLED_BACK_AFTER_INSTALL_FAILURE'
        except BaseException as rollback_error:
            receipt.update(status='ROLLBACK_REQUIRES_ATTENTION',rollback_error=str(rollback_error))
        write_json(backup/'receipt.json',receipt)
        print(json.dumps(receipt,indent=2));raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,default=Path.cwd())
    parser.add_argument('--stage',type=Path,required=True)
    parser.add_argument('--api-url',default='http://127.0.0.1:8123')
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check',action='store_true');mode.add_argument('--apply',action='store_true')
    args=parser.parse_args();repo=args.repo.resolve();stage=args.stage.resolve()
    if urlparse(args.api_url).hostname not in ('127.0.0.1','localhost','::1'):raise ValueError('LOCAL_API_REQUIRED')
    if stage==repo or repo in stage.parents:raise ValueError('ISOLATED_STAGE_REQUIRED')
    manifest=json.loads(raw(HERE/'manifest.json'))
    lock=repo/'data/deployments/.hilega-ui-policy-install.lock';lock.parent.mkdir(parents=True,exist_ok=True)
    if lock.is_symlink():raise ValueError('LOCK_SYMLINK_NOT_ALLOWED')
    with lock.open('a') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if args.check:
            files=verify_prepared(repo,stage,manifest);source_check(repo,manifest)
            status(args.api_url,manifest['strategy_version']);package_check(repo);package_check(stage)
            reference_check(stage,reference_arguments(repo))
            print(json.dumps(dict(status='UI_INSTALL_PREFLIGHT_PASS',stage=str(stage),
                reviewed_files=len(files),installed_files_modified=False,services_restarted=False,
                broker_requests_sent=False),indent=2))
        else:install(repo,stage,args.api_url,manifest)


if __name__=='__main__':main()
