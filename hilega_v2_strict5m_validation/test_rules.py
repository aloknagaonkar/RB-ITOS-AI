import unittest
from types import SimpleNamespace as S
from engine import check
class Rules(unittest.TestCase):
 def snap(self,r,e,w):return S(ready=True,rsi9=r,ema3_rsi=e,wma21_rsi=w)
 def test_bull_exit(self):
  q=check('BULLISH',self.snap(50,51,52),self.snap(40,42,50));self.assertTrue(q['dual_exit'] and q['exit_all_slopes'])
 def test_bear_exit(self):
  q=check('BEARISH',self.snap(50,49,48),self.snap(60,58,50));self.assertTrue(q['dual_exit'] and q['exit_all_slopes'])
 def test_mixed_wait(self):
  q=check('BULLISH',self.snap(50,51,48),self.snap(40,42,50));self.assertTrue(q['dual_exit']);self.assertFalse(q['exit_all_slopes'])
 def test_equality_wait(self):
  q=check('BULLISH',self.snap(50,51,50),self.snap(40,42,50));self.assertFalse(q['exit_all_slopes'])
 def test_entry_signs(self):
  for side,p,n in [('BULLISH',(50,45,40),(55,48,41)),('BEARISH',(40,45,50),(35,42,49))]:
   q=check(side,self.snap(*p),self.snap(*n));self.assertTrue(q['alignment'] and q['gap_expanding'] and q['entry_wma_slope']);self.assertEqual(q['strength'],1)
 def test_missing(self):self.assertFalse(check('BULLISH',None,self.snap(50,45,40))['available'])
