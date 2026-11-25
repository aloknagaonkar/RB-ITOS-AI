"""Optional local regression against user-supplied archives; no provider calls."""
from pathlib import Path
import sys,json,zipfile
from datetime import date
sys.path.insert(0,str(Path(__file__).resolve().parent/'files/backend/market_lab'))
from hilega_rsi_two_route_v1.engine import Engine
from hilega_rsi_two_route_v1.data import bars
from hilega_rsi_two_route_v1.calendar import required_sessions


def compare(actual, recorded):
    assert len(actual['trades'])==len(recorded['trades'])
    for a,b in zip(actual['trades'],recorded['trades']):
        for k in ('side','route_name','entry_time','exit_time','exit_reasons'):assert a[k]==b[k],k
        for k in ('entry_price','exit_price','points','peak_positive_points','giveback_points','worst_unrealized_points'):assert abs(a[k]-b[k])<1e-7,k
    for a,b in zip(actual['audit'],recorded['audit']):
        for k in ('frame','events','owner_before','owner_after','entry_evaluation','exit_evaluation'):assert a[k]==b[k],k
    assert len(actual['audit'])==len(recorded['audit'])
    assert actual['summary']==recorded['summary']


def main():
    root=Path(sys.argv[1] if len(sys.argv)>1 else '.')
    totals={};sessions_count=0;trades_count=0
    with zipfile.ZipFile(root/'upload/rsi-confirmed-midpoint-20261124T112618518222.zip') as z:
        results=json.loads(z.read('results.json'))['results']
        rows={Path(n).stem:json.loads(z.read(n))['candles'] for n in z.namelist() if n.startswith('verified-inputs/') and n.endswith('.json')}
        for r in results:
            if r.get('model')!='UPDATED' or 'audit' not in r:continue
            day=date.fromisoformat(r['session_date'])
            warm=[b for d in required_sessions(day) for b in bars(rows[str(d)],d)]
            e=Engine(str(day),warm)
            for b in bars(rows[str(day)],day):
                e.advance(b,rows[str(day)])
                e=Engine.restore(json.loads(json.dumps(e.snapshot())))
            compare(e.result(),r)
            totals['October']=totals.get('October',0)+e.result()['summary']['net_points']
            sessions_count+=1;trades_count+=len(e.trades)
    november=json.loads((root/'work_3m_update/confirmed_midpoint_test/results.json').read_text())['results']
    for r in november:
        if 'audit' not in r:continue
        frames=[a['frame'] for a in r['audit']]
        class Supplied:
            def __init__(self):self.i=0
            def update(self,b):
                f=frames[self.i];self.i+=1
                return {k:v for k,v in f.items() if k not in ('start','open','high','low','close')}
        # These are sparse modeled mark/extrema references from completed bars,
        # explicitly not independently fetched/reseeded November minute candles.
        refs=[dict(timestamp=f['start'],open=f['open'],high=f['high'],low=f['low']) for f in frames[1:]]
        from datetime import datetime,timedelta
        refs.append(dict(timestamp=(datetime.fromisoformat(r['audit'][-1]['decision_time'])-timedelta(minutes=1)).isoformat(),close=frames[-1]['close'],high=frames[-1]['close'],low=frames[-1]['close']))
        e=Engine(r['session_date']);e.tracker=Supplied()
        # use held 3m extrema once per completed bucket, not the final-close reference
        import hilega_rsi_two_route_v1.engine as module
        saved=module.excursion
        def extrema(t,_):
            sign=1 if t['side']=='CE' else -1
            held=[f for f in frames if t['entry_time']<=f['start']<t['exit_time']]
            peak=max([0.]+[sign*(f['high' if sign==1 else 'low']-t['entry_price']) for f in held])
            adverse=min([0.]+[sign*(f['low' if sign==1 else 'high']-t['entry_price']) for f in held])
            return dict(peak_positive_points=peak,giveback_points=peak-t['points'],worst_unrealized_points=adverse)
        module.excursion=extrema
        try:
            for f in frames:e.advance({k:f[k] for k in ('start','open','high','low','close')},refs)
        finally:module.excursion=saved
        compare(e.result(),r)
        totals['November']=totals.get('November',0)+e.result()['summary']['net_points']
        sessions_count+=1;trades_count+=len(e.trades)
    report=dict(status='PASS',sessions=sessions_count,trades=trades_count,net_points=totals,
        october_basis='20 sessions independently reseeded from 40 raw input sessions; restart after every boundary',
        november_basis='16 supplied 3m indicator-frame sessions; not an independent raw-candle reseed',
        checks='all frames, routes, gates, exit flags, trades, marks, extrema, events, owner and summaries')
    print(json.dumps(report,indent=2))
if __name__=='__main__':main()
