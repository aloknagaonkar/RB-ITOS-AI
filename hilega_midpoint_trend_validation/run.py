"""Offline V2 + accepted Midpoint confirmation research; never dispatches orders."""
import argparse, bisect, calendar, csv, hashlib, importlib.util, json, os, sys, tempfile
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from market_lab import hilega_v2_alignment_replay_v1 as engine
from market_lab.midpoint_strategy.config import live_shadow_config_from_env
from market_lab.midpoint_strategy.live_shadow_v1 import MidpointLiveShadowCoordinatorV1

DEFAULT_MIDPOINT = [Path('data/historical-evidence/hilega-pcr-oi-support-research-v1/midpoint-ui-replay-v1'), Path('data/recovery/october-2026/midpoint'), Path('data/recovery/october-2026/replay-input/midpoint')]
class OfflineSources:
 def __getattr__(self,name): raise RuntimeError('External data access prohibited: '+name)
def dump(p,x): p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,indent=2,default=str))
def csvwrite(p,rows):
 keys=list(dict.fromkeys(k for r in rows for k in r)) or ['session_date']
 with p.open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows([{k:json.dumps(v,default=str) if isinstance(v,(list,dict)) else v for k,v in r.items()} for r in rows])
def metrics(ts):
 gain=sum(max(t['points'],0) for t in ts);loss=sum(max(-t['points'],0) for t in ts)
 return dict(trades=len(ts),winners=sum(t['points']>0 for t in ts),losers=sum(t['points']<0 for t in ts),gains=round(gain,2),losses=round(loss,2),net=round(gain-loss,2),gain_loss_ratio=gain/loss if loss else None)
def start(end,months):
 y,m=divmod(end.year*12+end.month-1-months,12);m+=1
 return date(y,m,min(end.day,calendar.monthrange(y,m)[1]))+timedelta(days=1)
class Trend:
 def __init__(self,rows,events):
  grouped={}
  for e in events:
   if e.get('result')=='SHADOW_ENTRY' and e.get('direction') in ('BULLISH','BEARISH'):
    at=datetime.fromisoformat(e['event_timestamp'])+timedelta(minutes=1)
    grouped.setdefault(at,[]).append(e)
  self.timeline=[];side='NEUTRAL';mid=None;confirmation=None
  for r in sorted(rows,key=lambda r:r['timestamp']):
   at=datetime.fromisoformat(r['timestamp'])+timedelta(minutes=1);reason='RETAINED'
   if mid is not None and ((side=='BULLISH' and r['underlying_close']<mid) or (side=='BEARISH' and r['underlying_close']>mid)):
    side='NEUTRAL';mid=None;reason='CONFIRMED_STRUCTURE_INVALIDATED'
   es=grouped.get(at,[])
   if es:
    directions={e['direction'] for e in es}
    if len(directions)!=1 or any(e.get('midpoint') is None for e in es):side='NEUTRAL';mid=None;reason='CONFLICT_OR_MISSING_REFERENCE'
    else:
     side=es[-1]['direction'];mid=float(es[-1]['midpoint']);confirmation=at.isoformat();reason='ACCEPTED_MIDPOINT_CONFIRMATION'
   self.timeline.append(dict(available_at=at.isoformat(),direction=side,confirmed_midpoint=mid,confirmation_at=confirmation,reason=reason))
  self.times=[datetime.fromisoformat(r['available_at']) for r in self.timeline]
 def at(self,at):
  i=bisect.bisect_right(self.times,at)-1
  if i<0 or self.times[i].date()!=at.date() or at-self.times[i]>=timedelta(minutes=1):return dict(direction='NEUTRAL',reason='MISSING_OR_STALE_MIDPOINT')
  return self.timeline[i]
def midpoint(rows,config):
 with tempfile.TemporaryDirectory(prefix='hilega-midpoint-research-') as d:
  path=Path(d)/'audit.jsonl';coord=MidpointLiveShadowCoordinatorV1(market_sources=OfflineSources(),audit_path=path,config=config)
  coord._reset_session(date.fromisoformat(rows[0]['timestamp'][:10]));seen={}
  old=os.environ.get('MIDPOINT_V62_OOS_COLLECTOR_ENABLED');os.environ['MIDPOINT_V62_OOS_COLLECTOR_ENABLED']='0'
  try:
   for r in rows:
    t=datetime.fromisoformat(r['timestamp']);c=SimpleNamespace(timestamp=t,open=r['underlying_open'],high=r['underlying_high'],low=r['underlying_low'],close=r['underlying_close'],volume=0);seen[t]=c
    coord._process_minute(ts=t,underlying=c,futures_close=r['futures_close'],futures_vwap=r['futures_vwap'],futures_open=r.get('futures_open'),futures_volume=r['futures_volume'],underlying_by_ts=seen.copy())
  finally:
   if old is None:os.environ.pop('MIDPOINT_V62_OOS_COLLECTOR_ENABLED',None)
   else:os.environ['MIDPOINT_V62_OOS_COLLECTOR_ENABLED']=old
  events=[json.loads(s) for s in path.read_text().splitlines()] if path.exists() else []
 return Trend(rows,events),events

def filtered(day,raw,warm,trend):
 name='market_lab._isolated_midpoint_filtered_replay';spec=importlib.util.spec_from_file_location(name,engine.__file__);mod=importlib.util.module_from_spec(spec);sys.modules[name]=mod;spec.loader.exec_module(mod);logs=[]
 mod.WmaGapGate=make_gate(mod,trend,logs)
 try:x=mod.replay(day,raw,warm,{'source':'OFFLINE_MIDPOINT_TREND_FILTER'})
 finally:sys.modules.pop(name,None)
 x['midpoint_filter_checks']=logs;x['midpoint_timeline']=trend.timeline
 for t in x['trades']:t['midpoint_at_entry']=trend.at(datetime.fromisoformat(t['entry_time']))
 return x

def make_gate(mod,trend,logs):
 base=mod.WmaGapGate
 class Gate(base):
  def signal(self,event,available):
   side=mod.direction(event);t=trend.at(available);ok=t['direction']==side
   logs.append(dict(stage='SETUP',timestamp=available.isoformat(),direction=side,allowed=ok,midpoint=t))
   if ok:super().signal(event,available)
  def evaluate(self,**kw):
   at=kw['minute']+timedelta(minutes=1);t=trend.at(at)
   for side in list(self.pending):
    ok=t['direction']==side
    logs.append(dict(stage='ENTRY_CHECK',timestamp=at.isoformat(),direction=side,allowed=ok,midpoint=t))
    if not ok:del self.pending[side]
   return super().evaluate(**kw)
 return Gate

def validate_inputs(day,raw,rows):
 by={r['timestamp']:r for r in raw};seen=set()
 for r in rows:
  stamp=r['timestamp'];t=datetime.fromisoformat(stamp)
  if stamp in seen:raise ValueError('DUPLICATE_MIDPOINT_MINUTE:'+stamp)
  seen.add(stamp)
  if t.date().isoformat()!=day:raise ValueError('MIDPOINT_DATE_MISMATCH')
  if '09:15'<=t.strftime('%H:%M')<'14:55':
   n=by.get(stamp)
   if n is None:raise ValueError('MISSING_MATCHING_NIFTY_MINUTE:'+stamp)
   for key in ('open','high','low','close'):
    if abs(float(n[key])-float(r['underlying_'+key]))>0.011:raise ValueError('NIFTY_MIDPOINT_PRICE_MISMATCH:'+stamp+':'+key)
  for k in ('futures_close','futures_vwap','futures_volume'):
   if r.get(k) is None:raise ValueError('MISSING_MIDPOINT_FIELD:'+k+':'+stamp)
 first=datetime.fromisoformat(day+'T09:15:00+05:30')
 if any((first+timedelta(minutes=i)).isoformat() not in seen for i in range(340)):raise ValueError('INCOMPLETE_MIDPOINT_STRATEGY_WINDOW')

def run(a):
 roots=a.cache_root or list(engine.CACHE_ROOTS);index=engine.cache_index(roots);end=date.fromisoformat(a.end_date);begin=date.fromisoformat(a.start_date) if a.start_date else start(end,3)
 out=a.output_root
 if out.exists():raise ValueError('Output exists; choose a new --output-root to preserve previous research')
 out.mkdir(parents=True);config=live_shadow_config_from_env();config.assert_safe();daily=[];trades=[];coverage=[];alllogs=[];hashes={};warm=[]
 for day,p in sorted(index.items()):
  if day>end.isoformat():continue
  data=json.loads(p.read_text());raw=data.get('candles') or []
  if day<begin.isoformat():
   if raw:warm.append((day,raw))
   continue
  if not raw:coverage.append(dict(session_date=day,status='EMPTY_NIFTY_CACHE'));continue
  paths=[root/day/'minutes.jsonl' for root in (a.midpoint_root or DEFAULT_MIDPOINT)];mp=next((p for p in reversed(paths) if p.is_file()),None)
  try:
   if mp is None:raise ValueError('MIDPOINT_MINUTES_UNAVAILABLE')
   rows=sorted([json.loads(s) for s in mp.read_text().splitlines() if s.strip()],key=lambda r:r['timestamp']);validate_inputs(day,raw,rows)
   trend,events=midpoint(rows,config);b=engine.replay(day,raw,warm);f=filtered(day,raw,warm,trend)
   bm=metrics(b['trades']);fm=metrics(f['trades']);row=dict(session_date=day,**{'baseline_'+k:v for k,v in bm.items()},**{'filtered_'+k:v for k,v in fm.items()},net_delta=round(fm['net']-bm['net'],2),blocked_checks=sum(not l['allowed'] for l in f['midpoint_filter_checks']),accepted_midpoint_confirmations=sum(e.get('result')=='SHADOW_ENTRY' for e in events));daily.append(row);print(json.dumps(row),flush=True)
   dump(out/'sessions'/day/'filtered.json',f);dump(out/'sessions'/day/'midpoint-events.json',events)
   for variant,x in [('BASELINE',b),('MIDPOINT_FILTER',f)]:
    trades.extend(dict(session_date=day,variant=variant,**t) for t in x['trades'])
   alllogs.extend(dict(session_date=day,**l) for l in f['midpoint_filter_checks']);coverage.append(dict(session_date=day,status='EVALUATED',midpoint_source=str(mp)))
   hashes[str(mp)]=hashlib.sha256(mp.read_bytes()).hexdigest()
  except (ValueError,KeyError,FileNotFoundError) as e:coverage.append(dict(session_date=day,status='NOT_EVALUATED',reason=str(e)));print(day,str(e),flush=True)
  warm.append((day,raw))
 cursor=begin
 while cursor<=end:
  if cursor.isoformat() not in index:coverage.append(dict(session_date=cursor.isoformat(),status='NIFTY_CACHE_MISSING'))
  cursor+=timedelta(days=1)
 for d,p in index.items():
  if d<=end.isoformat():hashes[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
 summary=[]
 for months in (1,3):
  for variant in ('BASELINE','MIDPOINT_FILTER'):
   ts=[t for t in trades if t['variant']==variant and start(end,months).isoformat()<=t['session_date']]
   summary.append(dict(months=months,variant=variant,evaluated_sessions=sum(start(end,months).isoformat()<=r['session_date'] for r in daily),**metrics(ts)))
 csvwrite(out/'daily.csv',daily);csvwrite(out/'trades.csv',trades);csvwrite(out/'filter-checks.csv',alllogs);csvwrite(out/'coverage.csv',coverage);csvwrite(out/'summary.csv',summary)
 dump(out/'report.json',dict(configuration=asdict(config),baseline_rules=engine.RULES,summary=summary,coverage=coverage,input_sha256=hashes,engine_sha256=hashlib.sha256(Path(engine.__file__).read_bytes()).hexdigest(),research_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),execution_enabled=False,warning='Reconstructed Nifty points. Same covered dates only; missing data is not zero trades. No costs, option fills or live parity claim. Confirmation becomes available after its one-minute candle closes. Filter does not force exits.'))
 print('Output:',out,flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--end-date',default='2026-10-09');p.add_argument('--start-date');p.add_argument('--cache-root',action='append',type=Path);p.add_argument('--midpoint-root',action='append',type=Path);p.add_argument('--output-root',type=Path,default=Path('data/historical-evidence/hilega-midpoint-trend-validation-v1'));p.add_argument('--self-test',action='store_true');a=p.parse_args()
 if a.self_test:
  import unittest
  suite=unittest.defaultTestLoader.discover(str(Path(__file__).parent),pattern='test_*.py');result=unittest.TextTestRunner(verbosity=2).run(suite);sys.exit(not result.wasSuccessful())
 try:
  from dotenv import load_dotenv
  load_dotenv('.env',override=False)
 except ImportError:pass
 run(a)
