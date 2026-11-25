"""VM-only bullish optimization candidates; prior bearish extension retained."""
import argparse,json,hashlib,traceback
from pathlib import Path
from datetime import datetime,date,time
import core,study,common_input,hybrid,baseline_hybrid,reporting

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input-zip',type=Path,required=True);ap.add_argument('--session-input',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True);ap.add_argument('--cache-root',type=Path,action='append',default=[])
    ap.add_argument('--signal-interval',type=int,choices=[1,3,5],action='append',default=None)
    a=ap.parse_args();here=Path(__file__).parent;intervals=sorted(set(a.signal_interval or [1]))
    if a.output.exists():raise ValueError('OUTPUT_EXISTS_USE_NEW_DIRECTORY')
    a.output.mkdir(parents=True)
    try:
        installed,hashes=study.verify_sources()
        data,warm,records,actions=study.load_inputs(a.input_zip,a.session_input,list(study.CACHE_ROOTS)+a.cache_root)
        day=data['session_date']
        if day!='2026-10-26':raise ValueError('OCT26_ONLY_CANDIDATE_PACKAGE')
        expected=json.loads((here/'expected-controls.json').read_text())
        actual={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [a.input_zip,a.session_input]}
        if sorted(actual.values())!=sorted(expected['input_sha256'].values()):raise ValueError('INPUT_CHANGED_FROM_UPLOADED_CONTROL')
        until=datetime.combine(date.fromisoformat(day),time(14,55),core.IST)
        manifest=dict(session_date=day,signal_intervals=intervals,existing_policy_interval=5,comparison_basis='COMMON_LATER_API',
            bullish_entry_candidates=['BODY_CROSS','BODY_CROSS_OR_ALREADY_ABOVE'],bullish_profit_profiles=['MIDPOINT_ONLY','TRAIL20_10','TRAIL40_20'],
            bearish_rule='LAST_UPLOADED_EXTENSION_UNCHANGED',new_profit_exit_scope='INDEPENDENT_BULLISH_ONLY',warmup_sessions=len(warm),warmup_last=warm[-1][0],warmup_actions=actions,
            source_sha256=hashes,input_sha256=actual,package_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in here.iterdir() if p.suffix in ['.py','.json']},orders_sent=False,live_changes=False)
        (a.output/'manifest.json').write_text(json.dumps(manifest,indent=2))
        print('Recorded 5m bar reproduction...',flush=True)
        rr,basis=common_input.cutoff_source(data['candles'],records,day)
        replayed=core.run(core.policy5,core.legacy5,warm,rr,day,5,until,target_bars=common_input.recorded_bars(records,day))
        proof=core.parity(replayed,records,until);(a.output/'recorded-bar-parity.json').write_text(json.dumps(proof,indent=2))
        if proof['status']!='PASS':raise ValueError('RECORDED_BAR_REPRODUCTION_FAILED')
        print('Existing 5m common API control...',flush=True)
        control=core.run(core.policy5,core.legacy5,warm,data['candles'],day,5,until)
        drift=core.parity(control,records,until);(a.output/'api-live-parity.json').write_text(json.dumps(drift,indent=2))
        print('API/live parity:',drift['status'],'retained separately',flush=True)
        checks={'EXISTING_CONTROL':'PASS' if reporting.signature(control)==expected['control'] else 'FAIL'}
        c=core.legacy5.ExitFirstCanonical();tracker=core.policy5.PriceFrames();count=0
        for d,rows in warm:
            if d>=day:continue
            for bar in core.aggregate(rows,d,5,datetime.combine(date.fromisoformat(d),time(15,30),core.IST)):c.on_bar(bar);tracker.seed(bar)
            count+=1
        prepared=(c,tracker,count);results={'EXISTING_5M_CONTROL':control}
        for interval in intervals:
            print('Reproducing uploaded extended baseline',interval,'m...',flush=True)
            previous=baseline_hybrid.replay(warm,data['candles'],day,prepared=prepared,signal_interval=interval,protected=True)
            checks[f'UPLOADED_{interval}M']='PASS' if reporting.signature(previous)==expected['signatures'][str(interval)] else 'FAIL'
            for continuation in [False,True]:
                for profile in ['MIDPOINT_ONLY','TRAIL20_10','TRAIL40_20']:
                    key=f'SIGNAL_{interval}M_'+('CROSS_OR_ABOVE' if continuation else 'CROSS_ONLY')+'_'+profile
                    print('Running',key,flush=True)
                    results[key]=hybrid.replay(warm,data['candles'],day,prepared=prepared,signal_interval=interval,protected=True,bullish_continuation=continuation,profit_profile=profile)
                    if not continuation and profile=='MIDPOINT_ONLY':checks[f'NEW_ENGINE_BASELINE_{interval}M']='PASS' if reporting.signature(results[key])==reporting.signature(previous) else 'FAIL'
        (a.output/'baseline-regression.json').write_text(json.dumps(checks,indent=2))
        if any(v!='PASS' for v in checks.values()):raise ValueError('BASELINE_REGRESSION_FAILED')
        for p in results.values():reporting.enrich(p,data['candles'],day,until)
        reporting.reports(a.output,dict(session_date=day,research_only=True,manifest=manifest,recorded_bar_parity=proof,api_live_parity=drift,baseline_regression=checks,policies=results))
    except Exception as e:
        (a.output/'failure.json').write_text(json.dumps(dict(status='BLOCKED',error=str(e),traceback=traceback.format_exc(),orders_sent=False),indent=2))
        print('BLOCKED:',e,flush=True);raise SystemExit(2)
if __name__=='__main__':main()
