#!/usr/bin/env python3
"""Re-evaluate supplied completed-bar indicator frames. Does not recalculate seed indicators."""
import argparse,hashlib,json,zipfile
from datetime import datetime,timedelta
from pathlib import Path
import engine,baseline,strength_reference
from monthly_report import page,totals,daily_rows
from run import export_csv


def replay_frames(module,source):
    """Use only known next-bar opens; extrema use held completed bars, no invented 1m OHLC."""
    audits=source['audit'];frames=[a['frame'] for a in audits]
    bars=[{k:f[k] for k in ('start','open','high','low','close')} for f in frames]
    # Engine only looks up each signal boundary's next open or exact final close.
    # These are sparse fill references, explicitly not raw or synthetic minute candles.
    references=[dict(timestamp=f['start'],open=f['open']) for f in frames[1:]]
    final=datetime.fromisoformat(audits[-1]['decision_time'])-timedelta(minutes=1)
    references.append(dict(timestamp=final.isoformat(),close=frames[-1]['close']))
    class SuppliedIndicators:
        def __init__(self):self.i=0
        def update(self,bar):
            f=frames[self.i];self.i+=1
            return {k:v for k,v in f.items() if k not in ('start','open','high','low','close')}
    def extrema(trade,unused):
        first=datetime.fromisoformat(trade['entry_time']);last=datetime.fromisoformat(trade['exit_time']);sign=1 if trade['side']=='CE' else -1
        held=[f for f in frames if first<=datetime.fromisoformat(f['start'])<last]
        peak=max([0.]+[sign*(f['high' if sign==1 else 'low']-trade['entry_price']) for f in held])
        adverse=min([0.]+[sign*(f['low' if sign==1 else 'high']-trade['entry_price']) for f in held])
        return dict(peak_positive_points=peak,giveback_points=peak-trade['points'],worst_unrealized_points=adverse)
    old=module.excursion;module.excursion=extrema
    try:r=module.replay(source['session_date'],bars,references,[],indicator_factory=SuppliedIndicators)
    finally:module.excursion=old
    for k in ('session_kind','session_open','session_close','market_trend'):r[k]=source[k]
    r['validation_basis']='SUPPLIED_COMPLETED_3M_FRAMES; NO_INDEPENDENT_INDICATOR_RESEED'
    return r


def assert_parity(actual,source):
    assert len(actual['trades'])==len(source['trades']),'TRADE_COUNT_MISMATCH'
    for a,b in zip(actual['trades'],source['trades']):
        for k in ('side','route_name','entry_time','exit_time','exit_reasons'):assert a[k]==b[k],k
        for k in ('entry_price','exit_price','points','peak_positive_points','giveback_points','worst_unrealized_points'):assert abs(a[k]-b[k])<1e-7,k
    assert [a['events'] for a in actual['audit']]==[a['events'] for a in source['audit']],'EVENT_PARITY_FAILED'
    for a,b in zip(actual['audit'],source['audit']):assert (a['owner_before'],a['owner_after'])==(b['owner_before'],b['owner_after'])


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--archive',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    with zipfile.ZipFile(args.archive) as z:data=json.loads(z.read('results.json'))
    assert data['status']=='REPLAY_COMPLETE';assert data['strategy_version']==strength_reference.VERSION
    code_sha=hashlib.sha256(Path(strength_reference.__file__).read_bytes()).hexdigest()
    assert data['generator_sha256']['engine.py']==code_sha,'REFERENCE_ENGINE_HASH_MISMATCH'
    results=[];daily=[];parity=0
    for source in data['results']:
        if source['model']!='UPDATED':continue
        if 'audit' not in source:
            results.append(dict(session_date=source['session_date'],status=source['status']));continue
        # Reproduce both recorded strategies before evaluating the change.
        assert_parity(replay_frames(strength_reference,source),source)
        original=next(r for r in data['results'] if r['session_date']==source['session_date'] and r['model']=='BASELINE')
        assert source['input_evidence']['target_sha256']==original['input_evidence']['target_sha256']
        assert [a['frame'] for a in source['audit']]==[a['frame'] for a in original['audit']]
        assert_parity(replay_frames(baseline,original),original);parity+=2
        r=replay_frames(engine,source);r['model']='UPDATED_NO_STRENGTH';results.append(r)
        daily.append(dict(session_date=r['session_date'],baseline_net=original['summary']['net_points'],with_strength_net=source['summary']['net_points'],without_strength_net=r['summary']['net_points'],trades=r['summary']['trades'],peak_positive_points=r['summary']['peak_positive_points'],giveback_points=r['summary']['giveback_points']))
    report=dict(status='AUDIT_FRAME_REEVALUATION_PASS',strategy_version=engine.VERSION,validation_basis='EXISTING_3M_INDICATOR_FRAMES_AND_ALIGNED_NEXT_OPEN_FILLS',source_zip_sha256=hashlib.sha256(args.archive.read_bytes()).hexdigest(),source_strategies_reproduced=parity,summary=totals([t for r in results for t in r.get('trades',[])]),results=results,daily_comparison=daily,limitations=['Raw source minutes/warmup absent: indicator calculations are reused, not independently reseeded.','Full 3m holding intervals allow exact excursion aggregation from supplied bar highs/lows; no intra-bar exits are modeled.','NIFTY points before costs, no option fills.'],live_application_modified=False)
    args.output.mkdir(parents=True,exist_ok=False)
    (args.output/'results.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    banner='<aside style="border:2px solid #48e4a6;padding:14px"><b>Colour-only research re-evaluation.</b> Body and wick entry limits removed. Reused uploaded 3m indicator frames; both recorded baseline and strength-filter strategies were reproduced first. No fresh provider fetch or independent indicator reseeding. Trades and peaks use supplied completed bars and aligned next opens. Live application unchanged.</aside>'
    (args.output/'No-strength-November-audit.html').write_text(page(results).replace('<body>','<body>'+banner,1))
    export_csv(args.output/'daily-comparison.csv',daily)
    export_csv(args.output/'trades.csv',[dict(session_date=r['session_date'],**{k:v for k,v in t.items() if not isinstance(v,(dict,list))}) for r in results for t in r.get('trades',[])])
    print('SUMMARY',json.dumps(report['summary']));print('SOURCE STRATEGY PARITY',parity);print('DAILY',json.dumps(daily));print('HTML',args.output/'No-strength-November-audit.html')

if __name__=='__main__':main()
