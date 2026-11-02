"""Exact-plan closed pause recovery installation; default builds a reviewable plan only."""
import argparse,fcntl,hashlib,json,os,shlex,sqlite3,stat,subprocess,sys,tempfile
from pathlib import Path
from datetime import datetime,timedelta,timezone
import xml.etree.ElementTree as ET
from live_recovery import regular,sha,need
from plan_tools import unit,dropin,exact_files
from install import save,apply,rollback,expected_files,prior_action,definitions

UNITS=('hilega-production-source-worker.service','hilega-worker.service','hilega-api.service','hilega-lifecycle-reference.service','hilega-observation-analytics.service','hilega-observation-readiness.service')

def verify_tool(root,active):
    tool=root/'hilega-group1-rollout-v1';raw=regular(tool/'MANIFEST.json');need(sha(raw)==active['tool_manifest_sha256'],'APPROVED_MAINTENANCE_TOOL_CHANGED')
    for name,digest in json.loads(raw).items():need(sha(regular(tool/name))==digest,'APPROVED_MAINTENANCE_SOURCE_CHANGED')

def source_bindings(plan):
    need(sha(regular(Path(plan['active_plan'])))==plan['active_plan_sha256'],'ACTIVE_CLOSED_PLAN_CHANGED')
    for name,digest in plan['observed_input_bindings'].items():need(sha(regular(Path(name)))==digest,'PLAN_INPUT_CHANGED: '+Path(name).name)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--repo',type=Path,required=True)
    p.add_argument('--action',choices=('check','apply','status','rollback'),default='check');p.add_argument('--plan',type=Path);p.add_argument('--approve-plan-sha256');args=p.parse_args()
    root=args.repo.absolute();here=Path(__file__).absolute().parent
    for name,digest in json.loads(regular(here/'MANIFEST.json')).items():need(sha(regular(here/name))==digest,'RECOVERY_INSTALL_PACKAGE_CHANGED')
    for name,digest in json.loads(regular(here/'BASELINE-PINS.json')).items():need(sha(regular(root/name))==digest,'PASSED_VALIDATION_SOURCE_CHANGED')
    if args.action!='check':
        need(args.plan is not None and args.approve_plan_sha256 is not None,'EXACT_PLAN_AND_APPROVAL_REQUIRED')
        path=args.plan.absolute();raw=regular(path);need(sha(raw)==args.approve_plan_sha256,'EXACT_PLAN_APPROVAL_SHA_REQUIRED');plan=json.loads(raw);folder=path.parent
        need(plan['model']=='HILEGA_CLOSED_RECOVERY_INSTALL_PLAN_V1' and plan['repo']==str(root) and plan['tool_manifest_sha256']==sha(regular(here/'MANIFEST.json')),'PLAN_TOOL_OR_SCOPE_CHANGED')
        need(path.name=='PLAN.json' and folder.parent==root and folder.name.startswith('hilega-recovery-install-plan-'),'EXACT_PLAN_DIRECTORY_REQUIRED')
        need(plan['production_execution_enabled'] is False and plan['controller_resume_available'] is False,'CLOSED_RECOVERY_SCOPE_REQUIRED')
        active=json.loads(regular(Path(plan['active_plan'])));verify_tool(root,active);source_bindings(plan)
        validation=json.loads(regular(folder/'CHECK-VALIDATION.json'));need(validation['plan_sha256']==args.approve_plan_sha256 and validation['status']=='CLOSED_RECOVERY_INSTALL_PLAN_PASS','PASSING_EXACT_PLAN_CHECK_REQUIRED')
        lock=root/'.hilega-closed-rollout.lock';fd=os.open(lock,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        info=os.fstat(fd);need(stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid() and stat.S_IMODE(info.st_mode)&0o077==0,'PRIVATE_SHARED_MAINTENANCE_LOCK_REQUIRED');fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if args.action=='apply':
            need(datetime.now(timezone.utc)<=datetime.fromisoformat(plan['apply_before']),'PLAN_EXPIRED_REGENERATE_CHECK')
            result=apply(plan,folder)
        elif args.action=='rollback':result=rollback(plan,folder)
        else:
            tx=json.loads(regular(folder/'TRANSACTION.json'));need(tx['phase']=='CLOSED_RECOVERY_INSTALLED_RUNNING','INSTALLED_RUNNING_RECOVERY_REQUIRED')
            expected_files(plan,folder,installed=True);definitions(plan,installed=True);prior_action(plan,'status',folder)
            need(subprocess.run(['systemctl','--user','is-active','--quiet','hilega-closed-pause-recovery.service'],timeout=10).returncode==0,'RECOVERY_SERVICE_NOT_ACTIVE')
            result=tx
        print(json.dumps(dict(phase=result['phase'],controller_resumed=False,production_execution_enabled=False,production_ready=False),indent=2));return 0
    prior_raw=regular(root/'hilega-package-a-v2/VM-VALIDATION.json');prior=json.loads(prior_raw)
    need(prior['status']=='PACKAGE_A_CANDIDATE_VALIDATION_PASS' and prior['managed_window_fresh_synthetic_signal_end_to_end_verified'] is True and prior['managed_registry_recovery_admission_verified'] is True,'PACKAGE_A_PASS_REQUIRED')
    need(sha(regular(Path(prior['maintenance_plan'])))==prior['maintenance_plan_sha256'],'PACKAGE_A_REVIEW_RECEIPT_CHANGED')
    g1=json.loads(regular(root/'hilega-group1-cache-recovery-v1/VM-VALIDATION.json'));active_path=Path(g1['active_plan']);active_raw=regular(active_path);need(sha(active_raw)==g1['active_plan_sha256'],'ACTIVE_PLAN_CHANGED');active=json.loads(active_raw);verify_tool(root,active)
    output=Path(tempfile.mkdtemp(prefix='hilega-recovery-install-plan-',dir=root));output.chmod(0o700);(output/'.gitignore').write_text('*\n');(output/'PACKAGE-A-RECEIPT.json').write_bytes(prior_raw)
    review=root/'hilega-group2-window-review-v2';begin=datetime.now(timezone.utc)
    need(subprocess.run([sys.executable,'-B',str(review/'manage.py'),'--repo',str(root)],cwd=root).returncode==0,'CURRENT_CLOSED_BASELINE_FAILED')
    baseline_raw=regular(review/'VM-VALIDATION.json');baseline=json.loads(baseline_raw)
    need(datetime.fromisoformat(baseline['assessed_at'])>=begin and baseline['review']['blockers']==[],'FRESH_EMPTY_PAUSED_BASELINE_REQUIRED');(output/'CURRENT-BASELINE.json').write_bytes(baseline_raw)
    app=Path(active['application_db']);db=sqlite3.connect(app.as_uri()+'?mode=ro',uri=True)
    try:control=json.loads(db.execute('SELECT data FROM control WHERE id=1').fetchone()[0])
    finally:db.close()
    user_units=Path.home()/'.config/systemd/user';target_unit=user_units/'hilega-closed-pause-recovery.service'
    r=subprocess.run(['systemctl','--user','show','hilega-closed-pause-recovery.service','--property=LoadState','--value'],capture_output=True,text=True,timeout=10)
    need(r.stdout.strip()=='not-found','EXISTING_RECOVERY_UNIT_REQUIRES_UPGRADE_REVIEW')
    observed=dict(active['bindings']);observed[str(active_path)]=sha(active_raw);observed[str(root/'scripts/hilega_production_simulator_bridge.py')]=active['new_worker_sha256']
    unit_paths={}
    for name in UNITS:
        r=subprocess.run(['systemctl','--user','show',name,'--property=FragmentPath,DropInPaths'],capture_output=True,text=True,timeout=10);need(r.returncode==0,'MANAGED_UNIT_IDENTITY_UNAVAILABLE')
        values=dict(line.split('=',1) for line in r.stdout.splitlines() if '=' in line)
        paths=[values['FragmentPath'],*shlex.split(values.get('DropInPaths',''))];unit_paths[name]=paths
        for value in paths:observed[value]=sha(regular(Path(value)))
    config=dict(model='HILEGA_CLOSED_PAUSE_RECOVERY_CONFIG_V1',bundle=active['destination'],release_manifest_sha256=active['release_manifest_sha256'],worker=str(root/'scripts/hilega_production_simulator_bridge.py'),worker_sha256=active['new_worker_sha256'],application_db=active['application_db'],production_execution_enabled=False)
    config_raw=(json.dumps(config,indent=2,sort_keys=True)+'\n').encode();config_sha=sha(config_raw);recovery_dir=root/'data/runtime/hilega-closed-pause-recovery'/config_sha
    payload=output/'payload';payload.mkdir(mode=0o700);(payload/'CONFIG.json').write_bytes(config_raw);(payload/'live_recovery.py').write_bytes(regular(here/'live_recovery.py'))
    (payload/'recovery.service').write_bytes(unit(str(root/'.venv/bin/python'),str(recovery_dir/'live_recovery.py'),str(recovery_dir/'CONFIG.json'),config_sha));(payload/'dependency.conf').write_bytes(dropin())
    entries=[]
    for source,destination,mode in [('CONFIG.json',recovery_dir/'CONFIG.json',0o400),('live_recovery.py',recovery_dir/'live_recovery.py',0o400),('recovery.service',target_unit,0o644),*[( 'dependency.conf',user_units/(name+'.d')/'90-hilega-closed-pause-recovery.conf',0o644) for name in UNITS]]:
        need(not destination.exists() and not any(x.is_symlink() for x in [destination,*destination.parents]),'RECOVERY_TARGET_MUST_BE_ABSENT_REGULAR_PATH')
        entries.append(dict(payload='payload/'+source,destination=str(destination),new_sha256=sha(regular(payload/source)),old_sha256=None,mode=mode,parent_created_by_plan=not destination.parent.exists()))
    exact_files(entries)
    junit=output/'TESTS.xml';code=subprocess.run([sys.executable,'-B','-m','pytest','-q','-p','no:cacheprovider',str(here/'test_plan_tools.py'),'--junitxml='+str(junit)],cwd=root).returncode
    cases=list(ET.parse(junit).getroot().iter('testcase')) if junit.is_file() else [];need(code==0 and len(cases)==6 and all(c.find('failure') is None and c.find('error') is None and c.find('skipped') is None for c in cases),'INSTALL_PLAN_TESTS_FAILED')
    rehearsal=subprocess.run([sys.executable,'-B',str(here/'rehearse.py'),'--config',str(payload/'CONFIG.json'),'--output',str(output/'synthetic-recovery')],capture_output=True,text=True,timeout=210)
    save(output/'NATIVE-REHEARSAL.json',dict(exit_code=rehearsal.returncode,stdout=rehearsal.stdout,stderr=rehearsal.stderr));need(rehearsal.returncode==0,'NATIVE_PAUSE_ADAPTER_REHEARSAL_FAILED; inspect NATIVE-REHEARSAL.json')
    test_unit=output/'hilega-closed-pause-recovery.service';test_unit.write_bytes(regular(payload/'recovery.service'))
    checked=subprocess.run(['systemd-analyze','--user','verify',str(test_unit)],capture_output=True,text=True,timeout=20)
    save(output/'UNIT-SYNTAX.json',dict(exit_code=checked.returncode,stdout=checked.stdout,stderr=checked.stderr));need(checked.returncode==0,'RECOVERY_UNIT_SYNTAX_FAILED')
    now=datetime.now(timezone.utc)
    plan=dict(model='HILEGA_CLOSED_RECOVERY_INSTALL_PLAN_V1',repo=str(root),tool_manifest_sha256=sha(regular(here/'MANIFEST.json')),active_plan=str(active_path),active_plan_sha256=sha(active_raw),
        package_a_receipt_sha256=sha(prior_raw),created_at=now.isoformat(),apply_before=(now+timedelta(minutes=30)).isoformat(),
        expected_controller_version=control['version'],expected_session_date=control['session_date'],application_db=active['application_db'],adapter_db=active['adapter_db'],
        recovery_directory=str(recovery_dir),files=entries,observed_input_bindings=observed,observed_unit_paths=unit_paths,
        application_services_affected=list(UNITS),controller_resume_available=False,automatic_database_restore=False,
        rollback='STOP_SIX_SERVICES_REMOVE_ONLY_EXACT_NEW_FILES_RELOAD_START_ORIGINAL_CLOSED_RUNTIME',production_execution_enabled=False)
    save(output/'PLAN.json',plan);digest=sha(regular(output/'PLAN.json'))
    report=dict(status='CLOSED_RECOVERY_INSTALL_PLAN_PASS',plan=str(output/'PLAN.json'),plan_sha256=digest,new_targeted_cases=6,current_baseline_cases=10,
        native_recovery_synthetic_scenarios=2,recovery_unit_syntax_verified=True,exact_file_count=len(entries),application_services_to_quiesce=6,
        plan_apply_available=True,controller_resume_available=False,real_backups_created=False,recovery_installed=False,actual_vm_reboot_tested=False,
        services_changed=False,live_database_mutations_issued=False,production_execution_enabled=False,production_ready=False)
    save(output/'CHECK-VALIDATION.json',report);(here/'VM-VALIDATION.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
