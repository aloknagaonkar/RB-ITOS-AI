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
 def cache(self,root,day,count=375):
  p=root/(day+'.json');p.write_text(json.dumps({'session_date':day,'underlying':'NSE_INDEX|Nifty 50','candles':self.rows(day,count)}));return p
 def test_auto_evaluate_cache_and_invalidate(self):
  import market_lab.hilega_v2_alignment_replay_v1 as m
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);cache=root/'cache';cache.mkdir();out=root/'out'
   self.cache(cache,'2026-10-05');p=self.cache(cache,'2026-10-06')
   with patch.object(m,'replay',wraps=m.replay) as run:
    first=m.load_session('2026-10-06',out,[cache]);second=m.load_session('2026-10-06',out,[cache])
    self.assertEqual(run.call_count,1);self.assertEqual(first,second);self.assertEqual(first['report_count'],340)
    x=json.loads(p.read_text());x['candles'][0]['volume']=2;p.write_text(json.dumps(x))
    m.load_session('2026-10-06',out,[cache]);self.assertEqual(run.call_count,2)
   self.assertEqual(len(list((out/'previous-research-versions').glob('*.json'))),1)
 def test_missing_date_and_warmup_are_explicit(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td)
   with self.assertRaisesRegex(FileNotFoundError,'candle cache missing'):load_session('2026-10-06',root/'out',[root])
   self.cache(root,'2026-10-06')
   with self.assertRaisesRegex(ValueError,'warmup'):load_session('2026-10-06',root/'out',[root])
 def test_future_data_excluded_and_recovery_precedence(self):
  import market_lab.hilega_v2_alignment_replay_v1 as m
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);a=root/'a';b=root/'b';a.mkdir();b.mkdir()
   self.cache(a,'2026-10-05');self.cache(a,'2026-10-06');p=self.cache(b,'2026-10-06');self.cache(a,'2026-10-07')
   self.assertEqual(m.cache_index([a,b])['2026-10-06'],p)
   x=load_session('2026-10-06',root/'out',[a,b]);self.assertEqual(x['manifest']['warmup_last'],'2026-10-05')
   self.assertFalse(any('2026-10-07' in k for k in x['manifest']['source_sha256']))
   rows=merge_sessions([{'session_date':'2026-10-06','available_sources':['LIVE_SHADOW']}],root/'out',[a,b])
   self.assertTrue(rows[0]['alignment_candle_cache_available']);self.assertIn('LIVE_SHADOW',rows[0]['available_sources'])
 def test_endpoint_returns_specific_missing_candle_error(self):
  import market_lab.hilega_v2_alignment_replay_v1 as m
  from datetime import date
  from unittest.mock import patch
  source=Path(m.__file__).with_name('hilega_historical_ui_api_v1.py').read_text()
  node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='strategy_test');node.decorator_list=[]
  class HTTPError(Exception):
   def __init__(self,status,detail):self.status=status;self.detail=detail
  scope={'__package__':'market_lab','date':date,'Query':lambda value,**kw:value,'HTTPException':HTTPError}
  exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'route','exec'),scope)
  with patch.object(m,'CACHE_ROOTS',[]):
   with self.assertRaises(HTTPError) as got:scope['strategy_test']('2026-10-06','V2_ALIGN')
   self.assertEqual(got.exception.status,404);self.assertIn('candle cache missing',got.exception.detail)
if __name__=='__main__':unittest.main()
