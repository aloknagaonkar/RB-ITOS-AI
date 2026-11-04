"""Fixed historical F&O GETs using the running closed worker read context."""
import argparse,json,os,re,sqlite3,stat,sys,time,hmac
from pathlib import Path
from datetime import datetime,timezone,date
from zoneinfo import ZoneInfo
from urllib.request import Request
from urllib.parse import urlencode
from urllib.error import HTTPError
from finance import need,scope,review
from historical import page as historical_page,corroborate,observation

def private_file(path):
    need(path.is_absolute() and path.is_file() and not any(x.is_symlink() for x in [path,*path.parents]),'REGULAR_PRIVATE_INPUT_REQUIRED')
    info=path.stat();need(info.st_uid==os.getuid() and stat.S_IMODE(info.st_mode)&0o077==0,'PRIVATE_OWNED_INPUT_REQUIRED')

def save(path,value):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:json.dump(value,f,indent=2);f.write('\n')

PATHS={'charges':'/v2/trade/profit-loss/charges','metadata':'/v2/trade/profit-loss/metadata','data':'/v2/trade/profit-loss/data','historical':'/v2/charges/historical-trades'}
def get(client,kind,query):
    need(kind in PATHS,'POSTTRADE_ENDPOINT_FORBIDDEN')
    req=Request('https://api.upstox.com'+PATHS[kind]+'?'+urlencode(query),method='GET',headers={'Authorization':'Bearer '+client.token,'Accept':'application/json','Api-Version':'2.0','User-Agent':'RB-ITOS-AI/1.0 (read-only readiness validation)'})
    try:
        with client.opener.open(req,timeout=8) as response:raw=response.read(8_000_001)
        need(len(raw)<=8_000_000,'POSTTRADE_RESPONSE_TOO_LARGE')
        value=json.loads(raw)
        need(isinstance(value,dict) and value.get('status')=='success','POSTTRADE_RESPONSE_INVALID')
        return value
    except HTTPError as exc:raise ValueError('POSTTRADE_HTTP_'+str(exc.code)) from None

def main():
    p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,required=True);p.add_argument('--bundle',type=Path,required=True);p.add_argument('--adapter',type=Path,required=True);p.add_argument('--pid',type=int,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--session',required=True);p.add_argument('--evidence-review',type=Path,required=True);p.add_argument('--prior-finance',type=Path,required=True);a=p.parse_args()
    query=scope(a.session)
    need(date.fromisoformat(a.session)<=datetime.now(ZoneInfo('Asia/Kolkata')).date(),'FUTURE_SESSION_NOT_ALLOWED')
    proc=Path('/proc')/str(a.pid);need(proc.stat().st_uid==os.getuid() and (proc/'cwd').resolve()==a.repo.resolve(),'EXACT_SOURCE_PROCESS_REQUIRED')
    env={k.decode():v.decode() for part in (proc/'environ').read_bytes().split(b'\0') if b'=' in part for k,v in [part.split(b'=',1)]}
    need(env.get('HILEGA_PRODUCTION_EXECUTION_ROUTE')=='PREPARATION_ONLY','CLOSED_SOURCE_ROUTE_REQUIRED')
    home=Path(env.get('HOME',str(Path.home())))
    selected=Path(env.get('HILEGA_PREPARATION_ENV_FILE','.env'));env_path=selected if selected.is_absolute() else a.repo/selected
    pin_path=Path(env.get('HILEGA_PREPARATION_PIN_FILE',str(home/'hilega-private/upstox-account-pin.json')))
    private_file(env_path);private_file(pin_path)
    from dotenv import dotenv_values
    values=dotenv_values(env_path)
    def setting(name):
        shell=env.get(name);file=values.get(name)
        need(not(shell and file and shell!=file),'SOURCE_TOKEN_ENV_FILE_CONFLICT');return shell or file
    token=(setting('HILEGA_PRODUCTION_BROKER_READ_TOKEN') or setting('UPSTOX_ACCESS_TOKEN') or '').strip();need(bool(token),'SOURCE_READ_TOKEN_MISSING')
    sys.dont_write_bytecode=True;sys.path[:0]=[str(a.bundle/'backend'),str(a.bundle/'runtime')]
    from market_lab import hilega_production_account_adapter_v1 as api
    from market_lab.hilega_execution_port_v1 import adapter as port
    try:port.require_live_clearance()
    except port.GateClosed:pass
    else:raise ValueError('HARD_ORDER_GATE_NOT_CLOSED')
    pin=api.read_pin(pin_path);client=api.Client(token);del token,env,values
    db=sqlite3.connect(a.adapter.as_uri()+'?mode=ro',uri=True)
    try:
        db.execute('PRAGMA query_only=ON');meta=json.loads(db.execute('SELECT data FROM meta WHERE id=1').fetchone()[0]);need(meta==dict(scope=pin['scope'],mode='LIVE_CLOSED'),'SOURCE_PIN_ADAPTER_SCOPE_MISMATCH')
    finally:db.close()
    api.matches(client.get('profile'),pin)
    proof_path=a.evidence_review/'PRIVATE-ACCOUNT-BOUND-EVIDENCE.json';private_file(proof_path)
    prior=json.loads(proof_path.read_text());signature=prior.pop('signature',None)
    need(isinstance(signature,str) and hmac.compare_digest(signature,api.sign(prior,pin)),'PRIOR_ACCOUNT_SIGNATURE_INVALID')
    need(prior['model']=='HILEGA_ACCOUNT_BOUND_TIMESTAMP_AUDIT_V1' and prior['account_scope']==pin['scope'],'PRIOR_ACCOUNT_SCOPE_CHANGED')
    completed=datetime.fromisoformat(prior['completed_at'])
    need(completed.tzinfo is not None and completed.astimezone(ZoneInfo('Asia/Kolkata')).date().isoformat()==a.session,'EVIDENCE_SESSION_CHANGED')
    began=datetime.now(timezone.utc);deadline=time.monotonic()+160
    charges=get(client,'charges',query);save(a.output/'PRIVATE-RAW-CHARGES.json',charges)
    metadata=get(client,'metadata',query);save(a.output/'PRIVATE-RAW-METADATA.json',metadata);meta=metadata.get('data')
    need(isinstance(meta,dict) and type(meta.get('trades_count')) is int and meta['trades_count']>=0 and type(meta.get('page_size_limit')) is int and meta['page_size_limit']>0,'REPORT_METADATA_INVALID')
    size=min(100,meta['page_size_limit']);count=meta['trades_count'];pages=(count+size-1)//size
    need(pages<=5,'REPORT_EXCEEDS_BOUNDED_PAGINATION_LIMIT')
    collected=[];responses=[]
    for page in range(1,pages+1):
        need(time.monotonic()<deadline,'POSTTRADE_CAPTURE_DEADLINE')
        response=get(client,'data',dict(query,page_number=page,page_size=size));rows=response.get('data')
        need(isinstance(rows,list) and len(rows)<=size,'REPORT_PAGE_SCHEMA_INVALID')
        returned=response.get('metadata',{}).get('page',{})
        need(returned.get('page_number')==page and type(returned.get('page_size')) is int and 1<=returned['page_size']<=size,'REPORT_PAGE_IDENTITY_CHANGED')
        collected.extend(rows);responses.append(response)
    historical_responses=[];historical_rows=[];history_error=None;history_complete=False;history_observations=[]
    try:
        history_query=dict(segment='FO',start_date=a.session,end_date=a.session,page_size=100)
        first=get(client,'historical',dict(history_query,page_number=1));save(a.output/'PRIVATE-HISTORICAL-FIRST.json',first)
        rows,total,pages,page_size=historical_page(first,1,100);historical_responses.append(first);historical_rows.extend(rows);history_observations.append(observation(first))
        for number in range(2,pages+1):
            need(time.monotonic()<deadline,'POSTTRADE_CAPTURE_DEADLINE')
            response=get(client,'historical',dict(history_query,page_number=number))
            rows,new_total,new_pages,new_size=historical_page(response,number,100)
            need((new_total,new_pages,new_size)==(total,pages,page_size),'HISTORICAL_TOTALS_CHANGED_DURING_CAPTURE')
            historical_responses.append(response);historical_rows.extend(rows);history_observations.append(observation(response))
        history_complete=len(historical_rows)==total
        need(history_complete,'HISTORICAL_PAGINATION_COUNT_MISMATCH')
    except Exception as exc:
        label=str(exc);history_error=label if re.fullmatch(r'[A-Z][A-Z0-9_]{0,159}',label) else 'HISTORICAL_PROVIDER_REVIEW_REQUIRED'
    save(a.output/'PRIVATE-HISTORICAL-TRADES.json',dict(responses=historical_responses,pagination=history_observations,complete=history_complete,blocked=history_error))
    metadata_after=get(client,'metadata',query);charges_after=get(client,'charges',query)
    api.matches(client.get('profile'),pin)
    need(time.monotonic()<deadline,'POSTTRADE_CAPTURE_DEADLINE')
    save(a.output/'PRIVATE-RAW-PAGES.json',dict(pages=responses,metadata_after=metadata_after,charges_after=charges_after))
    summary=review(charges,collected,count)
    summary['metadata_stable_during_capture']=metadata_after==metadata
    summary['aggregate_charges_stable_during_capture']=charges_after==charges
    summary['prior_account_signature_verified']=True
    summary['session']=a.session;summary['financial_year']=query['financial_year'];summary['segment']='FO'
    summary['historical_get_capture_completed']=True
    summary['account_scope']=pin['scope']
    summary['component_arithmetic_state']='NOT_ASSESSABLE_NULL_COMPONENTS' if summary['missing_or_null_components'] else ('MATCH' if summary['aggregate_component_arithmetic_matches'] else 'MISMATCH')
    summary['ipft_null_is_shown_in_official_example']=True
    summary['null_component_converted_to_zero']=False
    summary['historical_trade_capture_complete']=history_complete
    summary['historical_pagination_observations']=history_observations
    summary['historical_completeness_basis']='EXACT_COLLECTED_ROW_COUNT_EQUALS_BROKER_TOTAL_RECORDS' if history_complete else 'INCOMPLETE_OR_BLOCKED'
    summary['historical_trade_capture_blocked']=history_error
    prior_trades=api.response_data(prior['raw_trades'],'prior_trades',list)
    summary['historical_trade_corroboration']=corroborate(historical_rows,prior_trades,a.session) if history_complete else None
    old_path=a.prior_finance/'PRIVATE-POSTTRADE-EVIDENCE.json';private_file(old_path)
    old=json.loads(old_path.read_text());old_signature=old.pop('signature',None)
    need(isinstance(old_signature,str) and hmac.compare_digest(old_signature,api.sign(old,pin)) and old['account_scope']==pin['scope'] and old['session']==a.session,'PRIOR_FINANCE_SIGNATURE_OR_SCOPE_CHANGED')
    summary['prior_finance_signature_verified']=True
    summary['prior_report_rows']=old['review']['report_rows']
    summary['report_row_count_changed']=summary['report_rows']!=old['review']['report_rows']
    summary['charge_response_changed']=charges!=old['raw_charges']

    proof=dict(model='HILEGA_ACCOUNT_BOUND_HISTORICAL_FINANCE_V1',account_scope=pin['scope'],session=a.session,query=query,started_at=began.isoformat(),completed_at=datetime.now(timezone.utc).isoformat(),raw_charges=charges,raw_charges_after=charges_after,raw_metadata=metadata,raw_metadata_after=metadata_after,raw_pages=responses,raw_historical_trades=historical_responses,review=summary,prior_evidence_signature=signature,not_atomic=True,production_execution_enabled=False)
    proof['signature']=api.sign(proof,pin);save(a.output/'PRIVATE-POSTTRADE-EVIDENCE.json',proof)
    print(json.dumps(summary));return 0

if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as exc:
        reason=str(exc);safe=reason if re.fullmatch(r'[A-Z][A-Z0-9_]{0,159}',reason) else 'POSTTRADE_PROVIDER_REVIEW_REQUIRED'
        print(json.dumps(dict(status='POSTTRADE_CAPTURE_BLOCKED',reason=safe,error_type=type(exc).__name__,production_execution_enabled=False)));raise SystemExit(2)
