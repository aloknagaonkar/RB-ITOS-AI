"""Read existing market evidence only. Writes only a new private audit folder."""
import argparse, hashlib, importlib.util, json, math, os, sqlite3, subprocess, sys, tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
sys.dont_write_bytecode=True
IST=ZoneInfo('Asia/Kolkata')
def need(ok,reason):
    if not ok: raise ValueError(reason)
def raw(p):
    p=Path(p);need(p.is_file() and not any(q.is_symlink() for q in (p,*p.parents)), 'REGULAR_INPUT_REQUIRED')
    return p.read_bytes()
def digest(b):return hashlib.sha256(b).hexdigest()
def load(p):return json.loads(raw(p))
def age(stamp,now):
    try:
        t=datetime.fromisoformat(stamp);need(t.tzinfo is not None,'AWARE_TIMESTAMP_REQUIRED')
        return (now-t).total_seconds()
    except (ValueError,TypeError):return None
def fresh(stamp,now,limit):
    a=age(stamp,now);return a is not None and 0<=a<=limit
def positive(v):return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) and v>0
def cached(p):
    if not p.exists():return None
    return load(p)
def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repo',type=Path,required=True);ap.add_argument('--active-plan',type=Path,required=True)
    ap.add_argument('--active-plan-sha256',required=True);a=ap.parse_args()
    root=a.repo.absolute();here=Path(__file__).absolute().parent;planpath=a.active_plan.absolute()
    for name,h in load(here/'MANIFEST.json').items():need(digest(raw(here/name))==h,'PACKAGE_CHANGED')
    for name,h in load(here/'BASELINE-PINS.json').items():need(digest(raw(root/name))==h,'BASELINE_CHANGED')
    need(digest(raw(planpath))==a.active_plan_sha256,'ACTIVE_PLAN_CHANGED');plan=load(planpath)
    need(plan['repo']==str(root) and plan['production_execution_enabled'] is False,'CLOSED_PLAN_REQUIRED')
    out=Path(tempfile.mkdtemp(prefix='hilega-market-readiness-',dir=root));out.chmod(0o700)
    def save(name,value):
        fd=os.open(out/name,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,'w') as f:json.dump(value,f,indent=2);f.write('\n')
    def status(label):
        r=subprocess.run([sys.executable,'-B',str(root/'hilega-registration-rollout-v1/manage.py'),'--repo',str(root),'--action','status','--plan',str(planpath),'--approve-plan-sha256',a.active_plan_sha256],capture_output=True,text=True,timeout=110)
        save(label+'.json',dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr))
        need(r.returncode==0 and json.loads(r.stdout)['phase']=='CLOSED_GROUP2_CANDIDATE_RUNNING','CLOSED_RUNTIME_REQUIRED')
    status('STATUS-BEFORE')
    # This entrypoint verifies the sealed release only; identity/token readers are not called.
    folder=root/'hilega-issuer-provision-v1';sys.path.insert(0,str(folder))
    spec=importlib.util.spec_from_file_location('market_release_reader',folder/'manage.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    bundle=m.verify_release(plan);sys.path[:0]=[str(bundle/'backend'),str(bundle/'runtime')]
    now=datetime.now(IST);issues=[]
    journal=root/'data/live-observation/hilega-directional-v1/step-audit.jsonl'
    source=dict(verified=False,source_fresh=False)
    try:
        raw(journal) # reject symlinks before native journal reader
        from market_lab.hilega_production_simulator_bridge_v1 import verified_records,POLICY,VERSION
        from market_lab.hilega_production_bridge_health_v1 import source_timestamp
        records=verified_records(journal);stamp=source_timestamp(records,POLICY,VERSION)
        source=dict(verified=True,policy=POLICY,version=VERSION,source_at=stamp,source_age_seconds=age(stamp,now),source_fresh=fresh(stamp,now,390),source_session_is_today=bool(stamp and datetime.fromisoformat(stamp).astimezone(IST).date()==now.date()),records_checked=len(records),natural_entry_signal_required_for_this_check=False)
        if not(source['source_fresh'] and source['source_session_is_today']):issues.append('CURRENT_SOURCE_NOT_FRESH')
    except Exception as e:
        source['error_type']=type(e).__name__;issues.append('SOURCE_JOURNAL_REVIEW_REQUIRED')
    monitor=cached(root/'data/live-observation/operational-readiness-v1/state.json') or {}
    w=monitor.get('warmup') or {}
    warmup=dict(cached_monitor_fresh=fresh(monitor.get('checked_at'),now,45),cached_monitor_checked_at=monitor.get('checked_at'),cached_warmup={k:w.get(k) for k in ('checked_at','session_date','complete_sessions','indicator_warmup_ready','ready','issues')},independently_recomputed=False,cache_repair_attempted=False)
    warmup['cached_current_warmup_ready']=bool(warmup['cached_monitor_fresh'] and w.get('session_date')==now.date().isoformat() and w.get('ready') is True and w.get('indicator_warmup_ready') is True)
    if not warmup['cached_current_warmup_ready']:issues.append('CURRENT_WARMUP_EVIDENCE_UNAVAILABLE_OR_NOT_READY')
    snap=cached(root/'data/live-observation/hilega-strike-observation-v1/active-live-quotes.json') or {}
    quotes=snap.get('quotes') or {};need(isinstance(quotes,dict),'QUOTE_MAP_SCHEMA_REQUIRED')
    rows=[]
    for key,q in quotes.items():
        if not isinstance(q,dict):continue
        live=fresh(q.get('feed_timestamp'),now,10)
        bid,ask=q.get('bid'),q.get('ask');lot=q.get('lot_size');expiry=q.get('expiry')
        rows.append(dict(instrument_key=key,feed_timestamp=q.get('feed_timestamp'),age_seconds=age(q.get('feed_timestamp'),now),fresh=live,ltp_positive=positive(q.get('ltp')),two_sided_book_valid=positive(bid) and positive(ask) and bid<=ask and positive(q.get('bid_quantity')),positive_integer_lot=isinstance(lot,int) and not isinstance(lot,bool) and lot>0,expiry_present=isinstance(expiry,str) and bool(expiry),timestamp_basis=q.get('timestamp_basis')))
    quote_report=dict(snapshot_at=snap.get('generated_at'),snapshot_fresh=fresh(snap.get('generated_at'),now,10),stream_connected=snap.get('stream_connected') is True,observed_contract_count=len(rows),contracts=rows,required_strategy_contract_coverage_verified=False,subscription_requests_written=False,broker_quote_requests_issued=False)
    quote_report['fresh_observed_quote_count']=sum(r['fresh'] and r['ltp_positive'] and r['two_sided_book_valid'] and r['positive_integer_lot'] and r['expiry_present'] for r in rows) if quote_report['snapshot_fresh'] and quote_report['stream_connected'] else 0
    if not quote_report['fresh_observed_quote_count']:issues.append('NO_FRESH_COMPLETE_OBSERVED_OPTION_QUOTE')
    issues.append('REQUIRED_STRATEGY_CONTRACT_COVERAGE_NOT_VERIFIED')
    with sqlite3.connect(Path(plan['application_db']).as_uri()+'?mode=ro',uri=True) as db:
        db.execute('PRAGMA query_only=ON');control=json.loads(db.execute('SELECT data FROM control WHERE id=1').fetchone()[0])
    need(control['mode']=='PAUSED','CONTROLLER_MUST_REMAIN_PAUSED');status('STATUS-AFTER')
    report=dict(status='MARKET_EVIDENCE_READ_REVIEW_REQUIRED',assessed_at=now.isoformat(),source=source,warmup=warmup,option_quotes=quote_report,remaining_checks=issues,controller_mode=control['mode'],broker_requests_issued=False,credentials_loaded=False,application_sql_mutations_issued=False,application_services_changed=False,source_cursor_changed_by_check=False,controller_resumed=False,orders_sent=False,production_execution_enabled=False,production_ready=False,group2_complete=False,audit_folder=str(out))
    save('RESULT.json',report);print(json.dumps(report,indent=2))
if __name__=='__main__':main()
