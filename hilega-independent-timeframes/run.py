"""VM-only full-state hybrid replay, common later API comparison."""
import argparse,json,hashlib,html,traceback
from pathlib import Path
from datetime import datetime,date,time
from zipfile import ZipFile,ZIP_DEFLATED
import core,study,common_input,hybrid,reference_protected,reference_unprotected

def signature(r):
    return [(t['direction'],t['entry_time'],t['entry_price'],t['exit_time'],t['exit_price'],t['exit_reason'],t.get('route','EXISTING')) for t in r['trades']]

def stats(r):
    eq=peak=dd=0;tt=r['trades']
    for t in tt:
        eq+=t['points'];peak=max(peak,eq);dd=max(dd,peak-eq)
    return dict(trades=len(tt),winners=sum(t['points']>0 for t in tt),losers=sum(t['points']<0 for t in tt),net_points=eq,closed_drawdown=dd,worst_trade=min((t['points'] for t in tt),default=0),independent_trades=sum(t.get('route')=='INDEPENDENT_BODY60_1M_BREAKOUT' for t in tt),midpoint_exits=sum(t['exit_reason']=='POST_ENTRY_1M_SIGNAL_MIDPOINT_REVERSED' for t in tt))

def write_reports(output,report):
    summaries={k:stats(v) for k,v in report['policies'].items()};report['summary']=summaries
    (output/'report.json').write_text(json.dumps(report,indent=2))
    lines=['# Independent body-cross + midpoint: 26 October 2026','',
        'COMMON_LATER_API. Existing 5m route and exits retained across every comparison. Only independent signal cadence changes; EMA10 remains 10 signal candles. 1m close breakout and fixed signal midpoint protection. Equality holds; no wick exits. No fees, slippage, option fills or live changes.',
        '',f"Recorded-bar reproduction: {report['recorded_bar_parity']['status']}. Later API versus live parity: {report['api_live_parity']['status']} (separate evidence, not waived).",'',
        '| Policy | Trades | Winners | Losers | Gross points | Closed DD | Independent trades | Midpoint exits |',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    for name,s in summaries.items():lines.append(f"| {name} | {s['trades']} | {s['winners']} | {s['losers']} | {s['net_points']:+.2f} | {s['closed_drawdown']:.2f} | {s['independent_trades']} | {s['midpoint_exits']} |")
    (output/'comparison.md').write_text('\n'.join(lines))
    esc=lambda x:html.escape(str(x));num=lambda x:f'{x:+.2f}'
    rows=''.join('<tr>'+''.join(f'<td>{esc(v)}</td>' for v in [k,s['trades'],s['winners'],s['losers'],num(s['net_points']),f"{s['closed_drawdown']:.2f}",s['independent_trades'],s['midpoint_exits']])+'</tr>' for k,s in summaries.items())
    sections=[]
    for name,result in report['policies'].items():
        body=''
        for t in result['trades']:
            ev=t.get('evidence') or {};f=ev.get('signal_frame') or {}
            values=[t['direction'],t.get('route','EXISTING'),(t.get('setup') or '')[11:16],t['entry_time'][11:16],t['entry_price'],t['exit_time'][11:16],t['exit_price'],num(t['points']),t['exit_reason'],ev.get('midpoint','—'),f.get('ema10','—'),ev.get('body_ratio','—')]
            body+='<tr>'+''.join(f'<td>{esc(v)}</td>' for v in values)+'</tr>'
        audit=esc(json.dumps(result['audit'],indent=2))
        sections.append(f'<section><h2>{esc(name)}</h2><div class="scroll"><table><thead><tr>'+''.join(f'<th>{x}</th>' for x in ['Direction','Route','Signal IST','Entry IST','Entry price','Exit IST','Exit price','Points','Exit reason','Signal midpoint','Signal EMA10','Body ratio'])+f'</tr></thead><tbody>{body}</tbody></table></div><details><summary>Full decision audit with values</summary><pre>{audit}</pre></details></section>')
    page='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Independent body-cross · 26 October 2026</title><style>body{font:15px/1.5 system-ui;margin:0;background:#f1f5fa;color:#193047}main{max-width:1350px;margin:auto;padding:28px}section{background:white;padding:22px;margin:20px 0;border-radius:12px}table{border-collapse:collapse;width:100%;font-size:13px}td,th{padding:10px;text-align:left;border-bottom:1px solid #ddd;white-space:nowrap}th{background:#e7eff8}.scroll{overflow:auto}pre{white-space:pre-wrap;font-size:12px}summary{cursor:pointer;font-weight:bold}button{padding:10px}</style><main><h1>Independent body-cross + midpoint protection</h1><p>26 October 2026 · 1m / 3m / 5m signal comparison · All times IST</p><p>Existing 5m route and exits stay unchanged. Independent signal candles vary; EMA10 is computed from that interval. Confirmation and midpoint protection always use later completed 1m closes. Original signal midpoint stays fixed. Equality holds. One position; existing entries win a same-5m-boundary entry conflict. Protected and unprotected full-state runs may generate different later entries.</p><p>Recorded-bar reproduction: PROOF. API versus recorded-live parity: DRIFT. This comparison uses the same later API minutes for every policy; it does not recover original live 1m candles. Gross index points only; no fees, slippage, execution latency or option fills. Closed-trade drawdown excludes intratrade excursions. Research only; no live changes.</p><section><h2>Comparison</h2><div class="scroll"><table><thead><tr><th>Policy</th><th>Trades</th><th>Winners</th><th>Losers</th><th>Gross points</th><th>Closed DD</th><th>Independent trades</th><th>Midpoint exits</th></tr></thead><tbody>ROWS</tbody></table></div></section>SECTIONS<p>Full report.json, comparison.md, manifest.json and parity checks are included in results.zip.</p></main></html>'''
    page=page.replace('PROOF',esc(report['recorded_bar_parity']['status'])).replace('DRIFT',esc(report['api_live_parity']['status'])).replace('ROWS',rows).replace('SECTIONS',''.join(sections))
    (output/'report.html').write_text(page)
    with ZipFile(output/'results.zip','x',ZIP_DEFLATED) as z:
        for p in sorted(output.iterdir()):
            if p.is_file() and p.name!='results.zip':z.write(p,p.name)
    print('\n'.join(lines));print('UPLOAD:',output/'results.zip',flush=True)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input-zip',type=Path,required=True);ap.add_argument('--session-input',type=Path,required=True)
    ap.add_argument('--cache-root',type=Path,action='append',default=[]);ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args()
    if a.output.exists():raise ValueError('OUTPUT_EXISTS_USE_NEW_DIRECTORY')
    a.output.mkdir(parents=True)
    try:
        installed,hashes=study.verify_sources()
        data,warm,records,actions=study.load_inputs(a.input_zip,a.session_input,list(study.CACHE_ROOTS)+a.cache_root)
        day=data['session_date']
        if day!='2026-10-26':raise ValueError('THIS_PACKAGE_REQUIRES_2026_10_26')
        until=datetime.combine(date.fromisoformat(day),time(14,55),core.IST)
        manifest=dict(session_date=day,comparison_basis='COMMON_LATER_API',signal_intervals=[1,3,5],existing_policy_interval=5,confirmation_interval=1,protection_interval=1,midpoint_reference='ORIGINAL_SIGNAL_RANGE',midpoint_equality='HOLD',cutoff='14:55 IST exact minute open',warmup_sessions=len(warm),warmup_last=warm[-1][0],warmup_actions=actions,source_sha256=hashes,input_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [a.input_zip,a.session_input]},package_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.iterdir() if p.suffix in ['.py','.json']},orders_sent=False,live_changes=False)
        (a.output/'manifest.json').write_text(json.dumps(manifest,indent=2))
        print('1/9 Recorded 5m bar reproduction...',flush=True)
        raw_cutoff,basis=common_input.cutoff_source(data['candles'],records,day)
        recorded=core.run(core.policy5,core.legacy5,warm,raw_cutoff,day,5,until,target_bars=common_input.recorded_bars(records,day))
        proof=core.parity(recorded,records,until)
        (a.output/'recorded-bar-parity.json').write_text(json.dumps(proof,indent=2))
        if proof['status']!='PASS':raise ValueError('RECORDED_BAR_REPRODUCTION_FAILED')
        print('2/9 Existing 5m common API control...',flush=True)
        baseline=core.run(core.policy5,core.legacy5,warm,data['candles'],day,5,until)
        drift=core.parity(baseline,records,until)
        (a.output/'api-live-parity.json').write_text(json.dumps(drift,indent=2))
        print('API/live parity:',drift['status'],'(retained separately)',flush=True)
        # Seed exact existing 5m state once; replay clones it for every policy.
        c=core.legacy5.ExitFirstCanonical();tracker=core.policy5.PriceFrames();count=0
        for d,rows in warm:
            if d>=day:continue
            for b in core.aggregate(rows,d,5,datetime.combine(date.fromisoformat(d),time(15,30),core.IST)):c.on_bar(b);tracker.seed(b)
            count+=1
        prepared=(c,tracker,count);results={'EXISTING_5M_CONTROL':baseline}
        for i,interval in enumerate([1,3,5]):
            for j,protected in enumerate([False,True]):
                key=f'SIGNAL_{interval}M_'+('MIDPOINT_ON' if protected else 'MIDPOINT_OFF')
                print(f'{3+i*2+j}/9 {key}...',flush=True)
                results[key]=hybrid.replay(warm,data['candles'],day,prepared=prepared,signal_interval=interval,protected=protected)
        print('9/9 Exact original 5m protected/unprotected regression controls...',flush=True)
        checks={}
        for flag,module in [('ON',reference_protected),('OFF',reference_unprotected)]:
            ref=module.replay(warm,data['candles'],day,prepared=prepared)
            match=signature(ref)==signature(results['SIGNAL_5M_MIDPOINT_'+flag]);checks[flag]='PASS' if match else 'FAIL'
        (a.output/'five-minute-regression.json').write_text(json.dumps(checks,indent=2))
        if any(v!='PASS' for v in checks.values()):raise ValueError('ORIGINAL_5M_REGRESSION_FAILED')
        write_reports(a.output,dict(session_date=day,research_only=True,manifest=manifest,recorded_bar_parity=proof,api_live_parity=drift,five_minute_regression=checks,policies=results))
    except Exception as e:
        (a.output/'failure.json').write_text(json.dumps(dict(status='BLOCKED',error=str(e),traceback=traceback.format_exc(),orders_sent=False),indent=2))
        print('BLOCKED:',e,flush=True);raise SystemExit(2)
if __name__=='__main__':main()
