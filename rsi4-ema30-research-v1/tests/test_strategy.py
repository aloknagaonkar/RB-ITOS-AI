from datetime import datetime,timedelta
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).parents[1]))
from engine import RSI,Indicators,entry_checks,exit_checks,replay


class StrategyTests(unittest.TestCase):
    def frame(self,**kw):
        return dict(dict(close=100,ema30_high=99,ema30_low=101,rsi5=60,rsi9=60,rsi14=60,rsi21=60,wma21_rsi9=60),**kw)

    def test_existing_rsi9_wma21_numeric_parity(self):
        fixture=json.loads(Path(__file__).with_name('canonical-parity.json').read_text());tracker=Indicators();got=[]
        for close in fixture['closes']:got.append(tracker.update(dict(close=close,high=close+1,low=close-1)))
        for expected in fixture['expected']:
            for key in ('rsi9','wma21_rsi9'):
                if expected[key] is None:self.assertIsNone(got[expected['index']][key])
                else:self.assertAlmostEqual(expected[key],got[expected['index']][key],places=12)

    def test_wilder_seed_flat_and_directional(self):
        for period in (5,9,14,21):
            for sign,expected in ((0,50),(1,100),(-1,0)):
                engine=RSI(period);values=[engine.update(100+sign*i) for i in range(period+1)]
                self.assertTrue(all(v is None for v in values[:-1]));self.assertEqual(values[-1],expected)

    def test_every_entry_condition_is_mandatory(self):
        self.assertTrue(all(entry_checks(self.frame(),'CE').values()))
        for key in ['rsi5','rsi9','rsi14','rsi21']:
            f=self.frame(**{key:55});self.assertFalse(all(entry_checks(f,'CE').values()))
        self.assertFalse(all(entry_checks(self.frame(wma21_rsi9=50),'CE').values()))

    def test_pe_uses_low_not_high(self):
        checks=entry_checks(self.frame(close=100,ema30_low=99,ema30_high=110,rsi5=40,rsi9=40,rsi14=40,rsi21=40,wma21_rsi9=40),'PE')
        self.assertFalse(checks['close_vs_ema30_low']);self.assertFalse(all(checks.values()))

    def test_balanced_exit_requires_both_fast_rsis(self):
        f=self.frame(rsi5=49,rsi9=51,ema30_low=90)
        self.assertFalse(exit_checks(f,'CE')['momentum_exit'])
        self.assertTrue(exit_checks(dict(f,rsi9=49),'CE')['momentum_exit'])
        self.assertFalse(exit_checks(dict(f,rsi9=50),'CE')['momentum_exit'])

    def test_price_exit_independent_of_momentum(self):
        self.assertTrue(exit_checks(self.frame(ema30_low=101),'CE')['opposite_ema_boundary_exit'])
        self.assertTrue(exit_checks(self.frame(ema30_high=99,rsi5=40,rsi9=40),'PE')['opposite_ema_boundary_exit'])

    def market(self):
        start=datetime.fromisoformat('2026-11-20T09:15:00+05:30');minutes=[]
        for i in range(375):
            at=start+timedelta(minutes=i);o=101 if i==3 else 103 if i==6 else 100
            minutes.append(dict(timestamp=at.isoformat(),open=o,high=104,low=98,close=100))
        bars=[dict(start=minutes[i]['timestamp'],open=minutes[i]['open'],high=104,low=98,close=100) for i in range(0,375,3)]
        return bars,minutes

    def fake(self,frames):
        class Fake:
            def __init__(self):self.i=0
            def update(self,bar):
                f=frames[min(self.i,len(frames)-1)];self.i+=1
                return {k:v for k,v in f.items() if k!='close'}
        return Fake

    def test_signal_close_not_used_as_fill_or_future_close(self):
        bars,minutes=self.market()
        f1=self.frame(ema30_low=90);f2=self.frame(rsi5=40,rsi9=40,ema30_high=110,ema30_low=90)
        neutral=self.frame(rsi5=50,rsi9=50,rsi14=50,rsi21=50,wma21_rsi9=50,ema30_high=110,ema30_low=90)
        result=replay('2026-11-20',bars,minutes,[],indicator_factory=self.fake([f1,f2,neutral]))
        t=result['trades'][0];self.assertEqual(t['entry_price'],101);self.assertEqual(t['exit_price'],103)
        self.assertEqual(t['points'],2);self.assertEqual(t['entry_time'][11:16],'09:18')
        self.assertEqual(t['peak_positive_points'],3);self.assertEqual(t['giveback_points'],1)

    def test_session_close_has_no_new_entry(self):
        bars,minutes=self.market();r=replay('2026-11-20',bars,minutes,[],indicator_factory=self.fake([self.frame(ema30_low=90)]))
        self.assertEqual(len(r['trades']),1);t=r['trades'][0]
        self.assertEqual(t['exit_time'][11:16],'15:30');self.assertEqual(t['exit_price'],100)
        self.assertEqual(t['exit_reasons'],['SESSION_END_1530'])
        self.assertFalse(any(e['event']=='ENTRY' for e in r['audit'][-1]['events']))

    def test_exit_then_reverse_at_same_boundary(self):
        bars,minutes=self.market();ce=self.frame(ema30_low=90)
        pe=self.frame(rsi5=40,rsi9=40,rsi14=40,rsi21=40,wma21_rsi9=40,ema30_low=101,ema30_high=110)
        neutral=self.frame(rsi5=50,rsi9=50,rsi14=50,rsi21=50,wma21_rsi9=50,ema30_high=110,ema30_low=90)
        r=replay('2026-11-20',bars,minutes,[],indicator_factory=self.fake([ce,pe,neutral]))
        self.assertEqual([e['event'] for e in r['audit'][1]['events']],['EXIT','ENTRY'])
        self.assertEqual([t['side'] for t in r['trades']],['CE','PE'])

    def test_incomplete_session_rejected(self):
        bars,minutes=self.market()
        with self.assertRaisesRegex(ValueError,'COMPLETE_REGULAR'):replay('2026-11-20',bars[:-1],minutes,[])


if __name__=='__main__':unittest.main()
