from datetime import datetime,timedelta
from itertools import product
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).parents[1]))
from engine import VERSION,ROUTE_NAME,PERIODS,RSI,Indicators,entry_checks,exit_checks,replay
from run import page


class NormalRouteTests(unittest.TestCase):
    def frame(self,**kw):
        return dict(dict(open=99,close=100,ema30_high=99,ema30_low=90,
            rsi5=60,rsi9=60,rsi14=60,rsi21=60,rsi28=60,wma21_rsi9=60),**kw)

    def test_name_periods_and_eight_entry_conditions(self):
        self.assertEqual(ROUTE_NAME,'Normal Route');self.assertIn(28,PERIODS)
        self.assertEqual(len(entry_checks(self.frame(),'CE')),8)
        self.assertTrue(all(entry_checks(self.frame(),'CE').values()))

    def test_existing_rsi9_wma21_parity(self):
        fixture=json.loads(Path(__file__).with_name('canonical-parity.json').read_text());engine=Indicators();out=[]
        for c in fixture['closes']:out.append(engine.update(dict(close=c,high=c+1,low=c-1)))
        for e in fixture['expected']:
            for k in ['rsi9','wma21_rsi9']:
                if e[k] is None:self.assertIsNone(out[e['index']][k])
                else:self.assertAlmostEqual(out[e['index']][k],e[k],places=12)

    def test_rsi28_seed_readiness(self):
        for direction,expected in [(1,100),(-1,0),(0,50)]:
            engine=RSI(28);values=[engine.update(100+direction*i) for i in range(29)]
            self.assertTrue(all(v is None for v in values[:-1]));self.assertEqual(values[-1],expected)

    def test_ce_red_and_doji_rejected(self):
        self.assertFalse(all(entry_checks(self.frame(open=101),'CE').values()))
        self.assertFalse(all(entry_checks(self.frame(open=100),'CE').values()))

    def test_pe_requires_red(self):
        f=self.frame(open=101,ema30_low=101,rsi5=40,rsi9=40,rsi14=40,rsi21=40,rsi28=40,wma21_rsi9=40)
        self.assertTrue(all(entry_checks(f,'PE').values()))
        self.assertFalse(all(entry_checks(dict(f,open=99),'PE').values()))

    def test_rsi28_both_thresholds_strict(self):
        self.assertFalse(all(entry_checks(self.frame(rsi28=55),'CE').values()))
        f=self.frame(open=101,ema30_low=101,rsi5=40,rsi9=40,rsi14=40,rsi21=40,rsi28=45,wma21_rsi9=40)
        self.assertFalse(all(entry_checks(f,'PE').values()))
        self.assertIsNone(entry_checks(self.frame(rsi28=None),'CE')['rsi28_threshold'])

    def test_all_exit_truth_combinations_for_both_sides(self):
        for side in ['CE','PE']:
            bull=side=='CE'
            for momentum,wma,price in product([False,True],repeat=3):
                f=self.frame(rsi5=40 if bull and momentum else 60 if bull else 60 if momentum else 40,
                    rsi9=40 if bull and momentum else 60 if bull else 60 if momentum else 40,
                    wma21_rsi9=40 if bull and wma else 60 if bull else 60 if wma else 40,
                    close=90 if bull and price else 110 if bull else 110 if price else 90,ema30_low=100,ema30_high=100)
                self.assertEqual(exit_checks(f,side)['all_three_exit'],momentum and wma and price)

    def test_exit_requires_both_fast_rsis_and_strict_wma(self):
        f=self.frame(close=80,ema30_low=90,rsi5=40,rsi9=60,wma21_rsi9=40)
        self.assertFalse(exit_checks(f,'CE')['all_three_exit'])
        self.assertFalse(exit_checks(dict(f,rsi9=40,wma21_rsi9=50),'CE')['all_three_exit'])

    def test_price_boundary_equality_does_not_exit(self):
        f=self.frame(close=90,ema30_low=90,rsi5=40,rsi9=40,wma21_rsi9=40)
        self.assertFalse(exit_checks(f,'CE')['all_three_exit'])

    def market(self):
        start=datetime.fromisoformat('2026-11-20T09:15:00+05:30');minutes=[]
        for i in range(375):
            at=start+timedelta(minutes=i);o=99 if i==0 else 101 if i==3 else 103 if i==6 else 99
            minutes.append(dict(timestamp=at.isoformat(),open=o,high=104,low=98,close=100))
        bars=[dict(start=minutes[i]['timestamp'],open=minutes[i]['open'],high=104,low=98,close=100) for i in range(0,375,3)]
        return bars,minutes

    def fake(self,frames):
        class Fake:
            def __init__(self):self.i=0
            def update(self,bar):
                f=frames[min(self.i,len(frames)-1)];self.i+=1
                return {k:v for k,v in f.items() if k not in ('open','close')}
        return Fake

    def test_next_open_exit_then_reverse_and_labels(self):
        bars,minutes=self.market()
        ce=self.frame();pe=self.frame(ema30_high=110,ema30_low=101,rsi5=40,rsi9=40,rsi14=40,rsi21=40,rsi28=40,wma21_rsi9=40)
        neutral=self.frame(rsi5=50,rsi9=50,rsi14=50,rsi21=50,rsi28=50,wma21_rsi9=50,ema30_high=110,ema30_low=90)
        r=replay('2026-11-20',bars,minutes,[],indicator_factory=self.fake([ce,pe,neutral]))
        self.assertEqual(r['route_name'],'Normal Route');self.assertEqual([t['side'] for t in r['trades']],['CE','PE'])
        self.assertEqual([e['event'] for e in r['audit'][1]['events']],['EXIT','ENTRY'])
        t=r['trades'][0];self.assertEqual(t['entry_price'],101);self.assertEqual(t['exit_price'],103)
        self.assertEqual(t['points'],2);self.assertEqual(t['peak_positive_points'],3)
        self.assertTrue(t['exit_checks']['all_three_exit']);self.assertEqual(t['route_name'],'Normal Route')

    def test_session_close_is_independent(self):
        bars,minutes=self.market();r=replay('2026-11-20',bars,minutes,[],indicator_factory=self.fake([self.frame()]))
        self.assertEqual(len(r['trades']),1);t=r['trades'][0]
        self.assertEqual(t['exit_time'][11:16],'15:30');self.assertEqual(t['exit_price'],100)
        self.assertFalse(t['exit_checks']['all_three_exit']);self.assertEqual(t['exit_reasons'],['SESSION_END_1530'])
        self.assertFalse(any(e['event']=='ENTRY' for e in r['audit'][-1]['events']))

    def test_html_handles_colour_and_rsi28_checks(self):
        bars,minutes=self.market();r=replay('2026-11-20',bars,minutes,[],indicator_factory=self.fake([self.frame()]))
        html=page([r]);self.assertIn('Normal Route',html);self.assertIn('rsi28_threshold',html)
        self.assertIn('Green: close &gt; open',html);self.assertIn('wma50_exit',html)


if __name__=='__main__':unittest.main()
