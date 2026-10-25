import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch
from datetime import datetime
import run as study

class Checks(unittest.TestCase):
    def snap(self,w=39,r=42,e=41):return NS(wma21_rsi=w,rsi9=r,ema3_rsi=e,ready=True)
    def test_bearish_dual_exit_below40_deferred(self):
        self.assertTrue(study.base.dual_exit('BEARISH',self.snap()))
        self.assertFalse(study.normal_exit_allowed('BEARISH',self.snap()))
    def test_equality_holds(self):
        self.assertFalse(study.normal_exit_allowed('BEARISH',self.snap(w=40)))
    def test_above40_requires_both_indicators(self):
        self.assertTrue(study.normal_exit_allowed('BEARISH',self.snap(w=40.5,r=44,e=43)))
        self.assertFalse(study.normal_exit_allowed('BEARISH',self.snap(w=40.5,r=44,e=40)))
    def test_bullish_exit_unchanged(self):
        snap=self.snap(w=35,r=30,e=31)
        self.assertEqual(study.normal_exit_allowed('BULLISH',snap),study.base.dual_exit('BULLISH',snap))
    def test_no_exit_latch(self):
        self.assertFalse(study.normal_exit_allowed('BEARISH',self.snap(w=39,r=45,e=44)))
        self.assertFalse(study.normal_exit_allowed('BEARISH',self.snap(w=41,r=40,e=44)))
    def test_private_exit_override_does_not_modify_live(self):
        original=study.base.dual_exit
        variant=study.Study(True)
        self.assertIs(study.base.dual_exit,original)
        self.assertIsNot(variant.policy,study.base)
    def scenario(self,confirmed):
        at=datetime.fromisoformat('2026-10-12T13:05:00+05:30')
        gate=study.base.make_gate({})
        gate.owner='BEARISH';gate.active=dict(time=at-study.core.timedelta(minutes=30),price=110)
        snap=self.snap(w=39,r=45,e=44)
        result=dict(current=snap,entries=[],exits=[],checks=[],policy_events=[])
        v=study.Study(True)
        v.advance=lambda *a,**kw:result
        v.monitor=(NS(bullish=NS(previous_indicators=snap)),None,None)
        event=study.legacy.StrategyEvent('ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21',at,
            None,'IDLE','ACTIVE',price=100,entry_time=at,entry_price=100,details={})
        mr=dict(entries=[event] if confirmed else [],checks=[],policy_events=[],setups=[])
        bar=NS(ts=at-study.core.timedelta(minutes=5),close=100)
        with patch.object(study.base,'advance_boundary',return_value=mr):
            output=v.boundary(None,gate,bar,snap,None)
        return gate,output
    def test_fully_confirmed_opposite_exits_then_enters(self):
        gate,result=self.scenario(True)
        self.assertEqual(gate.owner,'BULLISH')
        self.assertEqual(len(result['exits']),1);self.assertEqual(len(result['entries']),1)
        self.assertEqual(result['exits'][0].exit_reason,'FULLY_CONFIRMED_OPPOSITE_BULLISH')
        self.assertEqual(result['exits'][0].points,10)
    def test_unconfirmed_opposite_does_not_reverse(self):
        gate,result=self.scenario(False)
        self.assertEqual(gate.owner,'BEARISH');self.assertFalse(result['entries']);self.assertFalse(result['exits'])

if __name__=='__main__':unittest.main(verbosity=2)
