import unittest
from datetime import datetime,timedelta
from run import Trend
class Tests(unittest.TestCase):
 def make(self,closes,events):
  rows=[dict(timestamp=f'2026-10-06T09:{15+i:02d}:00+05:30',underlying_close=v) for i,v in enumerate(closes)]
  return Trend(rows,events)
 def event(self,minute=15,side='BULLISH',result='SHADOW_ENTRY'):
  return dict(event_timestamp=f'2026-10-06T09:{minute:02d}:00+05:30',direction=side,result=result,midpoint=100)
 def at(self,t,minute):return t.at(datetime.fromisoformat(f'2026-10-06T09:{minute:02d}:00+05:30'))
 def test_no_lookahead(self):
  t=self.make([101,102],[self.event()]);self.assertEqual(self.at(t,15)['direction'],'NEUTRAL');self.assertEqual(self.at(t,16)['direction'],'BULLISH')
 def test_invalidation_not_automatic_reentry(self):
  t=self.make([101,99,103],[self.event()]);self.assertEqual(self.at(t,17)['direction'],'NEUTRAL');self.assertEqual(self.at(t,18)['direction'],'NEUTRAL')
 def test_blocked_event_not_confirmation(self):
  t=self.make([101],[self.event(result='BLOCKED')]);self.assertEqual(self.at(t,16)['direction'],'NEUTRAL')
 def test_opposite_confirmation(self):
  t=self.make([101,99],[self.event(),self.event(16,'BEARISH')]);self.assertEqual(self.at(t,17)['direction'],'BEARISH')
 def test_conflicting_confirmation(self):
  t=self.make([101],[self.event(),self.event(side='BEARISH')]);self.assertEqual(self.at(t,16)['direction'],'NEUTRAL')
 def test_stale_and_daily_reset(self):
  t=self.make([101],[self.event()]);self.assertEqual(self.at(t,17)['reason'],'MISSING_OR_STALE_MIDPOINT');self.assertEqual(t.at(datetime.fromisoformat('2026-10-07T09:16:00+05:30'))['direction'],'NEUTRAL')
 def test_equality_retains(self):
  t=self.make([101,100],[self.event()]);self.assertEqual(self.at(t,17)['direction'],'BULLISH')
class GateTests(unittest.TestCase):
 def test_setup_and_entry_recheck_cancel(self):
  from run import make_gate,engine
  from types import SimpleNamespace
  trend=Tests().make([101,99],[Tests().event()]);logs=[];gate=make_gate(engine,trend,logs)()
  event=SimpleNamespace(event_type='ENTRY_BULLISH',event_time=datetime.fromisoformat('2026-10-06T09:15:00+05:30'))
  gate.signal(event,datetime.fromisoformat('2026-10-06T09:16:00+05:30'));self.assertIn('BULLISH',gate.pending)
  snap=SimpleNamespace(ready=True,wma21_rsi=40,ema3_rsi=45,rsi9=50)
  gate.evaluate(minute=datetime.fromisoformat('2026-10-06T09:16:00+05:30'),current=snap,reference=snap,price=100)
  self.assertEqual(gate.pending,{});self.assertFalse(logs[-1]['allowed'])
 def test_filter_does_not_force_active_exit(self):
  from run import make_gate,engine
  from types import SimpleNamespace
  trend=Tests().make([99],[]);gate=make_gate(engine,trend,[])();gate.owner='BULLISH';gate.active={'time':'old','price':100}
  snap=SimpleNamespace(ready=True,wma21_rsi=40,ema3_rsi=45,rsi9=50)
  gate.evaluate(minute=datetime.fromisoformat('2026-10-06T09:15:00+05:30'),current=snap,reference=snap,price=99)
  self.assertEqual(gate.owner,'BULLISH')
