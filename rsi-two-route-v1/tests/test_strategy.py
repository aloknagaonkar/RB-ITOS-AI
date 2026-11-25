import sys,unittest,json,subprocess,shutil,importlib.util
from pathlib import Path
from datetime import datetime,timedelta,date
from itertools import combinations,product
sys.path.insert(0,str(Path(__file__).parents[1]))
import engine as e
import baseline as b
from monthly_report import page,totals,requested_days

class StrategyTests(unittest.TestCase):
    def frame(self,side='CE',**kw):
        bull=side=='CE'
        f=dict(open=100 if bull else 108,close=108 if bull else 100,high=109,low=99,ema30_high=105,ema30_low=103,wma21_rsi9=60 if bull else 40)
        f.update({'rsi'+str(p):60 if bull else 40 for p in e.PERIODS});f.update(kw);return f
    def market(self,frames,day='2026-11-20'):
        special=day=='2026-11-08';start=datetime.fromisoformat(day+('T14:21:00+05:30' if special else 'T09:15:00+05:30'));n=23 if special else 125
        bars=[];minutes=[];neutral=self.frame(rsi5=50,rsi9=50,rsi14=50,rsi21=50,rsi28=50,wma21_rsi9=50)
        fs=[frames[i] if i<len(frames) else neutral for i in range(n)]
        for i,f in enumerate(fs):
            at=start+timedelta(minutes=3*i);bars.append(dict(start=at.isoformat(),**{k:f[k] for k in ('open','high','low','close')}))
            for j in range(3):minutes.append(dict(timestamp=(at+timedelta(minutes=j)).isoformat(),**{k:f[k] for k in ('open','high','low','close')}))
        class Fake:
            def __init__(self):self.i=0
            def update(self,bar):f=fs[self.i];self.i+=1;return {k:v for k,v in f.items() if k not in ('open','high','low','close')}
        return bars,minutes,Fake
    def replay(self,fs,day='2026-11-20'):
        bars,minutes,cls=self.market(fs,day);return e.replay(day,bars,minutes,[],indicator_factory=cls)
    def test_normal_any_two_both_sides(self):
        for side in ('CE','PE'):
            for pair in combinations(e.PERIODS,2):
                f=self.frame(side,**{'rsi'+str(p):60 if side=='CE' else 40 for p in pair})
                for p in set(e.PERIODS)-set(pair):f['rsi'+str(p)]=50
                r=e.evaluate_entry(f,side);self.assertEqual(r['selected_route'],'Normal Route');self.assertEqual(r['rsi_pass_count'],2)
    def test_one_rsi_fails_normal(self):
        for side in ('CE','PE'):
            f=self.frame(side,**{'rsi'+str(p):50 for p in e.PERIODS[1:]});self.assertIsNone(e.evaluate_entry(f,side)['selected_route'])
    def test_bypass_requires_all_five(self):
        for side in ('CE','PE'):
            f=self.frame(side,wma21_rsi9=40 if side=='CE' else 60);r=e.evaluate_entry(f,side)
            self.assertEqual(r['selected_route'],'WMA_bypass');self.assertEqual(r['blockers'],[])
            f['rsi28']=50;self.assertIsNone(e.evaluate_entry(f,side)['selected_route'])
    def test_normal_priority_and_wma_equality_bypass(self):
        self.assertEqual(e.evaluate_entry(self.frame(),'CE')['selected_route'],'Normal Route')
        self.assertEqual(e.evaluate_entry(self.frame(wma21_rsi9=50),'CE')['selected_route'],'WMA_bypass')
    def test_missing_values_never_waived(self):
        for k in ['wma21_rsi9','rsi28']:
            self.assertIsNone(e.evaluate_entry(self.frame(**{k:None}),'CE')['selected_route'])
    def test_strict_rsi_and_price(self):
        for side in ('CE','PE'):
            f=self.frame(side,**{'rsi'+str(p):55 if side=='CE' else 45 for p in e.PERIODS});self.assertIsNone(e.evaluate_entry(f,side)['selected_route'])
            f=self.frame(side);f['ema30_high' if side=='CE' else 'ema30_low']=f['close'];self.assertIsNone(e.evaluate_entry(f,side)['selected_route'])
    def test_strength_boundaries_both_sides(self):
        for side in ('CE','PE'):
            f=self.frame(side,high=110,low=100,open=101.5 if side=='CE' else 108.5,close=108.5 if side=='CE' else 101.5)
            f['ema30_low']=102
            self.assertIsNotNone(e.evaluate_entry(f,side)['selected_route'])
            for change in [dict(high=110.1),dict(low=99.9),dict(open=f['close']),dict(high=100,low=100,open=100,close=100)]:
                self.assertIsNone(e.evaluate_entry(dict(f,**change),side)['selected_route'])
    def test_colour_both_routes(self):
        for side in ('CE','PE'):
            f=self.frame(side);f['open'],f['close']=f['close'],f['open'];self.assertIsNone(e.evaluate_entry(f,side)['selected_route'])
    def test_reversal_without_all_three_both_sides(self):
        for first,second in [('CE','PE'),('PE','CE')]:
            f=self.frame(second,wma21_rsi9=60 if second=='PE' else 40)
            r=self.replay([self.frame(first),f]);t=r['trades'][0]
            self.assertEqual(t['exit_reasons'],['QUALIFIED_OPPOSITE_ENTRY']);self.assertFalse(t['exit_checks']['all_three_exit'])
            self.assertEqual([x['event'] for x in r['audit'][1]['events']],['EXIT','ENTRY'])
            self.assertEqual(r['trades'][1]['route_name'],'WMA_bypass');self.assertEqual(t['exit_price'],r['trades'][1]['entry_price'])
            self.assertEqual(t['exit_time'],r['trades'][1]['entry_time'])
    def test_same_direction_no_duplicate(self):
        r=self.replay([self.frame()]*3);self.assertEqual(len(r['trades']),1)
        self.assertEqual(r['audit'][1]['entry_evaluation']['CE']['status'],'QUALIFIED_ALREADY_ACTIVE')
    def test_weak_opposite_does_not_reverse(self):
        f=self.frame('PE',wma21_rsi9=60,high=120);r=self.replay([self.frame(),f]);self.assertEqual(len(r['trades']),1);self.assertEqual(r['trades'][0]['exit_reasons'],['SESSION_END_1530'])
    def test_original_exit_groups_unchanged(self):
        for side in ('CE','PE'):
            for momentum,wma,price in product((False,True),repeat=3):
                ce=side=='CE';f=self.frame(side,rsi5=(40 if ce else 60) if momentum else 50,rsi9=(40 if ce else 60) if momentum else 50,wma21_rsi9=(40 if ce else 60) if wma else 50,close=(90 if ce else 120) if price else 104)
                self.assertEqual(e.exit_checks(f,side),b.exit_checks(f,side))
                self.assertEqual(e.exit_checks(f,side)['all_three_exit'],momentum and wma and price)
    def test_session_end_overrides_reversal(self):
        fs=[self.frame()]*124+[self.frame('PE',wma21_rsi9=60)];r=self.replay(fs)
        self.assertEqual(len(r['trades']),1);self.assertEqual(r['trades'][0]['exit_reasons'],['SESSION_END_1530']);self.assertEqual(r['trades'][0]['exit_price'],100)
        self.assertFalse(any(x['event']=='ENTRY' for x in r['audit'][-1]['events']))
    def test_short_session(self):
        r=self.replay([self.frame()],'2026-11-08');self.assertEqual(len(r['audit']),23);self.assertEqual(r['trades'][0]['entry_time'][11:16],'14:24');self.assertEqual(r['trades'][0]['exit_time'][11:16],'15:30')
    def test_indicator_and_baseline_parity(self):
        i=e.Indicators();j=b.Indicators()
        for k in range(100):
            bar=dict(close=100+k%13,high=115,low=95);self.assertEqual(i.update(bar),j.update(bar))
    def test_html_route_votes_strength_and_escape(self):
        r=self.replay([self.frame(),self.frame('PE',wma21_rsi9=60)]);h=page([r])
        for x in ['id="route"','WMA_bypass','RSI votes: 5/5','candle_body_strength','opposite_entry_exit','data-route="WMA_bypass"']:self.assertIn(x,h)
        self.assertIn('Original baseline',page([r],updated=False))
    @unittest.skipUnless(shutil.which('node'),'Node unavailable')
    def test_javascript_filters_execute(self):
        r=self.replay([self.frame(),self.frame('PE',wma21_rsi9=60)]);h=page([r]);script=h.rsplit('<script>',1)[1].split('</script>',1)[0];payload=h.split('<script id="data" type="application/json">',1)[1].split('</script>',1)[0]
        stub='''const els={};for(const id of ['date','side','trend','route','totals','coverage','daily','expand','collapse','reset'])els[id]={value:'ALL',textContent:'',addEventListener(){},replaceChildren(){},append(){}};els.data={textContent:PAYLOAD};global.document={getElementById:id=>els[id],querySelectorAll:()=>[],createElement:()=>({append(){}})};'''.replace('PAYLOAD',json.dumps(payload))
        checks="if(!els.totals.textContent.includes('Selected trades: 2'))throw Error('total');route.value='WMA_bypass';apply();if(!els.totals.textContent.includes('Selected trades: 1'))throw Error('route');side.value='CE';apply();if(!els.totals.textContent.includes('Selected trades: 0'))throw Error('side');els.reset.onclick();if(!els.totals.textContent.includes('Selected trades: 2'))throw Error('reset');"
        subprocess.run(['node','-e',stub+script+checks],capture_output=True,check=True,text=True)

if __name__=='__main__':unittest.main()
