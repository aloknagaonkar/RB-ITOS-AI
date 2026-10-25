import importlib.util
from datetime import datetime, timedelta
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('timing_runner',Path(__file__).with_name('run.py'))
runner=importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

class Checks(unittest.TestCase):
    def rows(self,count=10):
        start=datetime.fromisoformat('2026-10-21T09:15:00+05:30')
        return [dict(timestamp=(start+timedelta(minutes=i)).isoformat(),
            open=100+i,high=102+i,low=99+i,close=101+i,volume=1) for i in range(count)]
    def test_three_minute_anchor_and_ohlc(self):
        bars=runner.aggregate(self.rows(),'2026-10-21',3,datetime.fromisoformat('2026-10-21T09:21:00+05:30'))
        self.assertEqual([b.ts.strftime('%H:%M') for b in bars],['09:15','09:18'])
        self.assertEqual((bars[0].open,bars[0].high,bars[0].low,bars[0].close),(100,104,99,103))
    def test_partial_candle_not_consumed(self):
        bars=runner.aggregate(self.rows(),'2026-10-21',3,datetime.fromisoformat('2026-10-21T09:20:00+05:30'))
        self.assertEqual(len(bars),1)
    def test_missing_minute_rejected(self):
        rows=self.rows();del rows[1]
        with self.assertRaisesRegex(ValueError,'MISSING_MINUTE'):
            runner.aggregate(rows,'2026-10-21',3,datetime.fromisoformat('2026-10-21T09:18:00+05:30'))
    def test_duplicate_rejected(self):
        rows=self.rows();rows.append(rows[0])
        with self.assertRaisesRegex(ValueError,'DUPLICATE_MINUTE'):
            runner.aggregate(rows,'2026-10-21',3,datetime.fromisoformat('2026-10-21T09:18:00+05:30'))
    def test_research_namespace_isolated(self):
        p,l=runner.isolated_three()
        self.assertIsNot(p,runner.policy5)
        self.assertEqual(runner.policy5.RULES['confirmation_interval_minutes'],5)
        self.assertEqual(p.RULES['confirmation_interval_minutes'],3)
        import sys
        self.assertIsNot(sys.modules['timing3.hilega_milega_strategy_v1'],
            sys.modules['market_lab.hilega_milega_strategy_v1'])
    def test_three_minute_frame_completion(self):
        p,l=runner.isolated_three()
        bar=runner.aggregate(self.rows(),'2026-10-21',3,datetime.fromisoformat('2026-10-21T09:18:00+05:30'))[0]
        from types import SimpleNamespace
        snap=SimpleNamespace(rsi9=50,ema3_rsi=45,wma21_rsi=40)
        t=p.PriceFrames();t.seed(bar)
        frame=t.complete(bar,snap,snap)
        self.assertEqual(frame['available_at'],'2026-10-21T09:18:00+05:30')
    def test_event_deduplication(self):
        event=dict(event_type='ENTRY_BEARISH_ROUTE_B_STRUCTURAL',entry_time='2026-10-21T10:10:00+05:30',
            event_time='2026-10-21T10:10:00+05:30',entry_price=100,exit_reason=None)
        records=[dict(payload=dict(event_details=[event]))]*2
        entries,exits=runner.recorded_events(records,datetime.fromisoformat('2026-10-21T11:55:00+05:30'))
        self.assertEqual(len(entries),1);self.assertFalse(exits)

if __name__=='__main__':unittest.main(verbosity=2)
