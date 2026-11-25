"""Prepare and install the reviewed warmup repair; deployment is after-close only."""
import argparse
from datetime import datetime, time
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from urllib.request import urlopen
from zoneinfo import ZoneInfo
import companion_bindings as bindings
import rollout_safety as safety

HERE = Path(__file__).resolve().parent
IST = ZoneInfo('Asia/Kolkata')
FRESH_ROOT = Path('data/historical-evidence/hilega-3m-warmup-verified-v1')
AUDIT = Path('data/live-observation/hilega-directional-v1/step-audit.jsonl')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_json(path):
    return json.loads(path.read_text())


def verify_package():
    manifest = read_json(HERE/'manifest.json')
    for relative, expected in manifest['candidate_sha256'].items():
        if digest(bindings.regular(HERE/'files'/relative)) != expected:
            raise ValueError('CANDIDATE_SOURCE_CHANGED:' + relative)
    for relative, expected in manifest['tool_sha256'].items():
        if digest(bindings.regular(HERE/relative)) != expected:
            raise ValueError('REPAIR_TOOL_CHANGED:' + relative)
    return manifest


def preflight(args, manifest):
    repo = args.repo.resolve()
    updates = {relative: bindings.regular(HERE/'files'/relative)
               for relative in manifest['candidate_sha256'] if relative.startswith('backend/')}
    for relative in manifest['candidate_sha256']:
        path = repo/relative
        expected = manifest['source_before'].get(relative)
        if expected is None:
            if path.exists() or path.is_symlink():
                raise ValueError('NEW_SOURCE_ALREADY_PRESENT:' + relative)
        elif digest(bindings.regular(path)) != expected:
            raise ValueError('CURRENT_VM_SOURCE_MISMATCH:' + relative)
    env = {}
    for line in (repo/'.env').read_text().splitlines():
        key, sep, value = line.partition('=')
        if sep and key.strip() in {'LIVE_SHADOW_STRATEGY','HILEGA_PRODUCTION_WORKSPACE_MODE'}:
            env[key.strip()] = value.strip().strip('"\'')
    if env != {'LIVE_SHADOW_STRATEGY':'HILEGA_V2_ALIGNMENT_DUAL_EXIT',
               'HILEGA_PRODUCTION_WORKSPACE_MODE':'SIMULATION_ONLY'}:
        raise ValueError('EXPECTED_OBSERVATION_CONFIGURATION_REQUIRED')
    api = safety.api_status(args.api_url)
    if api.get('strategy_version') != manifest['old_version']:
        raise ValueError('EXPECTED_INSTALLED_STRATEGY_VERSION_REQUIRED')
    units = {u:safety.service_state(u) for u in safety.RESTART_ORDER}
    active = [u for u in safety.RESTART_ORDER if units[u].get('ActiveState') == 'active']
    if not {'hilega-api.service','hilega-observation-analytics.service',
            'hilega-lifecycle-reference.service'} <= set(active):
        raise ValueError('EXPECTED_OBSERVATION_SERVICES_NOT_ACTIVE')
    for u in active:
        if Path(units[u].get('WorkingDirectory','')).resolve() != repo:
            raise ValueError('SERVICE_WORKING_DIRECTORY_CHANGED:' + u)
    protected = {u:safety.service_state(u) for u in safety.PROTECTED}
    if any(s.get('ActiveState') not in {'inactive','failed'} for s in protected.values()):
        raise ValueError('EXECUTION_SERVICE_NOT_INACTIVE')
    safety.no_execution_workers(repo)
    ledger = safety.sandbox_clear(repo)
    companion = bindings.prepare(repo, updates)
    return dict(repo=repo, active=active, units=units, protected=protected, ledger=ledger,
                strategy_updates=updates, companion=companion,
                env_sha256=safety.sha(repo/'.env'))


def candidate(args, context):
    with tempfile.TemporaryDirectory(prefix='hilega-warmup-candidate-') as folder:
        stage = Path(folder)
        shutil.copytree(context['repo']/'backend', stage/'backend',
                        ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        for relative, raw in context['strategy_updates'].items():
            path = stage/relative; path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(raw)
        package, service, checks = bindings.preview(context, stage)
        env = dict(os.environ, PYTHONPATH=str(stage/'backend')+os.pathsep+str(HERE),
                   PYTHONDONTWRITEBYTECODE='1', HILEGA_CANDLE_EVIDENCE_ENABLED='0',
                   HILEGA_ROLLOUT_TEST_REPO=str(stage), HILEGA_ROLLOUT_TEST_PACKAGE=str(package))
        run = subprocess.run([sys.executable,'-B','-m','pytest','-q','-p','no:cacheprovider',str(HERE/'tests')],
                             cwd=context['repo'],env=env)
        if run.returncode:
            raise ValueError('CANDIDATE_TESTS_FAILED_NO_INSTALLATION')
        if args.prepare:
            run = subprocess.run([sys.executable,'-u','-B',str(HERE/'research.py'),
                '--repo',str(context['repo']),'--output',str(args.work.resolve()),
                '--day',datetime.now(IST).date().isoformat()],cwd=context['repo'],env=env)
            if run.returncode:
                raise ValueError('CANDLE_PREPARATION_OR_RESEARCH_FAILED_NO_INSTALLATION')
        return checks


def cutoff_record(repo, day, version, *, started=None):
    if not (repo/AUDIT).is_file():
        return None
    found = None
    with (repo/AUDIT).open() as stream:
        for line in stream:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            p = row.get('payload') or {}
            if (row.get('stage') == 'DIRECTIONAL_SESSION_CUTOFF'
                    and row.get('status') == 'PROCESSED'
                    and p.get('strategy_version') == version
                    and p.get('session_date') == day
                    and p.get('trade_owner_after') == 'NONE'):
                if started is None or datetime.fromisoformat(row['event_time']) >= started:
                    found = row
    return found


def require_flat_after_close(args, context, version):
    now = datetime.now(IST); day = now.date().isoformat()
    if now.time() < time(15,35):
        raise ValueError('INSTALL_AFTER_1535_IST_ONLY; preparation is available now')
    api = safety.api_status(args.api_url)
    current = api.get('current') or {}
    if current.get('session_date') != day or current.get('trade_owner') != 'NONE':
        raise ValueError('CURRENT_SESSION_UNDERLYING_NOT_VERIFIED_FLAT')
    health = api.get('worker_component_health') or {}
    stamp = datetime.fromisoformat(health['timestamp']) if health.get('timestamp') else None
    # Worker may stop refreshing once cutoff completes; cutoff evidence below is
    # authoritative for that session, not a fabricated after-hours heartbeat.
    if stamp is None or stamp.astimezone(IST).date().isoformat() != day:
        raise ValueError('CURRENT_SESSION_WORKER_HEALTH_MISSING')
    if not cutoff_record(context['repo'], day, version):
        raise ValueError('CURRENT_SESSION_CUTOFF_NOT_CONFIRMED')
    with urlopen(args.api_url.rstrip('/')+'/api/live-shadow/hilega-directional/trade-dashboard',timeout=30) as response:
        dashboard = json.load(response)
    unsettled = [t for t in dashboard.get('trades',[]) if
        str(t.get('signal_boundary') or t.get('signal_bar') or '')[:10] == day
        and t.get('status') not in {'CLOSED','MANUAL_RELEASED'}]
    if unsettled:
        raise ValueError('CURRENT_SESSION_OPTION_LIFECYCLE_REQUIRES_RECONCILIATION')
    safety.sandbox_clear(context['repo']); safety.no_execution_workers(context['repo'])


def prepared(args, manifest, context):
    path = args.work.resolve()/'preparation.json'
    report = read_json(path)
    day = datetime.now(IST).date().isoformat()
    if (report.get('status') != 'VERIFIED_WARMUP_PREPARED'
            or report.get('repo') != str(context['repo'])
            or report.get('session_date') != day
            or report.get('strategy_version') != manifest['strategy_version']):
        raise ValueError('TODAYS_PREPARATION_REQUIRED')
    if report.get('candidate_sha256') != manifest['candidate_sha256'] or report.get('vm_tests_passed') is not True:
        raise ValueError('PREPARATION_SOURCE_OR_TEST_RECEIPT_INVALID')
    for name, expected in report['prepared_cache_sha256'].items():
        if Path(name).name != name or not name.endswith('.json'):
            raise ValueError('PREPARED_CACHE_NAME_INVALID')
        if digest(bindings.regular(args.work.resolve()/'verified-candles'/name)) != expected:
            raise ValueError('PREPARED_CACHE_CHANGED:' + name)
    return report


def install(args, manifest, context):
    report = prepared(args,manifest,context)
    require_flat_after_close(args,context,manifest['old_version'])
    checks = candidate(args,context)
    context = preflight(args,manifest)
    require_flat_after_close(args,context,manifest['old_version'])
    started = datetime.now(IST)
    backup = context['repo']/'data/deployments'/('hilega-warmup-'+started.strftime('%Y%m%dT%H%M%S%f'))
    backup.mkdir(parents=True,exist_ok=False)
    updates = {r:bindings.regular(HERE/'files'/r) for r in manifest['candidate_sha256']}
    receipt = dict(status='PREPARED',repo=str(context['repo']),started_at=started.isoformat(),
        strategy_version=manifest['strategy_version'],active_services=context['active'],
        files_before={}, installed_sha256={r:digest(raw) for r,raw in updates.items()},
        cache_files_added=[],companion_checks=checks,broker_execution_enabled=False,
        databases_edited_by_installer=False,frontend_modified=False)
    for relative in updates:
        path = context['repo']/relative
        receipt['files_before'][relative] = safety.sha(path) if path.is_file() else None
        if path.is_file():
            dest=backup/'files'/relative;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,dest)
    safety.write_json(backup/'receipt.json',receipt)
    stopped=False; touched=False
    try:
        print('Backup:',backup,flush=True)
        # This flag precedes the first stop so even partial stop failure restarts
        # the originally active services during error recovery.
        stopped=True
        safety.stop_units(context['active'])
        bindings.old_check(context['repo'])
        safety.sandbox_clear(context['repo']); safety.no_execution_workers(context['repo'])
        # API is now stopped; verify final journal evidence and all source leases.
        if not cutoff_record(context['repo'],started.date().isoformat(),manifest['old_version']):
            raise ValueError('FINAL_CUTOFF_RECHECK_FAILED')
        if safety.sha(context['repo']/'.env') != context['env_sha256']:
            raise ValueError('ENV_CHANGED_DURING_INSTALL')
        for relative, before in receipt['files_before'].items():
            path=context['repo']/relative
            current=safety.sha(path) if path.is_file() else None
            if current!=before:
                raise ValueError('SOURCE_CHANGED_DURING_STOP:'+relative)
        cache=context['repo']/FRESH_ROOT
        if cache.is_symlink() or any(p.is_symlink() for p in cache.absolute().parents):
            raise ValueError('VERIFIED_CACHE_SYMLINK_NOT_ALLOWED')
        cache.mkdir(parents=True,exist_ok=True)
        for name, expected in report['prepared_cache_sha256'].items():
            target=cache/name
            if target.exists():
                if digest(bindings.regular(target))!=expected:
                    raise ValueError('VERIFIED_CACHE_CONFLICT:'+name)
            else:
                raw=bindings.regular(args.work.resolve()/'verified-candles'/name)
                if digest(raw)!=expected:raise ValueError('PREPARED_CACHE_CHANGED:'+name)
                # Existing verified files are never replaced by the installer.
                with tempfile.NamedTemporaryFile('wb',dir=cache,delete=False) as f:
                    temporary=Path(f.name);f.write(raw);f.flush();os.fsync(f.fileno())
                try:
                    os.link(temporary,target)
                finally:
                    temporary.unlink()
                fd=os.open(cache,os.O_RDONLY)
                try:os.fsync(fd)
                finally:os.close(fd)
                receipt['cache_files_added'].append(str(target.relative_to(context['repo'])))
        touched=True
        for relative,raw in updates.items():
            path=context['repo']/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
        invalidate(context['repo'],updates)
        bindings.check_candidate(context['repo'],context['repo']/bindings.PACKAGE,
            context['repo']/bindings.SERVICE,context['companion']['service_args'])
        safety.start_units(context['active'])
        safety.VERSION=manifest['strategy_version']
        states=safety.verify_running(args,context,started)
        bootstrap=None
        with (context['repo']/AUDIT).open() as stream:
            for line in stream:
                try:row=json.loads(line)
                except ValueError:continue
                payload=row.get('payload') or {}
                if (row.get('stage')=='DIRECTIONAL_LIVE_BOOTSTRAP' and row.get('status')=='PASS'
                        and payload.get('strategy_version')==manifest['strategy_version']
                        and datetime.fromisoformat(row['event_time'])>=started):
                    bootstrap=payload
        coverage=(bootstrap or {}).get('warmup_coverage') or {}
        if (coverage.get('freshness_verified') is not True
                or coverage.get('warmup_last')!=report['coverage']['expected_last_session']):
            raise ValueError('NEW_BOOTSTRAP_WARMUP_FRESHNESS_NOT_VERIFIED')
        if not cutoff_record(context['repo'],started.date().isoformat(),manifest['strategy_version'],started=started):
            # Health can become ready just before the cutoff audit is appended.
            deadline=__import__('time').monotonic()+30
            while __import__('time').monotonic()<deadline:
                if cutoff_record(context['repo'],started.date().isoformat(),manifest['strategy_version'],started=started):break
                __import__('time').sleep(2)
            else:raise ValueError('NEW_POLICY_AFTER_CLOSE_FLAT_STATE_NOT_VERIFIED')
        require_flat_after_close(args,context,manifest['strategy_version'])
        if safety.sha(context['repo']/'.env')!=context['env_sha256']:
            raise ValueError('ENV_CHANGED_DURING_INSTALL')
        for unit,state in context['protected'].items():
            if safety.service_state(unit).get('ActiveState')!=state.get('ActiveState'):
                raise ValueError('PROTECTED_SERVICE_STATE_CHANGED:'+unit)
        receipt.update(status='WARMUP_REPAIR_DEPLOYED',backup=str(backup),service_states=states,
                       completed_at=datetime.now(IST).isoformat(),coverage=coverage)
        safety.write_json(backup/'receipt.json',receipt)
        print(json.dumps(receipt,indent=2));return
    except Exception as exc:
        receipt.update(status='INSTALL_FAILED',error=str(exc))
        try:
            if stopped:safety.stop_units(context['active'])
            if touched:restore(context['repo'],backup,receipt)
            if stopped:safety.start_units(context['active'])
            receipt['status']='SOURCE_ROLLED_BACK_AFTER_FAILURE'
        except Exception as error:
            receipt.update(status='ROLLBACK_REQUIRES_ATTENTION',rollback_error=str(error))
        receipt['note']='Validated dedicated cache additions retained; original caches and journals were not rewritten.'
        safety.write_json(backup/'receipt.json',receipt)
        print(json.dumps(receipt,indent=2));raise


def invalidate(repo,relatives):
    for relative in relatives:
        for path in (repo/relative).parent.glob('__pycache__/'+Path(relative).stem+'.*.pyc'):
            path.unlink()


def restore(repo,backup,receipt):
    for relative,expected in receipt['files_before'].items():
        if expected is not None and safety.sha(backup/'files'/relative)!=expected:
            raise ValueError('BACKUP_SOURCE_CHANGED:'+relative)
    for relative,expected in receipt['files_before'].items():
        path=repo/relative
        if expected is None:
            if path.exists():path.unlink()
        else:shutil.copy2(backup/'files'/relative,path)
    invalidate(repo,receipt['files_before'])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo',type=Path,default=Path.cwd())
    p.add_argument('--work',type=Path,default=Path('/tmp/hilega-warmup-repair-v1'))
    p.add_argument('--api-url',default='http://127.0.0.1:8123')
    p.add_argument('--startup-timeout',type=int,default=600)
    group=p.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare',action='store_true')
    group.add_argument('--apply',action='store_true')
    group.add_argument('--rollback',type=Path)
    args=p.parse_args()
    if not 30<=args.startup_timeout<=900:p.error('startup-timeout must be 30..900')
    args.repo=args.repo.resolve();args.work=args.work.resolve()
    # Share the old rollout lock, preventing concurrent cross-version installers.
    lock=Path(tempfile.gettempdir())/('hilega-3m-rollout-'+digest(str(args.repo).encode())[:16]+'.lock')
    with lock.open('a') as stream:
        fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        manifest=verify_package()
        if args.rollback:
            backup=args.rollback.resolve();receipt=read_json(backup/'receipt.json')
            if receipt.get('status')!='WARMUP_REPAIR_DEPLOYED' or receipt.get('repo')!=str(args.repo):
                raise ValueError('SUCCESSFUL_MATCHING_BACKUP_REQUIRED')
            active=receipt['active_services']
            require_flat_after_close(args,dict(repo=args.repo),manifest['strategy_version'])
            for relative,expected in receipt['installed_sha256'].items():
                if safety.sha(args.repo/relative)!=expected:raise ValueError('NEWER_SOURCE_PRESENT:'+relative)
            bindings.check_candidate(args.repo,args.repo/bindings.PACKAGE,args.repo/bindings.SERVICE,
                                     bindings.current_service_args(args.repo))
            safety.stop_units(active)
            try:
                restore(args.repo,backup,receipt)
            finally:safety.start_units(active)
            receipt['status']='SOURCE_ROLLBACK_COMPLETED';safety.write_json(backup/'receipt.json',receipt)
            print(json.dumps(receipt,indent=2));return
        context=preflight(args,manifest)
        if args.apply:
            install(args,manifest,context)
        else:
            checks=candidate(args,context)
            report=read_json(args.work/'preparation.json')
            report.update(candidate_sha256=manifest['candidate_sha256'],vm_tests_passed=True,
                          companion_checks=checks)
            safety.write_json(args.work/'preparation.json',report)
            print(json.dumps(dict(status='WARMUP_REPAIR_PREPARED',work=str(args.work),
                strategy_version=manifest['strategy_version'],vm_tests_passed=True,
                installed_files_modified=False,services_restarted=False),indent=2))


if __name__=='__main__':
    main()
