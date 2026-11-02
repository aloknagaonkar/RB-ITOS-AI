"""Account-bound GET-only cross-endpoint timestamp evidence; no timestamp corrections."""
import argparse,json,os,re,sqlite3,stat,sys,time
from pathlib import Path
from datetime import datetime,timezone
from email.utils import parsedate_to_datetime
from compare import compare_trade,need
from read_client import get

def private_file(path):
    need(path.is_absolute() and path.is_file() and not any(x.is_symlink() for x in [path,*path.parents]),'REGULAR_PRIVATE_INPUT_REQUIRED')
    info=path.stat();need(info.st_uid==os.getuid() and stat.S_IMODE(info.st_mode)&0o077==0,'PRIVATE_OWNED_INPUT_REQUIRED')

def save(path,value):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:json.dump(value,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())

def main():
    p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,required=True);p.add_argument('--bundle',type=Path,required=True);p.add_argument('--adapter',type=Path,required=True);p.add_argument('--pid',type=int,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
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
    start=datetime.now(timezone.utc);deadline=time.monotonic()+120
    api.matches(client.get('profile'),pin)
    raw_orders=client.get('orders');orders=api.response_data(raw_orders,'orders',list)
    raw_trades=client.get('trades');trades=api.response_data(raw_trades,'trades',list)
    raw_positions=client.get('positions');positions=api.response_data(raw_positions,'positions',list)
    lookup={o.get('order_id'):o for o in orders if isinstance(o,dict) and isinstance(o.get('order_id'),str)}
    ids=sorted({t['order_id'] for t in trades if isinstance(t,dict) and isinstance(t.get('order_id'),str) and t['order_id'] in lookup})
    selected=ids[:5];details={};summaries=[];dates=[]
    for index,oid in enumerate(selected,1):
        need(time.monotonic()<deadline,'AUDIT_COLLECTION_DEADLINE_EXCEEDED')
        history,hdate=get(client,'history',oid);per_order,tdate=get(client,'order_trades',oid)
        details[oid]=dict(history=history,order_trades=per_order)
        for kind,value in [('history',hdate),('order_trades',tdate)]:
            try:
                parsed=parsedate_to_datetime(value)
                dates.append(dict(order_ordinal=index,endpoint=kind,http_date_utc=parsed.astimezone(timezone.utc).isoformat() if parsed.tzinfo else None,local_minus_http_date_seconds=round((datetime.now(timezone.utc)-parsed).total_seconds(),3) if parsed.tzinfo else None))
            except (TypeError,ValueError,OverflowError):dates.append(dict(order_ordinal=index,endpoint=kind,http_date_utc=None))
        for trade in trades:
            if isinstance(trade,dict) and trade.get('order_id')==oid:summaries.append(dict(order_ordinal=index,**compare_trade(trade,per_order['data'],history['data'])))
    api.matches(client.get('profile'),pin);end=datetime.now(timezone.utc)
    need(time.monotonic()<=deadline,'AUDIT_COLLECTION_DEADLINE_EXCEEDED')
    proof=dict(model='HILEGA_ACCOUNT_BOUND_TIMESTAMP_AUDIT_V1',account_scope=pin['scope'],started_at=start.isoformat(),completed_at=end.isoformat(),profile_verified_before_and_after=True,
        raw_orders=raw_orders,raw_trades=raw_trades,raw_positions=raw_positions,per_order_details=details,not_atomic=True,
        timestamp_policy_confirmed=False,production_execution_enabled=False,orders_sent=False)
    proof['signature']=api.sign(proof,pin);save(a.output/'PRIVATE-ACCOUNT-BOUND-EVIDENCE.json',proof)
    position_schema=all(isinstance(row,dict) and type(row.get('quantity')) is int for row in positions)
    result=dict(status='CROSS_ENDPOINT_TIMESTAMP_AUDIT_CAPTURED' if summaries else 'NO_CURRENT_DAY_MATCHED_TRADES_AVAILABLE',
        order_rows=len(orders),trade_rows=len(trades),position_rows=len(positions),position_quantity_schema_complete=position_schema,
        nonzero_position_rows=sum(row['quantity']!=0 for row in positions) if position_schema else None,
        audited_orders=len(selected),order_limit=5,all_matched_orders_included=len(ids)<=5,
        unmatched_day_trade_rows=sum(not isinstance(t,dict) or t.get('order_id') not in lookup for t in trades),
        fill_comparisons=summaries,http_date_observations=dates,
        private_signed_capture_saved=True,profile_verified_before_and_after=True,
        timezone_contract_confirmed=False,timestamps_modified=False,execution_permission=False,
        strategy_ownership_verified=False,production_execution_enabled=False)
    save(a.output/'PUBLIC-COMPARISON.json',result);print(json.dumps(result));return 0
if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as exc:
        reason=str(exc);safe=reason if re.fullmatch(r'[A-Z][A-Z0-9_]{0,159}',reason) else 'TIMESTAMP_AUDIT_READ_REQUIRES_REVIEW'
        print(json.dumps(dict(status='TIMESTAMP_AUDIT_BLOCKED',reason=safe,error_type=type(exc).__name__,production_execution_enabled=False)));raise SystemExit(2)
