"""Bounded broker GET-only option quote evidence; never invokes a publisher or execution workflow."""
import argparse,hashlib,importlib.util,json,math,os,re,subprocess,sys,tempfile,time
from datetime import date,datetime,timezone
from pathlib import Path
from urllib.request import Request,build_opener,HTTPRedirectHandler
from urllib.parse import urlencode
from urllib.error import HTTPError
from zoneinfo import ZoneInfo
sys.dont_write_bytecode=True
INDEX='NSE_INDEX|Nifty 50';IST=ZoneInfo('Asia/Kolkata')
def need(ok,code):
    if not ok:raise ValueError(code)
def raw(p):
    need(p.is_absolute() and p.is_file() and not any(q.is_symlink() for q in (p,*p.parents)),'REGULAR_INPUT_REQUIRED');return p.read_bytes()
def sha(b):return hashlib.sha256(b).hexdigest()
def positive(v):return type(v) in (int,float) and math.isfinite(v) and v>0
def stamp(v):
    if isinstance(v,str) and not v.isdigit():
        t=datetime.fromisoformat(v.replace('Z','+00:00'));need(t.tzinfo is not None and t.utcoffset() is not None,'NAIVE_QUOTE_TIMESTAMP_REJECTED');return t
    need(type(v) in (int,float,str) and not isinstance(v,bool),'QUOTE_TIMESTAMP_REQUIRED')
    n=float(v);need(math.isfinite(n) and 1e12<=n<1e14,'EPOCH_MILLISECONDS_REQUIRED');return datetime.fromtimestamp(n/1000,timezone.utc)
def quote_map(body,keys):
    need(isinstance(body,dict) and body.get('status')=='success' and isinstance(body.get('data'),dict),'QUOTE_RESPONSE_SCHEMA_REQUIRED');out={}
    for q in body['data'].values():
        need(isinstance(q,dict),'QUOTE_ROW_SCHEMA_REQUIRED');k=q.get('instrument_token')
        need(k in keys and k not in out,'QUOTE_IDENTITY_OR_DUPLICATE_ERROR');out[k]=q
    need(set(out)==set(keys),'QUOTE_COVERAGE_INCOMPLETE');return out
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--repo',type=Path,required=True);ap.add_argument('--active-plan',type=Path,required=True);ap.add_argument('--active-plan-sha256',required=True);a=ap.parse_args()
    root=a.repo.absolute();here=Path(__file__).absolute().parent;path=a.active_plan.absolute()
    for name,h in json.loads(raw(here/'MANIFEST.json')).items():need(sha(raw(here/name))==h,'QUOTE_CHECK_PACKAGE_CHANGED')
    for name,h in json.loads(raw(here/'BASELINE-PINS.json')).items():need(sha(raw(root/name))==h,'QUOTE_CHECK_BASELINE_CHANGED')
    need(sha(raw(path))==a.active_plan_sha256,'ACTIVE_PLAN_CHANGED');plan=json.loads(raw(path));need(plan['repo']==str(root) and plan['production_execution_enabled'] is False,'CLOSED_PLAN_REQUIRED')
    out=Path(tempfile.mkdtemp(prefix='hilega-option-quote-readcheck-',dir=root));out.chmod(0o700)
    def save(name,value):
        fd=os.open(out/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as f:json.dump(value,f,indent=2,allow_nan=False);f.write('\n')
    def status(label):
        r=subprocess.run([sys.executable,'-B',str(root/'hilega-registration-rollout-v1/manage.py'),'--repo',str(root),'--action','status','--plan',str(path),'--approve-plan-sha256',a.active_plan_sha256],capture_output=True,text=True,timeout=110)
        save(label+'.json',dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr));need(r.returncode==0,'CLOSED_RUNTIME_STATUS_FAILED_'+label)
        need(json.loads(r.stdout)['phase']=='CLOSED_GROUP2_CANDIDATE_RUNNING','CLOSED_RUNTIME_REQUIRED')
    test=subprocess.run([sys.executable,'-B','-m','pytest','-q','-p','no:cacheprovider',str(here/'test_quotes.py')],capture_output=True,text=True,timeout=60)
    save('TESTS.json',dict(exit_code=test.returncode,stdout=test.stdout,stderr=test.stderr));need(test.returncode==0,'QUOTE_PARSER_TESTS_FAILED')
    print(test.stdout,flush=True)
    status('BEFORE');problems=[];samples=[];get_count=0;selected=[];blocked=None;pid=None
    try:
        folder=root/'hilega-issuer-provision-v1';sys.path.insert(0,str(folder))
        spec=importlib.util.spec_from_file_location('quote_identity',folder/'manage.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        identity=m.identity(root,plan);token=identity['forbidden'][1].decode();pid=identity['pid'];del identity
        opener=build_opener(NoRedirect())
        def get(endpoint,params,label):
            nonlocal get_count
            need(endpoint in {'/v2/option/contract','/v2/market-quote/quotes'},'GET_ENDPOINT_NOT_ALLOWED')
            req=Request('https://api.upstox.com'+endpoint+'?'+urlencode(params),headers={'Authorization':'Bearer '+token,'Accept':'application/json','User-Agent':'RB-ITOS-AI/1.0 (read-only readiness validation)'},method='GET')
            get_count+=1
            try:
                with opener.open(req,timeout=12) as r:data=r.read(8_000_001)
            except HTTPError as exc:raise ValueError('BROKER_HTTP_'+str(exc.code)) from None
            need(len(data)<=8_000_000,'BROKER_RESPONSE_TOO_LARGE');body=json.loads(data)
            need(isinstance(body,dict) and body.get('status')=='success','BROKER_RESPONSE_NOT_SUCCESS');save(label+'.json',body);return body
        local=datetime.now(IST);need(local.weekday()<5 and (9,15)<=(local.hour,local.minute)<(15,30),'REGULAR_SESSION_WINDOW_REQUIRED_EXCHANGE_CALENDAR_NOT_CHECKED')
        index=quote_map(get('/v2/market-quote/quotes',{'instrument_key':INDEX},'PRIVATE-INDEX'),{INDEX})[INDEX]
        need(positive(index.get('last_price')),'POSITIVE_INDEX_QUOTE_REQUIRED');spot=index['last_price'];index_age=(datetime.now(timezone.utc)-stamp(index.get('timestamp'))).total_seconds();need(0<=index_age<=10,'INDEX_QUOTE_STALE_OR_FUTURE')
        contracts=get('/v2/option/contract',{'instrument_key':INDEX},'PRIVATE-CONTRACTS').get('data');need(isinstance(contracts,list),'CONTRACT_LIST_REQUIRED')
        eligible=[];today=local.date()
        for c in contracts:
            if not isinstance(c,dict) or c.get('underlying_key')!=INDEX or c.get('segment')!='NSE_FO' or c.get('exchange')!='NSE' or c.get('instrument_type') not in {'CE','PE'}:continue
            expiry=date.fromisoformat(c['expiry'])
            if expiry<today:continue
            need(isinstance(c.get('instrument_key'),str) and c['instrument_key'].startswith('NSE_FO|'),'CONTRACT_KEY_INVALID')
            need(positive(c.get('strike_price')) and type(c.get('lot_size')) is int and c['lot_size']>0,'CONTRACT_STRIKE_OR_LOT_INVALID');eligible.append(c)
        need(bool(eligible),'NO_CURRENT_NIFTY_OPTION_CONTRACTS');expiry=min(c['expiry'] for c in eligible);eligible=[c for c in eligible if c['expiry']==expiry]
        lookup={}
        for c in eligible:
            k=(c['strike_price'],c['instrument_type']);need(k not in lookup,'AMBIGUOUS_CONTRACT_IDENTITY');lookup[k]=c
        strikes=sorted({c['strike_price'] for c in eligible if (c['strike_price'],'CE') in lookup and (c['strike_price'],'PE') in lookup})
        need(len(strikes)>=5,'FIVE_PAIRED_STRIKES_REQUIRED');i=min(range(len(strikes)),key=lambda i:(abs(strikes[i]-spot),strikes[i]));need(i>=2 and i+2<len(strikes),'ATM_TWO_NEIGHBOURS_REQUIRED')
        for strike in strikes[i-2:i+3]:
            for side in ('CE','PE'):
                c=lookup[strike,side];selected.append({k:c[k] for k in ('instrument_key','expiry','strike_price','instrument_type','lot_size','underlying_key')})
        keys={c['instrument_key'] for c in selected};need(len(keys)==10,'TEN_UNIQUE_CONTRACTS_REQUIRED')
        for sample in range(3):
            if sample:time.sleep(2)
            body=get('/v2/market-quote/quotes',{'instrument_key':','.join(sorted(keys))},'PRIVATE-QUOTES-'+str(sample+1));mapping=quote_map(body,keys);received=datetime.now(timezone.utc);rows=[]
            for c in selected:
                q=mapping[c['instrument_key']];depth=q.get('depth') or {};buy=depth.get('buy') or [];sell=depth.get('sell') or [];bid=buy[0] if buy and isinstance(buy[0],dict) else {};ask=sell[0] if sell and isinstance(sell[0],dict) else {};checks=[];at=None;seconds=None
                try:at=stamp(q.get('timestamp'));seconds=(received-at).total_seconds()
                except (ValueError,TypeError,OverflowError):checks.append('QUOTE_TIMESTAMP_UNVERIFIED')
                if seconds is not None and not 0<=seconds<=10:checks.append('QUOTE_STALE_OR_FUTURE')
                if not positive(q.get('last_price')):checks.append('INVALID_LAST_PRICE')
                if not(positive(bid.get('price')) and positive(ask.get('price')) and bid['price']<=ask['price']):checks.append('INVALID_OR_CROSSED_BOOK')
                if not(positive(bid.get('quantity')) and positive(ask.get('quantity'))):checks.append('MISSING_TWO_SIDED_DEPTH')
                trade_age=None
                try:trade_age=(received-stamp(q.get('last_trade_time'))).total_seconds()
                except (ValueError,TypeError,OverflowError):pass
                rows.append(dict(**c,quote_at=at.isoformat() if at else None,quote_age_seconds=seconds,last_trade_age_seconds=trade_age,bid=bid.get('price'),ask=ask.get('price'),bid_quantity=bid.get('quantity'),ask_quantity=ask.get('quantity'),issues=checks,quote_checks_passed=not checks))
            samples.append(dict(received_at=received.isoformat(),contracts=rows,all_ten_quote_checks_passed=all(r['quote_checks_passed'] for r in rows)))
        del token
        current=int(subprocess.check_output(['systemctl','--user','show','hilega-production-source-worker.service','--property=MainPID','--value'],text=True).strip());need(current==pid,'SOURCE_PROCESS_CHANGED')
    except Exception as exc:
        code=str(exc).split(':',1)[0];blocked=dict(reason=code if re.fullmatch('[A-Z][A-Z0-9_]*',code) else 'QUOTE_READ_REQUIRES_REVIEW',error_type=type(exc).__name__)
    after=None
    try:status('AFTER');after=True
    except Exception as exc:after=False;problems.append('CLOSED_RUNTIME_AFTER_CHECK_FAILED')
    passed=blocked is None and after is True and len(samples)==3 and all(s['all_ten_quote_checks_passed'] for s in samples)
    report=dict(status='BOUNDED_REST_OPTION_QUOTE_EVIDENCE_PASS' if passed else 'OPTION_QUOTE_EVIDENCE_REVIEW_REQUIRED',broker_get_count=get_count,blocked=blocked,problems=problems,selected_contract_count=len(selected),samples=samples,basket_basis='NEAREST_NONEXPIRED_EXPIRY_ATM_PLUS_MINUS_TWO_PAIRED_STRIKES',required_strategy_contract_coverage_verified=False,continuous_publisher_restored=False,websocket_validated=False,local_quote_cache_modified=False,broker_trade_timestamp_contract_resolved=False,last_trade_age_is_separate_from_quote_age=True,policy_changed=False,services_changed=False,controller_resumed=False,orders_sent=False,production_execution_enabled=False,production_ready=False,audit_folder=str(out))
    save('RESULT.json',report)
    public={k:v for k,v in report.items() if k!='samples'}
    public['sample_summary']=[dict(received_at=s['received_at'],contract_count=len(s['contracts']),passing_contracts=sum(r['quote_checks_passed'] for r in s['contracts']),issues=sorted({i for r in s['contracts'] for i in r['issues']})) for s in samples]
    print(json.dumps(public,indent=2));return 0 if passed else 2
if __name__=='__main__':raise SystemExit(main())
