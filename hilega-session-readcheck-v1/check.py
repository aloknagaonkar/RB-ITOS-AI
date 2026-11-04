"""Current-session GET-only account validation; no resume, enrollment, service control or orders."""
import argparse,hashlib,importlib.util,json,os,re,sqlite3,subprocess,sys,tempfile
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from readiness import collect


def need(ok,reason):
    if not ok:raise ValueError(reason)
def regular(path):
    p=Path(path);need(p.is_absolute() and p.is_file() and not any(q.is_symlink() for q in (p,*p.parents)),'REGULAR_SESSION_CHECK_INPUT_REQUIRED')
    return p.read_bytes()
def sha(raw):return hashlib.sha256(raw).hexdigest()
def save(path,value):
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:json.dump(value,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--repo',type=Path,required=True)
    ap.add_argument('--active-plan',type=Path,required=True);ap.add_argument('--active-plan-sha256',required=True);a=ap.parse_args()
    root=a.repo.absolute();here=Path(__file__).absolute().parent;path=a.active_plan.absolute()
    for name,h in json.loads(regular(here/'MANIFEST.json')).items():need(sha(regular(here/name))==h,'SESSION_CHECK_PACKAGE_CHANGED')
    for name,h in json.loads(regular(here/'BASELINE-PINS.json')).items():need(sha(regular(root/name))==h,'SESSION_CHECK_BASELINE_CHANGED')
    need(sha(regular(path))==a.active_plan_sha256,'SESSION_CHECK_ACTIVE_PLAN_CHANGED');plan=json.loads(regular(path))
    need(plan['repo']==str(root) and plan['production_execution_enabled'] is False,'CLOSED_SESSION_PLAN_REQUIRED')
    out=Path(tempfile.mkdtemp(prefix='hilega-session-readcheck-',dir=root));out.chmod(0o700);(out/'.gitignore').write_text('*\n')
    def status(label):
        r=subprocess.run([sys.executable,'-B',str(root/'hilega-registration-rollout-v1/manage.py'),'--repo',str(root),'--action','status','--plan',str(path),'--approve-plan-sha256',a.active_plan_sha256],capture_output=True,text=True,timeout=110)
        save(out/(label+'.json'),dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr))
        need(r.returncode==0 and json.loads(r.stdout)['phase']=='CLOSED_GROUP2_CANDIDATE_RUNNING','SESSION_CHECK_CLOSED_RUNTIME_REQUIRES_REVIEW')
    status('STATUS-BEFORE')
    # Reuse the pinned, deployed-context identity reader. No issuer creation,
    # root enablement or other action entrypoint is called.
    source=root/'hilega-issuer-provision-v1';sys.path.insert(0,str(source))
    spec=importlib.util.spec_from_file_location('session_identity_reader',source/'manage.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    started=datetime.now(timezone.utc);summary=None;blocked=None;stable=None
    try:
        identity=module.identity(root,plan);api=identity['api'];pin=identity['pin'];pid=identity['pid']
        from market_lab import hilega_production_broker_observation_v1 as observation
        need(api.Client is observation.Client,'CANONICAL_GET_ONLY_CLIENT_REQUIRED')
        with sqlite3.connect(Path(plan['adapter_db']).as_uri()+'?mode=ro',uri=True) as db:
            db.execute('PRAGMA query_only=ON');meta=json.loads(db.execute('SELECT data FROM meta WHERE id=1').fetchone()[0])
            need(meta==dict(scope=pin['scope'],mode='LIVE_CLOSED'),'SESSION_ACCOUNT_ADAPTER_SCOPE_CHANGED')
        client=api.Client(identity['forbidden'][1].decode());del identity['forbidden']
        evidence,summary=collect(client,pin,api,observation)
        save(out/'PRIVATE-SIGNED-CURRENT-ACCOUNT-CASH.json',evidence)
        summary['nonterminal_order_count']=sum(o['status'] not in {'FILLED','CANCELLED','REJECTED'} for o in evidence['account_capture']['orders'])
        summary['session_date_ist']=datetime.now(ZoneInfo('Asia/Kolkata')).date().isoformat()
        stable=pid==int(subprocess.check_output(['systemctl','--user','show','hilega-production-source-worker.service','--property=MainPID','--value'],text=True,timeout=10).strip())
        need(stable,'SOURCE_RESTARTED_DURING_SESSION_CAPTURE')
        del client,pin
    except Exception as exc:
        reason=str(exc);blocked=dict(reason=reason if re.fullmatch(r'[A-Z][A-Z0-9_]{0,159}',reason) else 'CURRENT_BROKER_CAPTURE_REQUIRES_REVIEW',error_type=type(exc).__name__)
    status('STATUS-AFTER')
    counts={};control=None
    for key,tables in [('application_db',['preparation_plans','preparation_shadow_holds','preparation_outbox','preparation_request_bindings','preparation_cash_reservations','preparation_candidate_exclusive_source_owner_v1','intents']),('adapter_db',['requests','attempts','receipts'])]:
        with sqlite3.connect(Path(plan[key]).as_uri()+'?mode=ro',uri=True) as db:
            db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
            for table in tables:
                counts[key+'.'+table]=db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] if db.execute('SELECT 1 FROM sqlite_master WHERE type=\'table\' AND name=?',(table,)).fetchone() else None
            if key=='application_db':control=json.loads(db.execute('SELECT data FROM control WHERE id=1').fetchone()[0])
    report=dict(status='CURRENT_SESSION_READ_CAPTURE_REVIEW_REQUIRED' if summary is not None and blocked is None else 'CURRENT_SESSION_READ_BLOCKED',
        started_at=started.isoformat(),completed_at=datetime.now(timezone.utc).isoformat(),broker_summary=summary,blocked=blocked,source_process_stable=stable,
        controller_mode=control['mode'],local_counts=counts,independent_database_snapshots_not_cross_database_atomic=True,
        manual_activity_confirmation_scope='2026-11-02_ONLY',current_session_activity_ownership_verified=False,
        option_quote_and_warmup_readiness_verified=False,broker_timestamp_contract_confirmed=False,actual_fees_reconciled=False,
        registry_enabled_or_changed=False,controller_resumed=False,live_database_mutations_issued=False,application_services_changed=False,
        orders_sent=False,production_execution_enabled=False,production_ready=False,group2_complete=False,audit_folder=str(out))
    save(out/'RESULT.json',report);print(json.dumps(report,indent=2));return 0 if blocked is None else 2


if __name__=='__main__':raise SystemExit(main())
