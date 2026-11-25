import sys,unittest,importlib.util
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]))
import test_strategy as helper
import engine as e
class ConfirmedTests(unittest.TestCase):
 def replay(self,side,f):
  h=helper.StrategyTests();bars,minutes,cls=h.market([h.frame(side),f]);return e.replay('2026-11-20',bars,minutes,[],indicator_factory=cls)
 def followup(self,side,**kw):
  h=helper.StrategyTests();ce=side=='CE'
  return h.frame(open=104,close=103 if ce else 105,ema30_high=110,ema30_low=90,rsi5=40 if ce else 60,rsi9=40 if ce else 60,rsi14=50,rsi21=50,rsi28=50,wma21_rsi9=60 if ce else 40,**kw)
 def test_both_directions_exit_with_midpoint_and_two_rsis(self):
  for side in ['CE','PE']:
   r=self.replay(side,self.followup(side));t=r['trades'][0]
   self.assertEqual(t['exit_time'][11:16],'09:21');self.assertEqual(t['exit_reasons'],['SIGNAL_MIDPOINT_AND_RSI5_RSI9']);self.assertFalse(t['exit_checks']['all_three_exit'])
 def test_each_rsi_is_mandatory_and_equality_fails(self):
  for side in ['CE','PE']:
   for key in ['rsi5','rsi9']:
    f=self.followup(side);f[key]=50
    r=self.replay(side,f);self.assertFalse(r['audit'][1]['exit_evaluation']['signal_midpoint_rsi_confirmed_exit']);self.assertEqual(r['audit'][1]['events'],[])
 def test_midpoint_equality_fails(self):
  for side in ['CE','PE']:
   f=self.followup(side);f['close']=104
   r=self.replay(side,f);self.assertEqual(r['audit'][1]['events'],[])
 def test_no_latched_rsi_votes(self):
  h=helper.StrategyTests();a=self.followup('CE');a['rsi9']=50;b=self.followup('CE');b['rsi5']=50
  bars,minutes,cls=h.market([h.frame(),a,b]);r=e.replay('2026-11-20',bars,minutes,[],indicator_factory=cls)
  self.assertEqual(r['audit'][1]['events'],[]);self.assertEqual(r['audit'][2]['events'],[])
 def test_wick_only_with_momentum_does_not_exit(self):
  f=self.followup('CE');f.update(open=106,close=106,low=95)
  r=self.replay('CE',f);self.assertEqual(r['audit'][1]['events'],[])
 def test_same_candle_same_side_reentry_is_blocked(self):
  h=helper.StrategyTests();f=self.followup('CE');f.update(open=100,close=103,ema30_high=101,rsi14=60,rsi21=60,rsi28=60)
  r=self.replay('CE',f);self.assertEqual([ev['event'] for ev in r['audit'][1]['events']],['EXIT'])
  self.assertIn('MIDPOINT_EXIT_SAME_CANDLE_REENTRY_BLOCKED',r['audit'][1]['entry_evaluation']['CE']['blockers'])
if __name__=='__main__':unittest.main()
