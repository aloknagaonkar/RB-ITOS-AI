from __future__ import annotations
import csv, hashlib, json, math, uuid
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

MODEL='LIVE_OBSERVATIONAL_SHADOW_V1'
STRATEGY_ID='ALL3_FUTURES_SPOT_LAG_SHADOW_V1'
EXECUTION_ENABLED=False
PAPER_ORDER_ENABLED=False
OBSERVATION_ONLY=True
POLICY_ID='SL5_BE5_TRAIL3_AFTER10_TIME15'
INITIAL_STOP_PCT=5.0
BE_TRIGGER_PCT=5.0
TRAIL_TRIGGER_PCT=10.0
TRAIL_DISTANCE_PCT=3.0
MAX_HOLD_MINUTES=15
ROUND_TRIP_COST_PCT_POINTS=0.5


def _iso(v):
    d=v if isinstance(v,datetime) else datetime.fromisoformat(str(v))
    if d.tzinfo is None: raise ValueError('timestamp must be timezone-aware')
    return d.isoformat()

def _num(v):
    try:
        x=float(v); return x if math.isfinite(x) else None
    except (TypeError,ValueError): return None

def _hash(d):
    return hashlib.sha256(json.dumps(d,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()

@dataclass
class ObservationState:
    observation_id:str
    session_date:str
    direction:str
    status:str='DETECTED'
    all3_state:str|None=None
    candle1_timestamp:str|None=None
    confirmation_timestamp:str|None=None
    futures_oi_state:str|None=None
    futures_aligned:bool|None=None
    spot_c1:float|None=None
    spot_c2:float|None=None
    price_lag_class:str|None=None
    atm_strike:float|None=None
    option_side:str|None=None
    option_instrument_key:str|None=None
    entry_timestamp:str|None=None
    entry_price:float|None=None
    active_stop_price:float|None=None
    best_price_seen:float|None=None
    be_armed:bool=False
    trail_armed:bool=False
    last_bar_timestamp:str|None=None
    mfe_pct:float=0.0
    mae_pct:float=0.0
    exit_timestamp:str|None=None
    exit_price:float|None=None
    exit_reason:str|None=None
    gross_return_pct:float|None=None
    net_return_pct:float|None=None
    rejection_reason:str|None=None

class AuditStore:
    def __init__(self,path):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
    def read_all(self):
        if not self.path.exists(): return []
        return [json.loads(x) for x in self.path.read_text().splitlines() if x.strip()]
    def append(self,oid,event_type,event_time,payload):
        events=self.read_all(); prev=events[-1]['event_hash'] if events else None
        e={'model':MODEL,'strategy_id':STRATEGY_ID,'observation_id':oid,'global_sequence':len(events)+1,
           'event_type':event_type,'event_time':_iso(event_time),'payload':payload,'prev_hash':prev}
        e['event_hash']=_hash(e)
        with self.path.open('a') as f: f.write(json.dumps(e,sort_keys=True)+'\n')
        return e
    def verify_chain(self):
        prev=None
        for i,e in enumerate(self.read_all(),1):
            if e.get('global_sequence')!=i: return False,f'sequence mismatch at {i}'
            if e.get('prev_hash')!=prev: return False,f'prev_hash mismatch at {i}'
            supplied=e.get('event_hash'); x=dict(e); x.pop('event_hash',None)
            if supplied!=_hash(x): return False,f'event_hash mismatch at {i}'
            prev=supplied
        return True,None

def reconstruct_states(events):
    states={}
    for e in events:
        oid=e['observation_id']; et=e['event_type']; p=e['payload']
        if et=='OBSERVATION_DETECTED':
            states[oid]=ObservationState(oid,p['session_date'],p['direction'],all3_state=p['all3_state'],
                candle1_timestamp=p['candle1_timestamp'],spot_c1=_num(p['spot_c1']))
            continue
        s=states[oid]
        if et=='CANDLE2_CONFIRMED': s.status='CONFIRMED_C2'; s.confirmation_timestamp=p['confirmation_timestamp']; s.spot_c2=_num(p['spot_c2'])
        elif et=='FUTURES_ALIGNMENT_CHECKED':
            s.futures_oi_state=p['futures_oi_state']; s.futures_aligned=bool(p['futures_aligned']); s.status='FUTURES_CONFIRMED' if s.futures_aligned else 'REJECTED'; s.rejection_reason=None if s.futures_aligned else 'FUTURES_MISALIGNED'
        elif et=='SPOT_LAG_CLASSIFIED': s.price_lag_class=p['price_lag_class']; s.status='CLASSIFIED'
        elif et=='OPTION_RESOLVED': s.atm_strike=_num(p['atm_strike']); s.option_side=p['option_side']; s.option_instrument_key=p['option_instrument_key']; s.status='OPTION_RESOLVED'
        elif et=='ENTRY_OPENED':
            s.entry_timestamp=p['entry_timestamp']; s.entry_price=_num(p['entry_price']); s.best_price_seen=s.entry_price; s.active_stop_price=s.entry_price*(1-INITIAL_STOP_PCT/100); s.status='OPEN'
        elif et=='RISK_STATE_UPDATED':
            s.active_stop_price=_num(p['active_stop_price']); s.best_price_seen=_num(p['best_price_seen']); s.be_armed=bool(p['be_armed']); s.trail_armed=bool(p['trail_armed']); s.last_bar_timestamp=p['bar_timestamp']; s.mfe_pct=_num(p['mfe_pct']) or 0.0; s.mae_pct=_num(p['mae_pct']) or 0.0; s.status='TRAIL_ARMED' if s.trail_armed else ('BE_ARMED' if s.be_armed else 'OPEN')
        elif et=='TRADE_CLOSED':
            s.status='CLOSED'; s.exit_timestamp=p['exit_timestamp']; s.exit_price=_num(p['exit_price']); s.exit_reason=p['exit_reason']; s.gross_return_pct=_num(p['gross_return_pct']); s.net_return_pct=_num(p['net_return_pct']); s.mfe_pct=_num(p['mfe_pct']) or s.mfe_pct; s.mae_pct=_num(p['mae_pct']) or s.mae_pct
        elif et in {'OBSERVATION_REJECTED','OBSERVATION_INCOMPLETE'}:
            s.status='REJECTED' if et=='OBSERVATION_REJECTED' else 'INCOMPLETE'; s.rejection_reason=p['reason']
    return states

class ShadowEngine:
    def __init__(self,store): self.store=store
    def state(self,oid): return reconstruct_states(self.store.read_all())[oid]
    def detect(self,session_date,direction,all3_state,candle1_timestamp,spot_c1,observation_id=None):
        direction=direction.upper(); expected=f'{direction}_ALL_3'
        if all3_state!=expected: raise ValueError(f'all3_state must be {expected}')
        oid=observation_id or f'OBS-{session_date}-{uuid.uuid4().hex[:10]}'
        self.store.append(oid,'OBSERVATION_DETECTED',candle1_timestamp,{'session_date':session_date,'direction':direction,'all3_state':all3_state,'candle1_timestamp':_iso(candle1_timestamp),'spot_c1':float(spot_c1),'execution_enabled':False,'paper_order_enabled':False,'observation_only':True})
        return oid
    def confirm_candle2(self,oid,confirmation_timestamp,spot_c2,all3_survived):
        if not all3_survived: return self.reject(oid,confirmation_timestamp,'ALL3_DID_NOT_SURVIVE_CANDLE2')
        self.store.append(oid,'CANDLE2_CONFIRMED',confirmation_timestamp,{'confirmation_timestamp':_iso(confirmation_timestamp),'spot_c2':float(spot_c2)})
    def check_futures(self,oid,timestamp,futures_oi_state,futures_aligned):
        self.store.append(oid,'FUTURES_ALIGNMENT_CHECKED',timestamp,{'futures_oi_state':futures_oi_state,'futures_aligned':bool(futures_aligned)})
    def classify_spot_lag(self,oid,timestamp):
        s=self.state(oid); signed=(s.spot_c2-s.spot_c1) if s.direction=='BULLISH' else (s.spot_c1-s.spot_c2); cls='SPOT_LAG' if signed<=0 else 'SPOT_ALREADY_MOVED'
        self.store.append(oid,'SPOT_LAG_CLASSIFIED',timestamp,{'price_lag_class':cls,'target_signed_spot_move_c1_c2':signed,'spot_c1':s.spot_c1,'spot_c2':s.spot_c2}); return cls
    def resolve_option(self,oid,timestamp,atm_strike,option_instrument_key):
        if not option_instrument_key: return self.incomplete(oid,timestamp,'NO_EXACT_ATM_INSTRUMENT')
        s=self.state(oid); side='CE' if s.direction=='BULLISH' else 'PE'
        self.store.append(oid,'OPTION_RESOLVED',timestamp,{'atm_strike':float(atm_strike),'option_side':side,'option_instrument_key':option_instrument_key,'nearest_strike_fallback':False})
    def open_hypothetical_entry(self,oid,entry_timestamp,entry_price):
        s=self.state(oid)
        if s.status!='OPTION_RESOLVED': raise ValueError('option must be resolved before entry')
        self.store.append(oid,'ENTRY_OPENED',entry_timestamp,{'entry_timestamp':_iso(entry_timestamp),'entry_price':float(entry_price),'policy_id':POLICY_ID,'initial_stop_pct':INITIAL_STOP_PCT,'breakeven_trigger_pct':BE_TRIGGER_PCT,'trail_activation_pct':TRAIL_TRIGGER_PCT,'trail_distance_pct':TRAIL_DISTANCE_PCT,'max_hold_minutes':MAX_HOLD_MINUTES,'broker_order_created':False})
    def process_option_bar(self,oid,bar_timestamp,open_,high,low,close):
        s=self.state(oid)
        if s.status in {'CLOSED','REJECTED','INCOMPLETE'}: return s.status
        ts=_iso(bar_timestamp); elapsed=int((datetime.fromisoformat(ts)-datetime.fromisoformat(s.entry_timestamp)).total_seconds()//60)
        stop=s.active_stop_price or s.entry_price*(1-INITIAL_STOP_PCT/100)
        if open_<=stop: return self._close(oid,ts,open_,'STOP_GAP',max(s.best_price_seen or s.entry_price,high),min(low,s.entry_price))
        if low<=stop: return self._close(oid,ts,stop,'STOP_TOUCH',max(s.best_price_seen or s.entry_price,high),min(low,s.entry_price))
        best=max(s.best_price_seen or s.entry_price,high); hp=(high/s.entry_price-1)*100; lp=(low/s.entry_price-1)*100; mfe=max(s.mfe_pct,hp); mae=min(s.mae_pct,lp)
        be=s.be_armed or hp>=BE_TRIGGER_PCT; tr=s.trail_armed or hp>=TRAIL_TRIGGER_PCT; next_stop=stop
        if be: next_stop=max(next_stop,s.entry_price)
        if tr: next_stop=max(next_stop,best*(1-TRAIL_DISTANCE_PCT/100))
        self.store.append(oid,'RISK_STATE_UPDATED',ts,{'bar_timestamp':ts,'bar_open':open_,'bar_high':high,'bar_low':low,'bar_close':close,'elapsed_minutes':elapsed,'active_stop_price':next_stop,'best_price_seen':best,'be_armed':be,'trail_armed':tr,'mfe_pct':mfe,'mae_pct':mae,'activation_effective_from_next_bar':True})
        if elapsed>=MAX_HOLD_MINUTES: return self._close(oid,ts,close,'TIME_EXIT',best,low)
        return self.state(oid).status
    def reject(self,oid,timestamp,reason): self.store.append(oid,'OBSERVATION_REJECTED',timestamp,{'reason':reason})
    def incomplete(self,oid,timestamp,reason): self.store.append(oid,'OBSERVATION_INCOMPLETE',timestamp,{'reason':reason})
    def _close(self,oid,ts,px,reason,best,worst):
        s=self.state(oid); gross=(px/s.entry_price-1)*100; net=gross-ROUND_TRIP_COST_PCT_POINTS
        self.store.append(oid,'TRADE_CLOSED',ts,{'exit_timestamp':ts,'exit_price':px,'exit_reason':reason,'gross_return_pct':gross,'net_return_pct':net,'mfe_pct':(best/s.entry_price-1)*100,'mae_pct':(worst/s.entry_price-1)*100,'broker_order_created':False}); return 'CLOSED'

LEDGER_FIELDS=['observation_id','session_date','direction','status','all3_state','candle1_timestamp','confirmation_timestamp','futures_oi_state','futures_aligned','spot_c1','spot_c2','price_lag_class','atm_strike','option_side','option_instrument_key','entry_timestamp','entry_price','exit_timestamp','exit_price','exit_reason','gross_return_pct','net_return_pct','mfe_pct','mae_pct','rejection_reason']

def write_ledger(events_jsonl,ledger_csv):
    states=list(reconstruct_states(AuditStore(events_jsonl).read_all()).values()); p=Path(ledger_csv); p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=LEDGER_FIELDS); w.writeheader()
        for s in states:
            d=asdict(s); w.writerow({k:d.get(k) for k in LEDGER_FIELDS})
    return states

def daily_summary(states,session_date):
    rows=[s for s in states if s.session_date==session_date]; closed=[s for s in rows if s.status=='CLOSED']; vals=[s.net_return_pct for s in closed if s.net_return_pct is not None]
    ex={}
    for s in closed: ex[s.exit_reason]=ex.get(s.exit_reason,0)+1
    return {'model':MODEL,'session_date':session_date,'observation_count':len(rows),'closed_trade_count':len(closed),'rejected_count':sum(s.status=='REJECTED' for s in rows),'incomplete_count':sum(s.status=='INCOMPLETE' for s in rows),'open_count':sum(s.status in {'OPEN','BE_ARMED','TRAIL_ARMED'} for s in rows),'winner_count':sum(v>0 for v in vals),'loser_count':sum(v<0 for v in vals),'net_return_pct_points_sum':sum(vals),'mean_net_return_pct':None if not vals else sum(vals)/len(vals),'best_trade_net_pct':None if not vals else max(vals),'worst_trade_net_pct':None if not vals else min(vals),'exit_reason_counts':ex,'bullish_closed_count':sum(s.direction=='BULLISH' for s in closed),'bearish_closed_count':sum(s.direction=='BEARISH' for s in closed),'spot_lag_closed_count':sum(s.price_lag_class=='SPOT_LAG' for s in closed),'spot_already_moved_closed_count':sum(s.price_lag_class=='SPOT_ALREADY_MOVED' for s in closed),'execution_enabled':False,'paper_order_enabled':False,'observation_only':True}
