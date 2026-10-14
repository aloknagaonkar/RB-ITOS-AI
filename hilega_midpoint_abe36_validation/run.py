"""Offline V2 + accepted Midpoint confirmation research; never dispatches orders."""
import argparse, bisect, calendar, csv, hashlib, importlib.util, json, os, sys, tempfile
from dataclasses import asdict, replace
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
   if e.get('family') in ('A','B','E') and e.get('result')=='SHADOW_ENTRY' and e.get('direction') in ('BULLISH','BEARISH'):
    at=datetime.fromisoformat(e['event_timestamp'])+timedelta(minutes=1)
    grouped.setdefault(at,[]).append(e)
  self.timeline=[];side='NEUTRAL';mid=None;confirmation=None;family=None;reference_high=None;reference_low=None
  for r in sorted(rows,key=lambda r:r['timestamp']):
   at=datetime.fromisoformat(r['timestamp'])+timedelta(minutes=1);reason='RETAINED'
   if mid is not None and ((side=='BULLISH' and r['underlying_close']<mid) or (side=='BEARISH' and r['underlying_close']>mid)):
    side='NEUTRAL';mid=None;family=None;confirmation=None;reason='CONFIRMED_STRUCTURE_INVALIDATED'
   es=grouped.get(at,[])
   if es:
    directions={e['direction'] for e in es}
    if len(directions)!=1 or any(e.get('midpoint') is None for e in es):side='NEUTRAL';mid=None;family=None;confirmation=None;reason='CONFLICT_OR_MISSING_REFERENCE'
    else:
     side=es[-1]['direction'];mid=float(es[-1]['midpoint']);family=es[-1]['family'];reference_high=es[-1].get('reference_high');reference_low=es[-1].get('reference_low');confirmation=at.isoformat();reason='ACCEPTED_MIDPOINT_CONFIRMATION'
   self.timeline.append(dict(available_at=at.isoformat(),direction=side,confirmed_midpoint=mid,confirmation_at=confirmation,confirming_family=family,reference_high=reference_high if family else None,reference_low=reference_low if family else None,reason=reason))
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
    coord._process_minute(ts=t,underlying=c,futures_close=r['futures_close'],futures_vwap=r['futures_vwap'],futures_open=r.get('futures_open'),futures_volume=r.get('futures_volume'),underlying_by_ts=seen.copy())
  finally:
   if old is None:os.environ.pop('MIDPOINT_V62_OOS_COLLECTOR_ENABLED',None)
   else:os.environ['MIDPOINT_V62_OOS_COLLECTOR_ENABLED']=old
  events=[json.loads(s) for s in path.read_text().splitlines()] if path.exists() else []
 return Trend(rows,events),events

def optimized_module():
 import types
 from warmup import prepare
 source=Path(engine.__file__).read_text()
 old=" for d,rows in sorted(warm):\n  for b in aggregate_exact_5m(candles(rows),date.fromisoformat(d)):c.on_bar(b)"
 if source.count(old)!=1:raise ValueError('Installed V2 warmup differs; refusing unverified optimization')
 source=source.replace(old," c,_,_=prepare_warmup(warm,TARGET)",1)
 mod=types.ModuleType('market_lab._abe36_isolated');mod.__package__='market_lab';mod.__file__=engine.__file__
 exec(compile(source,engine.__file__,'exec'),mod.__dict__);mod.prepare_warmup=prepare
 return mod

def filtered(day,raw,warm,trend):
 mod=optimized_module();logs=[]
 mod.WmaGapGate=make_gate(mod,trend,logs)
 x=mod.replay(day,raw,warm,{'source':'OFFLINE_MIDPOINT_TREND_FILTER'})
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
  for k in ('futures_close','futures_vwap'):
   if r.get(k) is None:raise ValueError('MISSING_MIDPOINT_FIELD:'+k+':'+stamp)
 first=datetime.fromisoformat(day+'T09:15:00+05:30')
 if any((first+timedelta(minutes=i)).isoformat() not in seen for i in range(340)):raise ValueError('INCOMPLETE_MIDPOINT_STRATEGY_WINDOW')

def cohort():
 x=json.loads(Path(__file__).with_name('cohort.json').read_text())
 if set(x)!={'BULLISH','BEARISH'} or any(len(v)!=18 for v in x.values()):raise ValueError('Expected 18+18 sessions')
 result={d:side for side,days in x.items() for d in days}
 if len(result)!=36:raise ValueError('Duplicate cohort dates')
 return result

def run(a):
 selected=cohort();index=engine.cache_index(a.cache_root or list(engine.CACHE_ROOTS));out=a.output_root
 if out.exists():raise ValueError('Output exists; select a fresh --output-root')
 out.mkdir(parents=True)
 config=replace(live_shadow_config_from_env(),family_a_enabled=True,family_b_enabled=True,family_e_enabled=True)
 config.assert_safe();daily=[];trades=[];coverage=[];logs=[];hashes={};warm=[]
 for day in sorted(set(index)|set(selected)):
  if day>max(selected):break
  path=index.get(day);raw=[]
  if path:
   hashes[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest();raw=json.loads(path.read_text()).get('candles') or []
  if day in selected:
   try:
    if not raw:raise ValueError('NIFTY_CACHE_MISSING_OR_EMPTY')
    paths=[root/day/'minutes.jsonl' for root in (a.midpoint_root or DEFAULT_MIDPOINT)]
    mp=next((p for p in reversed(paths) if p.is_file()),None)
    if mp is None:raise ValueError('MIDPOINT_MINUTES_UNAVAILABLE: '+str(paths))
    rows=sorted([json.loads(line) for line in mp.read_text().splitlines() if line.strip()],key=lambda r:r['timestamp'])
    validate_inputs(day,raw,rows);trend,events=midpoint(rows,config)
    baseline=optimized_module();b=baseline.replay(day,raw,warm);f=filtered(day,raw,warm,trend)
    bm=metrics(b['trades']);fm=metrics(f['trades'])
    row=dict(session_date=day,confirmed_session_label=selected[day],**{'baseline_'+k:v for k,v in bm.items()},**{'filtered_'+k:v for k,v in fm.items()},net_delta=round(fm['net']-bm['net'],2),blocked_checks=sum(not r['allowed'] for r in f['midpoint_filter_checks']),accepted_abe_confirmations=sum(e.get('family') in ('A','B','E') and e.get('result')=='SHADOW_ENTRY' for e in events))
    daily.append(row);print(json.dumps(row),flush=True)
    dump(out/'sessions'/day/'baseline.json',b);dump(out/'sessions'/day/'filtered.json',f);dump(out/'sessions'/day/'midpoint-events.json',events)
    for variant,replay in [('BASELINE',b),('MIDPOINT_ABE_FILTER',f)]:
     trades.extend(dict(session_date=day,variant=variant,confirmed_session_label=selected[day],label_alignment='ALIGNED' if t['direction']==selected[day] else 'COUNTER',**t) for t in replay['trades'])
    logs.extend(dict(session_date=day,**r) for r in f['midpoint_filter_checks']);coverage.append(dict(session_date=day,status='EVALUATED',midpoint_source=str(mp)));hashes[str(mp)]=hashlib.sha256(mp.read_bytes()).hexdigest()
   except (ValueError,KeyError,FileNotFoundError) as exc:
    coverage.append(dict(session_date=day,status='NOT_EVALUATED',reason=str(exc)));print(day,str(exc),flush=True)
  if raw:warm.append((day,raw))
 summary=[]
 for variant in ('BASELINE','MIDPOINT_ABE_FILTER'):
  for label in ('ALL','BULLISH','BEARISH'):
   for alignment in ('ALL','ALIGNED','COUNTER'):
    ts=[t for t in trades if t['variant']==variant and (label=='ALL' or t['confirmed_session_label']==label) and (alignment=='ALL' or t['label_alignment']==alignment)]
    summary.append(dict(variant=variant,session_label=label,label_alignment=alignment,**metrics(ts)))
 family_summary=[]
 for family in ('A','B','E'):
  ts=[t for t in trades if t['variant']=='MIDPOINT_ABE_FILTER' and (t.get('midpoint_at_entry') or {}).get('confirming_family')==family]
  family_summary.append(dict(confirming_family=family,**metrics(ts)))
 complete=len(daily)==36
 for name,rows in [('daily',daily),('trades',trades),('filter-checks',logs),('coverage',coverage),('summary',summary),('family-summary',family_summary)]:csvwrite(out/(name+'.csv'),rows)
 dump(out/'report.json',dict(complete_36_sessions=complete,evaluated_sessions=len(daily),requested_sessions=36,configuration=asdict(config),summary=summary,family_summary=family_summary,coverage=coverage,input_sha256=hashes,baseline_rules=engine.RULES,engine_sha256=hashlib.sha256(Path(engine.__file__).read_bytes()).hexdigest(),execution_enabled=False,warning='Offline Nifty points before costs. Labels are reporting only. Accepted A/B/E confirmations available after candle close; structure invalidation neutralizes trend. Filter checks setup and pending entry; exits unchanged. Missing sessions excluded from both variants.'))
 print('Complete 36:',complete,'Output:',out,flush=True)
 return 0 if complete else 2
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--end-date',default='2026-10-09');p.add_argument('--start-date');p.add_argument('--cache-root',action='append',type=Path);p.add_argument('--midpoint-root',action='append',type=Path);p.add_argument('--output-root',type=Path,default=Path('data/historical-evidence/hilega-midpoint-abe36-v1'));p.add_argument('--self-test',action='store_true');a=p.parse_args()
 if a.self_test:
  import unittest
  suite=unittest.defaultTestLoader.discover(str(Path(__file__).parent),pattern='test_*.py');result=unittest.TextTestRunner(verbosity=2).run(suite);sys.exit(not result.wasSuccessful())
 try:
  from dotenv import load_dotenv
  load_dotenv('.env',override=False)
 except ImportError:pass
 sys.exit(run(a))
