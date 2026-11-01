import json,unittest,tempfile,ast
from pathlib import Path
from datetime import datetime,timedelta
from types import SimpleNamespace
from market_lab.hilega_v2_alignment_replay_v1 import (replay,candles,dual_exit,WmaGapGate,StrategyEvent,merge_sessions,load_session,MODEL)
class Tests(unittest.TestCase):
 def rows(self,day,count=341):
  start=datetime.fromisoformat(day+'T09:15:00+05:30')
  return [dict(timestamp=(start+timedelta(minutes=i)).isoformat(),open=100,high=100,low=100,close=100,volume=1) for i in range(count)]
 def test_flat_session_is_available_not_missing(self):
  x=replay('2026-10-06',self.rows('2026-10-06'),[('2026-10-05',self.rows('2026-10-05',375))])
  self.assertEqual(x['trades'],[]);self.assertEqual(len(x['audit']),340)
  self.assertEqual(x['performance_summary'][0]['net_points'],0)
 def test_missing_minute_and_duplicate_rejected(self):
  rr=self.rows('2026-10-06');rr.pop(8)
  with self.assertRaisesRegex(ValueError,'INCOMPLETE'):replay('2026-10-06',rr,[('2026-10-05',self.rows('2026-10-05',375))])
  rr=self.rows('2026-10-06');rr.append(rr[0])
  with self.assertRaisesRegex(ValueError,'DUPLICATE'):candles(rr)
 def test_future_warmup_rejected(self):
  with self.assertRaisesRegex(ValueError,'FUTURE'):replay('2026-10-06',self.rows('2026-10-06'),[('2026-10-07',[])])
 def test_dual_exit_requires_both_and_equality_waits(self):
  snap=lambda r,e,w:SimpleNamespace(ready=True,rsi9=r,ema3_rsi=e,wma21_rsi=w)
  self.assertFalse(dual_exit('BULLISH',snap(40,60,50)))
  self.assertFalse(dual_exit('BULLISH',snap(40,50,50)))
  self.assertTrue(dual_exit('BULLISH',snap(40,45,50)))
  self.assertTrue(dual_exit('BEARISH',snap(60,55,50)))
  self.assertFalse(dual_exit('BEARISH',snap(60,45,50)))
 def test_exit_before_same_boundary_replacement(self):
  at=datetime.fromisoformat('2026-10-06T10:00:00+05:30');minute=at-timedelta(minutes=1)
  event=lambda name:StrategyEvent(name,at,None,'IDLE','ACTIVE')
  g=WmaGapGate();g.owner='BULLISH';g.active={'time':at-timedelta(minutes=20),'price':100}
  g.signal(event('ENTRY_BEARISH_ROUTE_B_STRUCTURAL'),at)
  g.previous={'minute':minute-timedelta(minutes=1),'snapshot':SimpleNamespace(ready=True,rsi9=39,ema3_rsi=41,wma21_rsi=45),'wma_change':-1}
  current=SimpleNamespace(ready=True,rsi9=35,ema3_rsi=39,wma21_rsi=44)
  reference=SimpleNamespace(ready=True,wma21_rsi=45)
  entries,checks=g.evaluate(minute=minute,current=current,reference=reference,price=95,exit_boundary=True)
  self.assertEqual(entries,[]);self.assertIn('ACTIVE_TRADE_OWNER',checks[0]['reasons'])
  g.previous={'minute':minute-timedelta(minutes=1),'snapshot':SimpleNamespace(ready=True,rsi9=39,ema3_rsi=41,wma21_rsi=45),'wma_change':-1}
  closed=g.close(event('STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21'),at,95)
  self.assertEqual(closed.points,-5)
  entries,_=g.evaluate(minute=minute,current=current,reference=reference,price=95,exit_boundary=True)
  self.assertEqual(len(entries),1);self.assertEqual(g.owner,'BEARISH')
 def test_registry_merge_and_invalid_saved_artifact(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);p=root/'2026-10-06.json';p.write_text(json.dumps({'model':MODEL,'session_date':'2026-10-06','execution_enabled':False}))
   self.assertEqual(load_session('2026-10-06',root)['model'],MODEL)
   rows=merge_sessions([{'session_date':'2026-10-06','available_sources':['LIVE_SHADOW']}],root)
   self.assertEqual(len(rows),1);self.assertIn('LIVE_SHADOW',rows[0]['available_sources'])
   p.write_text('{}')
   with self.assertRaises(ValueError):load_session('2026-10-06',root)
 def test_historical_endpoint_routes_new_strategy_before_legacy(self):
  import market_lab.hilega_v2_alignment_replay_v1 as module
  from datetime import date
  source=Path(module.__file__).with_name('hilega_historical_ui_api_v1.py').read_text()
  node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='strategy_test')
  node.decorator_list=[]
  tree=ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[]))
  class HTTPError(Exception):pass
  scope={'__package__':'market_lab','date':date,'Query':lambda value,**kw:value,'HTTPException':HTTPError}
  exec(compile(tree,'historical-route','exec'),scope)
  old=module.OUTPUT_ROOT
  try:
   with tempfile.TemporaryDirectory() as td:
    module.OUTPUT_ROOT=Path(td)
    (Path(td)/'2026-10-06.json').write_text(json.dumps({'model':MODEL,'session_date':'2026-10-06','execution_enabled':False}))
    self.assertEqual(scope['strategy_test']('2026-10-06','V2_ALIGN')['model'],MODEL)
  finally:module.OUTPUT_ROOT=old
if __name__=='__main__':unittest.main()
