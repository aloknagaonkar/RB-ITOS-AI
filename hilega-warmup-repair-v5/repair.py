"""Prepare and install the reviewed warmup repair; deployment is after-close only."""
import argparse
from datetime import datetime, time, timedelta
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
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
COLLECTOR_SOURCES = {
    'backend/market_lab/runtime.py': '6ee08f8c5c2108165486f9af123d8d7e9518de2bae03863f38735b580d7280f2',
    'backend/market_lab/worker.py': '979a356ff6ad980cbdc38d378a31b9ce91e858f277f98bac1fc8ccd04a96c20b',
    'backend/market_lab/storage.py': '01a4b14a56c0564f9b362bfa25ac2401740ddc4f411d57c3b310e2f346dd4784',
}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_json(path):
    return json.loads(path.read_text())


def process_snapshot(pid):
    proc = Path('/proc', pid)
    return dict(args=[a for a in (proc/'cmdline').read_bytes().decode().split('\0') if a],
                cwd=str((proc/'cwd').resolve()), executable=(proc/'exe').resolve().name)


def collector_identity(repo, state):
    """Approve only the exact reviewed data-collector entrypoint and source."""
    pid = state.get('MainPID', '0')
    if (state.get('ActiveState') != 'active' or state.get('SubState') != 'running'
            or not str(pid).isdigit() or pid == '0'):
        raise ValueError('COLLECTOR_PROCESS_NOT_RUNNING')
    snapshot = process_snapshot(pid)
    args = snapshot['args']
    if (snapshot['cwd'] != str(repo.resolve())
            or not snapshot['executable'].startswith('python')
            or args.count('-m') != 1):
        raise ValueError('COLLECTOR_ENTRYPOINT_NOT_REVIEWED')
    position = args.index('-m')
    if (position < 1 or not set(args[1:position]) <= {'-u','-B','-E','-s'}
            or args[position+1:] != ['market_lab.runtime','worker']):
        raise ValueError('COLLECTOR_ENTRYPOINT_NOT_REVIEWED')
    for relative, expected in COLLECTOR_SOURCES.items():
        if digest(bindings.regular(repo/relative)) != expected:
            raise ValueError('COLLECTOR_SOURCE_NOT_REVIEWED:' + relative)
    return dict(pid=pid, cwd=snapshot['cwd'], module='market_lab.runtime',
                subcommand='worker', purpose='REVIEWED_DATA_COLLECTOR',
                cmdline_sha256=digest('\0'.join(args).encode()),
                source_sha256=dict(COLLECTOR_SOURCES))


def protected_identities(repo, states):
    collectors = {}
    for unit, state in states.items():
        if state.get('ActiveState') in {'inactive','failed'} and state.get('MainPID') in {'0',None}:
            continue
        if unit == 'hilega-worker.service':
            try:
                collectors[unit] = collector_identity(repo, state)
                continue
            except (ValueError, OSError, UnicodeError) as exc:
                raise ValueError('EXECUTION_SERVICE_NOT_INACTIVE:' + unit + ':' +
                    (str(exc) if isinstance(exc,ValueError) else type(exc).__name__)) from None
        raise ValueError('EXECUTION_SERVICE_NOT_INACTIVE:' + unit)
    return collectors


def recheck_protected(context):
    states = {u:safety.service_state(u) for u in safety.PROTECTED}
    identities = protected_identities(context['repo'], states)
    if identities != context.get('collector_leases', {}):
        raise ValueError('COLLECTOR_PROCESS_CHANGED_DURING_ROLLOUT')
    for unit, previous in context['protected'].items():
        if any(states[unit].get(k) != previous.get(k) for k in ('ActiveState','MainPID')):
            raise ValueError('PROTECTED_SERVICE_STATE_CHANGED:' + unit)
    return states


def service_roles(states):
    """Report entrypoint identities, never raw arguments or process credentials."""
    roles = {}
    for unit, state in states.items():
        value = {k:state.get(k) for k in ('ActiveState','SubState','MainPID')}
        pid = state.get('MainPID', '0')
        if str(pid).isdigit() and pid != '0':
            try:
                args = Path('/proc',pid,'cmdline').read_bytes().decode().split('\0')
                module = None
                if '-m' in args and args.index('-m') + 1 < len(args):
                    candidate = args[args.index('-m') + 1]
                    if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.]{0,150}', candidate):
                        module = candidate
                value.update(module=module, scripts=[Path(a).name for a in args
                    if a.endswith('.py') and not a.startswith('-')])
                if module == 'market_lab.runtime':
                    pos=args.index('-m')+2
                    value['runtime_subcommand'] = args[pos] if pos<len(args) and args[pos] in {'api','worker'} else 'OTHER_OR_ABSENT'
            except (OSError, UnicodeError):
                value['process_inspection'] = 'UNAVAILABLE_OR_PROCESS_EXITED'
        roles[unit] = value
    return roles


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
    collectors = {}
    if args.prepare:
        # Preparation reads candles/ledgers and tests a temporary backend only.
        # It never stops, reloads, edits or installs into any running component.
        ledger = safety.sandbox_clear(repo, allow_open=True)
    else:
        collectors = protected_identities(repo, protected)
        safety.no_execution_workers(repo)
        ledger = safety.sandbox_clear(repo)
    companion = bindings.prepare(repo, updates)
    return dict(repo=repo, active=active, units=units, protected=protected, ledger=ledger,
                strategy_updates=updates, companion=companion,
                env_sha256=safety.sha(repo/'.env'),service_roles=service_roles(protected),
                collector_leases=collectors)


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


def intraday_snapshot(args, context, version):
    """Explicit user-authorized observation handover, not a broker square-off."""
    now=datetime.now(IST); day=now.date().isoformat()
    if not time(9,18)<=now.time()<time(15,30):
        raise ValueError('INTRADAY_HANDOVER_REQUIRES_REGULAR_SESSION')
    api=safety.api_status(args.api_url)
    if api.get('strategy_version')!=version:
        raise ValueError('INTRADAY_API_VERSION_MISMATCH')
    current=api.get('current') or {}
    if (current.get('session_date')!=day or current.get('state_available') is not True
            or current.get('trade_owner') not in {'NONE','BULLISH','BEARISH'}):
        raise ValueError('INTRADAY_CURRENT_STATE_NOT_VERIFIED')
    health=api.get('worker_component_health') or {}
    stamp=datetime.fromisoformat(health['timestamp']) if health.get('timestamp') else None
    if (stamp is None or stamp.tzinfo is None or not -5<=(now-stamp).total_seconds()<=90
            or (health.get('components') or {}).get('hilega')!='OK'):
        raise ValueError('INTRADAY_WORKER_NOT_FRESH_AND_HEALTHY')
    bar=datetime.fromisoformat(current['last_completed_bar']) if current.get('last_completed_bar') else None
    if (bar is None or bar.tzinfo is None or bar.astimezone(IST).date().isoformat()!=day
            or not -5<=(now-(bar+timedelta(minutes=3))).total_seconds()<=360):
        raise ValueError('INTRADAY_COMPLETED_CANDLE_NOT_FRESH')
    safety.sandbox_clear(context['repo']); safety.no_execution_workers(context['repo'])
    with urlopen(args.api_url.rstrip('/')+'/api/live-shadow/hilega-directional/trade-dashboard',timeout=30) as response:
        dashboard=json.load(response)
    options=[{k:t.get(k) for k in ('direction','signal_bar','signal_boundary',
              'strategy_version','status','recorded_status','exit_reason','issue')}
             for t in dashboard.get('trades',[])
             if t.get('strategy_version')==version
             and str(t.get('signal_boundary') or t.get('signal_bar') or '')[:10]==day]
    return dict(checked_at=now.isoformat(),strategy_version=version,current=current,
                worker_health_timestamp=health.get('timestamp'),option_observations=options,
                scope='OBSERVATION_ONLY_RECONSTRUCTION; NO_BROKER_POSITION_CHANGE',
                historical_shadow_exits_fabricated=False)


def transition_guard(args, context, version):
    if getattr(args,'allow_intraday',False):
        return intraday_snapshot(args,context,version)
    require_flat_after_close(args,context,version)
    return dict(mode='AFTER_CLOSE_VERIFIED_FLAT')


def frozen_policy_snapshot(repo, day, version):
    """Capture the last old-policy state after stopping its writers, read-only."""
    path=repo/AUDIT
    if not path.is_file():raise ValueError('HANDOVER_AUDIT_MISSING')
    state=None; anchor=None
    with path.open() as stream:
        for line in stream:
            try:row=json.loads(line)
            except ValueError:continue
            anchor={k:row.get(k) for k in ('sequence','record_hash','event_time')}
            payload=row.get('payload') or {}
            stamp=str(payload.get('decision_timestamp') or row.get('event_time') or '')
            if (stamp.startswith(day) and payload.get('strategy_version')==version
                    and row.get('stage') in {'DIRECTIONAL_DECISION','DIRECTIONAL_LIVE_BOOTSTRAP','DIRECTIONAL_SESSION_CUTOFF'}):
                state=dict(stage=row.get('stage'),status=row.get('status'),
                    event_time=row.get('event_time'),checkpoint=row.get('checkpoint'),
                    strategy_version=version,trade_owner=payload.get('trade_owner_after',payload.get('trade_owner')),
                    bullish_state=payload.get('bullish_state'),bearish_state=payload.get('bearish_state'),
                    last_completed_bar=payload.get('bar_timestamp',payload.get('last_completed_bar')),
                    reconstructed=payload.get('reconstructed'))
    if state is None or state['trade_owner'] not in {'NONE','BULLISH','BEARISH'}:
        raise ValueError('FROZEN_OLD_POLICY_STATE_NOT_AVAILABLE')
    return dict(state=state,journal_anchor=anchor,audit_bytes=path.stat().st_size,
                journal_edited=False,option_positions_closed_by_installer=False)


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
    transition_guard(args,context,manifest['old_version'])
    checks = candidate(args,context)
    collectors_before = context.get('collector_leases', {})
    context = preflight(args,manifest)
    if context.get('collector_leases', {}) != collectors_before:
        raise ValueError('COLLECTOR_PROCESS_CHANGED_AFTER_TESTS')
    handover_before=transition_guard(args,context,manifest['old_version'])
    started = datetime.now(IST)
    backup = context['repo']/'data/deployments'/('hilega-warmup-'+started.strftime('%Y%m%dT%H%M%S%f'))
    backup.mkdir(parents=True,exist_ok=False)
    updates = {r:bindings.regular(HERE/'files'/r) for r in manifest['candidate_sha256']}
    receipt = dict(status='PREPARED',repo=str(context['repo']),started_at=started.isoformat(),
        strategy_version=manifest['strategy_version'],active_services=context['active'],
        files_before={}, installed_sha256={r:digest(raw) for r,raw in updates.items()},
        cache_files_added=[],companion_checks=checks,broker_execution_enabled=False,
        databases_edited_by_installer=False,frontend_modified=False,
        collector_leases=context.get('collector_leases', {}),
        protected_service_states=context['protected'],handover_before=handover_before,
        transition_mode='INTRADAY_OBSERVATION_REBOOTSTRAP' if args.allow_intraday else 'AFTER_CLOSE_FLAT',
        intraday_installation_authorized=args.allow_intraday,
        prior_policy_audits_retained=True,shadow_exit_prices_fabricated=False)
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
        recheck_protected(context)
        # API is now stopped; verify final journal evidence and all source leases.
        if args.allow_intraday:
            receipt['frozen_prior_policy']=frozen_policy_snapshot(
                context['repo'],started.date().isoformat(),manifest['old_version'])
            safety.write_json(backup/'receipt.json',receipt)
        elif not cutoff_record(context['repo'],started.date().isoformat(),manifest['old_version']):
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
                or coverage.get('warmup_last')!=report['coverage']['expected_last_session']
                or coverage.get('recent_source_sha256')!=report['coverage']['recent_source_sha256']):
            raise ValueError('NEW_BOOTSTRAP_WARMUP_FRESHNESS_NOT_VERIFIED')
        if not args.allow_intraday and not cutoff_record(context['repo'],started.date().isoformat(),manifest['strategy_version'],started=started):
            # Health can become ready just before the cutoff audit is appended.
            deadline=__import__('time').monotonic()+30
            while __import__('time').monotonic()<deadline:
                if cutoff_record(context['repo'],started.date().isoformat(),manifest['strategy_version'],started=started):break
                __import__('time').sleep(2)
            else:raise ValueError('NEW_POLICY_AFTER_CLOSE_FLAT_STATE_NOT_VERIFIED')
        handover_after=transition_guard(args,context,manifest['strategy_version'])
        if safety.sha(context['repo']/'.env')!=context['env_sha256']:
            raise ValueError('ENV_CHANGED_DURING_INSTALL')
        recheck_protected(context)
        receipt.update(status='WARMUP_REPAIR_DEPLOYED',backup=str(backup),service_states=states,
                       completed_at=datetime.now(IST).isoformat(),coverage=coverage,
                       handover_after=handover_after,
                       reconstructed_owner=(handover_after.get('current') or {}).get('trade_owner'),
                       option_capture_note='Current underlying state is reconstructed. No option entry is backdated; new option observations start on subsequent fresh strategy entries.')
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
    p.add_argument('--allow-intraday',action='store_true',
                   help='Explicitly authorize observation-only intraday rebootstrapping; all execution guards remain mandatory.')
    group=p.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare',action='store_true')
    group.add_argument('--apply',action='store_true')
    group.add_argument('--rollback',type=Path)
    args=p.parse_args()
    if args.allow_intraday and not args.apply:p.error('--allow-intraday requires --apply')
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
            recheck_protected(dict(repo=args.repo,protected=receipt['protected_service_states'],
                                   collector_leases=receipt.get('collector_leases',{})))
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
        print('PROTECTED SERVICE IDENTITIES (no service changes):',flush=True)
        print(json.dumps(context['service_roles'],indent=2),flush=True)
        if args.apply:
            install(args,manifest,context)
        else:
            checks=candidate(args,context)
            report=read_json(args.work/'preparation.json')
            report.update(candidate_sha256=manifest['candidate_sha256'],vm_tests_passed=True,
                          companion_checks=checks,protected_service_roles=context['service_roles'],
                          observed_ledger_counts=context['ledger'],
                          installation_requires_execution_workers_inactive=True)
            safety.write_json(args.work/'preparation.json',report)
            print(json.dumps(dict(status='WARMUP_REPAIR_PREPARED',work=str(args.work),
                strategy_version=manifest['strategy_version'],vm_tests_passed=True,
                installed_files_modified=False,services_restarted=False),indent=2))


if __name__=='__main__':
    main()
