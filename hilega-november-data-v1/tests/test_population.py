from datetime import date,datetime
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

spec=importlib.util.spec_from_file_location('population',Path(__file__).parents[1]/'populate.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class PopulationTests(unittest.TestCase):
    def test_calendar_not_weekday_only(self):
        special=date(2026,11,8);holiday=date(2026,11,10)
        calendar=lambda d:d==special or (d.weekday()<5 and d!=holiday)
        days=m.days_between(date(2026,11,1),date(2026,11,23),calendar)
        self.assertIn(special,days);self.assertNotIn(holiday,days)
        self.assertEqual(len(days),16)

    def test_missing_cache(self):
        self.assertEqual(m.assess({},date(2026,11,2),None)['status'],'MISSING')

    def test_invalid_cache_is_not_valid(self):
        def bad(*args):raise ValueError('wrong coverage')
        out=m.assess({'2026-11-02':Path('x')},date(2026,11,2),SimpleNamespace(read_session=bad))
        self.assertEqual(out['status'],'INVALID')

    def test_valid_cache_preserves_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'2026-11-02.json';p.write_text('unchanged')
            out=m.assess({'2026-11-02':p},date(2026,11,2),SimpleNamespace(read_session=lambda *a:[{}]*375))
            self.assertEqual(out['minutes'],375);self.assertEqual(p.read_text(),'unchanged')

    def test_replay_wrong_version_rejected(self):
        with self.assertRaisesRegex(ValueError,'IDENTITY'):m.validate_result(dict(session_date='2026-11-02',strategy_version='old'),date(2026,11,2),m.VERSION)

    def test_unclosed_trade_rejected(self):
        r=dict(session_date='2026-11-02',strategy_version=m.VERSION,execution_enabled=False,observation_only=True,trades=[{}])
        with self.assertRaisesRegex(ValueError,'UNCLOSED'):m.validate_result(r,date(2026,11,2),m.VERSION)

    def test_valid_result(self):
        r=dict(session_date='2026-11-02',strategy_version=m.VERSION,execution_enabled=False,observation_only=True,
            trades=[dict(exit_time='2026-11-02T15:30:00+05:30')],performance_summary=[dict(net_points=10)])
        self.assertEqual(m.validate_result(r,date(2026,11,2),m.VERSION)['net_points'],10)

    def test_artifact_version_is_not_full_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            e=SimpleNamespace(OUTPUT_ROOT=Path(temp));p=Path(temp)/'2026-11-02.json'
            p.write_text(json.dumps(dict(strategy_version=m.VERSION)))
            self.assertEqual(m.saved_status(e,date(2026,11,2)),'SAVED_VERSION_MATCH_NOT_YET_REVALIDATED')

    def test_today_uses_validated_intraday_fallback(self):
        def missing(*args):raise ValueError('historical not ready')
        item=SimpleNamespace(timestamp=datetime(2026,11,23,9,15,tzinfo=m.IST),open=1,high=2,low=1,close=2)
        source=SimpleNamespace(nifty_intraday_1m=lambda **k:[item])
        warm=SimpleNamespace(fetch_session=missing,validate_rows=lambda rows,day:rows)
        out=m.fetch_complete(source,date(2026,11,23),warm,datetime(2026,11,23,16,tzinfo=m.IST))
        self.assertEqual(out[0]['timestamp'],'2026-11-23T09:15:00+05:30')

    def test_historical_failure_does_not_substitute_today_for_prior_day(self):
        def missing(*args):raise ValueError('missing')
        warm=SimpleNamespace(fetch_session=missing)
        with self.assertRaises(ValueError):m.fetch_complete(None,date(2026,11,20),warm,datetime(2026,11,23,16,tzinfo=m.IST))


if __name__=='__main__':unittest.main()
