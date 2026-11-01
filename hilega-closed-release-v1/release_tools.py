"""Closed release planning and rollback rehearsal. No live apply or service control API."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

TARGETS=('scripts/hilega_production_simulator_bridge.py',
    'backend/market_lab/hilega_preparation_runtime_v1/source.py',
    'backend/market_lab/hilega_exclusive_closed_route_v1.py')
SUPERVISOR_SHA='cd7286892f5099ab962d3a179aff15642cce20ccd59727e21c83ab3b6e707e8a'
UNITS=('hilega-production-source-worker.service','hilega-worker.service','hilega-api.service',
    'hilega-lifecycle-reference.service','hilega-observation-analytics.service','hilega-observation-readiness.service')


def need(ok,reason):
    if not ok:raise ValueError(reason)


def sha(data):return hashlib.sha256(data).hexdigest()


def regular(path):
    need(path.is_file() and not path.is_symlink(),'REGULAR_FILE_REQUIRED')
    return path.read_bytes()


def atomic(path,data,mode=0o600):
    temp=path.with_name(path.name+'.new')
    fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode)
    try:
        os.fchmod(fd,mode)
        with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.replace(temp,path)
        descriptor=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(descriptor)
        finally:os.close(descriptor)
    finally:
        if temp.exists():temp.unlink()


def private_json(path,value):atomic(path,(json.dumps(value,sort_keys=True,indent=2)+'\n').encode())


def rehearsal_root(root):
    root=Path(root)
    need(root.is_absolute() and root.is_dir() and not root.is_symlink(),'ABSOLUTE_REHEARSAL_DIRECTORY_REQUIRED')
    marker=json.loads(regular(root/'REHEARSAL_ROOT.json'))
    need(marker==dict(model='HILEGA_DISPOSABLE_FILE_REHEARSAL_V1',root=str(root.resolve())),
         'DISPOSABLE_REHEARSAL_MARKER_REQUIRED')
    need(not (root/'.git').exists(),'GIT_CHECKOUT_NOT_A_REHEARSAL_ROOT')
    return root


def target(root,name):
    need(name in TARGETS,'EXACT_RELEASE_TARGET_REQUIRED')
    path=root/name
    for p in [path,*path.parents]:
        if p==root.parent:break
        need(not p.is_symlink(),'SYMLINK_RELEASE_TARGET_FORBIDDEN')
    need(path.resolve().is_relative_to(root),'REHEARSAL_TARGET_ESCAPES_ROOT')
    return path


def prepare_rehearsal(root,replacements):
    """Only disposable marker roots are accepted; never installs into the application repository."""
    root=rehearsal_root(root);need(set(replacements)==set(TARGETS),'EXACT_RELEASE_TARGETS_REQUIRED')
    folder=root/'rehearsal-transaction';folder.mkdir(mode=0o700,exist_ok=False)
    entries=[]
    for i,name in enumerate(TARGETS):
        path=target(root,name);path.parent.mkdir(parents=True,exist_ok=True)
        old=regular(path) if path.exists() else None
        mode=stat.S_IMODE(path.stat().st_mode) if old is not None else 0o644
        new=replacements[name];need(isinstance(new,bytes),'REPLACEMENT_BYTES_REQUIRED')
        if old is not None:atomic(folder/(str(i)+'.old'),old)
        atomic(folder/(str(i)+'.new'),new)
        entries.append(dict(name=name,old_sha256=sha(old) if old is not None else None,
            new_sha256=sha(new),mode=mode))
    plan=dict(model='HILEGA_DISPOSABLE_FILE_TRANSACTION_V1',root=str(root),entries=entries)
    private_json(folder/'PLAN.json',plan);private_json(folder/'STATE.json',dict(phase='PREPARED',plan_sha256=sha(regular(folder/'PLAN.json'))))
    return plan


def load_rehearsal(root):
    root=rehearsal_root(root);folder=root/'rehearsal-transaction'
    need(folder.is_dir() and not folder.is_symlink(),'REGULAR_REHEARSAL_TRANSACTION_REQUIRED')
    raw=regular(folder/'PLAN.json');state=json.loads(regular(folder/'STATE.json'))
    need(sha(raw)==state['plan_sha256'],'REHEARSAL_PLAN_CHANGED')
    plan=json.loads(raw)
    need(plan['root']==str(root) and [e['name'] for e in plan['entries']]==list(TARGETS),'REHEARSAL_PLAN_BINDING_CHANGED')
    for i,e in enumerate(plan['entries']):
        target(root,e['name'])
        need(sha(regular(folder/(str(i)+'.new')))==e['new_sha256'],'REHEARSAL_NEW_CONTENT_CHANGED')
        if e['old_sha256'] is not None:
            need(sha(regular(folder/(str(i)+'.old')))==e['old_sha256'],'REHEARSAL_BACKUP_CHANGED')
    return root,folder,plan,state


def apply_rehearsal(root,*,checkpoint=lambda at:None):
    root,folder,plan,state=load_rehearsal(root)
    need(state['phase']=='PREPARED','REHEARSAL_APPLY_REQUIRES_PREPARED')
    for e in plan['entries']:
        p=target(root,e['name']);current=sha(regular(p)) if p.exists() else None
        need(current==e['old_sha256'],'REHEARSAL_ORIGINAL_CHANGED')
    state['phase']='APPLYING';private_json(folder/'STATE.json',state)
    for i,e in enumerate(plan['entries']):
        atomic(target(root,e['name']),regular(folder/(str(i)+'.new')),e['mode'])
        checkpoint('AFTER_FILE_'+str(i+1))
    state['phase']='APPLIED';private_json(folder/'STATE.json',state)
    return dict(status='DISPOSABLE_FILES_APPLIED',production_execution_enabled=False)


def rollback_rehearsal(root):
    root,folder,plan,state=load_rehearsal(root)
    # Preflight every target before any restore: never overwrite third-party changes.
    for e in plan['entries']:
        p=target(root,e['name']);current=sha(regular(p)) if p.exists() else None
        need(current in {e['old_sha256'],e['new_sha256']},'REHEARSAL_TARGET_CHANGED_EXTERNALLY')
    for i,e in reversed(list(enumerate(plan['entries']))):
        p=target(root,e['name'])
        if e['old_sha256'] is None:
            if p.exists():p.unlink()
        else:atomic(p,regular(folder/(str(i)+'.old')),e['mode'])
    state['phase']='ROLLED_BACK';private_json(folder/'STATE.json',state)
    return dict(status='DISPOSABLE_FILES_RESTORED',production_execution_enabled=False)


def service_inventory(repo,home):
    """Read only systemctl show. Never exports raw arguments or environment values."""
    repo=Path(repo).resolve();runner=Path(home)/'hilega-persistent-supervision-stage-v1/runner.py'
    rows=[];limitations=[]
    for unit in UNITS:
        try:
            query=subprocess.run(['systemctl','--user','show',unit,
                '--property=ActiveState,SubState,UnitFileState,WorkingDirectory,ExecStart'],
                capture_output=True,text=True,timeout=10)
            if query.returncode:
                rows.append(dict(unit=unit,query_succeeded=False));continue
            fields=dict(line.split('=',1) for line in query.stdout.splitlines() if '=' in line)
            command=fields.get('ExecStart','')
            rows.append(dict(unit=unit,query_succeeded=True,active=fields.get('ActiveState'),
                sub_state=fields.get('SubState'),enabled=fields.get('UnitFileState'),
                working_directory_matches=fields.get('WorkingDirectory')==str(repo),
                references_reviewed_supervisor=str(runner) in command,
                references_source_role='production-source-worker' in command))
        except (OSError,subprocess.TimeoutExpired):rows.append(dict(unit=unit,query_succeeded=False))
    supervisor_ok=runner.is_file() and not runner.is_symlink() and sha(runner.read_bytes())==SUPERVISOR_SHA
    if not supervisor_ok:limitations.append('SUPERVISOR_MISSING_OR_CHANGED')
    source=next(r for r in rows if r['unit']==UNITS[0])
    mapped=supervisor_ok and source.get('working_directory_matches') and source.get('references_reviewed_supervisor') and source.get('references_source_role')
    if not mapped:limitations.append('SOURCE_SERVICE_MAPPING_NOT_CONFIRMED')
    return dict(services=rows,supervisor_matches_reviewed_version=supervisor_ok,
        source_service_mapping_confirmed=bool(mapped),limitations=limitations,
        private_configuration_opened=False,environment_values_exported=False,service_control_commands_issued=False)


def release_plan(repo,candidate,staged_hashes,inventory):
    repo=Path(repo).resolve();candidate=Path(candidate).resolve();entries=[]
    for name in TARGETS:
        new=regular(candidate/name);need(sha(new)==staged_hashes[name],'STAGED_RELEASE_CONTENT_CHANGED')
        p=repo/name
        need(not p.is_symlink(),'REGULAR_INSTALLED_RELEASE_TARGET_REQUIRED')
        old=regular(p) if p.exists() else None
        entries.append(dict(target=name,current_sha256=sha(old) if old is not None else None,
            candidate_sha256=sha(new),operation='REPLACE' if old is not None else 'CREATE'))
    return dict(model='HILEGA_CLOSED_WORKER_RELEASE_REVIEW_V1',status='REVIEW_PLAN_ONLY',files=entries,
        source_service_mapping_confirmed=inventory['source_service_mapping_confirmed'],
        intended_source_unit=UNITS[0],automatic_execution_session_configured=False,
        prerequisites=['QUIESCE_ALL_OLD_SOURCE_PROCESSES','RECONCILE_RELEASE_AND_SUPERVISOR_MANIFESTS',
            'BACK_UP_CODE_AND_DATABASES','VERIFY_NO_EXISTING_OWNER_STATE_REQUIRES_MIGRATION',
            'REVIEW_PAUSED_CLOSED_STARTUP','VERIFY_HEARTBEAT_AND_SOURCE_CURSOR','REVIEW_ROLLBACK_AND_RESTART'],
        runtime_dependency_manifest_fully_reconciled=False,
        database_migration_implemented=False,live_apply_available=False,
        installed_sources_modified=False,services_changed=False,production_execution_enabled=False)


def probe_unit(python,script):
    for p in (Path(python),Path(script)):
        need(p.is_absolute() and all(c not in str(p) for c in ('"','%','\n','\r','\\')),'SAFE_ABSOLUTE_UNIT_PATH_REQUIRED')
    return '\n'.join(['[Unit]','Description=Hilega bounded closed release probe (no application session)',
        '[Service]','Type=oneshot','ExecStart="'+str(python)+'" -I "'+str(script)+'" --watch --interval 1 --max-ticks 2',
        'Restart=no','TimeoutStartSec=15','NoNewPrivileges=true','PrivateTmp=true',
        'ProtectSystem=strict','ProtectHome=read-only',''])


def direct_dependency_inventory(sources,search_paths):
    """Resolve declared imports without importing packages or executing __init__.py."""
    import ast
    from importlib.machinery import PathFinder
    required=set()
    for module,text in sources.items():
        tree=ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):required.update(a.name for a in node.names)
            elif isinstance(node,ast.ImportFrom):
                if node.level:
                    package=module.split('.')[:-1]
                    base=package[:len(package)-node.level+1]
                    name='.'.join(base+([node.module] if node.module else []))
                    if name:required.add(name)
                elif node.module:required.add(node.module)
    rows=[]
    for name in sorted(required):
        if name.split('.')[0] in sys.stdlib_module_names:
            rows.append(dict(module=name,resolution='STANDARD_LIBRARY'));continue
        paths=list(map(str,search_paths));spec=None
        for i,part in enumerate(name.split('.')):
            spec=PathFinder.find_spec('.'.join(name.split('.')[:i+1]),paths)
            if spec is None:break
            paths=list(spec.submodule_search_locations or [])
        if spec is None:rows.append(dict(module=name,resolution='UNRESOLVED'));continue
        origin=spec.origin
        row=dict(module=name,resolution='RESOLVED_WITHOUT_IMPORT')
        if origin and origin not in {'built-in','frozen'}:
            p=Path(origin)
            row['regular_origin']=p.is_file() and not p.is_symlink()
            if row['regular_origin']:row['origin_sha256']=sha(p.read_bytes())
        rows.append(row)
    return dict(scope='DECLARED_DIRECT_IMPORTS_ONLY',modules=rows,
        unresolved_count=sum(r['resolution']=='UNRESOLVED' for r in rows),
        package_code_executed=False,transitive_runtime_closure_verified=False,
        production_dependency_manifest_fully_reconciled=False)
