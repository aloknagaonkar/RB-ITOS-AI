"""Independent UI-only readiness monitoring. No order, arm, or strategy mutations."""
import argparse,json,os,time,re
from pathlib import Path
from datetime import datetime,timedelta,time as walltime
from zoneinfo import ZoneInfo
from urllib.request import urlopen
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter
from filelock import FileLock
from dotenv import load_dotenv
IST=ZoneInfo('Asia/Kolkata');ROOT=Path('data/live-observation/operational-readiness-v1');STATE=ROOT/'state.json';PID=Path('data/operational-readiness.pid')
router=APIRouter(prefix='/api/data-health/readiness',tags=['data-health'])

def read_json(path,default=None):
    try:return json.loads(Path(path).read_text())
    except (OSError,ValueError):return {} if default is None else default

def atomic(path,data):
    path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data,default=str));tmp.replace(path)

def age(now,stamp):
    try:return (now-datetime.fromisoformat(stamp)).total_seconds()
    except (TypeError,ValueError):return None

def phase(now):
    t=now.time().replace(tzinfo=None)
    if now.weekday()>=5:return 'OUT_OF_SESSION'
    if t<walltime(8,45):return 'SCHEDULED'
    if t<walltime(9,15):return 'PRE_MARKET'
    if t<=walltime(15,30):return 'MARKET'
    return 'OUT_OF_SESSION'

def boundary(now):
    # Active decision checkpoints use completed 5m bars; labels are five minutes earlier.
    return now.replace(minute=now.minute//5*5,second=0,microsecond=0)

def inspect_warmup(now,root=Path('data/historical-evidence/hilega-milega-underlying-cache-v1'),repair=False):
    from .hilega_milega_historical_replay_v1 import _read_cache,UNDERLYING,aggregate_exact_5m,load_validated_warmup_1m
    from .hilega_directional_live_shadow_v1 import HilegaDirectionalCoordinatorV1
    first=now.date()-timedelta(days=45);day=first;checks=[];sessions=[];missing_dates=[]
    sources=None
    while day<now.date():
        path=root/(day.isoformat()+'.json')
        if not path.exists():missing_dates.append(day.isoformat());day+=timedelta(days=1);continue
        try:
            rows=_read_cache(path,UNDERLYING,day)
            if rows is None:raise ValueError('Unreadable or invalid warmup cache')
            if rows:
                try:bars=aggregate_exact_5m(rows,day,require_full_session=True)
                except ValueError:
                    if not repair:raise
                    if sources is None:
                        from .upstox_live_shadow_sources_v1 import UpstoxLiveShadowSourcesV1
                        sources=UpstoxLiveShadowSourcesV1(os.getenv('UPSTOX_ACCESS_TOKEN',''))
                    rows=load_validated_warmup_1m(sources,underlying=UNDERLYING,session_date=day,cache_root=root)
                    bars=aggregate_exact_5m(rows,day,require_full_session=True)
                # Exact expected timestamps, no extras, duplicates, or missing bars.
                if len(bars)!=75:raise ValueError('Expected 75 complete five-minute bars')
                sessions.append((day,bars))
        except Exception as exc:
            message=str(exc) if isinstance(exc,ValueError) and re.fullmatch(r'[A-Za-z0-9 :,;._\-]+',str(exc)) else type(exc).__name__
            checks.append(dict(date=day.isoformat(),message=f'Warmup {day}: {message}'))
        day+=timedelta(days=1)
    warmed=False
    if not checks and sessions:
        coordinator=HilegaDirectionalCoordinatorV1()
        for d,bars in sessions:
            for bar in bars:coordinator.on_bar(bar)
        warmed=bool(coordinator.bullish.previous_indicators and coordinator.bullish.previous_indicators.ready)
    return dict(checked_at=now.isoformat(),session_date=now.date().isoformat(),complete_sessions=len(sessions),indicator_warmup_ready=warmed,issues=checks,missing_calendar_dates=missing_dates,missing_dates_verified=False,repair_attempted=repair,ready=not checks and warmed)

def get_api(base,path):
    try:
        with urlopen(base+path,timeout=4) as r:return json.load(r)
    except Exception as exc:return {'monitor_error':type(exc).__name__}

def inspect_local(now):
    # Bounded audit tail is enough for latest evidence and fresh unhandled entries.
    path=Path('data/live-observation/hilega-directional-v1/step-audit.jsonl');rows=[]
    try:
        with path.open('rb') as f:
            f.seek(0,2);size=f.tell();f.seek(max(0,size-512000));raw=f.read().decode('utf-8')
        lines=raw.splitlines();lines=lines[1:] if size>512000 else lines
        rows=[json.loads(l) for l in lines if l.strip()]
    except (OSError,ValueError):pass
    day=now.date().isoformat();sid=os.getenv('LIVE_SHADOW_STRATEGY','HILEGA_V2_ALIGNMENT_DUAL_EXIT')
    rows=[r for r in rows if (r.get('payload') or {}).get('strategy_id')==sid and str((r.get('payload') or {}).get('decision_timestamp') or r.get('event_time','')).startswith(day)]
    decision_rows=[r for r in rows if r.get('stage') in ('DIRECTIONAL_DECISION','DIRECTIONAL_SESSION_CUTOFF') and r.get('status') in ('PROCESSED','PASS','RECOVERED')]
    latest=max(decision_rows,key=lambda r:str((r.get('payload') or {}).get('decision_timestamp') or r.get('event_time','')),default=None)
    intents_path=Path(os.getenv('HILEGA_SANDBOX_BRIDGE_OUTPUT','data/live-observation/hilega-upstox-sandbox-v1/would-submit.jsonl'))
    intents=[]
    if intents_path.exists():
        try:intents=[json.loads(l) for l in intents_path.read_text().splitlines() if l.strip()]
        except (OSError,ValueError):pass
    journal=Path('data/live-observation/hilega-upstox-sandbox-v2/basket-events.jsonl');dispatch=[]
    if journal.exists():
        try:dispatch=[json.loads(l) for l in journal.read_text().splitlines() if l.strip()]
        except (OSError,ValueError):pass
    acknowledged={r.get('intent_id') for r in dispatch if r.get('status') in ('ACCEPTED','INTENT_COMPLETE','ENTRY_BLOCKED','SUBMISSION_UNCERTAIN','EXIT_BLOCKED')}
    missing=[];recovered=[]
    for r in rows:
        p=r.get('payload') or {};events=p.get('accepted_events') or [];stamp=p.get('decision_timestamp') or r.get('event_time');elapsed=age(now,stamp)
        if any(str(ev).startswith('ENTRY_') for ev in events):
            if r.get('status')=='RECOVERED':recovered.append(dict(entry_time=stamp,sandbox_submitted=any(d.get('event_type')=='ENTRY' and d.get('event_timestamp')==stamp and d.get('status')=='ACCEPTED' for d in dispatch)));continue
            if r.get('status') not in ('PASS','PROCESSED') or elapsed is None or not elapsed>30:continue
            matching=[i for i in intents if i.get('source_sequence')==r.get('sequence') and i.get('event_type')=='ENTRY' and i.get('strategy_id')==sid]
            if not matching or any(i.get('decision')=='WOULD_SUBMIT' and i.get('intent_id') not in acknowledged for i in matching):missing.append(stamp)
    return dict(latest_decision=((latest or {}).get('payload',{}).get('decision_timestamp') or (latest or {}).get('event_time')),missing_dispatch=sorted(set(missing)),resolved_dispatch=sorted({r.get('event_timestamp') for r in dispatch if r.get('event_type')=='ENTRY' and r.get('status') in ('ACCEPTED','INTENT_COMPLETE','ENTRY_BLOCKED','SUBMISSION_UNCERTAIN')}),recovered_entries=list({r['entry_time']:r for r in recovered}.values()))

def evaluate(now,live,sandbox,warm,local,health,previous):
    day=now.date().isoformat();ph=phase(now);issues=[];checks=[]
    def check(key,label,ok,message):
        checks.append(dict(id=key,label=label,status='PASS' if ok else 'FAIL',message=message))
        if not ok:issues.append(dict(id=key,component=label,message=message))
    active=ph in ('PRE_MARKET','MARKET')
    if active:
        check('WARMUP','Warmup',bool(warm.get('ready') and warm.get('session_date')==day),'; '.join(i['message'] for i in warm.get('issues',[])) or ('Indicators warmed from validated historical bars' if warm.get('ready') else 'Historical warmup validation unavailable or incomplete'))
        check('API','API','monitor_error' not in live,'API reachable' if 'monitor_error' not in live else 'Live status request failed: '+live['monitor_error'])
        sid=os.getenv('LIVE_SHADOW_STRATEGY','HILEGA_V2_ALIGNMENT_DUAL_EXIT')
        check('STRATEGY','Strategy',live.get('active_strategy_id')==sid,'Expected strategy '+sid)
        probe=warm.get('analytics_probe') or {}
        require_probe=now.time().replace(tzinfo=None)>=walltime(9,0)
        check('ANALYTICS_TOKEN','Analytics credentials',bool(os.getenv('UPSTOX_ACCESS_TOKEN')) and (not require_probe or probe.get('status')=='PASS'),'Read-only NIFTY quote authentication: '+str(probe.get('status','scheduled for 09:00'))+' · '+str(probe.get('checked_at','not checked')))
        w=sandbox.get('worker') or {}
        check('SANDBOX','Sandbox',bool(w.get('running') and w.get('armed') and w.get('session_date')==day and w.get('strategy_id')==sid and not w.get('kill_switch') and not w.get('entries_blocked') and not w.get('uncertain_requests')),'Sandbox must be running, armed for today/current strategy, without blocked entries or uncertain requests')
        check('SANDBOX_TOKEN','Sandbox credentials',bool(os.getenv('UPSTOX_SANDBOX_ACCESS_TOKEN')),'Sandbox token presence check only; broker authentication is not independently certified')
    if ph=='MARKET':
        ha=age(now,health.get('timestamp'));check('HEARTBEAT','Worker heartbeat',ha is not None and 0<=ha<=60,f'Heartbeat age {round(ha,1) if ha is not None else "unavailable"} seconds; limit 60')
        for name,status in health.get('components',{}).items():
            check('COMPONENT_'+name,name,status=='OK',f'{name}: {status}')
        for name,detail in (health.get('component_errors') or {}).items():
            if health.get('components',{}).get(name)!='OK':check('ERROR_'+name,name,False,detail.get('message') or detail.get('error_type','Component failure'))
        after_grace=now>=datetime.combine(now.date(),walltime(9,21,30),tzinfo=IST)
        if after_grace:
            check('BOOTSTRAP','Hilega bootstrap',bool(live.get('current_session_ready') and live.get('current',{}).get('session_date')==day),'Current-session bootstrap ready' if live.get('current_session_ready') else 'Waiting for current-session bootstrap; previous-session rows are historical')
            expected=min(boundary(now-timedelta(seconds=90)),datetime.combine(now.date(),walltime(14,55),tzinfo=IST));bar=live.get('current',{}).get('last_completed_bar')
            try:fresh=datetime.fromisoformat(bar)+timedelta(minutes=5)>=expected
            except (TypeError,ValueError):fresh=False
            check('CANDLES','Completed candles',fresh,f'Latest completed bar {bar or "unavailable"}; expected availability at least {expected.strftime("%H:%M")} IST')
            decision=local.get('latest_decision')
            try:dfresh=datetime.fromisoformat(decision)>=expected
            except (TypeError,ValueError):dfresh=False
            check('DECISIONS','Decision table',dfresh,f'Latest decision {decision or "unavailable"}; current session required')
        for stamp in local.get('missing_dispatch',[]):check('DISPATCH_'+stamp,'Sandbox dispatch',False,'Fresh entry '+stamp+' has no dispatch outcome after 30 seconds')
    success=dict(previous.get('last_successful',{}))
    for c in checks:
        if c['status']=='PASS':success[c['id']]=now.isoformat()
    alerts=previous.get('alerts',[]);old={a['id']:a for a in alerts if a.get('active')};new=[];events=list(previous.get('notifications',[]))
    for i in issues:
        a=old.pop(i['id'],None)
        if a is None:
            a=dict(i,active=True,first_seen=now.isoformat(),last_reminded=now.isoformat(),last_successful=success.get(i['id']));events.append(dict(kind='FAILURE',timestamp=now.isoformat(),message=i['message']))
        else:a=dict(a,message=i['message'])
        duration=age(now,a['first_seen']) or 0;a['escalated']=duration>=60;a['last_seen']=now.isoformat()
        if (age(now,a.get('last_reminded')) or 0)>=300:a['last_reminded']=now.isoformat();events.append(dict(kind='REMINDER',timestamp=now.isoformat(),message=i['message']))
        new.append(a)
    # Out-of-session does not falsely recover unresolved market alerts.
    if active:
        for a in old.values():
            if a['id'].startswith('DISPATCH_') and a['id'][9:] not in local.get('resolved_dispatch',[]):
                new.append(a);continue
            events.append(dict(kind='RECOVERY',timestamp=now.isoformat(),message=a['component']+' recovered'));a=dict(a,active=False,recovered_at=now.isoformat());new.append(a)
    else:new.extend(old.values())
    previous_closed=[a for a in alerts if not a.get('active')]
    return dict(model='OPERATIONAL_READINESS_V1',checked_at=now.isoformat(),session_date=day,phase=ph,status='NOT_READY' if issues or active and any(a.get('active') for a in new) else 'READY' if active else ph,checks=checks,last_successful=success,alerts=(previous_closed+new)[-100:],notifications=events[-100:],warmup=warm,recovered_entries=local.get('recovered_entries',[]),credential_scope='Analytics token verified using read-only NIFTY quote; sandbox token presence only because order submission is excluded from monitoring',live_execution_enabled=False,schedule=[dict(time=t,check=c) for t,c in [('08:45','Validate warmup'),('08:50','Repair incomplete warmup'),('09:00','API / configuration / credentials / sandbox'),('09:10','Final readiness'),('09:15','Continuous component monitoring')]])

@router.get('')
def status():
    x=read_json(STATE);now=datetime.now(IST);a=age(now,x.get('checked_at'));x=dict(x,monitor_stale=a is None or a>45,monitor_age_seconds=a)
    if x['monitor_stale']:x['status']='MONITOR_UNAVAILABLE'
    return x

def tick(base):
    now=datetime.now(IST);prev=read_json(STATE);warm=prev.get('warmup') or {};ph=phase(now);elapsed=age(now,warm.get('checked_at'))
    if ph in ('PRE_MARKET','MARKET') and (warm.get('session_date')!=now.date().isoformat() or elapsed is None or elapsed>300):
        repair=ph=='PRE_MARKET' and now.time().replace(tzinfo=None)>=walltime(8,50) and os.getenv('HILEGA_READINESS_AUTO_REPAIR','1')=='1'
        warm=inspect_warmup(now,repair=repair)
        # Persist ongoing check so UI does not mislabel a long scan as a healthy result.
    probe=prev.get('warmup',{}).get('analytics_probe') or {}
    if ph in ('PRE_MARKET','MARKET') and now.time().replace(tzinfo=None)>=walltime(9,0) and (probe.get('session_date')!=now.date().isoformat() or (age(now,probe.get('checked_at')) or 999)>300):
        import httpx
        token=os.getenv('UPSTOX_ACCESS_TOKEN','')
        probe=dict(checked_at=now.isoformat(),session_date=now.date().isoformat(),status='FAIL')
        try:
            with httpx.Client(timeout=4) as client:
                r=client.get('https://api.upstox.com/v3/market-quote/ltp',params={'instrument_key':'NSE_INDEX|Nifty 50'},headers={'Authorization':'Bearer '+token,'Accept':'application/json'})
                body=r.json();probe['status']='PASS' if r.is_success and body.get('status')=='success' and body.get('data') else 'FAIL';probe['http_status']=r.status_code
        except Exception as exc:probe['error_type']=type(exc).__name__
    warm=dict(warm,analytics_probe=probe)
    with ThreadPoolExecutor(max_workers=2) as pool:
        one=pool.submit(get_api,base,'/api/live-shadow/hilega-directional/status?fast=true');two=pool.submit(get_api,base,'/api/live-shadow/hilega-upstox-sandbox/dashboard');live,sandbox=one.result(),two.result()
    report=evaluate(now,live,sandbox,warm,inspect_local(now),read_json('data/live-observation/shadow-worker-health.json'),prev);atomic(STATE,report);return report

def main():
    p=argparse.ArgumentParser();p.add_argument('--once',action='store_true');p.add_argument('--base-url',default='http://127.0.0.1:8123');a=p.parse_args();load_dotenv('.env');ROOT.mkdir(parents=True,exist_ok=True)
    with FileLock(str(ROOT/'monitor.lock'),timeout=0):
        if not a.once:PID.write_text(str(os.getpid()))
        while True:
            started=time.monotonic()
            try:report=tick(a.base_url)
            except Exception as exc:
                report=read_json(STATE);report.update(checked_at=datetime.now(IST).isoformat(),status='MONITOR_ERROR',monitor_error=type(exc).__name__);atomic(STATE,report)
            print(json.dumps({'status':report.get('status'),'checked_at':report.get('checked_at')}),flush=True)
            if a.once:break
            time.sleep(max(1,15-(time.monotonic()-started)))
if __name__=='__main__':main()
