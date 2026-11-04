"""Read-only combined activation/recovery/enrollment dossier. No apply or resume action."""
import argparse,hashlib,hmac,json,os,sqlite3,stat,subprocess,sys,tempfile
from datetime import datetime,timezone
from pathlib import Path


def need(ok,reason):
    if not ok:raise ValueError(reason)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def regular(path):
    p=Path(path);need(p.is_absolute() and p.is_file() and not any(q.is_symlink() for q in (p,*p.parents)),'REGULAR_DOSSIER_INPUT_REQUIRED')
    return p.read_bytes()
def load(p):return json.loads(regular(p))
def save(p,v):
    fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:json.dump(v,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())


def run_status(command,folder,label):
    r=subprocess.run(command,capture_output=True,text=True,timeout=110)
    save(folder/(label+'.json'),dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr))
    need(r.returncode==0,'DOSSIER_BOUND_STATUS_FAILED: '+label)
    return json.loads(r.stdout)


def snapshot(path,tables,control=False):
    regular(path)
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
        db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
        names={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        result=dict(counts={t:db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] if t in names else None for t in tables})
        if control:
            result['control']=json.loads(db.execute('SELECT data FROM control WHERE id=1').fetchone()[0])
            stop=db.execute('SELECT generation,handled FROM sim_stop_state WHERE id=1').fetchone();result['stop_pending']=stop[0]!=stop[1]
            result['source_cursor']=json.loads(db.execute('SELECT data FROM preparation_source WHERE id=1').fetchone()[0])
            result['bridge_health']=json.loads(db.execute('SELECT data FROM sim_bridge_health WHERE id=1').fetchone()[0])
        return result


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--repo',type=Path,required=True)
    ap.add_argument('--active-plan',type=Path,required=True);ap.add_argument('--active-plan-sha256',required=True)
    ap.add_argument('--issuer-plan',type=Path,required=True);ap.add_argument('--issuer-plan-sha256',required=True)
    ap.add_argument('--evidence-review',type=Path,required=True);a=ap.parse_args()
    root=a.repo.absolute();here=Path(__file__).absolute().parent;active_path=a.active_plan.absolute();issuer_path=a.issuer_plan.absolute();review=a.evidence_review.absolute()
    for name,digest in load(here/'MANIFEST.json').items():need(sha(regular(here/name))==digest,'DOSSIER_PACKAGE_CHANGED')
    for name,digest in load(here/'BASELINE-PINS.json').items():need(sha(regular(root/name))==digest,'DOSSIER_BASELINE_CHANGED')
    need(sha(regular(active_path))==a.active_plan_sha256 and sha(regular(issuer_path))==a.issuer_plan_sha256,'DOSSIER_APPROVED_PLAN_CHANGED')
    active=load(active_path);issuer=load(issuer_path)
    need(active['repo']==str(root) and active['production_execution_enabled'] is False and issuer['active_plan']==str(active_path)
         and issuer['active_plan_sha256']==a.active_plan_sha256 and issuer['release_sha256']==active['release_sha256'],'DOSSIER_ACCOUNT_RELEASE_PLAN_MISMATCH')
    bundle=Path(active['destination']);manifest=load(bundle/'RELEASE-MANIFEST.json');need(sha(regular(bundle/'RELEASE-MANIFEST.json'))==active['release_sha256'],'DOSSIER_RELEASE_CHANGED')
    for name,digest in manifest['files'].items():
        rel=Path(name);need(not rel.is_absolute() and '..' not in rel.parts,'SAFE_DOSSIER_RELEASE_PATH_REQUIRED')
        need(sha(regular(bundle/rel))==digest,'DOSSIER_RELEASE_FILE_CHANGED')
    folder=Path(tempfile.mkdtemp(prefix='hilega-activation-dossier-',dir=root));folder.chmod(0o700);(folder/'.gitignore').write_text('*\n')
    runtime_cmd=[sys.executable,'-B',str(root/'hilega-registration-rollout-v1/manage.py'),'--repo',str(root),'--action','status','--plan',str(active_path),'--approve-plan-sha256',a.active_plan_sha256]
    issuer_cmd=[sys.executable,'-B',str(root/'hilega-issuer-provision-v1/manage.py'),'--repo',str(root),'--action','status','--plan',str(issuer_path),'--approve-plan-sha256',a.issuer_plan_sha256]
    runtime=run_status(runtime_cmd,folder,'RUNTIME-BEFORE');material=run_status(issuer_cmd,folder,'ISSUER-STATUS')
    need(runtime['phase']=='CLOSED_GROUP2_CANDIDATE_RUNNING' and material['status']=='REAL_ISSUER_MATERIAL_PREPARED_REGISTRY_DISABLED'
         and material['registry_enabled'] is False and material['account_scope']==issuer['account_scope'],'CLOSED_ISSUER_AND_RUNTIME_REQUIRED')
    prior=load(review/'RESULT.json');need(prior['historical_capture_completed'] is True and prior['source_process_stable'] is True,'VERIFIED_PREREQUISITE_CAPTURE_REQUIRED')
    # Recover the pin location only, without reading the .env or broker token.
    pid=subprocess.check_output(['systemctl','--user','show','hilega-production-source-worker.service','--property=MainPID','--value'],text=True,timeout=10).strip()
    need(pid.isdigit() and int(pid)>0,'DOSSIER_RUNNING_SOURCE_REQUIRED');proc=Path('/proc')/pid
    need(proc.stat().st_uid==os.getuid() and (proc/'cwd').resolve()==root,'DOSSIER_SOURCE_IDENTITY_CHANGED')
    env={k.decode():v.decode() for item in (proc/'environ').read_bytes().split(b'\0') if b'=' in item for k,v in [item.split(b'=',1)]}
    need(env.get('HILEGA_PRODUCTION_EXECUTION_ROUTE')=='PREPARATION_ONLY','DOSSIER_CLOSED_ROUTE_REQUIRED')
    pin_path=Path(env.get('HILEGA_PREPARATION_PIN_FILE',str(Path(env.get('HOME',str(Path.home())))/'hilega-private/upstox-account-pin.json')))
    source_flags={name:env.get(name) for name in ['HILEGA_PREPARATION_CAPTURE_ON_SIGNAL','HILEGA_PREPARATION_ATOMIC_BINDING_ENABLED']}
    attachment_present=any(name in env for name in ['HILEGA_FACTORY_ATTACHMENT_FILE','HILEGA_FACTORY_ATTACHMENT_SHA256','HILEGA_DISABLED_HANDOFF_CONFIG','HILEGA_DISABLED_HANDOFF_CONFIG_SHA256']);del env
    sys.dont_write_bytecode=True;sys.path[:0]=[str(bundle/'backend'),str(bundle/'runtime')]
    from market_lab import hilega_production_account_adapter_v1 as api
    from market_lab.hilega_execution_port_v1 import adapter as port
    try:port.require_live_clearance()
    except port.GateClosed:pass
    else:raise ValueError('DOSSIER_REQUIRES_HARD_GATE_CLOSED')
    pin=api.read_pin(pin_path);proof_path=review/'PRIVATE-POSTTRADE-EVIDENCE.json';proof=load(proof_path);signature=proof.pop('signature',None)
    need(isinstance(signature,str) and hmac.compare_digest(signature,api.sign(proof,pin)) and proof['account_scope']==issuer['account_scope']==pin['scope'],'DOSSIER_EVIDENCE_SIGNATURE_OR_SCOPE_CHANGED')
    finance=proof['review'];at=datetime.fromisoformat(proof['completed_at']);need(at.tzinfo is not None,'AWARE_EVIDENCE_TIME_REQUIRED')
    age=(datetime.now(timezone.utc)-at).total_seconds();need(age>=0,'FUTURE_DOSSIER_EVIDENCE')
    app=snapshot(Path(active['application_db']),['preparation_plans','preparation_shadow_holds','preparation_outbox','preparation_request_bindings','preparation_cash_reservations','preparation_candidate_exclusive_source_owner_v1','intents'],True)
    adapter=snapshot(Path(active['adapter_db']),['requests','attempts','receipts'])
    need(app['control']['mode']=='PAUSED' and not app['stop_pending'] and all(v in (None,0) for v in [*app['counts'].values(),*adapter['counts'].values()]),'DOSSIER_PAUSED_EMPTY_BASELINE_REQUIRED')
    registration=load(bundle/'runtime/FACTORY-REGISTRATION.json');need(registration['enabled'] is False and not attachment_present,'DOSSIER_DISABLED_REGISTRATION_REQUIRED')
    snapshots=dict(application=app,adapter=adapter,independent_database_snapshots_not_cross_database_atomic=True,source_configuration_flags=source_flags)
    save(folder/'STATE-SNAPSHOT.json',snapshots)
    bindings=dict(release_sha256=active['release_sha256'],active_plan=str(active_path),active_plan_sha256=a.active_plan_sha256,
        issuer_plan=str(issuer_path),issuer_plan_sha256=a.issuer_plan_sha256,issuer_id=material['issuer_id'],key_file=material['key_file'],key_sha256=material['key_sha256'],
        registry_file=material['registry_file'],registry_sha256=material['registry_sha256'],registry_enabled=False,
        wrapper_and_recovery_files=[dict(path=e['destination'],sha256=e['new_sha256']) for e in [*active['files'],*active['new_recovery_files']]],
        unit_definitions=active['unit_definitions'],evidence_file=str(proof_path),evidence_sha256=sha(regular(proof_path)),evidence_age_seconds=round(age,3))
    save(folder/'EXACT-BINDINGS.json',bindings)
    blockers=[]
    if not prior.get('broker_timezone_contract_confirmed'):blockers.append('BROKER_TIMESTAMP_CONTRACT_NOT_CONFIRMED')
    if not finance.get('broker_report_finality_verified'):blockers.append('FINAL_BROKER_REPORT_NOT_VERIFIED')
    if not finance.get('actual_fees_reconciled') or not finance.get('per_trade_fee_attribution_verified'):blockers.append('FINAL_PER_TRADE_FEES_NOT_RECONCILED')
    if not finance.get('strategy_ownership_verified'):blockers.append('EXISTING_ACCOUNT_ACTIVITY_OWNERSHIP_NOT_VERIFIED')
    if not (finance.get('historical_trade_corroboration') or {}).get('full_contract_identity_verified'):blockers.append('FULL_CONTRACT_IDENTITY_NOT_VERIFIED')
    if age>86400:blockers.append('ACCOUNT_EVIDENCE_REFRESH_REQUIRED')
    stages=[
        dict(step=1,name='Resolve external account evidence',available_now=False,required=blockers),
        dict(step=2,name='Approve exact bounded preparation window',available_now=False,required=['IMPLEMENT_AND_REVIEW_LIVE_WINDOW_PLAN','INDEPENDENT_DEADLINE_GUARD_AND_NATIVE_PAUSE_RECOVERY','FRESH_LIVE_ACCOUNT_MARKET_PREFLIGHT']),
        dict(step=3,name='Capture one natural fresh disabled preparation then pause',available_now=False,required=['ONE_POST_RESUME_CONFIRMED_SIGNAL','ATOMIC_REQUEST_BINDING_AND_SIGNED_LOCAL_RESERVATION','NO_SOURCE_CURSOR_REWIND_OR_SIGNAL_REPLAY']),
        dict(step=4,name='Approve and enroll the exact disabled seed',available_now=False,required=['FRESH_PAUSED_SEED_AND_DURABLE_HANDOFF','EXACT_SIGNED_LOCAL_APPROVAL','SAME_KEY_COMMIT_RECOVERY','NO_ORDER_ATTEMPT']),
        dict(step=5,name='Enable reviewed registry/registration attachment',available_now=False,required=['EXACT_SEED_CONTEXT_OWNER_LEASE_HASHES','EXACT_WRAPPER_ENVIRONMENT_AND_RECOVERY_APPROVAL','EXPLICIT_SIGNED_GRANT_AND_ATTACHMENT_EXPIRY']),
        dict(step=6,name='Release hard gate and perform controlled live activation',available_now=False,required=['SEPARATE_GATE_RELEASE_REVIEW','FINAL_OPERATIONAL_REGRESSION_AND_MONITORING','ONE_POSITION_POLICY','NATIVE_PAUSE_EXIT_UNKNOWN_ORDER_RECOVERY'])]
    proposal=dict(model='HILEGA_ACTIVATION_RECOVERY_ENROLLMENT_DOSSIER_V1',prepared_at=datetime.now(timezone.utc).isoformat(),bindings=bindings,
        existing_evidence_blockers=blockers,stages=stages,exact_live_seed_fields=dict(seed_request_id=None,source_record_hash=None,bridge_run_id=None,private_context_sha256=None,owner_row_sha256=None),
        proposed_bounded_window_seconds=300,window_duration_not_approved=True,automatic_key_rotation=False,automatic_lease_migration=False,
        recovery_policy=['PAUSE_ON_STARTUP','PAUSE_ON_GUARD_LOSS_TIMEOUT_EXPIRY_OR_INVALID_AUTHORITY','NEVER_RESUBMIT_UNKNOWN_ORDER','NEVER_AUTOMATICALLY_RESTORE_DATABASE_OR_REWIND_CURSOR'],
        apply_available=False,controller_resume_available=False,registry_enable_available=False,live_enrollment_available=False,production_execution_enabled=False)
    save(folder/'COMBINED-WORKFLOW.json',proposal)
    after=run_status(runtime_cmd,folder,'RUNTIME-AFTER');need(after['phase']==runtime['phase'],'DOSSIER_RUNTIME_CHANGED')
    final=snapshot(Path(active['application_db']),[],True)
    need(final['control']['mode']=='PAUSED' and final['control']['version']==app['control']['version'] and not final['stop_pending'],'DOSSIER_CONTROL_CHANGED_DURING_REVIEW')
    report=dict(status='ACTIVATION_RECOVERY_ENROLLMENT_DOSSIER_PREPARED_BLOCKED',closed_release_verified=True,real_issuer_material_verified=True,
        registry_enabled=False,controller_paused=True,live_owner_enrolled=False,existing_evidence_blockers=blockers,
        workflow=str(folder/'COMBINED-WORKFLOW.json'),workflow_sha256=sha(regular(folder/'COMBINED-WORKFLOW.json')),
        exact_bindings=str(folder/'EXACT-BINDINGS.json'),apply_available=False,live_enrollment_available=False,
        real_key_created_or_rotated=False,live_database_mutations_issued=False,application_services_changed=False,
        broker_requests_issued=False,production_execution_enabled=False,production_ready=False,group2_complete=False,audit_folder=str(folder))
    save(folder/'RESULT.json',report)
    text='# Combined live flow — current blockers and remaining implementation\n\n- [x] Closed release and real disabled issuer verified.\n- [x] Exact wrapper/recovery/key/registry/evidence bindings recorded.\n- [x] Combined activation/enrollment sequence prepared.\n'
    text+='\nExternal evidence still needed:\n'+''.join('- [ ] '+b+'\n' for b in blockers)
    text+='\nRemaining live implementation/approval:\n'+''.join('- [ ] '+s['name']+'\n' for s in stages[1:])
    text+='\nThis dossier is not an executable activation or preparation-window plan. No controller resume or registry enablement occurred.\n'
    (folder/'MILESTONES.md').write_text(text);(folder/'MILESTONES.md').chmod(0o600)
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
