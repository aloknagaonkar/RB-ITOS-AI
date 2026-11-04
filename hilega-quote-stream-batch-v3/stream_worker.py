"""Quote-only observer. No strategy imports, journal consumption, order API or database writes."""
import atexit,argparse,contextlib,hashlib,importlib.util,json,logging,os,queue,re,signal,sys,tempfile,threading,time
from datetime import datetime,timezone
from pathlib import Path
from urllib.request import Request,build_opener,HTTPRedirectHandler
from urllib.parse import urlencode
from urllib.error import HTTPError
from quote_core import INDEX,IST,need,stamp,basket,quote_map,decode,valid,session_preflight
sys.dont_write_bytecode=True
from successor import status_driver
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*a,**kw):return None

def regular(p):
    need(p.is_absolute() and p.is_file() and not any(q.is_symlink() for q in (p,*p.parents)),'REGULAR_INPUT_REQUIRED');return p.read_bytes()
def sha(b):return hashlib.sha256(b).hexdigest()
def atomic(p,value):
    need(not any(q.is_symlink() for q in (p,*p.parents)),'SYMLINK_OUTPUT_REJECTED')
    fd,name=tempfile.mkstemp(prefix=p.name+'.new-',dir=p.parent)
    try:
        with os.fdopen(fd,'w') as f:json.dump(value,f,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
        os.replace(name,p)
    finally:
        if os.path.exists(name):os.unlink(name)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--repo',type=Path,required=True);ap.add_argument('--plan',type=Path,required=True);ap.add_argument('--plan-sha256',required=True);ap.add_argument('--output',type=Path,required=True);ap.add_argument('--seconds',type=int,required=True);ap.add_argument('--publish',action='store_true');a=ap.parse_args()
    root=a.repo.absolute();here=Path(__file__).absolute().parent;out=a.output.absolute();need(out.is_dir() and not any(p.is_symlink() for p in (out,*out.parents)),'REGULAR_OUTPUT_DIRECTORY_REQUIRED');need(10<=a.seconds<=8*3600,'BOUNDED_DURATION_REQUIRED')
    for n,h in json.loads(regular(here/'MANIFEST.json')).items():need(sha(regular(here/n))==h,'STREAM_PACKAGE_CHANGED')
    for n,h in json.loads(regular(here/'BASELINE-PINS.json')).items():need(sha(regular(root/n))==h,'STREAM_BASELINE_CHANGED')
    need(sha(regular(a.plan))==a.plan_sha256,'PLAN_CHANGED');plan=json.loads(regular(a.plan));need(plan['repo']==str(root) and plan['production_execution_enabled'] is False,'CLOSED_PLAN_REQUIRED')
    status_driver(root,plan)
    need(sha(regular(root/'hilega-warmup-prevention-deploy-v1/MANIFEST.json'))==plan['tool_manifest_sha256'],'SUCCESSOR_TOOL_BINDING_CHANGED')
    window=session_preflight(datetime.now(IST),minimum_seconds=min(a.seconds,35))
    if not window['clock_window_open']:
        atomic(out/'RESULT.json',dict(status='QUOTE_STREAM_DEFERRED_OUTSIDE_USABLE_SESSION',session=window,qualified=False,websocket_validation_attempted=False,broker_get_count=0,credentials_loaded=False,controller_resumed=False,production_execution_enabled=False));return 2
    folder=root/'hilega-issuer-provision-v1';sys.path.insert(0,str(folder));spec=importlib.util.spec_from_file_location('stream_identity_reader',folder/'manage.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    from filelock import FileLock
    shared=root/'data/live-observation/hilega-strike-observation-v1';need(shared.is_dir() and not any(p.is_symlink() for p in (shared,*shared.parents)),'REGULAR_QUOTE_DIRECTORY_REQUIRED')
    lockpath=shared/'integration.lock';need(not lockpath.is_symlink(),'REGULAR_QUOTE_LOCK_REQUIRED')
    publishlock=FileLock(str(lockpath));publishlock.acquire(timeout=0);atexit.register(publishlock.release)
    identity=m.identity(root,plan);token=identity['forbidden'][1].decode();pid=identity['pid'];del identity
    opener=build_opener(NoRedirect());calls=0
    def get(path,params):
        nonlocal calls
        need(path in {'/v2/option/contract','/v2/market-quote/quotes'},'ENDPOINT_NOT_ALLOWED');calls+=1
        req=Request('https://api.upstox.com'+path+'?'+urlencode(params),headers={'Authorization':'Bearer '+token,'Accept':'application/json','User-Agent':'RB-ITOS-AI/1.0 (read-only readiness validation)'},method='GET')
        try:
            with opener.open(req,timeout=10) as r:b=r.read(8_000_001)
        except HTTPError as exc:raise ValueError('BROKER_HTTP_'+str(exc.code)) from None
        need(len(b)<=8_000_000,'BROKER_RESPONSE_TOO_LARGE');v=json.loads(b);need(v.get('status')=='success','BROKER_GET_FAILED');return v
    def select():
        q=quote_map(get('/v2/market-quote/quotes',{'instrument_key':INDEX}),{INDEX})[INDEX];now=datetime.now(timezone.utc);need(0<=(now-stamp(q.get('timestamp'))).total_seconds()<=10,'FRESH_UNDERLYING_REQUIRED')
        contracts=get('/v2/option/contract',{'instrument_key':INDEX}).get('data');need(isinstance(contracts,list),'CONTRACT_LIST_REQUIRED');return basket(contracts,q.get('last_price'),now.astimezone(IST).date())
    metadata=select();atomic(out/'CONTRACTS.json',metadata)
    import upstox_client
    cfg=upstox_client.Configuration();cfg.access_token=token
    streamer=upstox_client.MarketDataStreamerV3(upstox_client.ApiClient(cfg),sorted(metadata),'full')
    events=queue.Queue(maxsize=2048);connected=False;generation=0;event_lock=threading.Lock();stop=False;cache={};errors=0;drops=0;decoded=0;ready_since=None;qualified=False;refreshes=0
    def open_event(*args):
        nonlocal connected,generation
        with event_lock:connected=True;generation+=1
    def close_event(*args):
        nonlocal connected,generation
        with event_lock:connected=False;generation+=1
    def error_event(*args):
        nonlocal errors
        errors+=1;close_event()
    def message(v):
        nonlocal drops
        with event_lock:g=generation;c=connected
        if c:
            try:events.put_nowait((g,v))
            except queue.Full:drops+=1
    def halt(*args):
        nonlocal stop
        stop=True
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,halt)
    streamer.on('open',open_event);streamer.on('close',close_event);streamer.on('error',error_event);streamer.on('message',message);streamer.auto_reconnect(False,5,0)
    start=time.monotonic();last_fresh=start;last_refresh=start;last_guard=start;last_generation=-1;last_good={};failure=None;session_ended=False
    stream_path=root/'data/live-observation/hilega-strike-observation-v1/active-live-quotes.json'
    status_path=root/'data/live-observation/hilega-strike-observation-v1/quote-observer-status.json'
    def emit(state):
        nonlocal ready_since,qualified
        now=datetime.now(timezone.utc);fresh={k:q for k,q in cache.items() if k in metadata and valid(q,now)} if connected else {};all_ready=len(fresh)==10
        if all_ready:
            if ready_since is None:ready_since=time.monotonic()
            if time.monotonic()-ready_since>=5:qualified=True
        else:ready_since=None
        result=dict(model='HILEGA_QUOTE_ONLY_OBSERVER_V1',generated_at=now.isoformat(),stream_connected=connected,status=state,quotes=dict(cache) if connected else {},observed_contract_count=len(metadata),fresh_complete_contract_count=len(fresh),basket_full_coverage=all_ready,continuous_five_second_coverage_verified=qualified,decoded_feed_rows=decoded,stream_error_count=errors,dropped_messages=drops,metadata_refreshes=refreshes,broker_get_count=calls,basket_basis='NEAREST_EXPIRY_ATM_PLUS_MINUS_TWO_CE_PE',strategy_admission_or_full_production_coverage_verified=False,observation_only=True,orders_enabled=False,production_execution_enabled=False)
        atomic(out/'STREAM-STATUS.json',result)
        if a.publish:atomic(stream_path,result);atomic(status_path,{k:v for k,v in result.items() if k!='quotes'})
        return result
    # Suppress SDK output: authorized websocket URLs must never enter service logs.
    logging.disable(logging.CRITICAL)
    with open(os.devnull,'w') as quiet,contextlib.redirect_stdout(quiet),contextlib.redirect_stderr(quiet):
        try:
            streamer.connect()
            while not stop and time.monotonic()-start<a.seconds:
                local=datetime.now(IST)
                if not(local.weekday()<5 and (9,15)<=(local.hour,local.minute)<(15,30)):
                    session_ended=True;break
                if time.monotonic()-last_guard>=5:
                    need(sha(regular(a.plan))==a.plan_sha256,'PLAN_CHANGED');need(sha(regular(Path(plan['destination'])/'RELEASE-MANIFEST.json'))==plan['release_sha256'],'RELEASE_CHANGED')
                    proc=Path('/proc')/str(pid);need(proc.exists(),'SOURCE_PROCESS_EXITED');cmd=(proc/'cmdline').read_bytes();need(b'hilega_production_simulator_bridge.py' in cmd,'SOURCE_PID_IDENTITY_CHANGED');last_guard=time.monotonic()
                if generation!=last_generation:cache.clear();last_generation=generation
                for _ in range(2048):
                    try:g,value=events.get_nowait()
                    except queue.Empty:break
                    if not connected or g!=generation:continue
                    try:rows=decode(value,metadata)
                    except (ValueError,TypeError,KeyError,OverflowError):errors+=1;continue
                    for key,q in rows.items():
                        if key not in cache or stamp(q['feed_timestamp'])>=stamp(cache[key]['feed_timestamp']):cache[key]=q;decoded+=1
                if time.monotonic()-last_refresh>=60:
                    new=select();oldkeys=set(metadata);newkeys=set(new)
                    if oldkeys!=newkeys:
                        streamer.unsubscribe(sorted(oldkeys-newkeys));streamer.subscribe(sorted(newkeys-oldkeys),'full');cache={k:v for k,v in cache.items() if k in newkeys};ready_since=None
                    metadata=new;atomic(out/'CONTRACTS.json',metadata);refreshes+=1;last_refresh=time.monotonic()
                last_good=emit('RUNNING' if connected else 'CONNECTING_OR_DISCONNECTED')
                if last_good['basket_full_coverage']:last_fresh=time.monotonic()
                need(time.monotonic()-last_fresh<=30,'NO_COMPLETE_FRESH_BASKET_FOR_THIRTY_SECONDS')
                time.sleep(1)
        except Exception as exc:
            code=str(exc).split(':',1)[0];failure=dict(reason=code if re.fullmatch('[A-Z][A-Z0-9_]*',code) else 'STREAM_OBSERVER_FAILED',error_type=type(exc).__name__)
        finally:
            try:streamer.disconnect()
            except Exception:pass
            connected=False;emit('STOPPED')
    report=dict(status='QUOTE_OBSERVER_SESSION_ENDED' if session_ended else ('WEBSOCKET_QUOTE_COVERAGE_PASS' if qualified and failure is None else 'WEBSOCKET_QUOTE_REVIEW_REQUIRED'),session_ended=session_ended,qualified=qualified,failure=failure,elapsed_seconds=round(time.monotonic()-start,1),last_running_fresh_contracts=last_good.get('fresh_complete_contract_count',0),decoded_feed_rows=decoded,stream_errors=errors,broker_get_count=calls,metadata_refreshes=refreshes,published_active_cache=a.publish,controller_resumed=False,orders_sent=False,production_execution_enabled=False)
    atomic(out/'RESULT.json',report);return 0 if report['status']=='WEBSOCKET_QUOTE_COVERAGE_PASS' else 2
if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as exc:
        # Failures before connection have no credential/provider text in stdout.
        code=str(exc).split(':',1)[0];print(json.dumps(dict(status='STREAM_START_BLOCKED',reason=code if re.fullmatch('[A-Z][A-Z0-9_]*',code) else 'STREAM_START_REQUIRES_REVIEW',error_type=type(exc).__name__)));raise SystemExit(2)
