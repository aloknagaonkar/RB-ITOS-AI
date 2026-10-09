"""Five actual Sandbox submissions per signal; no daily count cap or live orders."""
from __future__ import annotations
import argparse,hashlib,json,os,time
from dataclasses import asdict
from datetime import date,datetime
from pathlib import Path
from filelock import FileLock
from dotenv import dotenv_values
from .hilega_upstox_sandbox_execution_v1 import SandboxConfig,UpstoxTransport,UNDERLYING
from .hilega_upstox_sandbox_live_worker_v1 import JsonControl,DispatchStore,arm_session as arm_v1,DEFAULT_DISPATCH,DEFAULT_PID,IST
from .hilega_sandbox_event_bridge_v1 import BridgeConfig,HilegaSandboxEventBridgeV1,IntentStore,DEFAULT_SOURCE,DEFAULT_OUTPUT
from .hilega_sandbox_prearm_exit_guard_v1 import is_prearm_exit
MODEL='HILEGA_UPSTOX_SANDBOX_BASKET_V2'
ROOT=Path('data/live-observation/hilega-upstox-sandbox-v2')
CONTROL=ROOT/'control.json';JOURNAL=ROOT/'basket-events.jsonl'
def now():return datetime.now(IST)
def strategy(env=Path('.env')):return os.getenv('LIVE_SHADOW_STRATEGY') or dotenv_values(env).get('LIVE_SHADOW_STRATEGY') or 'HILEGA_DIRECTIONAL_SHADOW_V1'

def select_five(contracts,spot,direction,day):
    future=[r for r in contracts if str(r.get('expiry',''))>=day]
    if not future:raise ValueError('NO_ELIGIBLE_EXPIRY')
    expiry=min(r['expiry'] for r in future);side='CE' if direction=='BULLISH' else 'PE'
    rs=sorted([r for r in future if r['expiry']==expiry and r['instrument_type']==side],key=lambda r:float(r['strike_price']))
    strikes=[float(r['strike_price']) for r in rs]
    if not rs or len(set(strikes))!=len(strikes):raise ValueError('MISSING_OR_AMBIGUOUS_STRIKES')
    index=min(range(len(rs)),key=lambda i:(abs(strikes[i]-spot),strikes[i]))
    if index<2 or index+2>=len(rs):raise ValueError('FIVE_ADJACENT_STRIKES_UNAVAILABLE')
    selected=rs[index-2:index+3]
    if any(float(selected[i+1]['strike_price'])-float(selected[i]['strike_price'])!=50 for i in range(4)):raise ValueError('NON_CONTIGUOUS_NIFTY_STRIKES')
    if len({r['instrument_key'] for r in selected})!=5 or any(int(r['lot_size'])<=0 for r in selected):raise ValueError('INVALID_CONTRACTS')
    return [dict(role=i-2,expiry=expiry,strike=float(r['strike_price']),option_type=side,instrument_key=r['instrument_key'],lot_size=int(r['lot_size']),spot=spot) for i,r in enumerate(selected)]

class BasketTransport(UpstoxTransport):
    def resolve_five(self,direction,day):
        payload=self._body(self.analytics.get('/v3/market-quote/ltp',params={'instrument_key':UNDERLYING}))
        spot=float(next(iter(payload['data'].values()))['last_price'])
        contracts=self._body(self.analytics.get('/v2/option/contract',params={'instrument_key':UNDERLYING}))['data']
        return select_five(contracts,spot,direction,day)
    def quotes(self,keys):
        if not keys:return {}
        payload=self._body(self.analytics.get('/v3/market-quote/ltp',params={'instrument_key':','.join(keys)}))
        return {str(r.get('instrument_token')):float(r['last_price']) for r in payload['data'].values() if r.get('instrument_token')}
    def close(self):self.analytics.close();self.sandbox.close()

class BasketStore(DispatchStore):
    def append(self,row):super().append({**dict(model=MODEL,sandbox_only=True,live_execution_enabled=False,timestamp=now().isoformat()),**row})
    def accepted(self):return [r for r in self.rows() if r.get('status')=='ACCEPTED']
    def open_legs(self):
        opened={}
        for r in self.accepted():
            key=(r['trade_id'],r['role'])
            if r['event_type']=='ENTRY':opened[key]=r
            else:opened.pop(key,None)
        return list(opened.values())
    def uncertain(self):
        rows=self.rows();done={r['request_id'] for r in rows if r.get('status')=='ACCEPTED'}
        return [r for r in rows if r.get('status')=='REQUESTED' and r['request_id'] not in done]
    def terminal_ids(self):return {r['intent_id'] for r in self.rows() if r.get('status') in {'INTENT_COMPLETE','SKIPPED_PRE_ARM_TRADE_EXIT','ENTRY_BLOCKED','EXIT_BLOCKED'}}

def ensure_clear(store):
    if store.open_legs() or store.uncertain():raise ValueError('OPEN_OR_UNCERTAIN_SANDBOX_LEGS_RECONCILE_BEFORE_REARM')
def arm(day,source,control,store,env=Path('.env'),at=None,check_legacy=True):
    ensure_clear(store)
    if check_legacy:
        legacy=DispatchStore(DEFAULT_DISPATCH).rows();open_ids=set()
        for r in legacy:
            if r.get('status')=='ACCEPTED':
                if r['event_type']=='ENTRY':open_ids.add(r['trade_id'])
                else:open_ids.discard(r['trade_id'])
        if open_ids or any(r.get('status')=='FAILED' and not r.get('terminal') for r in legacy):raise ValueError('LEGACY_SANDBOX_POSITION_OR_FAILURE_REQUIRES_RECONCILIATION')
    if check_legacy:
        from .hilega_upstox_sandbox_execution_v1 import JsonlJournal
        history=JsonlJournal(SandboxConfig.from_env(env).journal_path).rows()
        terminal={r.get('event_id') for r in history if r.get('terminal')}
        if any(r.get('status')=='REQUESTED' and r.get('event_id') not in terminal for r in history):raise ValueError('LEGACY_UNCERTAIN_REQUEST_RECONCILE_BEFORE_SWITCH')
    c=arm_v1(session_date=day,source=source,control=control,max_orders=20,confirmation='ARM_UPSTOX_SANDBOX_ONLY',now=at)
    c.update(model=MODEL,strategy_id=strategy(env),execution_mode='FIVE_ACTUAL_SANDBOX_LEGS',order_count_limit=None,max_orders=None)
    control.write(c);return c

class BasketWorker:
    def __init__(self,control=CONTROL,journal=JOURNAL,env=Path('.env'),transport=None,clock=now):
        self.control=JsonControl(control);self.store=BasketStore(journal);self.env=env;self.transport=transport;self.clock=clock
    def block(self,reason):
        c=self.control.read();c.update(entries_blocked=True,failure_reason=reason,failed_at=self.clock().isoformat());self.control.write(c)
    def process(self,intent,intents,transport,config):
        c=self.control.read();rows=self.store.rows();base=dict(intent_id=intent['intent_id'],event_id=intent['event_id'],trade_id=intent['trade_id'],event_type=intent['event_type'],direction=intent['direction'],session_date=c['session_date'],event_timestamp=intent['event_timestamp'],source_sequence=intent['source_sequence'],strategy_id=c['strategy_id'])
        if intent['intent_id'] in self.store.terminal_ids():return
        if is_prearm_exit(intent,intents,c,rows):self.store.append(dict(base,status='SKIPPED_PRE_ARM_TRADE_EXIT',terminal=True));return
        opened=self.store.open_legs()
        if intent['event_type']=='ENTRY':
            if c.get('entries_blocked') or opened or self.store.uncertain():self.store.append(dict(base,status='ENTRY_BLOCKED',terminal=True,reason='OPEN_BASKET_OR_RECONCILIATION_REQUIRED'));return
            plans=[r for r in rows if r.get('status')=='BASKET_PLANNED' and r.get('intent_id')==intent['intent_id']]
            try:contracts=plans[-1]['contracts'] if plans else transport.resolve_five(intent['direction'],c['session_date'])
            except Exception as exc:self.store.append(dict(base,status='ENTRY_BLOCKED',terminal=True,reason='CONTRACT_SELECTION_FAILED',error_type=type(exc).__name__));return
            # Freeze the complete basket BEFORE any submission; never reselect on retry/exit.
            if len(contracts)!=5 or sorted(x['role'] for x in contracts)!=[-2,-1,0,1,2]:raise ValueError('INVALID_FIVE_LEG_PLAN')
            self.store.append(dict(base,status='BASKET_PLANNED',contracts=contracts))
            legs=[dict(contract=x,quantity=int(x['lot_size'])*config.lots,role=x['role']) for x in contracts]
        else:
            legs=[r for r in opened if r['trade_id']==intent['trade_id'] and r['direction']==intent['direction']]
            if not legs:
                self.block('UNMATCHED_EXIT_REQUIRES_RECONCILIATION');self.store.append(dict(base,status='EXIT_BLOCKED',reason='NO_MATCHING_ACCEPTED_ENTRY'));return
        for leg in legs:
            request_id=hashlib.sha256(f"{intent['intent_id']}|{leg['role']}".encode()).hexdigest()
            history=[r for r in self.store.rows() if r.get('request_id')==request_id]
            if any(r['status']=='ACCEPTED' for r in history):continue
            if history:self.block('UNCERTAIN_REQUEST_REQUIRES_RECONCILIATION');continue
            contract=leg['contract'];transaction='BUY' if intent['event_type']=='ENTRY' else 'SELL'
            try:quote=transport.instrument_ltp(contract['instrument_key'])
            except Exception:quote=None
            request=dict(base,request_id=request_id,role=leg['role'],contract=contract,quantity=leg['quantity'],transaction_type=transaction,observed_option_price=quote,observed_option_price_at=self.clock().isoformat(),status='REQUESTED',terminal=False)
            self.store.append(request)
            try:
                order_id=transport.place_market(instrument_key=contract['instrument_key'],quantity=leg['quantity'],transaction_type=transaction,tag='HIL5_'+request_id[:32])
            except Exception as exc:
                # Unknown response: do not assume rejection or replay this request.
                self.store.append(dict(base,status='SUBMISSION_UNCERTAIN',request_id=request_id,role=leg['role'],error_type=type(exc).__name__))
                self.block('SUBMISSION_UNCERTAIN_RECONCILE_REQUIRED')
                if transaction=='BUY':break
                continue # Attempt exits for the OTHER known accepted legs.
            self.store.append(dict(request,status='ACCEPTED',terminal=True,broker_order_id=order_id))
        if not any(r.get('intent_id')==intent['intent_id'] and r.get('status')=='SUBMISSION_UNCERTAIN' for r in self.store.rows()):
            self.store.append(dict(base,status='INTENT_COMPLETE',terminal=True))
    def run_once(self):
        self.store.path.parent.mkdir(parents=True,exist_ok=True)
        with FileLock(str(self.store.path)+'.worker.lock'):
            c=self.control.read()
            if not c.get('armed') or c.get('kill_switch'):return self.status('DISARMED')
            if self.clock().date().isoformat()!=c.get('session_date'):return self.status('WAITING_FOR_ARMED_SESSION')
            if c.get('strategy_id')!=strategy(self.env):self.block('STRATEGY_CHANGED');return self.status('STRATEGY_CHANGED')
            cfg=SandboxConfig.from_env(self.env);cfg.assert_ready('SANDBOX_ONLY') # Config's V1 cap is intentionally not consulted for submission counts.
            bridge=HilegaSandboxEventBridgeV1(BridgeConfig(True,Path(os.getenv('HILEGA_SANDBOX_BRIDGE_SOURCE',str(DEFAULT_SOURCE))),Path(os.getenv('HILEGA_SANDBOX_BRIDGE_OUTPUT',str(DEFAULT_OUTPUT)))))
            bridge.run_once();intents=IntentStore(bridge.config.output).rows()
            eligible=sorted([r for r in intents if r.get('decision')=='WOULD_SUBMIT' and r['event_timestamp'][:10]==c['session_date'] and int(r['source_sequence'])>int(c['baseline_source_sequence']) and r['intent_id'] not in self.store.terminal_ids() and (r.get('strategy_id')==c['strategy_id'] or (not r.get('strategy_id') and c['strategy_id']=='HILEGA_DIRECTIONAL_SHADOW_V1'))],key=lambda r:(int(r['source_sequence']),0 if r['event_type']=='EXIT' else 1,r['intent_id']))
            transport=self.transport or BasketTransport(cfg.analytics_token,cfg.sandbox_token)
            try:
                for r in eligible:self.process(r,intents,transport,cfg)
            finally:
                if self.transport is None:transport.close()
            return self.status('PROCESSED')
    def status(self,state='STATUS'):
        c=self.control.read();rs=[r for r in self.store.accepted() if r['session_date']==c.get('session_date')]
        return dict(c,status=state,accepted_orders_this_session=len(rs),open_legs=len(self.store.open_legs()),uncertain_requests=len(self.store.uncertain()),live_order_sent=False)


def build_dashboard(env=Path('.env')):
    worker=BasketWorker(env=env);control=worker.control.read();day=control.get('session_date');accepted=[r for r in worker.store.accepted() if r['session_date']==day];pairs={}
    for r in accepted:
        pair=pairs.setdefault((r['trade_id'],r['role']),{});pair[r['event_type']]=r
    cfg=SandboxConfig.from_env(env);keys=[p['ENTRY']['contract']['instrument_key'] for p in pairs.values() if p.get('ENTRY') and not p.get('EXIT')];quotes={};quote_error=None
    if keys and cfg.analytics_token:
        tr=BasketTransport(cfg.analytics_token,cfg.sandbox_token)
        try:quotes=tr.quotes(keys)
        except Exception:quote_error='CURRENT_QUOTES_UNAVAILABLE'
        finally:tr.close()
    trades={}
    for (trade_id,role),pair in pairs.items():
        en=pair.get('ENTRY');ex=pair.get('EXIT')
        if not en:continue
        entry_price=en.get('observed_option_price');mark=ex.get('observed_option_price') if ex else quotes.get(en['contract']['instrument_key']);pts=mark-entry_price if mark is not None and entry_price is not None else None
        leg=dict(**en['contract'],quantity=en['quantity'],entry_time=en['timestamp'],entry_signal_time=en['event_timestamp'],entry_price=entry_price,entry_order_id=en['broker_order_id'],exit_time=ex.get('timestamp') if ex else None,exit_price=ex.get('observed_option_price') if ex else None,exit_order_id=ex.get('broker_order_id') if ex else None,current_price=mark,quote_timestamp=now().isoformat() if not ex and mark is not None else None,points=pts,pnl_rupees=pts*en['quantity'] if pts is not None else None,status='SELL_ACKNOWLEDGED' if ex else 'BUY_ACKNOWLEDGED')
        trade=trades.setdefault(trade_id,dict(trade_id=trade_id,direction=en['direction'],signal_time=en['event_timestamp'],strategy_id=en['strategy_id'],expiry=en['contract']['expiry'],legs=[]));trade['legs'].append(leg)
    for plan in worker.store.rows():
        if plan.get('status')!='BASKET_PLANNED' or plan.get('session_date')!=day:continue
        t=trades.setdefault(plan['trade_id'],dict(trade_id=plan['trade_id'],direction=plan['direction'],signal_time=plan['event_timestamp'],strategy_id=plan['strategy_id'],expiry=plan['contracts'][0]['expiry'],legs=[]))
        for contract in plan['contracts']:
            if any(l['role']==contract['role'] for l in t['legs']):continue
            uncertain=any(r['trade_id']==plan['trade_id'] and r['role']==contract['role'] for r in worker.store.uncertain())
            t['legs'].append(dict(role=contract['role'],**{k:v for k,v in contract.items() if k!='role'},quantity=int(contract['lot_size'])*cfg.lots,entry_time=None,entry_signal_time=plan['event_timestamp'],entry_price=None,entry_order_id=None,exit_time=None,exit_price=None,exit_order_id=None,current_price=None,quote_timestamp=None,points=None,pnl_rupees=None,status='SUBMISSION_UNCERTAIN' if uncertain else 'NOT_SUBMITTED'))
    for t in trades.values():
        t['legs'].sort(key=lambda l:l['role']);t['status']='RECONCILIATION_REQUIRED' if any(l['status']=='SUBMISSION_UNCERTAIN' for l in t['legs']) or any(r['trade_id']==t['trade_id'] for r in worker.store.uncertain()) else 'NOT_SUBMITTED' if not any(l['entry_order_id'] for l in t['legs']) else 'CLOSED_ACKNOWLEDGED' if all(l['exit_order_id'] for l in t['legs'] if l['entry_order_id']) else 'OPEN_ACKNOWLEDGED';t['pnl_rupees']=sum(l['pnl_rupees'] for l in t['legs'] if l['pnl_rupees'] is not None);t['missing_pnl_legs']=sum(l['pnl_rupees'] is None for l in t['legs']);t['partial_basket']=sum(bool(l['entry_order_id']) for l in t['legs'])!=5
    opened=[t for t in trades.values() if t['status']!='CLOSED_ACKNOWLEDGED'];closed=[t for t in trades.values() if t['status']=='CLOSED_ACKNOWLEDGED']
    legs=[l for t in trades.values() for l in t['legs']];priced_closed=[l['pnl_rupees'] for l in legs if l['exit_order_id'] and l['pnl_rupees'] is not None];gains=sum(max(0,v) for v in priced_closed);losses=-sum(min(0,v) for v in priced_closed)
    try:os.kill(int(DEFAULT_PID.read_text()),0);running=True
    except (OSError,ValueError):running=False
    return dict(model=MODEL,worker=dict(worker.status(),running=running),strategy=dict(active_strategy_id=strategy(env),armed_strategy_id=control.get('strategy_id')),active_trades=opened,active_trade=next((l for t in opened for l in t['legs'] if l['role']==0),None),completed_trades=closed,
        pnl=dict(open_estimated_rupees=sum(l['pnl_rupees'] for l in legs if not l['exit_order_id'] and l['pnl_rupees'] is not None),closed_estimated_rupees=sum(priced_closed),total_estimated_rupees=sum(l['pnl_rupees'] for l in legs if l['pnl_rupees'] is not None),gross_profit_rupees=gains,gross_loss_rupees=losses,gain_loss_ratio=gains/losses if losses else None,missing_pnl_legs=sum(l['pnl_rupees'] is None for l in legs)),
        events=[r for r in worker.store.rows() if r.get('session_date')==day and r['status'] not in {'ACCEPTED','REQUESTED','BASKET_PLANNED'}][-50:][::-1],last_refresh=now().isoformat(),quote_error=quote_error,warning='Actual Sandbox order acknowledgements; P&L estimated from observed quotes, not confirmed fills. Missing legs/prices are explicit. No daily order-count cap.',safety=dict(sandbox_only=True,live_execution_enabled=False))

def main():
    p=argparse.ArgumentParser();g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--arm-session',type=date.fromisoformat);g.add_argument('--disarm',action='store_true');g.add_argument('--status',action='store_true');g.add_argument('--serve',action='store_true');g.add_argument('--once',action='store_true')
    p.add_argument('--confirm');p.add_argument('--env-file',type=Path,default=Path('.env'));p.add_argument('--interval-seconds',type=int,default=10);a=p.parse_args();w=BasketWorker(env=a.env_file)
    if a.arm_session:
        if a.confirm!='ARM_UPSTOX_SANDBOX_FIVE_LEGS':raise ValueError('Explicit five-leg Sandbox confirmation required')
        result=arm(a.arm_session,Path(os.getenv('HILEGA_SANDBOX_BRIDGE_SOURCE',str(DEFAULT_SOURCE))),w.control,w.store,a.env_file)
    elif a.disarm:
        c=w.control.read();c.update(armed=False,kill_switch=True);w.control.write(c);result=c
    elif a.status:result=w.status()
    elif a.once:result=w.run_once()
    else:
        if not 2<=a.interval_seconds<=60:raise ValueError('Invalid poll interval')
        while True:
            try:result=w.run_once()
            except Exception as exc:
                w.block('WORKER_ERROR:'+type(exc).__name__);result=w.status('ERROR_RECONCILIATION_REQUIRED')
            print(json.dumps(result),flush=True);time.sleep(a.interval_seconds)
    print(json.dumps(result,indent=2))
if __name__=='__main__':main()
