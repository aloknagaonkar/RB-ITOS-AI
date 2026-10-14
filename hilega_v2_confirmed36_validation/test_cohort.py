import unittest
import run
class Cohort(unittest.TestCase):
 def test_exact_cohort(self):
  c=run.cohort();self.assertEqual(len(c),36);self.assertEqual(sum(s=='BULLISH' for s in c.values()),18)
 def test_labels_only(self):
  t={'direction':'BEARISH','entry_price':100};before=dict(t)
  self.assertEqual(run.label(t,'BEARISH'),'ALIGNED');self.assertEqual(run.label(t,'BULLISH'),'COUNTER_TREND');self.assertEqual(t,before)
