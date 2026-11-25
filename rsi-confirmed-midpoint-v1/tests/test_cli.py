"""Integration of exports and explicit partial failure using isolated synthetic sources."""
import unittest,tempfile,json,subprocess,sys
from pathlib import Path

class CliTests(unittest.TestCase):
    def test_cli_comparison_and_missing_date_fail_explicitly(self):
        with tempfile.TemporaryDirectory() as td:
            repo=Path(td);pkg=repo/'backend/market_lab/hilega_three_minute_v1';pkg.mkdir(parents=True)
            for p in [pkg/'__init__.py',pkg.parent/'__init__.py']:p.write_text('')
            (repo/'target.json').write_text('{}')
            (pkg/'warmup.py').write_text('''from datetime import date,datetime,timedelta
from zoneinfo import ZoneInfo
from types import SimpleNamespace
IST=ZoneInfo('Asia/Kolkata');SPECIAL=date(2026,11,8)
def session_day(day):return True
def read_session(path,day):
 start=datetime.combine(day,datetime.min.time(),tzinfo=IST).replace(hour=9,minute=15)
 return [dict(timestamp=(start+timedelta(minutes=i)).isoformat(),open=100+i,high=101+i,low=99+i,close=100.8+i) for i in range(375)]
def load_warmup(index,day,source=None):
 return [(str(day-timedelta(days=i)),read_session(None,day-timedelta(days=i))) for i in range(20,0,-1)],{'synthetic_test':True}
def warmup_bars(raw,day):
 return [SimpleNamespace(ts=datetime.fromisoformat(raw[i]['timestamp']),open=raw[i]['open'],high=max(r['high'] for r in raw[i:i+3]),low=min(r['low'] for r in raw[i:i+3]),close=raw[i+2]['close']) for i in range(0,375,3)]
''')
            (pkg/'hilega_combined_replay_v1.py').write_text("from pathlib import Path\ndef cache_index():return {'2026-11-20':Path('target.json')}\n")
            script=Path(__file__).parents[1]/'run.py'
            proc=subprocess.run([sys.executable,'-B',str(script.resolve()),'--repo',str(repo),'--days','2026-11-20','2026-11-23'],capture_output=True,text=True)
            self.assertEqual(proc.returncode,2,proc.stdout+proc.stderr)
            outputs=list((repo/'data/research').glob('rsi-confirmed-midpoint-*/results.json'));self.assertEqual(len(outputs),1)
            data=json.loads(outputs[0].read_text());self.assertEqual(data['status'],'PARTIAL_FAILURE')
            for m in ('BASELINE','UPDATED'):
                self.assertEqual(data['coverage'][m]['replayed'],1);self.assertEqual(data['coverage'][m]['failed'],1)
                successful=next(r for r in data['results'] if r['model']==m and 'summary' in r)
                self.assertEqual(len(successful['audit']),125)
            for f in ['audit.html','baseline-audit.html','comparison.html','daily-summary.csv','candle-audit.csv']:self.assertTrue((outputs[0].parent/f).is_file())
            self.assertTrue(outputs[0].parent.with_suffix('.zip').exists())

if __name__=='__main__':unittest.main()
