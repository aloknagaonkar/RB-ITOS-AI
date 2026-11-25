"""Deploy validated 3m observation rules to the explicitly identified user services."""
import argparse
import ast
from datetime import datetime,timezone
import difflib
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen
import companion_bindings

HERE=Path(__file__).resolve().parent
VERSION='bullish-gap2-full-wma2-3.0.0-3m-two-of-three-session-close'
RESTART_ORDER=['hilega-api.service','hilega-lifecycle-reference.service',
               'hilega-observation-analytics.service','hilega-observation-readiness.service']
PROTECTED=['hilega-worker.service','hilega-production-source-worker.service']
WORKER='backend/market_lab/live_shadow_worker_v1.py'
HELPER='backend/market_lab/hilega_three_minute_v1/worker_close.py'

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write_json(path,value):
    path.write_text(json.dumps(value,indent=2,default=str)+'\n')

def systemctl(*args,check=True):
    p=subprocess.run(['systemctl','--user',*args],capture_output=True,text=True,timeout=60)
    if check and p.returncode:raise ValueError('SYSTEMCTL_FAILED:'+args[0]+':'+args[-1])
    return p

def service_state(unit):
    p=systemctl('show',unit,'--property=ActiveState,SubState,WorkingDirectory,MainPID,NRestarts',check=False)
    return dict(line.split('=',1) for line in p.stdout.splitlines() if '=' in line)

def api_status(base):
    with urlopen(base.rstrip('/')+'/api/live-shadow/hilega-directional/status?fast=true',timeout=15) as response:
        body=json.load(response)
    if body.get('selected_live_shadow_strategy')!='HILEGA_V2_ALIGNMENT_DUAL_EXIT':raise ValueError('WRONG_ACTIVE_API_STRATEGY')
    if body.get('observation_only') is not True or body.get('execution_enabled') is not False:
        raise ValueError('OBSERVATION_MODE_REQUIRED')
    return body

def sandbox_clear(repo):
    # Only pure local ledger reads. No transport is constructed or called.
    code='''import json
from pathlib import Path
from market_lab.hilega_sandbox_fill_ledger_v1 import open_legs,pending_orders
p=Path("data/live-observation/hilega-upstox-sandbox-v2/basket-events.jsonl")
rows=[json.loads(s) for s in p.read_text().splitlines() if s.strip()] if p.is_file() else []
done={r.get("request_id") for r in rows if r.get("status") in {"ACCEPTED","REQUEST_RESOLVED_NO_FILL"}}
uncertain=[r for r in rows if r.get("status")=="REQUESTED" and r.get("request_id") not in done]
print(json.dumps(dict(open_legs=len(open_legs(rows)),pending_orders=len(pending_orders(rows)),uncertain_requests=len(uncertain))))
'''
    env=dict(os.environ,PYTHONPATH=str(repo/'backend'),PYTHONDONTWRITEBYTECODE='1')
    p=subprocess.run([sys.executable,'-B','-c',code],cwd=repo,env=env,capture_output=True,text=True)
    if p.returncode:raise ValueError('LOCAL_LEDGER_CHECK_FAILED')
    result=json.loads(p.stdout)
    if any(result.values()):raise ValueError('OPEN_OR_UNCERTAIN_SANDBOX_STATE:'+json.dumps(result))
    return result

def no_execution_workers(repo):
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit() or int(proc.name)==os.getpid():continue
        try:
            args=(proc/'cmdline').read_bytes().decode().split('\0')
            if (proc/'cwd').resolve()!=repo:continue
            if any(any(tag in arg for tag in ('hilega_upstox_sandbox_basket','hilega_upstox_sandbox_live_worker',
                    'hilega_production_source_worker','market_lab.worker')) for arg in args):
                raise ValueError('EXECUTION_WORKER_ACTIVE_PID:'+proc.name)
        except (OSError,UnicodeError):continue

def patch_worker(source):
    tree=ast.parse(source)
    expected={'HILEGA_DIRECTIONAL_STRATEGY_ID','WMA_GAP_V2_ID','ALIGNMENT_V2_ID'}
    matches=[]
    for node in ast.walk(tree):
        if not isinstance(node,ast.If) or not isinstance(node.test,ast.Compare):continue
        test=node.test
        if (not isinstance(test.left,ast.Name) or test.left.id!='selected'
                or len(test.comparators)!=1 or not isinstance(test.comparators[0],ast.Set)):continue
        names={x.id for x in test.comparators[0].elts if isinstance(x,ast.Name)}
        if names==expected:matches.append(node)
    if len(matches)!=1:raise ValueError('DIRECTIONAL_WORKER_BRANCH_CHANGED')
    node=matches[0];lines=source.splitlines(True)
    start=node.body[0].lineno-1;end=node.body[-1].end_lineno
    body=''.join(lines[start:end])
    pattern=r'(?m)^([ \t]*)if not in_session\(now\):time\.sleep\(5\);continue[ \t]*$'
    if len(re.findall(pattern,body))!=1:raise ValueError('WORKER_SESSION_GUARD_CHANGED: current source review required')
    def replacement(m):
        i=m.group(1)
        return (i+'if not in_session(now):\n'+i+'    from .hilega_three_minute_v1.worker_close import process_after_close\n'
            +i+'    process_after_close(now,selected,ALIGNMENT_V2_ID,coord,process_isolated_tick)\n'
            +i+'    time.sleep(5);continue')
    updated=''.join(lines[:start])+re.sub(pattern,replacement,body)+''.join(lines[end:])
    compile(updated,'live_shadow_worker_v1.py','exec')
    if updated.count('process_after_close(now,selected,ALIGNMENT_V2_ID,coord,process_isolated_tick)')!=1:
        raise ValueError('INVALID_CLOSE_DISPATCH_PATCH')
    return updated

def preflight(args):
    repo=args.repo.resolve();stage=args.stage.resolve();package=repo/'hilega-3m-two-of-three-v2'
    spec=importlib.util.spec_from_file_location('hilega_staging_check',package/'stage.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    result=module.check(repo)
    if result['status']!='SOURCE_MATCH':raise ValueError('SOURCE_CHANGED:'+json.dumps(result['mismatches']))
    report=json.loads(args.validation.read_text())
    if report.get('status')!='OFFLINE_VALIDATION_PASS' or report.get('strategy_version')!=VERSION:
        raise ValueError('OFFLINE_VALIDATION_REQUIRED')
    passed={c['name'] for c in report.get('checks',[]) if c.get('status')=='PASS'}
    if not {'candidate_tests','frontend_build','saved_candle_comparison'}<=passed:raise ValueError('VALIDATION_CHECKS_MISSING')
    receipt=json.loads((stage/'stage-receipt.json').read_text())
    if receipt.get('repo')!=str(repo) or receipt.get('strategy_version')!=VERSION:raise ValueError('STAGE_IDENTITY_MISMATCH')
    manifest=json.loads((package/'manifest.json').read_text())
    for relative,digest in manifest['candidate_sha256'].items():
        if sha(stage/relative)!=digest:raise ValueError('VALIDATED_STAGE_CHANGED:'+relative)
    if not (stage/'frontend/dist/index.html').is_file():raise ValueError('VALIDATED_FRONTEND_DIST_MISSING')
    env_file=repo/'.env'
    config={}
    for line in env_file.read_text().splitlines():
        key,sep,value=line.partition('=')
        if sep and key.strip() in ('LIVE_SHADOW_STRATEGY','HILEGA_PRODUCTION_WORKSPACE_MODE'):
            config[key.strip()]=value.strip().strip('"\'')
    if config.get('LIVE_SHADOW_STRATEGY')!='HILEGA_V2_ALIGNMENT_DUAL_EXIT':raise ValueError('ENV_STRATEGY_CHANGED')
    if config.get('HILEGA_PRODUCTION_WORKSPACE_MODE')!='SIMULATION_ONLY':raise ValueError('SIMULATION_WORKSPACE_REQUIRED')
    units={unit:service_state(unit) for unit in RESTART_ORDER}
    for unit in ('hilega-api.service','hilega-observation-analytics.service'):
        if units[unit].get('ActiveState')!='active':raise ValueError('EXPECTED_ACTIVE_SERVICE_MISSING:'+unit)
    active=[u for u in RESTART_ORDER if units[u].get('ActiveState')=='active']
    for unit in active:
        cwd=units[unit].get('WorkingDirectory','')
        if not cwd or Path(cwd).resolve()!=repo:raise ValueError('SERVICE_REPOSITORY_MISMATCH:'+unit)
    protected={u:service_state(u) for u in PROTECTED}
    if any(s.get('ActiveState')=='active' for s in protected.values()):raise ValueError('EXECUTION_SERVICE_ACTIVE')
    no_execution_workers(repo);ledger=sandbox_clear(repo);api=api_status(args.api_url)
    worker_source=(repo/WORKER).read_text();worker_new=patch_worker(worker_source)
    strategy_updates={relative:(stage/relative).read_bytes() for relative in manifest['candidate_sha256'] if relative.startswith('backend/')}
    strategy_updates[WORKER]=worker_new.encode()
    strategy_updates[HELPER]=(HERE/'files'/HELPER).read_bytes()
    companion=companion_bindings.prepare(repo,strategy_updates)
    return dict(repo=repo,stage=stage,manifest=manifest,active=active,units=units,protected=protected,
        strategy_updates=strategy_updates,companion=companion,
        ledger=ledger,old_version=api.get('strategy_version'),worker_source=worker_source,worker_new=worker_new,
        worker_old_sha256=sha(repo/WORKER),env_sha256=sha(env_file))

def stop_units(units):
    for unit in reversed(units):systemctl('stop',unit)
    for unit in units:
        state=service_state(unit)
        if state.get('ActiveState') not in ('inactive','failed') or state.get('MainPID') not in ('0',None):
            raise ValueError('SERVICE_NOT_STOPPED:'+unit)

def start_units(units):
    for unit in units:systemctl('start',unit)

def restore_files(backup,receipt):
    repo=Path(receipt['repo'])
    for relative,digest in receipt['files_before'].items():
        if digest is not None and sha(backup/'files'/relative)!=digest:
            raise ValueError('BACKUP_SOURCE_CHANGED:'+relative)
    for relative,digest in receipt.get('frontend_before_sha256',{}).items():
        if sha(backup/'frontend-dist'/relative)!=digest:raise ValueError('BACKUP_FRONTEND_CHANGED:'+relative)
    for relative,old in receipt['files_before'].items():
        target=repo/relative
        if old is None:
            if target.exists():target.unlink()
        else:
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(backup/'files'/relative,target)
    dist=repo/'frontend/dist'
    if dist.exists():shutil.rmtree(dist)
    if receipt['frontend_dist_existed']:shutil.copytree(backup/'frontend-dist',dist)
    for relative in receipt['files_before']:
        cache=(repo/relative).parent/'__pycache__'
        if cache.is_dir():
            for cached in cache.glob(Path(relative).stem+'.*.pyc'):cached.unlink()

def tail_bootstrap(repo,started):
    path=repo/'data/live-observation/hilega-directional-v1/step-audit.jsonl'
    if not path.is_file():return False
    with path.open('rb') as stream:
        size=path.stat().st_size;offset=max(0,size-4*1024*1024);stream.seek(offset)
        if offset:stream.readline()
        lines=stream.read().decode(errors='replace').splitlines()
    for line in reversed(lines):
        try:row=json.loads(line)
        except ValueError:continue
        p=row.get('payload') or {}
        if row.get('stage')=='DIRECTIONAL_LIVE_BOOTSTRAP' and row.get('status')=='PASS' and p.get('strategy_version')==VERSION:
            stamp=datetime.fromisoformat(row['event_time'])
            if stamp>=started:return True
    return False

def verify_running(args,context,started):
    deadline=time.monotonic()+args.startup_timeout
    while time.monotonic()<deadline:
        states={u:service_state(u) for u in context['active']}
        failed=[unit for unit,state in states.items() if state.get('ActiveState')=='failed']
        if failed:raise ValueError('SERVICE_START_FAILED:'+','.join(failed))
        try:
            api=api_status(args.api_url)
            correct=api.get('strategy_version')==VERSION
            if all(s.get('ActiveState')=='active' for s in states.values()) and correct and tail_bootstrap(context['repo'],started):
                health=context['repo']/'data/live-observation/shadow-worker-health.json'
                h=json.loads(health.read_text()) if health.is_file() else {}
                stamp=datetime.fromisoformat(h['timestamp']) if h.get('timestamp') else None
                if stamp and stamp>=started and (h.get('components') or {}).get('hilega')=='OK':return states
        except (OSError,ValueError,KeyError):pass
        print('Waiting for API version and fresh 3m worker bootstrap...',flush=True)
        time.sleep(5)
    raise ValueError('FRESH_3M_BOOTSTRAP_NOT_CONFIRMED_WITHIN_TIMEOUT')

def apply(args):
    context=preflight(args);repo=context['repo'];stage=context['stage']
    print('Source, validated stage, service scope and local ledgers passed.',flush=True)
    with tempfile.TemporaryDirectory(prefix='hilega-3m-rollout-test-') as temporary:
        test_stage=Path(temporary)
        shutil.copytree(repo/'backend',test_stage/'backend',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        for relative,raw in context['strategy_updates'].items():
            target=test_stage/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
        test_package,test_service,companion_checks=companion_bindings.preview(context,test_stage)
        env=dict(os.environ,PYTHONPATH=str(test_stage/'backend')+os.pathsep+str(HERE),PYTHONDONTWRITEBYTECODE='1',
            HILEGA_ROLLOUT_TEST_REPO=str(test_stage),HILEGA_ROLLOUT_TEST_PACKAGE=str(test_package))
        result=subprocess.run([sys.executable,'-B','-m','pytest','-q','-p','no:cacheprovider',str(HERE/'tests')],cwd=repo,env=env)
        if result.returncode:raise ValueError('SESSION_CLOSE_WORKER_TESTS_FAILED_NO_INSTALLATION')
        tested_hashes={relative:hashlib.sha256(raw).hexdigest() for relative,raw in context['companion']['files'].items()}
    print('Candidate lifecycle package and service checks passed; integrity protections retained.',flush=True)
    if not args.apply:
        print(json.dumps(dict(status='ROLLOUT_CHECK_PASS',strategy_version=VERSION,services=context['active'],
            scope='LIVE_DATA_OBSERVATION_ONLY',installed_files_modified=False),indent=2));return
    # Recheck after tests, before any service or installed source changes.
    context=preflight(args)
    if tested_hashes!={relative:hashlib.sha256(raw).hexdigest() for relative,raw in context['companion']['files'].items()}:
        raise ValueError('COMPANION_CANDIDATE_CHANGED_AFTER_TESTS')
    started=datetime.now(timezone.utc)
    backup=repo/'data/deployments'/('hilega-3m-'+started.strftime('%Y%m%dT%H%M%S%fZ'))
    backup.mkdir(parents=True,exist_ok=False)
    sources={relative:stage/relative for relative in context['manifest']['candidate_sha256']}
    worker_candidate=backup/'candidate-live-shadow-worker.py';worker_candidate.write_text(context['worker_new'])
    sources[WORKER]=worker_candidate;sources[HELPER]=HERE/'files'/HELPER
    for index,(relative,raw) in enumerate(sorted(context['companion']['files'].items())):
        candidate=backup/('candidate-companion-'+str(index));candidate.write_bytes(raw)
        sources[relative]=candidate
    receipt=dict(status='PREPARED',repo=str(repo),strategy_version=VERSION,started_at=started.isoformat(),
        active_services=context['active'],protected_service_states=context['protected'],files_before={},
        installed_sha256={relative:sha(path) for relative,path in sources.items()},
        frontend_dist_existed=(repo/'frontend/dist').exists(),env_sha256=context['env_sha256'],
        frontend_before_sha256={},frontend_installed_sha256={p.relative_to(stage/'frontend/dist').as_posix():sha(p)
            for p in (stage/'frontend/dist').rglob('*') if p.is_file()},
        broker_execution_enabled_by_rollout=False,databases_edited_by_installer=False,
        companion_compatibility_checks=companion_checks,
        companion_runtime_binding={key:context['companion'][key] for key in (
            'changed_runtime','added_runtime','unchanged_runtime_count','old_runtime_count','new_runtime_count')},
        note='Normal service startup/recovery may update application state and journals.')
    for relative in sources:
        path=repo/relative
        if path.exists():
            if path.is_symlink() or not path.is_file():raise ValueError('REGULAR_SOURCE_FILE_REQUIRED:'+relative)
            receipt['files_before'][relative]=sha(path)
            copy=backup/'files'/relative;copy.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,copy)
        else:receipt['files_before'][relative]=None
    if receipt['frontend_dist_existed']:
        if (repo/'frontend/dist').is_symlink():raise ValueError('REGULAR_FRONTEND_DIST_REQUIRED')
        shutil.copytree(repo/'frontend/dist',backup/'frontend-dist')
        receipt['frontend_before_sha256']={p.relative_to(backup/'frontend-dist').as_posix():sha(p)
            for p in (backup/'frontend-dist').rglob('*') if p.is_file()}
    write_json(backup/'receipt.json',receipt)
    touched=False
    try:
        print('Backup:',backup,flush=True)
        stop_units(context['active'])
        sandbox_clear(repo);no_execution_workers(repo)
        companion_bindings.old_check(repo)
        for relative,old in receipt['files_before'].items():
            current=repo/relative
            actual=sha(current) if current.is_file() else None
            if actual!=old:raise ValueError('SOURCE_CHANGED_DURING_STOP:'+relative)
        touched=True
        for relative,source in sources.items():
            target=repo/relative;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(source,target)
        dist=repo/'frontend/dist'
        if dist.exists():shutil.rmtree(dist)
        shutil.copytree(stage/'frontend/dist',dist)
        # Do not reuse timestamp-valid bytecode from an older source copy.
        for relative in sources:
            parent=(repo/relative).parent/'__pycache__'
            if parent.is_dir():
                for cached in parent.glob(Path(relative).stem+'.*.pyc'):cached.unlink()
        companion_bindings.check_candidate(repo,repo/companion_bindings.PACKAGE,
            repo/companion_bindings.SERVICE,context['companion']['service_args'])
        start_units(context['active'])
        states=verify_running(args,context,started)
        no_execution_workers(repo);sandbox_clear(repo)
        if sha(repo/'.env')!=context['env_sha256']:raise ValueError('ENV_CHANGED_DURING_ROLLOUT')
        for unit in PROTECTED:
            if service_state(unit).get('ActiveState')!=context['protected'][unit].get('ActiveState'):
                raise ValueError('PROTECTED_EXECUTION_SERVICE_STATE_CHANGED:'+unit)
        receipt.update(status='LIVE_OBSERVATION_DEPLOYED',service_states=states,
            fresh_worker_bootstrap_verified=True,api_strategy_version_verified=True,
            backup=str(backup),completed_at=datetime.now(timezone.utc).isoformat())
        write_json(backup/'receipt.json',receipt)
        print(json.dumps(receipt,indent=2));return
    except Exception as exc:
        receipt.update(status='ROLLOUT_FAILED',error=str(exc))
        receipt['service_states_at_failure']={unit:service_state(unit) for unit in context['active']}
        try:
            stop_units(context['active'])
            if touched:restore_files(backup,receipt)
            start_units(context['active'])
            receipt['status']='ROLLED_BACK_AFTER_FAILURE'
        except Exception as rollback_error:
            receipt['status']='ROLLBACK_REQUIRES_ATTENTION';receipt['rollback_error']=str(rollback_error)
        write_json(backup/'receipt.json',receipt)
        print(json.dumps(receipt,indent=2));raise

def rollback(args):
    backup=args.rollback.resolve();receipt=json.loads((backup/'receipt.json').read_text())
    repo=Path(receipt['repo']).resolve()
    if repo!=args.repo.resolve():raise ValueError('ROLLBACK_REPOSITORY_MISMATCH')
    if receipt.get('status')!='LIVE_OBSERVATION_DEPLOYED':raise ValueError('SUCCESSFUL_DEPLOYMENT_RECEIPT_REQUIRED')
    sandbox_clear(repo);no_execution_workers(repo)
    for relative,digest in receipt['installed_sha256'].items():
        if not (repo/relative).is_file() or sha(repo/relative)!=digest:raise ValueError('NEWER_SOURCE_PRESENT:'+relative)
    for relative,digest in receipt.get('frontend_installed_sha256',{}).items():
        if not (repo/'frontend/dist'/relative).is_file() or sha(repo/'frontend/dist'/relative)!=digest:
            raise ValueError('NEWER_FRONTEND_PRESENT:'+relative)
    stop_units(receipt['active_services'])
    restore_files(backup,receipt)
    for relative in receipt['files_before']:
        parent=(repo/relative).parent/'__pycache__'
        if parent.is_dir():
            for p in parent.glob(Path(relative).stem+'.*.pyc'):p.unlink()
    start_units(receipt['active_services'])
    receipt.update(status='SOURCE_ROLLBACK_COMPLETED',rollback_at=datetime.now(timezone.utc).isoformat())
    write_json(backup/'receipt.json',receipt)
    print(json.dumps(dict(status=receipt['status'],backup=str(backup),note='Audits and databases retained; inspect restarted worker health.'),indent=2))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo',type=Path,default=Path.cwd())
    p.add_argument('--stage',type=Path,default=Path('/tmp/hilega-3m-two-of-three-stage-v2'))
    p.add_argument('--validation',type=Path,default=Path('/tmp/hilega-3m-two-of-three-validation-v2/validation.json'))
    p.add_argument('--api-url',default='http://127.0.0.1:8123')
    p.add_argument('--startup-timeout',type=int,default=300)
    group=p.add_mutually_exclusive_group(required=True)
    group.add_argument('--check',action='store_true');group.add_argument('--apply',action='store_true')
    group.add_argument('--rollback',type=Path)
    args=p.parse_args()
    if not 30<=args.startup_timeout<=900:p.error('startup-timeout must be 30..900 seconds')
    lockfile=Path(tempfile.gettempdir())/('hilega-3m-rollout-'+hashlib.sha256(str(args.repo.resolve()).encode()).hexdigest()[:16]+'.lock')
    with lockfile.open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('ANOTHER_ROLLOUT_IS_RUNNING')
        if args.rollback:rollback(args)
        else:apply(args)

if __name__=='__main__':main()
