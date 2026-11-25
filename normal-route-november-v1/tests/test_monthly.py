import json,unittest,sys,subprocess,shutil
from datetime import date,datetime,timedelta
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]))
from monthly_report import requested_days,totals,daily_rows,page
from engine import replay
import test_normal_route as base

class MonthlyTests(unittest.TestCase):
    def test_month_scope_and_future_rejected(self):
        days=requested_days(None,'2026-11','2026-11-23',date(2026,11,23))
        self.assertEqual(len(days),23);self.assertEqual(days[0],'2026-11-01');self.assertEqual(days[-1],'2026-11-23')
        with self.assertRaises(ValueError):requested_days(None,'2026-11','2026-12-01',date(2026,12,1))
        with self.assertRaises(ValueError):requested_days(['2026-11-24'],'2026-11','2026-11-23',date(2026,11,23))

    def test_short_session_uses_real_grid_and_closes(self):
        start=datetime.fromisoformat('2026-11-08T14:20:00+05:30')
        minutes=[dict(timestamp=(start+timedelta(minutes=i)).isoformat(),open=99,high=104,low=98,close=100) for i in range(70)]
        bars=[dict(start=minutes[i]['timestamp'],open=99,high=104,low=98,close=100) for i in range(1,70,3)]
        helper=base.NormalRouteTests();r=replay('2026-11-08',bars,minutes,[],indicator_factory=helper.fake([helper.frame()]))
        self.assertEqual(len(r['audit']),23);self.assertEqual(r['trades'][0]['entry_time'][11:16],'14:24')
        self.assertEqual(r['trades'][0]['exit_time'][11:16],'15:30')
        with self.assertRaises(ValueError):replay('2026-11-08',bars[1:],minutes,[])

    def test_totals_distinguish_failure_from_zero_trade(self):
        ts=[dict(side='CE',points=10,peak_positive_points=15,giveback_points=5),dict(side='PE',points=-5,peak_positive_points=3,giveback_points=8)]
        self.assertEqual(totals(ts)['net_points'],5);self.assertEqual(totals(ts)['giveback_points'],13)
        rows=daily_rows([dict(session_date='2026-11-02',trades=[]),dict(session_date='2026-11-03',status='REPLAY_FAILED',error='missing')])
        self.assertEqual(rows[0]['status'],'REPLAYED');self.assertEqual(rows[1]['status'],'REPLAY_FAILED')

    @unittest.skipUnless(shutil.which('node'),'Node unavailable')
    def test_html_filter_totals_execute(self):
        ts=[dict(side='CE',points=10,peak_positive_points=15,giveback_points=5),dict(side='PE',points=-5,peak_positive_points=3,giveback_points=8)]
        # Only feed structured report data to the script; synthetic test records have no audit.
        rs=[dict(session_date='2026-11-02',status='REPLAY_FAILED'),dict(session_date='2026-11-03',status='NON_TRADING_DAY')]
        h=page(rs);script=h.rsplit('<script>',1)[1].split('</script>',1)[0]
        payload=[dict(session_date='2026-11-02',status='REPLAYED',market_trend='BULLISH',trades=ts),dict(session_date='2026-11-03',status='REPLAYED',market_trend='BEARISH',trades=[ts[1]])]
        stub='''const els={};for(const id of ['date','side','trend','totals','coverage','daily','expand','collapse','reset'])els[id]={value:'ALL',textContent:'',addEventListener(){},replaceChildren(){},append(){}};
els.data={textContent:PAYLOAD};global.document={getElementById:id=>els[id],querySelectorAll:()=>[],createElement:()=>({append(){}})};
'''.replace('PAYLOAD',json.dumps(json.dumps(payload)))
        check='''
function check(s){if(!els.totals.textContent.includes(s))throw Error(els.totals.textContent)}
check('Net: 0.00');side.value='CE';apply();check('Net: 10.00');
side.value='PE';apply();check('Net: -10.00');date.value='2026-11-02';apply();check('Net: -5.00');
date.value='ALL';trend.value='BEARISH';apply();check('Net: -5.00');
date.value='2026-11-02';apply();check('Selected trades: 0');els.reset.onclick();check('Net: 0.00');
'''
        subprocess.run(['node','-e',stub+script+check],check=True,capture_output=True,text=True)

    def test_status_escaped_and_filter_controls(self):
        h=page([dict(session_date='2026-11-02',status='REPLAY_FAILED',error='<script>alert(1)</script>')])
        self.assertIn('&lt;script&gt;',h);self.assertIn('id="date"',h);self.assertIn('id="side"',h);self.assertIn('id="trend"',h)
        self.assertIn('Failed dates are not zero-trade validation passes',h)

if __name__=='__main__':unittest.main()
