"""Guarded CODE-ONLY deployment/rollback. Default command is read-only check."""
import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
from contextlib import contextmanager
from datetime import datetime,timezone
from pathlib import Path,PurePosixPath

PINNED_MANIFEST='3f583f5cd16034382cc773a4a4c08396c79675885905f6394bad8dd3b6b79369'
MODEL='PRICING_PREVIEW_CODE_DEPLOYMENT_V1'
RELEASE_LOCK=Path(__file__).with_name('release.json')


class Blocked(ValueError):pass


def need(condition,reason):
    if not condition:raise Blocked(reason)


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def target(root,name):
    parts=PurePosixPath(name)
    need(not parts.is_absolute() and '..' not in parts.parts and bool(parts.parts),'UNSAFE_RELEASE_PATH')
    path=Path(root).joinpath(*parts.parts)
    cursor=Path(root)
    for part in parts.parts:
        cursor=cursor/part
        need(not cursor.is_symlink(),'SYMLINK_OR_OUTSIDE_TARGET')
    need(not path.is_symlink() and path.parent.resolve().is_relative_to(Path(root).resolve()),'SYMLINK_OR_OUTSIDE_TARGET')
    return path


def read_json(path):
    path=Path(path)
    need(path.is_file() and not path.is_symlink(),'REGULAR_JSON_FILE_REQUIRED')
    return json.loads(path.read_text())



def trusted_manifest():
    need(sha(RELEASE_LOCK)==PINNED_MANIFEST,'DEPLOYMENT_RELEASE_LOCK_CHANGED')
    value=read_json(RELEASE_LOCK)
    need(value.get('model')=='HILEGA_PRICING_PREVIEW_RELEASE_V1' and
         value.get('scope')=='CODE_ONLY_NON_EXECUTABLE_PRICING_PREVIEW' and
         value.get('applied') is False and
         value.get('route_activation_included') is False and
         value.get('production_execution_enabled') is False,
         'PRICING_RELEASE_IDENTITY_INVALID')
    names=value['runtime_files']+value['test_files']
    need(len(names)==len(set(names)) and
         set(names)==set(value['files'])==set(value['expected_target_hashes']),
         'RELEASE_FILE_MAP_INVALID')
    need(not(set(value['files']) & set(value['unchanged_dependencies'])),
         'RELEASE_DEPENDENCY_MAP_OVERLAPS')
    value['expected']=value['expected_target_hashes']
    value['dependencies']=value['unchanged_dependencies']
    return value



def release_manifest(release):
    value=trusted_manifest()
    need(sha(target(release,'manifest.json'))==PINNED_MANIFEST,
         'PRICING_RELEASE_MANIFEST_CHANGED')
    for name,wanted in value['files'].items():
        path=target(Path(release)/'files',name)
        need(path.is_file() and sha(path)==wanted,'PACKAGED_FILE_CHANGED_'+name)
    return value



def proof(stage,report,manifest):
    need(sha(report)==manifest['validation']['regression_report_sha256'],
         'REGRESSION_REPORT_CHANGED')
    evidence=read_json(report)
    expected={**manifest['dependencies'],**manifest['files']}
    need(evidence.get('model')=='HILEGA_PRICING_PREVIEW_REGRESSION_V1' and
         evidence.get('status')=='PASS' and
         type(evidence.get('returncode')) is int and evidence['returncode']==0 and
         evidence.get('files')==expected and
         evidence.get('production_execution_enabled') is False and
         evidence.get('applied') is False,
         'MATCHING_PASS_VALIDATION_REPORT_REQUIRED')
    for name,wanted in expected.items():
        path=target(stage,name)
        need(path.is_file() and sha(path)==wanted,'VALIDATED_STAGE_CHANGED_'+name)


def configuration(root):
    from dotenv import dotenv_values
    file=Path(root)/'.env'
    need(not file.is_symlink(),'ENV_SYMLINK_REQUIRES_REVIEW')
    values=dotenv_values(file,interpolate=False) if file.is_file() else {}
    def setting(key,default):
        shell=os.getenv(key);stored=values.get(key)
        need(not(shell and stored and shell!=stored),'SHELL_FILE_ROUTE_CONFIGURATION_CONFLICT')
        return shell or stored or default
    selected=setting('HILEGA_PRODUCTION_EXECUTION_ROUTE','SIMULATOR')
    mode=setting('HILEGA_PRODUCTION_WORKSPACE_MODE','DISABLED')
    need(selected=='SIMULATOR','PREPARATION_ROUTE_ACTIVATION_NOT_AUTHORIZED_BY_CODE_DEPLOYMENT')
    need(mode in {'DISABLED','SIMULATION_ONLY'},'UNSUPPORTED_WORKSPACE_MODE')
    return dict(execution_route=selected,workspace_mode=mode,configuration_changed=False)


def workspace(path):
    path=Path(path)
    need(path.is_file() and not path.is_symlink(),'EXISTING_WORKSPACE_DATABASE_REQUIRED')
    db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=10)
    try:
        db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        row=db.execute('SELECT data FROM control WHERE id=1').fetchone()
        need(row is not None,'WORKSPACE_CONTROL_REQUIRED')
        control=json.loads(row[0]);need(control.get('mode')=='PAUSED','WORKSPACE_MUST_BE_PAUSED')
        for table in ('intents','sim_orders','sim_fills','sim_allocation_reservations'):
            need(table in tables,'WORKSPACE_SCHEMA_REQUIRES_REVIEW')
            need(not db.execute('SELECT 1 FROM '+table+' LIMIT 1').fetchone(),'WORKSPACE_EXECUTION_HISTORY_REQUIRES_REVIEW')
        for table in ('preparation_route','preparation_plans','preparation_shadow_holds','preparation_outbox'):
            if table in tables:
                need(not db.execute('SELECT 1 FROM '+table+' LIMIT 1').fetchone(),
                     'ENROLLED_OR_PENDING_PREPARATION_REQUIRES_DATA_RECOVERY_REVIEW')
        stop=db.execute('SELECT generation,handled FROM sim_stop_state WHERE id=1').fetchone()
        need(stop is not None and stop[0]==stop[1],'UNHANDLED_STOP_REQUIRES_REVIEW')
        return dict(control_mode='PAUSED',execution_history_empty=True,preparation_enrolled=False,database_modified=False)
    finally:db.close()



def check(root,release,stage,report,workspace_db):
    root=Path(root).resolve()
    manifest=release_manifest(release)
    proof(stage,report,manifest)
    before={}
    for name,wanted in manifest['files'].items():
        path=target(root,name)
        need(not path.exists() or path.is_file(),'TARGET_NOT_REGULAR_'+name)
        actual=sha(path) if path.is_file() else None
        need(actual in {manifest['expected'][name],wanted},
             'APPLICATION_SOURCE_CHANGED_'+name)
        before[name]=actual
    initial=all(before[n]==manifest['expected'][n] for n in before)
    deployed=all(before[n]==manifest['files'][n] for n in before)
    need(initial or deployed,'PARTIAL_OR_MIXED_DEPLOYMENT_USE_RECORDED_RECOVERY')
    for name,wanted in manifest['dependencies'].items():
        path=target(root,name)
        need(path.is_file() and sha(path)==wanted,
             'APPLICATION_DEPENDENCY_CHANGED_'+name)
    config=configuration(root)
    state=workspace(workspace_db)
    return dict(
        status='ALREADY_DEPLOYED' if deployed else 'CODE_DEPLOYMENT_CHECKS_PASS',
        manifest=manifest,before=before,configuration=config,workspace=state,
        replaced_files=sum(before[n] is not None and before[n]!=manifest['files'][n] for n in before),
        new_files=sum(before[n] is None for n in before),
        validated_release_matches=True,services_stopped_verified=False,
        apply_ready=False,source_repository_modified=False,
        production_execution_enabled=False,route_activation_included=False,
        validation_report_sha256=sha(report))


def verify_units(units):
    need(bool(units),'REVIEWED_SYSTEMD_UNIT_LIST_REQUIRED')
    selected=set(units)
    for unit in sorted(selected):
        need(re.fullmatch(r'[A-Za-z0-9_.@:-]+\.(service|socket|timer)',unit) is not None,'INVALID_UNIT_NAME')
        result=subprocess.run(['systemctl','show',unit,'--property=LoadState,ActiveState,TriggeredBy','--no-pager'],
                              text=True,capture_output=True,timeout=10)
        need(result.returncode==0,'SERVICE_STATE_UNAVAILABLE')
        values=dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)
        need(values.get('LoadState')=='loaded','SERVICE_UNIT_NOT_LOADED')
        need(values.get('ActiveState') in {'inactive','failed'},'REVIEWED_SERVICE_IS_NOT_STOPPED')
        need(set(values.get('TriggeredBy','').split())<=selected,'TRIGGERING_UNIT_MUST_ALSO_BE_REVIEWED_AND_STOPPED')



def verify_quiescence(root,units,process_mode):
    if process_mode=='systemd':return verify_units(units)
    need(process_mode=='pid-managed' and not units,'PID_MANAGED_MODE_CANNOT_USE_SYSTEMD_UNITS')
    from managed_processes import require_stopped,ManagedBlocked
    try:return require_stopped(root)
    except ManagedBlocked as exc:raise Blocked(str(exc)) from None


def fsync_directory(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)


def atomic_bytes(path,data,mode=0o644):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.deployment-',dir=path.parent)
    try:
        os.fchmod(fd,mode)
        with os.fdopen(fd,'wb') as stream:
            stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.replace(name,path);fsync_directory(path.parent)
    finally:
        Path(name).unlink(missing_ok=True)


def journal(backup,value):atomic_bytes(Path(backup)/'deployment.json',json.dumps(value,indent=2).encode(),0o600)


@contextmanager
def deployment_lock(root):
    fd=os.open(Path(root)/'.hilega-code-deployment.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'a') as stream:
        fcntl.flock(stream,fcntl.LOCK_EX)
        try:yield
        finally:fcntl.flock(stream,fcntl.LOCK_UN)


def rollback(root,backup,workspace_db,units,*,services_stopped,checkpoint=lambda name:None,process_mode='systemd'):
    need(services_stopped,'ALL_API_AND_WORKER_PROCESSES_MUST_BE_STOPPED')
    verify_quiescence(root,units,process_mode);configuration(root);workspace(workspace_db)
    root=Path(root).resolve();backup=Path(backup).resolve()
    state=read_json(backup/'deployment.json')
    need(state.get('model')==MODEL and state.get('root')==str(root) and
         state.get('release_manifest_sha256')==PINNED_MANIFEST,'BACKUP_SCOPE_OR_RELEASE_MISMATCH')
    trusted=trusted_manifest()
    need(state.get('files')==trusted['files'] and state.get('before')=={name:trusted['expected'].get(name) for name in trusted['files']},'BACKUP_FILE_MAP_DIFFERS_FROM_RELEASE')
    need(set(state.get('modes',{}))==set(trusted['files']) and all(type(v) is int and 0<=v<=0o777 for v in state['modes'].values()),'BACKUP_MODE_MAP_INVALID')
    # Inspect EVERY destination and backup before altering any source file.
    for name,new in state['files'].items():
        path=target(root,name);old=state['before'][name]
        actual=sha(path) if path.is_file() else None
        need(actual in {new,old},'POST_DEPLOYMENT_EDIT_REQUIRES_REVIEW_'+name)
        if old is not None:need(sha(target(backup/'original',name))==old,'BACKUP_CONTENT_CHANGED_'+name)
    state['phase']='ROLLING_BACK';journal(backup,state)
    for name in reversed(list(state['files'])):
        verify_quiescence(root,units,process_mode)
        path=target(root,name);old=state['before'][name]
        actual=sha(path) if path.is_file() else None
        if old is None:
            if actual is not None:path.unlink();fsync_directory(path.parent)
        elif actual!=old:
            atomic_bytes(path,target(backup/'original',name).read_bytes(),state['modes'][name])
        checkpoint(name)
    state['phase']='ROLLED_BACK';journal(backup,state)
    return dict(status='CODE_ROLLED_BACK',backup=str(backup),services_started=False,
                configuration_changed=False,database_modified=False,production_execution_enabled=False)


def apply(root,release,stage,report,workspace_db,units,*,services_stopped,checkpoint=lambda name:None,process_mode='systemd'):
    need(services_stopped,'ALL_API_AND_WORKER_PROCESSES_MUST_BE_STOPPED')
    verify_quiescence(root,units,process_mode)
    checked=check(root,release,stage,report,workspace_db)
    need(checked['status']!='ALREADY_DEPLOYED','CODE_ALREADY_DEPLOYED_NO_REAPPLY')
    root=Path(root).resolve();manifest=checked['manifest']
    backup=root/'backups'/('hilega-application-code-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    need(not backup.parent.is_symlink() and backup.parent.resolve().is_relative_to(root),'BACKUP_DIRECTORY_REQUIRES_REVIEW')
    backup.mkdir(parents=True,mode=0o700)
    modes={}
    for name,old in checked['before'].items():
        path=target(root,name)
        modes[name]=path.stat().st_mode & 0o777 if old is not None else 0o644
        if old is not None:atomic_bytes(target(backup/'original',name),path.read_bytes(),modes[name])
    state=dict(model=MODEL,phase='BACKUP_COMPLETE',root=str(root),files=manifest['files'],
        before=checked['before'],modes=modes,release_manifest_sha256=PINNED_MANIFEST,
        validation_report_sha256=checked['validation_report_sha256'],units=list(units),
        workspace_db=str(Path(workspace_db).resolve()),process_mode=process_mode,production_execution_enabled=False)
    journal(backup,state)
    state['phase']='APPLYING';journal(backup,state)
    try:
        for name,wanted in manifest['files'].items():
            verify_quiescence(root,units,process_mode)
            path=target(root,name);old=state['before'][name]
            actual=sha(path) if path.is_file() else None
            need(actual==old,'TARGET_CHANGED_DURING_DEPLOYMENT_'+name)
            source=target(Path(release)/'files',name)
            data=source.read_bytes();need(hashlib.sha256(data).hexdigest()==wanted,'PACKAGED_SOURCE_CHANGED_DURING_DEPLOYMENT')
            atomic_bytes(path,data,modes[name]);checkpoint(name)
        state['phase']='APPLIED';journal(backup,state)
    except BaseException:
        # No automatic restart or broad rollback after unknown interference.
        # The durable journal/backup permits explicitly reviewed recovery.
        state['phase']='INTERRUPTED_REQUIRES_ROLLBACK';journal(backup,state)
        raise
    return dict(status='CODE_APPLIED_SERVICES_STILL_STOPPED',backup=str(backup),files=len(manifest['files']),
                services_started=False,configuration_changed=False,database_modified=False,
                production_execution_enabled=False,route_activation_included=False)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',nargs='?',choices=['check','apply','rollback'],default='check')
    p.add_argument('--root',type=Path,default=Path.cwd())
    p.add_argument('--release',type=Path,default=Path('hilega-production-pricing-preview-release-v1'))
    p.add_argument('--stage',type=Path,default=Path.home()/'hilega-pricing-preview-stage-v1')
    p.add_argument('--validation',type=Path,default=Path('hilega-production-pricing-preview-release-v1/validation/PRICING_PREVIEW_REGRESSION_V1.json'))
    p.add_argument('--workspace-db',type=Path,default=Path('data/research/hilega-production-workspace/sim.sqlite'))
    p.add_argument('--backup',type=Path)
    p.add_argument('--unit',action='append',default=[])
    p.add_argument('--process-mode',choices=['systemd','pid-managed'],default='pid-managed')
    p.add_argument('--services-stopped',action='store_true')
    p.add_argument('--confirmation')
    a=p.parse_args();root=a.root.resolve()
    def resolve(path):return path if path.is_absolute() else root/path
    try:
        if a.action=='check':
            result=check(root,resolve(a.release),a.stage,resolve(a.validation),resolve(a.workspace_db))
            result.pop('manifest');result.pop('before')
            if a.process_mode=='pid-managed':
                need(not a.unit,'PID_MANAGED_MODE_CANNOT_USE_SYSTEMD_UNITS')
                from managed_processes import inspect
                result['managed_processes']=inspect(root)
                result['process_mode']='pid-managed'
        else:
            need(a.confirmation==('APPLY_VALIDATED_CODE_ONLY' if a.action=='apply' else 'ROLLBACK_CODE_ONLY'),
                 'EXPLICIT_CODE_ACTION_CONFIRMATION_REQUIRED')
            with deployment_lock(root):
                if a.action=='apply':result=apply(root,resolve(a.release),a.stage,resolve(a.validation),resolve(a.workspace_db),a.unit,services_stopped=a.services_stopped,process_mode=a.process_mode)
                else:
                    need(a.backup is not None,'RECORDED_BACKUP_REQUIRED')
                    result=rollback(root,resolve(a.backup),resolve(a.workspace_db),a.unit,services_stopped=a.services_stopped,process_mode=a.process_mode)
        print(json.dumps(result));return 0
    except Exception as exc:
        reason=str(exc) if isinstance(exc,Blocked) else 'LOCAL_PREFLIGHT_OR_DEPLOYMENT_ERROR'
        print(json.dumps(dict(status='BLOCKED',reason=reason,services_started=False,production_execution_enabled=False)))
        return 2


if __name__=='__main__':raise SystemExit(main())
