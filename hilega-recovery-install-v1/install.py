"""Approved exact-plan recovery installation; preserves paused closed runtime and source cursor."""
import json,os,shlex,shutil,sqlite3,subprocess,sys
from pathlib import Path
from live_recovery import need,regular,sha

def save(path,value):
    raw=(json.dumps(value,indent=2)+'\n').encode();atomic(path,raw,0o600)
def atomic(path,raw,mode):
    need(not path.is_symlink(),'SYMLINK_INSTALL_TARGET_FORBIDDEN');temp=path.with_name(path.name+'.install-new')
    fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode)
    try:
        with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
        os.replace(temp,path);fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
    finally:
        if temp.exists():temp.unlink()

def control(action,unit):
    need(unit=='hilega-closed-pause-recovery.service' and action in {'start','stop','reset-failed'},'EXACT_RECOVERY_UNIT_REQUIRED')
    result=subprocess.run(['systemctl','--user',action,unit],capture_output=True,text=True,timeout=100)
    need(result.returncode==0,'RECOVERY_UNIT_ACTION_FAILED: '+action)
def reload():need(subprocess.run(['systemctl','--user','daemon-reload'],capture_output=True,timeout=20).returncode==0,'USER_MANAGER_RELOAD_FAILED')
def prior_action(plan,action,folder):
    # Run the pinned native functions under the installer's shared maintenance lock.
    # Calling the old CLI here would attempt to acquire that same lock again.
    import importlib.util
    active_path=Path(plan['active_plan']);active=json.loads(regular(active_path));old_folder=active_path.parent
    checked=json.loads(regular(old_folder/'CHECK-VALIDATION.json'))
    need(checked['status']=='PASS_TARGETED_ONLY' and checked['plan_sha256']==plan['active_plan_sha256'] and checked['closed_release_scope_regression_reexecuted'] is True,'PRIOR_CLOSED_RELEASE_VALIDATION_REQUIRED')
    tool=Path(plan['repo'])/'hilega-group1-rollout-v1';sys.path.insert(0,str(tool))
    spec=importlib.util.spec_from_file_location('recovery_pinned_group1_rollout',tool/'rollout.py');old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
    old.check_plan(active);old.bound_inputs(active);m=primitives(plan);manager=m.Systemd()
    if action=='hold':result=old.hold(active,old_folder,manager)
    elif action=='start':result=old.start(active,old_folder,manager)
    elif action=='status':
        result=json.loads(regular(old_folder/'TRANSACTION.json'));need(result['phase']=='CLOSED_BUNDLE_RUNNING','CURRENT_CLOSED_BUNDLE_REQUIRED')
        need(sha(regular(Path(plan['repo'])/'scripts/hilega_production_simulator_bridge.py'))==active['new_worker_sha256'],'WORKER_WRAPPER_CHANGED')
        old.wait_health(Path(active['application_db']),'STATUS_OBSERVATION',manager,[u for u in m.UNITS if result['before'][u]['active']=='active'],timeout=35)
        m.require_empty_closed_baseline(Path(active['application_db']),Path(active['adapter_db']))
    else:raise ValueError('UNKNOWN_CLOSED_MAINTENANCE_ACTION')
    save(folder/('GROUP1-'+action+'.json'),dict(phase=result['phase'],production_execution_enabled=False))
def database_control(path):
    db=sqlite3.connect(Path(path).as_uri()+'?mode=ro',uri=True)
    try:return json.loads(db.execute('SELECT data FROM control WHERE id=1').fetchone()[0])
    finally:db.close()
def expected_files(plan,folder,*,installed):
    for item in plan['files']:
        target=Path(item['destination']);need(not any(x.is_symlink() for x in [target,*target.parents]),'SYMLINK_INSTALL_PATH_FORBIDDEN')
        source=regular(folder/item['payload']);need(sha(source)==item['new_sha256'],'STAGED_RECOVERY_PAYLOAD_CHANGED')
        if installed:need(target.is_file() and sha(regular(target))==item['new_sha256'],'INSTALLED_RECOVERY_INPUT_CHANGED')
        else:need(not target.exists(),'RECOVERY_TARGET_ALREADY_EXISTS')
def primitives(plan):
    tool=Path(plan['repo'])/'hilega-group1-rollout-v1';sys.path.insert(0,str(tool))
    import maintenance_primitives as m
    return m

def definitions(plan,*,installed):
    for name,original in plan['observed_unit_paths'].items():
        result=subprocess.run(['systemctl','--user','show',name,'--property=FragmentPath,DropInPaths'],capture_output=True,text=True,timeout=10)
        need(result.returncode==0,'MANAGED_UNIT_DEFINITION_UNAVAILABLE')
        values=dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)
        actual=[values['FragmentPath'],*shlex.split(values.get('DropInPaths',''))]
        added=[i['destination'] for i in plan['files'] if Path(i['destination']).parent.name==name+'.d'] if installed else []
        need(actual[0]==original[0] and set(actual[1:])==set(original[1:]+added),'UNPLANNED_UNIT_DEFINITION_CHANGED: '+name)
    if installed:
        result=subprocess.run(['systemctl','--user','show','hilega-closed-pause-recovery.service','--property=FragmentPath,DropInPaths'],capture_output=True,text=True,timeout=10)
        values=dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)
        target=next(i['destination'] for i in plan['files'] if Path(i['destination']).name=='hilega-closed-pause-recovery.service')
        need(values.get('FragmentPath')==target and not values.get('DropInPaths','').strip(),'UNPLANNED_RECOVERY_UNIT_OVERRIDE')

def apply(plan,folder):
    need(not (folder/'TRANSACTION.json').exists(),'INSTALLATION_ALREADY_STARTED')
    expected_files(plan,folder,installed=False);definitions(plan,installed=False);m=primitives(plan)
    m.require_empty_closed_baseline(Path(plan['application_db']),Path(plan['adapter_db']))
    c=database_control(plan['application_db']);need(c['mode']=='PAUSED' and c['version']==plan['expected_controller_version'] and c['session_date']==plan['expected_session_date'],'EXACT_PAUSED_STATE_CHANGED')
    manager=m.Systemd();need(all(manager.state(u)['active']=='active' and manager.state(u)['pid']>0 for u in m.UNITS),'ALL_SIX_SERVICES_REQUIRED_BEFORE_INSTALL')
    tx=dict(phase='HOLD_REQUESTED',production_execution_enabled=False);save(folder/'TRANSACTION.json',tx)
    prior_action(plan,'hold',folder)
    need(all(manager.state(u)['active']=='inactive' and manager.state(u)['pid']==0 for u in m.UNITS),'ALL_SIX_SERVICES_MUST_BE_STOPPED')
    m.no_unmanaged_python(Path(plan['repo']));m.require_empty_closed_baseline(Path(plan['application_db']),Path(plan['adapter_db']))
    backup=folder/'backups';backup.mkdir(mode=0o700)
    for key,name in [('application_db','application.sqlite'),('adapter_db','adapter.sqlite')]:
        m.backup_database(Path(plan[key]),backup/name)
        db=sqlite3.connect(backup/name)
        try:need(db.execute('PRAGMA integrity_check').fetchone()[0]=='ok','SQLITE_BACKUP_INTEGRITY_FAILED')
        finally:db.close()
    # Preserve approved installed code and every existing binding, including private configuration, privately.
    active=json.loads(regular(Path(plan['active_plan'])));bundle=Path(active['destination']);manifest=json.loads(regular(bundle/'RELEASE-MANIFEST.json'))
    code=backup/'closed-bundle';code.mkdir(mode=0o700)
    for name,digest in manifest['files'].items():
        rel=Path(name);need(not rel.is_absolute() and '..' not in rel.parts,'RELATIVE_BACKUP_PATH_REQUIRED')
        raw=regular(bundle/rel);need(sha(raw)==digest,'INSTALLED_CODE_CHANGED_BEFORE_BACKUP')
        dst=code/rel;dst.parent.mkdir(parents=True,exist_ok=True,mode=0o700);atomic(dst,raw,0o600)
    atomic(code/'RELEASE-MANIFEST.json',regular(bundle/'RELEASE-MANIFEST.json'),0o600)
    atomic(backup/'worker.py',regular(Path(plan['repo'])/'scripts/hilega_production_simulator_bridge.py'),0o600)
    original=backup/'bindings';original.mkdir(mode=0o700);index=[]
    for i,(name,digest) in enumerate(active['bindings'].items()):
        raw=regular(Path(name));need(sha(raw)==digest,'SUPERVISOR_BINDING_CHANGED_BEFORE_BACKUP');atomic(original/str(i),raw,0o600);index.append(dict(original=name,backup=str(i),sha256=digest))
    save(original/'INDEX.json',index)
    hashes={str(f.relative_to(backup)):sha(regular(f)) for f in backup.rglob('*') if f.is_file()};save(folder/'BACKUP-RECEIPT.json',dict(files=hashes,quiescent=True,automatic_database_restore=False))
    tx['phase']='BACKED_UP_SERVICES_STOPPED';save(folder/'TRANSACTION.json',tx)
    expected_files(plan,folder,installed=False)
    for item in plan['files']:
        target=Path(item['destination']);target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        atomic(target,regular(folder/item['payload']),item['mode'])
    Path(plan['recovery_directory']).chmod(0o500)
    tx['phase']='RECOVERY_INSTALLED_SERVICES_STOPPED';save(folder/'TRANSACTION.json',tx)
    reload();definitions(plan,installed=True);control('start','hilega-closed-pause-recovery.service')
    need(database_control(plan['application_db'])['mode']=='PAUSED','RECOVERY_DID_NOT_PAUSE')
    tx['phase']='RECOVERY_VERIFIED_SERVICES_STOPPED';save(folder/'TRANSACTION.json',tx)
    prior_action(plan,'start',folder);expected_files(plan,folder,installed=True)
    tx['phase']='CLOSED_RECOVERY_INSTALLED_RUNNING';save(folder/'TRANSACTION.json',tx);return tx

def rollback(plan,folder):
    tx=json.loads(regular(folder/'TRANSACTION.json'));need(tx['phase']!='ROLLED_BACK_RUNNING','ROLLBACK_ALREADY_COMPLETED')
    prior_action(plan,'hold',folder);m=primitives(plan);m.no_unmanaged_python(Path(plan['repo']))
    # Remove only exact files created by this plan. Never restore databases or rewind cursors.
    existing=[item for item in plan['files'] if Path(item['destination']).exists()]
    for item in existing:need(sha(regular(Path(item['destination'])))==item['new_sha256'],'ROLLBACK_TARGET_CHANGED')
    unit_present=any(Path(i['destination']).name=='hilega-closed-pause-recovery.service' for i in existing)
    if unit_present:control('stop','hilega-closed-pause-recovery.service')
    directory=Path(plan['recovery_directory'])
    if directory.exists():directory.chmod(0o700)
    for item in reversed(existing):Path(item['destination']).unlink()
    for item in reversed(plan['files']):
        parent=Path(item['destination']).parent
        if item['parent_created_by_plan']:
            try:parent.rmdir()
            except OSError:pass
    reload();definitions(plan,installed=False);prior_action(plan,'start',folder)
    tx['phase']='ROLLED_BACK_RUNNING';save(folder/'TRANSACTION.json',tx);return tx
