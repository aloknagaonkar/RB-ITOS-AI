"""36-session diagnostic labels are attached AFTER causal strategy replay."""
import argparse,csv,hashlib,json,sys
from pathlib import Path
import common as c

def cohort():
 x=json.loads((Path(__file__).parent/'cohort.json').read_text())
 if set(x)!={'BULLISH','BEARISH'} or any(len(v)!=18 or len(set(v))!=18 for v in x.values()) or set(x['BULLISH'])&set(x['BEARISH']):raise ValueError('INVALID_FROZEN_COHORT')
 return {d:side for side,days in x.items() for d in days}

def label(trade,expected):return 'ALIGNED' if trade['direction']==expected else 'COUNTER_TREND'

def detail(t):
 q=t.get('entry_checks') or {};ex=t.get('exit_checks') or {};previous=q.get('previous') or {};current=q.get('current') or {};slopes=q.get('slopes') or {}
 return dict(session_date=t['session_date'],policy=t['policy'],trade_id=t['trade_id'],session_label=t['session_label'],alignment_to_label=t['alignment_to_label'],direction=t['direction'],setup_source=t.get('setup_source'),entry_time=t['entry_time'],entry_price=t['entry_price'],exit_time=t['exit_time'],exit_price=t['exit_price'],points=t['points'],mfe_points=t.get('mfe_points'),exit_reason=t['exit_reason'],
 previous_rsi9=previous.get('rsi9',q.get('previous_rsi9')),previous_ema3=previous.get('ema3',q.get('previous_ema3')),previous_wma21=previous.get('wma21',q.get('previous_wma21')),
 current_rsi9=current.get('rsi9',q.get('current_rsi9')),current_ema3=current.get('ema3',q.get('current_ema3')),current_wma21=current.get('wma21',q.get('current_wma21')),
 rsi9_slope=slopes.get('rsi9'),ema3_slope=slopes.get('ema3'),wma21_slope=slopes.get('wma21'),current_gap=q.get('current_gap'),previous_gap=q.get('previous_gap'),gap_delta=q.get('gap_delta'),strength=q.get('strength',q.get('directional_wma_strength')),entry_ema10=q.get('ema10_price'),entry_all_slopes=q.get('entry_all_slopes'),exit_ema10=ex.get('ema10_price'),exit_slopes=ex.get('slopes'),completed_5m_at_entry=t.get('completed_5m_at_entry'),completed_5m_changes_at_entry=t.get('completed_5m_changes_at_entry'),diagnostic_note='BASELINE slope fields are unavailable here; its entry values are provisional minute values' if t['policy']=='BASELINE' else 'Completed five-minute indicator comparison')

def run(args):
 labels=cohort();out=args.output_root
 if out.exists():raise ValueError('Output exists; choose fresh --output-root')
 out.mkdir(parents=True);index=c.base.cache_index(args.cache_root);warm=[];coverage=[];trades=[];daily=[];attrs=[];hashes={};modules={p:c.policy_module(p) for p in c.POLICIES}
 for day,path in sorted(index.items()):
  if day>max(labels):continue
  data=json.loads(path.read_text());rr=data.get('candles') or [];hashes[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
  if data.get('session_date') not in (None,day) or data.get('underlying') not in (None,'NSE_INDEX|Nifty 50'):raise ValueError('INVALID_NIFTY_CACHE:'+str(path))
  if day not in labels:
   if rr:warm.append((day,rr))
   continue
  if not rr:coverage.append(dict(session_date=day,session_label=labels[day],status='EMPTY_CACHE'));continue
  try:
   # No retrospective session direction passed to engine or filter.
   results={p:m.replay(day,rr,warm,{'source':'FROZEN36_CAUSAL_REPLAY','policy':p}) for p,m in modules.items()}
   for policy,x in results.items():
    c.dump(out/'sessions'/day/(policy+'.json'),x)
    if policy=='BASELINE':
     for t in x['trades']:
      completed=[a for a in x['audit'] if a.get('five_minute_label') and a['checkpoint']<=t['entry_time']]
      t['completed_5m_at_entry']=completed[-1].get('completed_5m_indicators') if completed else None
      t['completed_5m_changes_at_entry']=completed[-1].get('five_minute_changes') if completed else None
    labeled=[dict(**t,session_date=day,policy=policy,session_label=labels[day],alignment_to_label=label(t,labels[day])) for t in x['trades']]
    trades.extend(labeled)
    for relation in ('ALL','ALIGNED','COUNTER_TREND'):
     ts=[t for t in labeled if relation=='ALL' or t['alignment_to_label']==relation]
     daily.append(dict(session_date=day,session_label=labels[day],policy=policy,relation=relation,**c.metrics(ts)))
    if policy!='BASELINE':attrs.extend(dict(session_date=day,session_label=labels[day],policy=policy,**a) for a in c.attribution(results['BASELINE']['trades'],x['trades']))
   coverage.append(dict(session_date=day,session_label=labels[day],status='EVALUATED'))
   print(json.dumps(dict(date=day,label=labels[day],net={p:c.metrics(x['trades'])['net'] for p,x in results.items()})),flush=True)
  except (ValueError,KeyError,FileNotFoundError) as exc:
   coverage.append(dict(session_date=day,session_label=labels[day],status='FAILED_ALL_VARIANTS',issue=str(exc)));print(day,str(exc),flush=True)
  warm.append((day,rr))
 for day in sorted(set(labels)-set(index)):coverage.append(dict(session_date=day,session_label=labels[day],status='CACHE_MISSING'))
 summary=[]
 for policy in c.POLICIES:
  for session_direction in ('ALL','BULLISH','BEARISH'):
   for relation in ('ALL','ALIGNED','COUNTER_TREND'):
    ts=[t for t in trades if t['policy']==policy and (session_direction=='ALL' or t['session_label']==session_direction) and (relation=='ALL' or t['alignment_to_label']==relation)]
    summary.append(dict(policy=policy,session_direction=session_direction,relation=relation,requested_sessions=36 if session_direction=='ALL' else 18,evaluated_sessions=sum(v['status']=='EVALUATED' and (session_direction=='ALL' or v['session_label']==session_direction) for v in coverage),**c.metrics(ts)))
 for name,rows in [('summary',summary),('daily',daily),('trades',trades),('losses',[t for t in trades if t['points']<0]),('entry_details',[detail(t) for t in trades]),('attribution',attrs),('coverage',coverage)]:c.write(out/(name+'.csv'),rows)
 complete=all(v['status']=='EVALUATED' for v in coverage) and len(coverage)==36
 c.dump(out/'report.json',dict(model='HILEGA_V2_CONFIRMED36_REPLAY_V1',complete_36=complete,cohort=labels,summary=summary,coverage=coverage,input_sha256=hashes,code_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),Path(c.__file__),Path(c.engine.__file__),Path(c.warmup.__file__),Path(c.base.__file__)]},execution_enabled=False,warning='Retrospective labels used for reporting only. Reconstructed Nifty points before costs. Frozen selected trend days are not independent OOS, not a causal live trend filter. Missing dates excluded consistently across all variants. No live/chart parity claim.'))
 for row in summary:
  if row['session_direction']=='ALL':print(json.dumps(row),flush=True)
 print('Complete36:',complete,'Output:',out,'; no live/Sandbox/broker changes',flush=True)
 return complete

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--self-test',action='store_true');p.add_argument('--cache-root',action='append',type=Path);p.add_argument('--output-root',type=Path,default=Path('data/historical-evidence/hilega-v2-confirmed36-validation-v1'));a=p.parse_args()
 if a.self_test:
  import unittest
  result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover(str(Path(__file__).parent),pattern='test_*.py'));sys.exit(not result.wasSuccessful())
 sys.exit(0 if run(a) else 2)
