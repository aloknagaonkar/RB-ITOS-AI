"""Exact coordinated warmup install/rollback and status. Execution remains closed."""
import argparse,copy,fcntl,importlib.util,json,os,shutil,sqlite3,stat,subprocess,sys,tempfile
from datetime import datetime,timedelta,timezone
from pathlib import Path
from file_transaction import need,sha,regular,atomic,apply_files,restore_files
sys.dont_write_bytecode=True
MODEL='HILEGA_WARMUP_PREVENTION_INSTALL_V1';RECOVERY='hilega-closed-pause-recovery.service'
def load(p):return json.loads(regular(p))
def save(p,v):atomic(p,(json.dumps(v,indent=2)+'\n').encode())
def command(argv,timeout=110):
    r=subprocess.run(argv,capture_output=True,text=True,timeout=timeout);need(r.returncode==0,'COMMAND_FAILED');return r

def milestone(folder,phase):
    installed=phase=='CLOSED_WARMUP_PREVENTION_RUNNING'
    text='''# Hilega milestone status\n\nEvidence carried forward from the VM session of 3 November 2026; these are not new market captures.\n\n- [x] Oct 30 warmup repaired: 375 one-minute / 75 five-minute bars.\n- [x] Current-session warmup monitor reported ready with 28 sessions on Nov 3.\n- [x] Closed runtime and companion recovered after incompatible writer rollback.\n- [x] Bounded REST quote evidence: 10 option contracts, three passing snapshots.\n- [x] Quote stream v2: 18 offline cases and after-hours deferral passed.\n- [ ] WebSocket feed and managed current-session observer qualified during open market.\n- [ ] Automatic quote observer startup for later sessions installed.\n- [x] Four-file prevention proposal and six binding cases passed.\n'''
    text+=('- [x]' if installed else '- [ ]')+' Coordinated prevention installed, managed consumers reloaded and warmup verified.\n'
    text+='''- [ ] Production strategy-specific contract admission/coverage verified.\n- [ ] Broker historical trade timestamp semantics confirmed.\n- [ ] Final fee components and per-trade attribution reconciled.\n- [ ] Real fresh disabled seed, signed ownership and enrollment completed.\n- [ ] Production authority/registration activation and final readiness approved.\n- [ ] Production execution enabled.\n\nInitial capacity: one position. Premium and daily loss caps remain unset; no policy changes.\n'''
    text+='\nMaintenance phase: `'+phase+'`. Controller paused; production execution disabled.\n'
    atomic(folder/'MILESTONES.md',text.encode())

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--repo',type=Path,required=True);ap.add_argument('--action',choices=['check','apply','status','rollback'],default='check');ap.add_argument('--active-plan',type=Path);ap.add_argument('--active-plan-sha256');ap.add_argument('--proposal',type=Path);ap.add_argument('--proposal-sha256');ap.add_argument('--plan',type=Path);ap.add_argument('--approve-plan-sha256');a=ap.parse_args()
    root=a.repo.absolute();here=Path(__file__).absolute().parent
    for n,h in load(here/'MANIFEST.json').items():need(sha(regular(here/n))==h,'MAINTENANCE_TOOL_CHANGED')
    for n,h in load(here/'BASELINE-PINS.json').items():need(sha(regular(root/n))==h,'MAINTENANCE_BASELINE_CHANGED')
    sys.path.insert(0,str(root/'hilega-registration-rollout-v1'));spec=importlib.util.spec_from_file_location('reviewed_registration',root/'hilega-registration-rollout-v1/manage.py');h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
    old,m=h.pinned_runtime(root);manager=m.Systemd()
    def stable(p,label):
        h.verify_bundle(Path(p['destination']),p['release_sha256']);old.wait_inventory(root);old.wait_health(Path(p['application_db']),'STATUS_OBSERVATION',manager,list(m.UNITS),timeout=35);m.require_empty_closed_baseline(Path(p['application_db']),Path(p['adapter_db']));command(['systemctl','--user','is-active','--quiet',RECOVERY],20)
    def verify_bindings(bindings):
        for name,digest in bindings.items():need(sha(regular(Path(name)))==digest,'BOUND_INPUT_CHANGED')
    def warmup(folder,label):
        code="import sys,json;sys.path.insert(0,sys.argv[1]);from datetime import datetime;from zoneinfo import ZoneInfo;from market_lab.operational_readiness_v1 import inspect_warmup;print(json.dumps(inspect_warmup(datetime.now(ZoneInfo('Asia/Kolkata')),repair=False)))"
        r=subprocess.run([sys.executable,'-B','-c',code,str(root/'backend')],cwd=root,capture_output=True,text=True,timeout=90);save(folder/(label+'.json'),dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr));need(r.returncode==0,'NATIVE_WARMUP_CHECK_FAILED');v=json.loads(r.stdout);need(v['ready'] is True and v['indicator_warmup_ready'] is True,'WARMUP_NOT_READY');return v
    def package_check(p,folder,label):
        cli=root/'hilega-operational-lifecycle-tools-6cexrur_/cli.py';r=subprocess.run([sys.executable,'-B',str(cli),'check','--repo',str(root)],capture_output=True,text=True,timeout=35);save(folder/(label+'.json'),dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr));need(r.returncode==0 and json.loads(r.stdout)['status']=='PACKAGE_AND_RUNTIME_CHECK_PASS','REFERENCE_PACKAGE_CHECK_FAILED')
    def quote_stopped():
        r=subprocess.run(['systemctl','--user','show','hilega-quote-observer.service','--property=MainPID','--value'],capture_output=True,text=True,timeout=10);need(not r.stdout.strip().isdigit() or int(r.stdout.strip())==0,'STOP_QUOTE_OBSERVER_BEFORE_MAINTENANCE')
    if a.action=='check':
        need(all((a.active_plan,a.active_plan_sha256,a.proposal,a.proposal_sha256)),'CURRENT_PLAN_AND_PROPOSAL_REQUIRED')
        parentpath=a.active_plan.absolute();need(sha(regular(parentpath))==a.active_plan_sha256,'PREDECESSOR_PLAN_CHANGED');current=load(parentpath)
        need(current['repo']==str(root) and current['production_execution_enabled'] is False,'CLOSED_CURRENT_PLAN_REQUIRED');h.verify_inputs(current,installed=True);stable(current,'BEFORE');quote_stopped()
        proposalpath=a.proposal.absolute();need(sha(regular(proposalpath))==a.proposal_sha256,'PROPOSAL_CHANGED');proposal=load(proposalpath)
        need(proposal['model']=='HILEGA_WARMUP_PREVENTION_COMPATIBILITY_PROPOSAL_V1' and proposal['active_plan_sha256']==a.active_plan_sha256 and proposal['candidate_cli_check_passed'] is True,'PASSING_BOUND_PROPOSAL_REQUIRED')
        rreceipt=load(proposalpath.parent/'RESULT.json');need(rreceipt['status']=='COORDINATED_WARMUP_PREVENTION_PROPOSAL_PASS' and rreceipt['binding_tests']==6 and rreceipt['candidate_package_runtime_check_passed'] is True,'PASSING_BINDING_RECEIPT_REQUIRED')
        verify_bindings(proposal['observed_source_hashes'])
        folder=Path(tempfile.mkdtemp(prefix='hilega-warmup-install-plan-',dir=root));folder.chmod(0o700);(folder/'payload').mkdir(mode=0o700)
        r=subprocess.run([sys.executable,'-B','-m','pytest','-q','-p','no:cacheprovider',str(here/'test_transaction.py')],capture_output=True,text=True,timeout=60);save(folder/'TRANSACTION-TESTS.json',dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr));need(r.returncode==0,'TRANSACTION_TESTS_FAILED');print(r.stdout,flush=True)
        before=dict(current['observed_bindings'])
        for e in [*current['files'],*current['new_recovery_files']]:before[e['destination']]=e['new_sha256']
        before[str(parentpath)]=a.active_plan_sha256;before[str(proposalpath)]=a.proposal_sha256
        defs=h.definitions([*m.UNITS,RECOVERY])
        for paths in defs.values():
            for name in paths:before[name]=sha(regular(Path(name)))
        # Bind the native read-only warmup inspector too, even if the prior plan did not list it.
        inspector=root/'backend/market_lab/operational_readiness_v1.py';before[str(inspector)]=sha(regular(inspector))
        changes=[];effective=dict(before)
        expected={str(root/'backend/market_lab/hilega_milega_historical_replay_v1.py'),str(root/'hilega-operational-lifecycle-tools-6cexrur_/manifest.json'),str(root/'hilega-operational-lifecycle-tools-6cexrur_/cli.py'),str(root/'hilega-reference-service-stage-yup3_wr1/lifecycle_reference_service.py')}
        need({e['path'] for e in proposal['files']}==expected,'EXACT_FOUR_FILE_CHANGE_REQUIRED')
        for i,e in enumerate(proposal['files']):
            target=Path(e['path']);need(sha(regular(target))==e['original_sha256'] and sha(regular(Path(e['candidate'])))==e['candidate_sha256'],'PROPOSED_INPUT_CHANGED')
            payload=folder/'payload'/str(i);atomic(payload,regular(Path(e['candidate'])));before[str(target)]=e['original_sha256'];effective[str(target)]=e['candidate_sha256']
            changes.append(dict(path=str(target),old_sha256=e['original_sha256'],new_sha256=e['candidate_sha256'],payload=str(payload),backup=str(folder/'backups'/('file-'+str(i))),mode=stat.S_IMODE(target.stat().st_mode)))
        verify_bindings(before);native=warmup(folder,'WARMUP-BEFORE');stable(current,'AFTER');h.verify_inputs(current,installed=True)
        now=datetime.now(timezone.utc);control=h.control(Path(current['application_db']))
        plan=dict(model=MODEL,repo=str(root),created_at=now.isoformat(),apply_before=(now+timedelta(minutes=30)).isoformat(),tool_manifest_sha256=sha(regular(here/'MANIFEST.json')),status_driver=str(here/'manage.py'),predecessor_plan=str(parentpath),predecessor_plan_sha256=a.active_plan_sha256,proposal=str(proposalpath),proposal_sha256=a.proposal_sha256,destination=current['destination'],release_sha256=current['release_sha256'],application_db=current['application_db'],adapter_db=current['adapter_db'],execution_factory_configured=False,production_execution_enabled=False,production_ready=False,controller_version=control['version'],session_date=control['session_date'],before_bindings=before,installed_bindings=effective,changes=changes,unit_definitions=defs,services=list(m.UNITS),automatic_database_restore=False,rollback_driver=str(here/'manage.py'),position_policy=current.get('position_policy'))
        save(folder/'PLAN.json',plan);digest=sha(regular(folder/'PLAN.json'));save(folder/'TRANSACTION.json',dict(phase='CHECKED_NOT_APPLIED'));milestone(folder,'CHECKED_NOT_APPLIED')
        report=dict(status='COORDINATED_WARMUP_INSTALL_CHECK_PASS',transaction_cases=6,prior_binding_cases=6,prior_18_writer_cases_reexecuted=False,native_warmup_ready=native['ready'],complete_warmup_sessions=native['complete_sessions'],plan=str(folder/'PLAN.json'),plan_sha256=digest,apply_before=plan['apply_before'],apply_available=True,live_backups_created=False,prevention_deployed=False,application_sources_modified=False,services_changed=False,controller_resumed=False,production_execution_enabled=False,production_ready=False,milestones=str(folder/'MILESTONES.md'),successor_status_driver=str(here/'manage.py'))
        save(folder/'CHECK-VALIDATION.json',report);print(json.dumps(report,indent=2));return
    need(a.plan and a.approve_plan_sha256,'EXACT_APPROVED_PLAN_REQUIRED');path=a.plan.absolute();need(sha(regular(path))==a.approve_plan_sha256,'APPROVED_PLAN_CHANGED');p=load(path);folder=path.parent
    need(p['model']==MODEL and p['repo']==str(root) and p['tool_manifest_sha256']==sha(regular(here/'MANIFEST.json')),'PLAN_SCOPE_CHANGED');check=load(folder/'CHECK-VALIDATION.json');need(check['plan_sha256']==a.approve_plan_sha256 and check['status']=='COORDINATED_WARMUP_INSTALL_CHECK_PASS','PASSING_PLAN_REQUIRED')
    tx=load(folder/'TRANSACTION.json');phase=tx['phase']
    if a.action=='status':
        need(phase in {'CLOSED_WARMUP_PREVENTION_RUNNING','ROLLED_BACK_RUNNING'},'RUNNING_MAINTENANCE_PHASE_REQUIRED');verify_bindings(p['installed_bindings'] if phase=='CLOSED_WARMUP_PREVENTION_RUNNING' else p['before_bindings']);stable(p,'STATUS');package_check(p,folder,'PACKAGE-STATUS');milestone(folder,phase)
        print(json.dumps(dict(phase=phase,prevention_deployed=phase=='CLOSED_WARMUP_PREVENTION_RUNNING',controller_resumed=False,production_execution_enabled=False,production_ready=False,milestones=str(folder/'MILESTONES.md')),indent=2));return
    quote_stopped();lock=root/'.hilega-closed-rollout.lock';need(not lock.is_symlink(),'REGULAR_MAINTENANCE_LOCK_REQUIRED');fd=os.open(lock,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'r+') as held:
        fcntl.flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB)
        installing=a.action=='apply'
        recovery_phase=phase in {'FAILED_SERVICES_STOPPED_REVIEW_SOURCE_BACKUPS','FAILURE_SERVICE_STATE_REQUIRES_REVIEW'}
        need(phase=='CHECKED_NOT_APPLIED' if installing else phase=='CLOSED_WARMUP_PREVENTION_RUNNING' or recovery_phase,'MAINTENANCE_PHASE_NOT_APPLICABLE')
        if installing:
            need(datetime.now(timezone.utc)<datetime.fromisoformat(p['apply_before']),'PLAN_EXPIRED_RECHECK_REQUIRED');need(h.control(Path(p['application_db']))['version']==p['controller_version'],'CONTROLLER_CHANGED_RECHECK_REQUIRED')
        if not installing and recovery_phase:
            changed={e['path'] for e in p['changes']}
            verify_bindings({k:v for k,v in p['before_bindings'].items() if k not in changed})
            for e in p['changes']:need(sha(regular(Path(e['path']))) in {e['old_sha256'],e['new_sha256']},'EXTERNAL_SOURCE_EDIT_BLOCKS_ROLLBACK')
        else:verify_bindings(p['before_bindings'] if installing else p['installed_bindings'])
        m.require_empty_closed_baseline(Path(p['application_db']),Path(p['adapter_db']))
        def mark(value,**extra):save(folder/'TRANSACTION.json',dict(phase=value,**extra));milestone(folder,value)
        def stopped():
            h.stop_services(m,manager);command(['systemctl','--user','stop',RECOVERY],30);m.no_unmanaged_python(root);m.require_empty_closed_baseline(Path(p['application_db']),Path(p['adapter_db']))
        def started():
            command(['systemctl','--user','start',RECOVERY],60);h.start_services(p,old,m,manager)
        mark('QUIESCING_FOR_INSTALL' if installing else 'QUIESCING_FOR_ROLLBACK');stopped()
        if installing:
            (folder/'backups').mkdir(mode=0o700);backup_hashes={}
            for e in p['changes']:
                data=regular(Path(e['path']));need(sha(data)==e['old_sha256'],'SOURCE_CHANGED_AFTER_QUIESCE');atomic(Path(e['backup']),data);backup_hashes[e['backup']]=sha(data)
            for key in ('application_db','adapter_db'):
                db=Path(p[key]);data=regular(db);backup=folder/'backups'/Path(key+'.sqlite');atomic(backup,data);need(regular(db)==data,'DATABASE_CHANGED_DURING_QUIESCENT_BACKUP');backup_hashes[str(backup)]=sha(data)
            save(folder/'BACKUPS.json',dict(files=backup_hashes,databases_quiescent=True,automatic_database_restore=False));mark('BACKED_UP_SERVICES_STOPPED')
        try:
            if installing:apply_files(p['changes'])
            else:restore_files(p['changes'])
            package_check(p,folder,'PACKAGE-AFTER-FILES');verify_bindings(p['installed_bindings'] if installing else p['before_bindings']);started();native=warmup(folder,'WARMUP-AFTER-RELOAD');stable(p,'POST-RELOAD')
            final='CLOSED_WARMUP_PREVENTION_RUNNING' if installing else 'ROLLED_BACK_RUNNING';mark(final,native_warmup_ready=native['ready'],complete_warmup_sessions=native['complete_sessions'])
        except Exception as exc:
            # Leave services stopped for exact source rollback; never restore databases automatically.
            try:stopped();mark('FAILED_SERVICES_STOPPED_REVIEW_SOURCE_BACKUPS')
            except Exception:mark('FAILURE_SERVICE_STATE_REQUIRES_REVIEW')
            raise
    print(json.dumps(dict(phase=final,prevention_deployed=installing,managed_consumers_reloaded=True,native_warmup_ready=native['ready'],controller_resumed=False,production_execution_enabled=False,production_ready=False,successor_plan=str(path),successor_plan_sha256=a.approve_plan_sha256,status_driver=str(here/'manage.py'),milestones=str(folder/'MILESTONES.md')),indent=2))
if __name__=='__main__':
    try:main()
    except Exception as exc:
        import re,traceback
        code=str(exc).split(':',1)[0];print(json.dumps(dict(status='WARMUP_MAINTENANCE_BLOCKED',reason=code if re.fullmatch('[A-Z][A-Z0-9_]*',code) else 'REVIEW_EXACT_AUDIT_BEFORE_RETRY',error_type=type(exc).__name__,location=[dict(file=Path(f.filename).name,line=f.lineno) for f in traceback.extract_tb(exc.__traceback__)[-3:]],automatic_database_restore=False,controller_resume_requested=False)));raise SystemExit(2)
