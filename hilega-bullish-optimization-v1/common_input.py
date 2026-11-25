"""Separate research: one later API dataset on 1m/3m/5m; no live-parity waiver.
First reproduce the recorded 5m strategy using actual recorded 5m OHLC frames.
This does NOT recover original 1m candles or certify live lower-timeframe alerts.
"""
import argparse
from datetime import datetime,date,time,timedelta
import hashlib
import json
from pathlib import Path
import tempfile
import study
import core


def recorded_bars(records,day):
    frames={}
    for row in records:
        if row.get('stage')!='DIRECTIONAL_DECISION':continue
        payload=row.get('payload') or {};stamp=payload.get('decision_timestamp')
        if not stamp or not stamp.startswith(day):continue
        frame=payload.get('price_ema_frame')
        if not frame:raise ValueError('RECORDED_5M_FRAME_MISSING:'+stamp)
        if stamp in frames and frames[stamp]!=frame:raise ValueError('CONFLICTING_RECORDED_5M_FRAME:'+stamp)
        frames[stamp]=frame
    bars=[];at=datetime.combine(date.fromisoformat(day),time(9,20),core.IST)
    cutoff=datetime.combine(date.fromisoformat(day),time(14,55),core.IST)
    while at<=cutoff:
        frame=frames.get(at.isoformat())
        if frame is None:raise ValueError('RECORDED_5M_BOUNDARY_MISSING:'+at.isoformat())
        label=at-timedelta(minutes=5)
        if frame.get('available_at')!=at.isoformat() or frame.get('candle_label')!=label.isoformat():
            raise ValueError('RECORDED_5M_FRAME_TIMESTAMP_MISMATCH')
        check=dict(timestamp=label.isoformat(),**{k:frame[k] for k in ('open','high','low','close')})
        core.validate_rows([check],day)
        # These are actual recorded 5m bars, never distributed into synthetic 1m bars.
        bars.append(core.FiveMinuteBar(label,frame['open'],frame['high'],frame['low'],frame['close'],0))
        at+=timedelta(minutes=5)
    return bars


def cutoff_source(raw,records,day):
    """Require an observed cutoff mark if a recorded position closed at cutoff.
    No cutoff exits in the supplied day, but don't borrow API pricing silently.
    """
    cutoff=day+'T14:55:00+05:30';prices=set()
    for row in records:
        p=row.get('payload') or {}
        for event in p.get('event_details') or []:
            if event.get('event_time')==cutoff and event.get('exit_reason') and 'CUTOFF' in event['exit_reason']:
                prices.add(float(event['price']))
    if len(prices)>1:raise ValueError('CONFLICTING_RECORDED_CUTOFF_MARK')
    if not prices:return raw,'NO_RECORDED_CUTOFF_EXIT'
    price=next(iter(prices));copy=[dict(r) for r in raw]
    row=next((r for r in copy if r['timestamp']==cutoff),None)
    if row is None:raise ValueError('CUTOFF_MINUTE_MISSING')
    # For recorded-bar reproduction ONLY; no 1m strategy consumes this copy.
    # The core reads just the open at cutoff, not its OHLC aggregate.
    row['open']=price
    return copy,'RECORDED_CUTOFF_EXIT_MARK'


def build_matches(results,raw):
    five=results['DEPLOYED_5M'];matches={}
    for interval in (1,3):
        result=results[f'RESEARCH_{interval}M']
        for stage in ('SETUP','ENTRY'):
            matches[f'{interval}m_{stage}']=study.match_alerts(study.with_lifetime(study.alerts(result,stage),result),five,raw)
    one,three=results['RESEARCH_1M'],results['RESEARCH_3M']
    together=study.agreement_lifetimes(study.agreement(one,three),one,three)
    matches['1m_3m_ACTIVE_AGREEMENT']=study.match_alerts(together,five,raw)
    return matches


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input-zip',type=Path,required=True)
    ap.add_argument('--session-input',type=Path,required=True)
    ap.add_argument('--cache-root',type=Path,action='append')
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    if args.output.exists():raise ValueError('OUTPUT_EXISTS_USE_NEW_DIRECTORY')
    args.output.mkdir(parents=True)
    try:
        installed,hashes=study.verify_sources()
        data,warm,records,actions=study.load_inputs(args.input_zip,args.session_input,list(study.CACHE_ROOTS)+(args.cache_root or []))
        day=data['session_date'];until=datetime.combine(date.fromisoformat(day),time(14,55),core.IST)
        manifest=dict(package_version=study.PACKAGE_VERSION,comparison_basis='COMMON_LATER_API',
            session_date=day,source_version=study.EXPECTED_VERSION,source_sha256=hashes,
            input_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (args.input_zip,args.session_input)},
            warmup_sessions=len(warm),warmup_last=warm[-1][0],warmup_input_actions=actions,
            research_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in study.HERE.glob('*.py')},
            interval_anchor='09:15 IST',live_minute_reconstruction=False,orders_sent=False)
        (args.output/'manifest.json').write_text(json.dumps(manifest,indent=2))
        print('1/4 Reproducing recorded 5m bars against all recorded indicators/trades...',flush=True)
        original_raw,cutoff_basis=cutoff_source(data['candles'],records,day)
        original=core.run(core.policy5,core.legacy5,warm,original_raw,day,5,until,target_bars=recorded_bars(records,day))
        proof=core.parity(original,records,until)
        (args.output/'recorded-bar-parity.json').write_text(json.dumps(proof,indent=2))
        (args.output/'recorded-bars-replay.json').write_text(json.dumps(dict(input_basis='RECORDED_5M_BARS',cutoff_basis=cutoff_basis,result=original),indent=2))
        if proof['status']!='PASS':
            raise ValueError('RECORDED_5M_BAR_STRATEGY_REPRODUCTION_FAILED; inspect recorded-bar-parity.json; comparison not run')
        print('Recorded 5m bar reproduction PASS. This is not original live 1m recovery.',flush=True)
        print('2/4 Running current 5m strategy on common later API data...',flush=True)
        five=core.run(core.policy5,core.legacy5,warm,data['candles'],day,5,until)
        drift=core.parity(five,records,until)
        (args.output/'parity.json').write_text(json.dumps(drift,indent=2))
        print('Later API versus recorded-live parity:',drift['status'],'(retained as its own result)',flush=True)
        results={'DEPLOYED_5M':five}
        with tempfile.TemporaryDirectory(prefix='hilega-common-api-timeframes-') as directory:
            for interval in (1,3):
                print(f'{3 if interval==1 else 4}/4 Running {interval}m on exactly the same later API data...',flush=True)
                try:
                    policy,legacy=study.isolated(Path(directory)/str(interval),installed,interval)
                    results[f'RESEARCH_{interval}M']=core.run(policy,legacy,warm,data['candles'],day,interval,until)
                finally:study.cleanup(interval)
        study.report(args.output,day,results,build_matches(results,data['candles']),proof,manifest,common_input_drift=drift)
    except Exception as e:
        (args.output/'failure.json').write_text(json.dumps(dict(status='BLOCKED',comparison_basis='COMMON_LATER_API',error=str(e),orders_sent=False),indent=2))
        print('BLOCKED:',str(e),flush=True);raise SystemExit(2)

if __name__=='__main__':main()
