import copy, unittest, tempfile, json,csv
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from run import panel,category,run
AT=datetime.fromisoformat('2026-10-09T10:00:00+05:30')
def fixture():
 strikes=[]
 for n in range(11):
  strike=22000+n*50
  sides={s:dict(status='AVAILABLE',side=s.upper(),strike=strike,instrument_key='KEY'+s+str(strike),baseline_oi=100,current_oi=110,baseline_ltp=20,current_ltp=21,baseline_received_at='2026-10-09T09:54:00+05:30') for s in ('ce','pe')}
  strikes.append(dict(strike=strike,**sides))
 return dict(status='AVAILABLE',available_at='2026-10-09T09:59:00+05:30',expiry='2026-10-13',panels=[dict(mode=m,atm=22250,pcr=1.1,combined_bias='BULLISH',expected=22,received=22,strikes=copy.deepcopy(strikes)) for m in ('fixed','moving')])
class Tests(unittest.TestCase):
 def test_available_and_category(self):
  f=panel(fixture(),'fixed',AT,120);m=panel(fixture(),'moving',AT,120);self.assertEqual(f['status'],'AVAILABLE');self.assertEqual(category('BULLISH',f,m),'BOTH_SUPPORT');self.assertEqual(category('BEARISH',f,m),'BOTH_OPPOSE')
 def test_missing(self):self.assertEqual(panel({},'fixed',AT,120)['status'],'UNAVAILABLE')
 def test_future_and_stale(self):
  for t in ('2026-10-09T10:01:00+05:30','2026-10-09T09:50:00+05:30'):
   c=fixture();c['available_at']=t;self.assertEqual(panel(c,'fixed',AT,120)['status'],'UNAVAILABLE')
 def test_expired(self):
  c=fixture();c['expiry']='2026-10-06';self.assertEqual(panel(c,'fixed',AT,120)['reason'],'EXPIRED_CONTRACT')
 def test_missing_strike(self):
  c=fixture();c['panels'][0]['strikes'].pop();self.assertEqual(panel(c,'fixed',AT,120)['status'],'UNAVAILABLE')
 def test_missing_baseline_and_price(self):
  for k in ('baseline_oi','baseline_ltp','baseline_received_at'):
   c=fixture();del c['panels'][0]['strikes'][0]['ce'][k];self.assertEqual(panel(c,'fixed',AT,120)['status'],'UNAVAILABLE')
 def test_conflict_and_partial(self):
  f=dict(status='AVAILABLE',combined_bias='BULLISH');m=dict(status='AVAILABLE',combined_bias='BEARISH');self.assertEqual(category('BULLISH',f,m),'CONFLICTING_DIRECTIONS');m['status']='UNAVAILABLE';self.assertEqual(category('BULLISH',f,m),'UNAVAILABLE')
 def test_runner_read_only_join(self):
  with tempfile.TemporaryDirectory() as d:
   d=Path(d);p=d/'trades.csv';p.write_text('trade_id,session_date,direction,signal_time,entry_time,points\nt,2026-10-09,BULLISH,2026-10-09T10:00:00+05:30,2026-10-09T10:01:00+05:30,10\n');original=p.read_bytes()
   a=SimpleNamespace(base_url='http://127.0.0.1:8123',trades=p,start_date='2026-10-06',end_date='2026-10-09',output_root=d/'out',horizon=300,max_age=120)
   with patch('run.query',return_value=fixture()) as q,patch('run.time.sleep'):run(a)
   self.assertEqual(q.call_count,2);self.assertEqual(p.read_bytes(),original)
   rows=list(csv.DictReader((a.output_root/'trade-support.csv').open()));self.assertEqual(len(rows),2);self.assertEqual(rows[1]['support_category'],'BOTH_SUPPORT')
