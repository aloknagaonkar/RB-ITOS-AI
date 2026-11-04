"""Successor plan preparation against the currently installed Group 2 release."""
from datetime import datetime,timedelta,timezone
import fcntl
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import uuid


def prepare(a,root,here,lock_fd,old,m,h):
    need,regular,sha,save,load=h.need,h.regular,h.sha,h.save,h.load
    need(a.current_plan is not None and a.current_plan_sha256 and a.worker_review is not None and a.proposal_sha256,'CURRENT_PLAN_AND_POLICY_REVIEW_REQUIRED')
    current_path=a.current_plan.absolute();need(sha(regular(current_path))==a.current_plan_sha256,'CURRENT_PLAN_DIGEST_CHANGED')
    current=load(current_path)
    need(current['model']=='HILEGA_GROUP2_CLOSED_UPGRADE_V1' and current['repo']==str(root) and current['production_execution_enabled'] is False,'CURRENT_CLOSED_UPGRADE_REQUIRED')
    review=a.worker_review.absolute()
    need(review.parent==root and review.name.startswith('hilega-bootstrap-worker-review-'),'EXACT_POLICY_REVIEW_REQUIRED')
    receipt=load(review/'RESULT.json')
    need(receipt['status']=='CLOSED_WORKER_CLI_HANDOFF_AND_RESTART_CANDIDATE_PASS' and receipt['reexecuted_cases']==36
         and receipt['new_worker_cases']==3 and receipt['closed_handoff_process_qualified'] is True
         and receipt['installed_sources_modified'] is False and receipt['execution_factory_process_qualified'] is False,'PASSED_WORKER_CANDIDATE_REQUIRED')
    proposal_path=review/'DEPLOYMENT-PROPOSAL.json'
    need(sha(regular(proposal_path))==a.proposal_sha256==receipt['deployment_proposal_sha256'],'WORKER_PROPOSAL_CHANGED')
    proposal=load(proposal_path)
    need(proposal['predecessor_plan']==str(current_path) and proposal['predecessor_plan_sha256']==a.current_plan_sha256
         and proposal['production_execution_enabled'] is False and proposal['factory_enabled'] is False
         and proposal['local_handoff_config_deployed'] is False,'EXACT_CLOSED_WORKER_PROPOSAL_REQUIRED')
    source=Path(receipt['candidate']);need(source==review/'candidate','EXACT_WORKER_CANDIDATE_REQUIRED')
    digest=receipt['candidate_release_sha256'];h.verify_bundle(source,digest)
    need(digest=='7ff8f3e672b68a58945cb400aae278028e65dd7d5494d2454376ea795581235b'
         and proposal['candidate_release_sha256']==digest and proposal['rollback_release_sha256']==current['release_sha256'],'PASSED_RELEASE_AND_ROLLBACK_BINDING_REQUIRED')
    policy=load(source/'runtime/POSITION-POLICY.json')
    need(policy==dict(model='HILEGA_POSITION_POLICY_CANDIDATE_V1',max_simultaneous_positions=1,max_premium_per_entry_cents=None,
                     daily_loss_cutoff_cents=None,production_execution_enabled=False),'EXACT_USER_POSITION_POLICY_REQUIRED')
    gate='backend/market_lab/hilega_execution_port_v1/adapter.py'
    prior_manifest=h.verify_bundle(Path(current['destination']),current['release_sha256'])
    need(sha(regular(source/gate))==prior_manifest['files'][gate],'EXECUTION_GATE_CHANGE_FORBIDDEN')
    destination=root/'data/runtime/hilega-closed-releases'/digest
    need(not destination.exists() and not any(p.is_symlink() for p in (destination,*destination.parents)),'NEW_POLICY_RELEASE_DESTINATION_REQUIRED')
    output=Path(tempfile.mkdtemp(prefix='hilega-group2-upgrade-plan-',dir=root));output.chmod(0o700)
    (output/'.gitignore').write_text('*\n')
    h.atomic(output/'MILESTONES-BASE.md',regular(review/'MILESTONES.md'),0o600)
    status_command=[sys.executable,'-B',str(root/'hilega-worker-qualification-v1/manage.py'),'--repo',str(root),'--action','status',
                    '--plan',str(current_path),'--approve-plan-sha256',a.current_plan_sha256]
    def current_status(label):
        fcntl.flock(lock_fd,fcntl.LOCK_UN)
        try:
            r=subprocess.run(status_command,capture_output=True,text=True,timeout=100)
            save(output/(label+'.json'),dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr))
            need(r.returncode==0 and json.loads(r.stdout)['phase']=='CLOSED_GROUP2_CANDIDATE_RUNNING','CURRENT_RUNTIME_STATUS_FAILED; inspect '+str(output/(label+'.json'))+'; '+r.stderr[-3000:])
        finally:fcntl.flock(lock_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    current_status('CURRENT-STATUS-BEFORE')
    h.verify_inputs(current,installed=True)
    observed=dict(current['observed_bindings'])
    for entry in [*current['files'],*current['new_recovery_files']]:observed[entry['destination']]=entry['new_sha256']
    observed[str(current_path)]=a.current_plan_sha256
    observed[str(review/'RESULT.json')]=sha(regular(review/'RESULT.json'))
    observed[str(proposal_path)]=a.proposal_sha256
    observed[str(review/'TESTS.xml')]=sha(regular(review/'TESTS.xml'))
    import xml.etree.ElementTree as ET
    cases=list(ET.fromstring(regular(review/'TESTS.xml')).iter('testcase'))
    need(len(cases)==36 and all(all(c.find(t) is None for t in ['failure','error','skipped']) for c in cases),'PASSING_36_CASE_XML_REQUIRED')
    observed[str(output/'MILESTONES-BASE.md')]=sha(regular(output/'MILESTONES-BASE.md'))
    definitions=h.definitions([*m.UNITS,h.RECOVERY])
    for paths in definitions.values():
        for path in paths:observed[path]=sha(regular(Path(path)))
    for path,expected in observed.items():need(sha(regular(Path(path)))==expected,'CURRENT_BOUND_INPUT_CHANGED')
    payload=output/'payload';payload.mkdir(mode=0o700)
    worker=Path(next(entry['destination'] for entry in current['files'] if entry['payload']=='payload/worker.py'))
    new_wrapper=h.wrapper(destination,digest);h.atomic(payload/'worker.py',new_wrapper,0o600)
    config=dict(model='HILEGA_CLOSED_PAUSE_RECOVERY_CONFIG_V1',bundle=str(destination),release_manifest_sha256=digest,
                worker=str(worker),worker_sha256=sha(new_wrapper),application_db=current['application_db'],production_execution_enabled=False)
    save(payload/'CONFIG.json',config);config_sha=sha(regular(payload/'CONFIG.json'))
    directory=root/'data/runtime/hilega-closed-pause-recovery'/config_sha
    need(not directory.exists() and not any(p.is_symlink() for p in (directory,*directory.parents)),'NEW_RECOVERY_CONFIG_REQUIRED')
    h.atomic(payload/'live_recovery.py',regular(here/'live_recovery.py'),0o600)
    # Check the native recovery implementation against the changed candidate,
    # with a matching wrapper and only new disposable databases.
    synthetic_wrapper=payload/'synthetic-worker.py';h.atomic(synthetic_wrapper,h.wrapper(source,digest),0o600)
    synthetic_config=dict(config,bundle=str(source),worker=str(synthetic_wrapper),worker_sha256=sha(regular(synthetic_wrapper)))
    save(payload/'SYNTHETIC-CONFIG.json',synthetic_config)
    clean=dict(PATH=os.defpath,LANG='C.UTF-8',HOME=str(output),PYTHONDONTWRITEBYTECODE='1')
    # Exercise the exact new wrapper's no-activation boundary, using the
    # candidate path and fictional settings only. No live context is supplied.
    guard_results=[]
    for label,inline in [('environment',True),('dotenv',False)]:
        guard_env=dict(clean);args=[]
        if inline:guard_env['HILEGA_DISABLED_HANDOFF_CONFIG']='UNAPPROVED_SYNTHETIC_SETTING'
        else:
            probe=payload/'synthetic-activation.env'
            h.atomic(probe,b'HILEGA_DISABLED_HANDOFF_CONFIG=UNAPPROVED_SYNTHETIC_SETTING\n',0o600)
            args=['--env-file',str(probe)]
        r=subprocess.run([sys.executable,'-I','-B',str(synthetic_wrapper),*args],cwd=output,env=guard_env,capture_output=True,text=True,timeout=45)
        save(output/('WRAPPER-GUARD-'+label+'.json'),dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr))
        need(r.returncode!=0 and 'HANDOFF_ACTIVATION_NOT_APPROVED_FOR_CLOSED_DEPLOYMENT' in r.stderr,'CLOSED_WRAPPER_ACTIVATION_GUARD_FAILED: '+label)
        guard_results.append(label)

    launch='import sys,runpy;sys.path.insert(0,'+repr(str(here))+');runpy.run_path('+repr(str(here/'rehearse.py'))+',run_name="__main__")'
    r=subprocess.run([sys.executable,'-I','-B','-c',launch,'--config',str(payload/'SYNTHETIC-CONFIG.json'),'--output',str(output/'native-recovery')],
                     cwd=output,env=clean,capture_output=True,text=True,timeout=210)
    save(output/'NATIVE-RECOVERY.json',dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr))
    need(r.returncode==0,'POLICY_NATIVE_RECOVERY_FAILED: '+r.stderr[-3500:])
    native=json.loads(r.stdout);need(native['status']=='LIVE_ADAPTER_SYNTHETIC_REHEARSAL_PASS' and len(native['scenarios'])==2,'TWO_RECOVERY_SCENARIOS_REQUIRED')
    name='hilega-policy-worker-rehearsal-'+uuid.uuid4().hex+'.service';managed_output=output/'managed-disposable'
    cmd=['systemd-run','--user','--wait','--collect','--unit='+name,'--property=Type=oneshot','--property=NoNewPrivileges=yes',
         '--property=RestrictAddressFamilies=AF_UNIX','--property=RuntimeMaxSec=55','--property=UMask=0077','--working-directory='+str(output),
         '/usr/bin/env','-i','PATH='+os.defpath,'LANG=C.UTF-8','HOME='+str(output),'PYTHONDONTWRITEBYTECODE=1',
         sys.executable,'-I','-B',str(source/'rehearse.py'),'--release',str(source),'--output',str(managed_output)]
    r=subprocess.run(cmd,capture_output=True,text=True,timeout=65)
    save(output/'MANAGED-REHEARSAL.json',dict(unit=name,exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr))
    need(r.returncode==0,'MANAGED_POLICY_WORKER_FAILED: '+r.stderr[-3500:])
    need(load(managed_output/'RESULT.json')['status']=='ACTUAL_DISPOSABLE_CLOSED_WORKER_RESTART_PASS','ACTUAL_POLICY_WORKER_RESTART_REQUIRED')
    unit_raw=h.unit(sys.executable,str(directory/'live_recovery.py'),str(directory/'CONFIG.json'),config_sha)
    h.atomic(payload/'recovery.service',unit_raw,0o600)
    syntax=output/h.RECOVERY;h.atomic(syntax,unit_raw,0o600)
    h.command(['systemd-analyze','--user','verify',str(syntax)],timeout=20)
    recovery_unit=Path(next(e['destination'] for e in current['files'] if Path(e['destination']).name==h.RECOVERY))
    files=[]
    for target,filename in [(worker,'worker.py'),(recovery_unit,'recovery.service')]:
        mode=stat.S_IMODE(target.stat().st_mode)
        files.append(dict(destination=str(target),payload='payload/'+filename,old_sha256=sha(regular(target)),new_sha256=sha(regular(payload/filename)),old_mode=mode,mode=mode))
        observed[str(target)]=files[-1]['old_sha256']
    new_recovery=[dict(destination=str(directory/name),payload='payload/'+name,new_sha256=sha(regular(payload/name))) for name in ['CONFIG.json','live_recovery.py']]
    m.require_empty_closed_baseline(Path(current['application_db']),Path(current['adapter_db']))
    c=h.control(Path(current['application_db']));now=datetime.now(timezone.utc)
    plan=dict(model='HILEGA_GROUP2_CLOSED_UPGRADE_V1',repo=str(root),tool_manifest_sha256=sha(regular(here/'MANIFEST.json')),
              created_at=now.isoformat(),apply_before=(now+timedelta(minutes=30)).isoformat(),candidate=str(source),destination=str(destination),release_sha256=digest,
              old_bundle=current['destination'],old_release_sha256=current['release_sha256'],observed_bindings=observed,
              application_db=current['application_db'],adapter_db=current['adapter_db'],controller_version=c['version'],session_date=c['session_date'],
              recovery_directory=str(directory),files=files,new_recovery_files=new_recovery,unit_definitions=definitions,
              automatic_database_restore=False,execution_factory_configured=False,production_execution_enabled=False,position_policy=policy,
              predecessor_plan=str(current_path),predecessor_plan_sha256=a.current_plan_sha256)
    current_status('CURRENT-STATUS-AFTER');h.verify_inputs(plan,installed=False);h.verify_bundle(source,digest)
    need(h.control(Path(current['application_db']))['version']==c['version'],'CONTROLLER_CHANGED_DURING_REHEARSAL')
    save(output/'PLAN.json',plan);plan_sha=sha(regular(output/'PLAN.json'))
    report=dict(status='CLOSED_UPGRADE_CHECK_PASS',scope='CLOSED_INTEGRATED_BOOTSTRAP_WORKER_INSTALLATION',
                prior_worker_cases_passed=36,prior_worker_cases_reexecuted=False,
                transaction_engine_reused_from_verified_upgrade=True,
                managed_actual_worker_startup_and_restart_verified=True,native_recovery_scenarios=2,
                unapproved_handoff_configuration_blocked=True,wrapper_negative_scenarios=len(guard_results),
                max_simultaneous_positions=1,max_premium_per_entry_cents=None,daily_loss_cutoff_cents=None,
                factory_registration_enabled=False,local_handoff_configuration_deployed=False,
                execution_factory_process_qualified=False,production_trust_provisioned=False,
                rollback_target='CURRENT_DEPLOYED_GROUP2_RELEASE',rollback_release_sha256=current['release_sha256'],
                plan=str(output/'PLAN.json'),plan_sha256=plan_sha,apply_before=plan['apply_before'],apply_available=True,
                backups_created=False,installed_sources_modified=False,controller_resumed=False,
                production_execution_enabled=False,production_ready=False,group2_complete=False)
    save(output/'CHECK-VALIDATION.json',report);h.update_checklist(output,installed=False,phase='CLOSED_BOOTSTRAP_WORKER_DEPLOYMENT_PENDING')
    print(json.dumps(report,indent=2))
