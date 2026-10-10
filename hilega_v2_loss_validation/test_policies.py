import unittest
from datetime import datetime,timedelta
from types import SimpleNamespace
from run import policy_module,alignment,protect,attribution,metrics,patch
class Tests(unittest.TestCase):
 def gate(self,policy,gap=3,at='12:30',aligned=True):
  m=policy_module(policy);g=m.WmaGapGate();t=datetime.fromisoformat('2026-10-06T'+at+':00+05:30')-timedelta(minutes=1)
  current=SimpleNamespace(ready=True,rsi9=50,ema3_rsi=40+gap,wma21_rsi=40)
  prev=SimpleNamespace(ready=True,rsi9=49,ema3_rsi=39.9+gap-.1,wma21_rsi=39.9)
  ref=SimpleNamespace(ready=True,rsi9=48,ema3_rsi=42,wma21_rsi=39)
  ev=m.StrategyEvent('ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21',t,None,'IDLE','ARMED',details={})
  g.signal(ev,t-timedelta(minutes=2));g.pending['BULLISH']['armed_at']=t-timedelta(minutes=1)
  g.previous=dict(minute=t-timedelta(minutes=1),snapshot=prev,wma_change=.9)
  g.latest_completed=current if aligned else SimpleNamespace(ready=True,rsi9=30,ema3_rsi=35,wma21_rsi=40)
  return g.evaluate(minute=t,current=current,reference=ref,price=100)
 def test_gap_boundary_and_baseline(self):
  self.assertEqual(len(self.gate('BASELINE')[0]),1);self.assertEqual(len(self.gate('BULL_GAP_GE5')[0]),0);self.assertEqual(len(self.gate('BULL_GAP_GE5',gap=5)[0]),1)
 def test_time_boundaries(self):
  self.assertEqual(len(self.gate('BULL_NO_13_TO14',at='12:59')[0]),1);self.assertEqual(len(self.gate('BULL_NO_13_TO14',at='13:00')[0]),0);self.assertEqual(len(self.gate('BULL_NO_13_TO14',at='14:00')[0]),1)
 def test_alignment_cancellation(self):
  self.assertEqual(len(self.gate('RECHECK_ALIGNMENT',aligned=False)[0]),0);self.assertEqual(self.gate('RECHECK_ALIGNMENT',aligned=False)[1][0]['status'],'CANCELED');self.assertEqual(len(self.gate('RECHECK_ALIGNMENT',aligned=True)[0]),1)
 def test_signs_and_equality(self):
  s=SimpleNamespace(ready=True,rsi9=30,ema3_rsi=35,wma21_rsi=40)
  self.assertTrue(alignment('BEARISH',s));self.assertFalse(alignment('BULLISH',s));s.ema3_rsi=40;self.assertFalse(alignment('BEARISH',s))
 def test_protection(self):
  self.assertFalse(protect(19,5));self.assertFalse(protect(20,11));self.assertTrue(protect(20,10));self.assertTrue(protect(40,19));self.assertFalse(protect(20,30))
 def test_attribution_new_lifecycle(self):
  b=[dict(trade_id='b',direction='BULLISH',entry_time='a',entry_price=100,exit_time='b',points=-10)]
  f=[dict(trade_id='f',direction='BULLISH',entry_time='a',entry_price=100,exit_time='c',points=5),dict(trade_id='new',direction='BEARISH',entry_time='d',entry_price=100,exit_time='e',points=-2)]
  self.assertEqual(sum(r['net_delta'] for r in attribution(b,f)),13)
 def test_source_guard(self):
  with self.assertRaises(ValueError):patch('a','missing','x')
 def test_all_modules_load(self):
  for p in ('BASELINE','BULL_GAP_GE5','BULL_NO_13_TO14','RECHECK_ALIGNMENT','CLOSE_PROFIT_PROTECTION'):self.assertTrue(callable(policy_module(p).replay))
