"""VM-only five-session data fetch and unchanged-strategy replay."""
import argparse,json,hashlib,csv,html
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
import collect,strategy,daily_report
HERE=Path(__file__).parent

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    if a.output.exists():raise ValueError('OUTPUT_EXISTS_USE_NEW_DIRECTORY')
    a.output.mkdir(parents=True)
    try:
        pin=json.loads((HERE/'strategy-pin.json').read_text())
        if hashlib.sha256((HERE/'strategy.py').read_bytes()).hexdigest()!=pin['sha256']:raise ValueError('STRATEGY_CHANGED_FROM_OCT26')
        contract,inputs=collect.collect(a.output);days={};all_trades=[];daily_rows=[]
        for day in collect.DAYS:
            futures,index=inputs[day];print('Replaying',day,flush=True)
            r=strategy.replay(futures,index);s=strategy.summarize(r)
            manifest=dict(session_date=day,contract=contract,source='UPSTOX_LATER_API',interval=3,vwap_source='OHLC4_AGGREGATED_3M_VOLUME_WEIGHTED',ema_seed='FIRST_COMPLETED_3M_CLOSE_RESET_EACH_SESSION',fill='NEXT_3M_OPEN',study_window='09:15-15:30 IST',same_signal_reversal=False,orders_sent=False,live_changes=False,index_is_separate_timestamp_benchmark=True,input_sha256={k:hashlib.sha256((a.output/'inputs'/(k+'-'+day+'.json')).read_bytes()).hexdigest() for k in ['futures','index']})
            data=dict(manifest=manifest,result=r,summary=s);dest=a.output/day;dest.mkdir();daily_report.write_report(dest,data)
            days[day]=data;all_trades.extend(dict(t,session_date=day) for t in r['trades']);daily_rows.append(dict(session_date=day,**s))
        # Study reports a single futures contract across these five post-expiry dates.
        total=strategy.summarize(dict(trades=all_trades,index_benchmark_available=True));daily_worst=min((s['futures_points'] for s in daily_rows),default=0)
        daily_best=max((s['futures_points'] for s in daily_rows),default=0)
        report=dict(status='COMPLETE_ALL_FIVE_SESSIONS',contract=contract,dates=collect.DAYS,days=days,aggregate=total,
            positive_days=sum(r['futures_points']>0 for r in daily_rows),negative_days=sum(r['futures_points']<0 for r in daily_rows),
            worst_day=daily_worst,best_day=daily_best,without_best_day=total['futures_points']-daily_best,
            strategy_sha256=pin['sha256'],orders_sent=False,live_changes=False)
        (a.output/'report.json').write_text(json.dumps(report,indent=2))
        (a.output/'manifest.json').write_text(json.dumps(dict(status=report['status'],dates=collect.DAYS,contract=contract,strategy_sha256=pin['sha256'],package_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in HERE.glob('*.py')},orders_sent=False),indent=2))
        fields=['session_date','trades','winners','losers','futures_points','index_points','bullish_futures_points','bearish_futures_points','closed_drawdown','without_largest_winner']
        with (a.output/'daily-summary.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(daily_rows)
        columns=['session_date','direction','entry_time','entry_price','exit_time','exit_price','points','index_points','peak_profit','peak_time','giveback','exit_reason']
        with (a.output/'all-trades.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=columns,extrasaction='ignore');w.writeheader();w.writerows(all_trades)
        lines=['# EMA9 + OHLC4 VWAP / 3m: last five completed sessions','', '| Date | Trades | Wins | Futures points | Index points | Closed DD |','|---|---:|---:|---:|---:|---:|']
        for r in daily_rows:lines.append(f"| {r['session_date']} | {r['trades']} | {r['winners']} | {r['futures_points']:+.2f} | {r['index_points']:+.2f} | {r['closed_drawdown']:.2f} |")
        lines+=['',f"Total futures points: {total['futures_points']:+.2f}; index benchmark: {total['index_points']:+.2f}; chronological closed DD: {total['closed_drawdown']:.2f}",f"Positive/negative days: {report['positive_days']}/{report['negative_days']}; without best day: {report['without_best_day']:+.2f}; without largest trade winner: {total['without_largest_winner']:+.2f}",'','Same agreed strategy. Daily EMA9 seed and VWAP reset. Gross marks, no costs. Common 09:15–15:30 study window. Session-end close convention. No live changes.']
        (a.output/'comparison.md').write_text('\n'.join(lines))
        esc=lambda v:html.escape(str(v));rows=''
        for r in daily_rows:rows+='<tr>'+''.join('<td>'+esc(f'{r[k]:+.2f}' if isinstance(r[k],float) else r[k])+'</td>' for k in fields)+'</tr>'
        trs=''
        for t in all_trades:trs+='<tr>'+''.join('<td>'+esc(f'{t.get(k):+.2f}' if isinstance(t.get(k),float) else (t.get(k) or '—'))+'</td>' for k in columns)+'</tr>'
        page='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>EMA9 VWAP five-session comparison</title><style>body{font:15px/1.6 system-ui;color:#1c354e;background:#edf3f9}main{max-width:1450px;margin:auto;padding:24px}section{background:white;padding:20px;margin:18px 0;border-radius:10px}.scroll{overflow:auto}td,th{padding:9px;white-space:nowrap;text-align:right;border-bottom:1px solid #ddd}table{border-collapse:collapse;width:100%;font-size:13px}th{background:#e8f0fa}pre{white-space:pre-wrap}</style><main><h1>EMA9 + OHLC4 VWAP · 3m · five sessions</h1><p>29 October–4 November 2026. All times IST. Futures points primary; index points are same-timestamp benchmarks. No independent index signals.</p><section><pre>SUMMARY</pre></section><section><h2>Daily results</h2><div class="scroll"><table><thead><tr>DAYHEAD</tr></thead><tbody>DAYROWS</tbody></table></div></section><section><h2>Every trade, peak and giveback</h2><div class="scroll"><table><thead><tr>TRADEHEAD</tr></thead><tbody>TRADEROWS</tbody></table></div></section><section><h2>Conventions</h2><p>Same 3m wick rejection of EMA9 and OHLC4 VWAP, exit on 3m close beyond EMA9, fills next 3m open. EMA9 seed first completed candle each session; VWAP resets daily. 09:15–15:30 common study window; final position receives session-end close. One position; no immediate reversal on exit signal. Each date folder contains the full 125-candle audit and detailed HTML report.</p><p>Gross futures marks exclude fees, slippage, latency and options. Peaks are hindsight diagnostics, not guaranteed exits; giveback includes additional losses. Closed DD excludes intratrade excursions. These five sessions do not establish general performance.</p><pre>CONTRACT</pre></section></main></html>'''
        page=page.replace('SUMMARY',esc('\n'.join(lines[-4:]))).replace('DAYHEAD',''.join('<th>'+esc(k)+'</th>' for k in fields)).replace('DAYROWS',rows).replace('TRADEHEAD',''.join('<th>'+esc(k)+'</th>' for k in columns)).replace('TRADEROWS',trs).replace('CONTRACT',esc(json.dumps(contract,indent=2)))
        (a.output/'report.html').write_text(page)
        with ZipFile(a.output/'results.zip','x',ZIP_DEFLATED) as z:
            for p in sorted(a.output.rglob('*')):
                if p.is_file() and p.name!='results.zip':z.write(p,str(p.relative_to(a.output)))
        print('\n'.join(lines));print('UPLOAD:',a.output/'results.zip',flush=True)
    except Exception as e:
        # Avoid tracebacks through authenticated HTTP requests or token setup.
        error=str(e) if isinstance(e,(collect.DataError,ValueError)) else 'LOCAL_PROCESSING_ERROR_'+type(e).__name__
        (a.output/'failure.json').write_text(json.dumps(dict(status='BLOCKED_NO_COMPLETE_FIVE_DAY_RESULT',error=error,orders_sent=False),indent=2));print('BLOCKED:',error,flush=True);raise SystemExit(2)
if __name__=='__main__':main()
