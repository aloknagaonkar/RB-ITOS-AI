"""VM-only strict-cross versus added bearish continuation, 26 October."""
import argparse,json,hashlib,traceback
from pathlib import Path
from datetime import date,datetime,time,timedelta
import core,study,common_input,hybrid,strict_hybrid,reporting

def signature(p):
    return [[t['direction'],t['entry_time'],t['entry_price'],t['exit_time'],t['exit_price'],t['exit_reason'],t.get('route','EXISTING')] for t in p['trades']]

def enrich(p,raw,day,until):
    minutes={b.ts+timedelta(minutes=1):float(b.close) for b in core.aggregate(raw,day,1,until)}
    for t in p['trades']:
        side=1 if t['direction']=='BULLISH' else -1;peak=0;peak_at=None
        start=datetime.fromisoformat(t['entry_time']);end=datetime.fromisoformat(t['exit_time'])
        path=[(at,px) for at,px in minutes.items() if start<at<=end]
        if len(path)!=int((end-start).total_seconds()/60):raise ValueError('MISSING_PEAK_PATH_MINUTES')
        for at,px in path:
            points=side*(px-t['entry_price'])
            if points>peak:peak=points;peak_at=at.isoformat()
        t.update(peak_profit=peak,peak_time=peak_at,giveback=peak-t['points'])

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input-zip',type=Path,required=True);ap.add_argument('--session-input',type=Path,required=True)
    ap.add_argument('--cache-root',type=Path,action='append',default=[]);ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args();here=Path(__file__).parent
    if a.output.exists():raise ValueError('OUTPUT_EXISTS_USE_NEW_DIRECTORY')
    a.output.mkdir(parents=True)
    try:
        installed,hashes=study.verify_sources()
        data,warm,records,actions=study.load_inputs(a.input_zip,a.session_input,list(study.CACHE_ROOTS)+a.cache_root)
        day=data['session_date']
        if day!='2026-10-26':raise ValueError('REQUIRES_2026_10_26')
        until=datetime.combine(date.fromisoformat(day),time(14,55),core.IST)
        expected=json.loads((here/'expected-controls.json').read_text())
        actual={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [a.input_zip,a.session_input]}
        if sorted(actual.values())!=sorted(expected['input_sha256'].values()):raise ValueError('INPUT_DIFFERS_FROM_UPLOADED_OCT26_CONTROL')
        manifest=dict(session_date=day,comparison_basis='COMMON_LATER_API',extension='BEARISH_ONLY_BODY_CROSS_OR_ALREADY_BELOW',continuation_definition='red body entirely below completed-signal EMA10, body/range > 0.60, EMA10 falling',bullish='STRICT_BODY_CROSS_UNCHANGED',signal_intervals=[1,3,5],existing_policy_interval=5,confirmation_interval=1,midpoint_exit_interval=1,midpoint_equality='HOLD',warmup_sessions=len(warm),warmup_last=warm[-1][0],warmup_actions=actions,source_sha256=hashes,input_sha256=actual,package_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in here.iterdir() if p.suffix in ['.py','.json']},orders_sent=False,live_changes=False)
        (a.output/'manifest.json').write_text(json.dumps(manifest,indent=2))
        print('Recorded 5m bar reproduction...',flush=True)
        rr,basis=common_input.cutoff_source(data['candles'],records,day)
        recorded=core.run(core.policy5,core.legacy5,warm,rr,day,5,until,target_bars=common_input.recorded_bars(records,day))
        proof=core.parity(recorded,records,until)
        (a.output/'recorded-bar-parity.json').write_text(json.dumps(proof,indent=2))
        if proof['status']!='PASS':raise ValueError('RECORDED_BAR_REPRODUCTION_FAILED')
        print('Existing 5m common API control...',flush=True)
        baseline=core.run(core.policy5,core.legacy5,warm,data['candles'],day,5,until)
        drift=core.parity(baseline,records,until)
        (a.output/'api-live-parity.json').write_text(json.dumps(drift,indent=2))
        print('API/live parity',drift['status'],'retained separately',flush=True)
        checks={'EXISTING_5M_CONTROL':'PASS' if signature(baseline)==expected['signatures']['EXISTING_5M_CONTROL'] else 'FAIL'}
        c=core.legacy5.ExitFirstCanonical();tracker=core.policy5.PriceFrames();count=0
        for d,rows in warm:
            if d>=day:continue
            for b in core.aggregate(rows,d,5,datetime.combine(date.fromisoformat(d),time(15,30),core.IST)):c.on_bar(b);tracker.seed(b)
            count+=1
        prepared=(c,tracker,count);results={'EXISTING_5M_CONTROL':baseline}
        for variant,module in [('STRICT',strict_hybrid),('EXTENDED',hybrid)]:
            for interval in [1,3,5]:
                for protected in [False,True]:
                    basekey=f'SIGNAL_{interval}M_MIDPOINT_'+('ON' if protected else 'OFF');key=variant+'_'+basekey
                    print('Running',key,flush=True)
                    results[key]=module.replay(warm,data['candles'],day,prepared=prepared,signal_interval=interval,protected=protected)
                    if variant=='STRICT':checks[basekey]='PASS' if signature(results[key])==expected['signatures'][basekey] else 'FAIL'
        (a.output/'strict-regression.json').write_text(json.dumps(checks,indent=2))
        if any(v!='PASS' for v in checks.values()):raise ValueError('UPLOADED_STRICT_CONTROL_REGRESSION_FAILED')
        for p in results.values():enrich(p,data['candles'],day,until)
        summary={k:reporting.stats(v) for k,v in results.items()}
        delta=['# Bearish continuation extension: full-state differences','', '| Signal TF | Protection | Strict gross | Extended gross | Difference |','|---|---|---:|---:|---:|']
        for tf in [1,3,5]:
            for flag in ['OFF','ON']:
                k=f'SIGNAL_{tf}M_MIDPOINT_{flag}';s=summary['STRICT_'+k]['net_points'];v=summary['EXTENDED_'+k]['net_points']
                delta.append(f'| {tf}m | {flag} | {s:+.2f} | {v:+.2f} | {v-s:+.2f} |')
        (a.output/'extension-deltas.md').write_text('\n'.join(delta));print('\n'.join(delta),flush=True)
        reporting.write_reports(a.output,dict(session_date=day,research_only=True,manifest=manifest,recorded_bar_parity=proof,api_live_parity=drift,strict_regression=checks,policies=results))
    except Exception as e:
        (a.output/'failure.json').write_text(json.dumps(dict(status='BLOCKED',error=str(e),traceback=traceback.format_exc(),orders_sent=False),indent=2))
        print('BLOCKED:',e,flush=True);raise SystemExit(2)
if __name__=='__main__':main()
