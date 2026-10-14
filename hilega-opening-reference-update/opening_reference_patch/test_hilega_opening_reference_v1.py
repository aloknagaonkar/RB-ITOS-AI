import unittest
from datetime import datetime,date
from types import SimpleNamespace
from market_lab.domain import IST
from market_lab.hilega_milega_strategy_v1 import IndicatorSnapshot
from market_lab.hilega_opening_reference_v1 import capture_opening_reference,confirmation_reference
class Tests(unittest.TestCase):
 def canonical(self,stamp=None,snapshot=None):
  return SimpleNamespace(bullish=SimpleNamespace(previous_indicators=snapshot or IndicatorSnapshot(40,42,45),previous_bar=SimpleNamespace(ts=stamp or datetime(2026,10,7,15,25,tzinfo=IST))))
 def test_ready_prior_session_is_copied(self):
  c=self.canonical();r=capture_opening_reference(c,date(2026,10,8))
  self.assertEqual(r.snapshot.wma21_rsi,45);self.assertIsNot(r.snapshot,c.bullish.previous_indicators)
 def test_missing_reference_is_not_invented(self):
  c=self.canonical();c.bullish.previous_indicators=None
  self.assertIsNone(capture_opening_reference(c,date(2026,10,8)))
 def test_unready_reference_rejected(self):
  self.assertIsNone(capture_opening_reference(self.canonical(snapshot=IndicatorSnapshot(None,None,None)),date(2026,10,8)))
 def test_target_or_future_reference_rejected(self):
  for day in [8,9]:self.assertIsNone(capture_opening_reference(self.canonical(stamp=datetime(2026,10,day,9,15,tzinfo=IST)),date(2026,10,8)))
 def test_nonfinite_reference_rejected(self):
  self.assertIsNone(capture_opening_reference(self.canonical(snapshot=IndicatorSnapshot(40,42,float('nan'))),date(2026,10,8)))
 def test_first_candle_only_and_matching_day(self):
  r=capture_opening_reference(self.canonical(),date(2026,10,8))
  for minute in [15,16,17,18,19]:self.assertIs(confirmation_reference(None,r,datetime(2026,10,8,9,minute,tzinfo=IST)),r.snapshot)
  for stamp in [datetime(2026,10,8,9,14,tzinfo=IST),datetime(2026,10,8,9,20,tzinfo=IST),datetime(2026,10,9,9,15,tzinfo=IST)]:self.assertIsNone(confirmation_reference(None,r,stamp))
 def test_current_session_reference_takes_precedence(self):
  r=capture_opening_reference(self.canonical(),date(2026,10,8));current=IndicatorSnapshot(50,51,52)
  self.assertIs(confirmation_reference(current,r,datetime(2026,10,8,9,19,tzinfo=IST)),current)
 def test_capture_does_not_change_crossover_state(self):
  c=self.canonical();prev=c.bullish.previous_indicators;bar=c.bullish.previous_bar
  capture_opening_reference(c,date(2026,10,8))
  self.assertIs(c.bullish.previous_indicators,prev);self.assertIs(c.bullish.previous_bar,bar)
if __name__=='__main__':unittest.main()
