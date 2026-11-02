"""Combined read-only snapshot and bounded preparation-window proposal."""
import argparse,hashlib,json,sqlite3,subprocess,sys,tempfile
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from window_review import assess

def need(ok,reason):
    if not ok:raise ValueError(reason)

def regular(p):
    need(p.is_file() and not any(x.is_symlink() for x in [p,*p.absolute().parents]),'REGULAR_INPUT_REQUIRED');return p.read_bytes()

def sha(raw):return hashlib.sha256(raw).hexdigest()

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--repo',type=Path,required=True);args=ap.parse_args()
    root=args.repo.absolute();here=Path(__file__).absolute().parent
    for n,h in json.loads(regular(here/'MANIFEST.json')).items():need(sha(regular(here/n))==h,'REVIEW_PACKAGE_CHANGED')
    need(subprocess.run([sys.executable,'-B','-m','pytest','-q','-p','no:cacheprovider',str(here/'test_review.py')]).returncode==0,'REVIEW_TESTS_FAILED')
    receipt=json.loads(regular(root/'hilega-group1-cache-recovery-v1/VM-VALIDATION.json'))
    path=Path(receipt['active_plan']);raw=regular(path);digest=receipt['active_plan_sha256'];need(sha(raw)==digest,'ACTIVE_PLAN_CHANGED');plan=json.loads(raw)
    tool=root/'hilega-group1-rollout-v1';manifest=regular(tool/'MANIFEST.json');need(sha(manifest)==plan['tool_manifest_sha256'],'ROLLOUT_TOOL_CHANGED')
    for n,h in json.loads(manifest).items():need(sha(regular(tool/n))==h,'ROLLOUT_SOURCE_CHANGED')
    r=subprocess.run([sys.executable,'-B',str(tool/'manage.py'),'--repo',str(root),'--action','status','--plan',str(path),'--approve-plan-sha256',digest],capture_output=True,text=True,timeout=60)
    need(r.returncode==0 and json.loads(r.stdout)['phase']=='CLOSED_BUNDLE_RUNNING','CLOSED_DEPLOYMENT_CHECK_FAILED')
    bundle=Path(plan['destination'])
    pins=json.loads(regular(here/'SOURCE-PINS.json'))
    for name,h in pins.items():need(sha(regular(bundle/name))==h,'RESUME_CONTRACT_SOURCE_CHANGED: '+name)
    snapshots=[];counts={};control={};allocation=None;health={}
    for kind,key,names in [('application','application_db',[
        'preparation_plans','preparation_shadow_holds','preparation_outbox','preparation_request_bindings',
        'preparation_cash_reservations','preparation_candidate_exclusive_source_owner_v1','intents','sim_allocation_reservations']),
        ('adapter','adapter_db',['requests','attempts','receipts'])]:
        dbpath=Path(plan[key]);regular(dbpath);db=sqlite3.connect(dbpath.as_uri()+'?mode=ro',uri=True)
        try:
            db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
            tables={x[0] for x in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for name in names:counts[kind+'.'+name]=db.execute('SELECT COUNT(*) FROM "'+name+'"').fetchone()[0] if name in tables else None
            if kind=='application':
                def read(name):
                    if name not in tables:return None
                    row=db.execute('SELECT data FROM "'+name+'" WHERE id=1').fetchone();return json.loads(row[0]) if row else None
                control=read('control') or {};allocation=read('sim_allocation_config');health=read('sim_bridge_health') or {}
                cursor=read('preparation_source') or {}
        finally:db.close()
    now=datetime.now(ZoneInfo('Asia/Kolkata'))
    try:
        at=datetime.fromisoformat(health['heartbeat_at']);healthy=health.get('phase')=='RUNNING' and not health.get('problem') and 0<=(now-at).total_seconds()<=30
    except (KeyError,TypeError,ValueError):healthy=False
    review=assess(control,counts,allocation,now=now,bridge_healthy=healthy)
    report=dict(status='PREPARATION_WINDOW_REVIEW_ONLY',new_test_cases=8,assessed_at=now.isoformat(),
        active_plan_sha256=digest,control_mode=control.get('mode'),control_version=control.get('version'),
        source_sequence=cursor.get('sequence'),counts=counts,resume_contract_sources_verified=True,
        independently_snapshotted_databases_not_cross_database_atomic=True,review=review,
        application_sql_mutations_issued=False,service_control_commands_issued=False,
        secret_material_created=False,live_database_enrolled=False,production_ready=False)
    folder=Path(tempfile.mkdtemp(prefix='hilega-group2-window-review-',dir=root));folder.chmod(0o700);(folder/'.gitignore').write_text('*\n')
    output=json.dumps(report,indent=2)+'\n';(folder/'WINDOW-REVIEW.json').write_text(output);(here/'VM-VALIDATION.json').write_text(output)
    print(output);print('Review:',folder);return 0
if __name__=='__main__':raise SystemExit(main())
