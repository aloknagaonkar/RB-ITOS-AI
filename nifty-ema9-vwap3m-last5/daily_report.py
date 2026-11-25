import argparse,json,hashlib,csv,html,traceback
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
import strategy
HERE=Path(__file__).parent

def write_report(output,data):
    result=data['result'];summary=data['summary'];esc=lambda x:html.escape(str(x));fmt=lambda v:'—' if v is None else f'{v:+.2f}'
    cols=['direction','entry_time','entry_price','exit_time','exit_price','points','index_points','peak_profit','peak_time','giveback','close_mae','exit_reason']
    with (output/'trades.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=cols);w.writeheader();w.writerows({k:t.get(k) for k in cols} for t in result['trades'])
    lines=['# EMA9 + OHLC4 VWAP: 3m wick rejection','',f"Session: {data['manifest']['session_date']}; futures: {data['manifest']['contract']['trading_symbol']}",
        '',f"Trades: {summary['trades']}; winners: {summary['winners']}; losers: {summary['losers']}",
        f"Futures points: {summary['futures_points']:+.2f}; NIFTY index comparison: {fmt(summary['index_points'])}",
        f"Closed futures drawdown: {summary['closed_drawdown']:.2f}; worst trade: {summary['worst_trade']:.2f}",
        f"Futures points without largest winner: {summary['without_largest_winner']:+.2f}",
        '', 'Completed 3m wick rejection of both lines; VWAP = cumulative 3m OHLC4 × volume / volume. EMA9 of 3m closes, seeded from first session close. Entry/EMA-close exit fills at next 3m open. Single position. No same-signal reversal. Final open position receives 15:30 close mark. Gross candle marks, no execution costs or options. Index points are a separate timestamp benchmark, not independently generated signals.',
        '', '| Direction | Entry IST | Exit IST | Futures points | Index points | Peak futures points | Peak IST | Giveback | Exit reason |',
        '|---|---|---|---:|---:|---:|---|---:|---|']
    tr=''
    for t in result['trades']:
        vals=[t['direction'],t['entry_time'][11:16],t['exit_time'][11:16],fmt(t['points']),fmt(t['index_points']),fmt(t['peak_profit']),(t['peak_time'] or '')[11:16],f"{t['giveback']:.2f}",t['exit_reason']]
        lines.append('| '+' | '.join(str(v) for v in vals)+' |')
        full=[t['direction'],t['entry_signal']['available_at'][11:16],t['entry_time'][11:16],f"{t['entry_price']:.2f}",t['exit_time'][11:16],f"{t['exit_price']:.2f}",fmt(t['points']),fmt(t['index_points']),fmt(t['peak_profit']),(t['peak_time'] or '')[11:16],f"{t['giveback']:.2f}",f"{t['entry_signal']['ema9']:.2f}",f"{t['entry_signal']['vwap']:.2f}",t['exit_reason']]
        tr+='<tr>'+''.join('<td>'+esc(v)+'</td>' for v in full)+'</tr>'
    (output/'comparison.md').write_text('\n'.join(lines));(output/'report.json').write_text(json.dumps(data,indent=2))
    ar=''
    for a in result['audit']:
        f=a['frame'];v=[f['candle_label'][11:16]+' → '+a['time'][11:16],f['open'],f['high'],f['low'],f['close'],f['volume'],f['vwap_source_ohlc4'],f['ema9'],f['vwap'],a['checks']['bullish_entry'],a['checks']['bearish_entry'],a['position_at_close'],', '.join(a['actions']),json.dumps(a['executions'])]
        ar+='<tr>'+''.join('<td>'+esc(f'{x:.3f}' if isinstance(x,float) else x)+'</td>' for x in v)+'</tr>'
    th=lambda names:'<tr>'+''.join('<th>'+esc(n)+'</th>' for n in names)+'</tr>'
    page='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>EMA9 + VWAP 3m research</title><style>body{font:15px/1.55 system-ui;color:#19334b;background:#edf3f9;margin:0}main{max-width:1450px;margin:auto;padding:28px}section{padding:22px;background:white;border-radius:12px;margin:20px 0}.scroll{overflow:auto;max-height:700px}table{border-collapse:collapse;width:100%;font-size:13px}td,th{padding:9px;border-bottom:1px solid #dae3ee;white-space:nowrap;text-align:right}th{background:#e7eff8;position:sticky;top:0}td:first-child,th:first-child{text-align:left}.note{padding:14px;background:#fff2d6}pre{white-space:pre-wrap;font-size:12px}summary{cursor:pointer}</style><main><h1>EMA9 + OHLC4 VWAP · 3m wick rejection</h1><p>{{SESSION}} · {{CONTRACT}} · completed session research · all times IST</p><section><h2>Outcome</h2><p>Trades: {{N}} · winners: {{W}} · losers: {{L}}. <strong>Futures points: {{FP}}</strong>. NIFTY index comparison points: {{IP}}.</p><p>Closed futures drawdown: {{DD}}. Worst trade: {{WORST}}. Without largest winner: {{WITHOUT}}. Session-end closes: {{ENDCOUNT}}.</p></section><section><h2>Exact strategy</h2><p>Bullish: completed 3m low &lt; both EMA9 and VWAP, with close &gt; both. Bearish: high &gt; both, with close &lt; both. Touch/equality does not qualify. No candle-colour, slope, RSI/WMA, fixed-stop or target filter is added.</p><p>EMA9 is exponential averaging of 3m closes (alpha 0.2). VWAP source is each aggregated 3m candle’s (O+H+L+C)/4, weighted by that candle’s futures volume and reset each session. Signal evaluation uses the final completed-candle line values; intrabar line paths are not reconstructed.</p><p>Bullish exits after completed 3m close &lt; EMA9; bearish after close &gt; EMA9. Equality holds. Both entries and these exits execute at next 3m candle OPEN; gaps are included. One position, no adding or immediate reversal from a candle that generated an exit while active.</p><p class="note">Only one futures session is supplied: EMA9 is seeded at its first completed 3m close with no extra nine-bar waiting filter. Prior-session-seeded charts may differ. A position still open at 15:30 is closed at the last observed session close for this intraday study; this is recorded separately from EMA exits. No entry after the final bar. No 14:55 cutoff.</p><p>Gross futures points exclude fees, slippage, latency, option fills and brokerage. NIFTY index points are computed using index prices at the same futures entry/exit timestamps; no futures VWAP is applied to index candles and these are not separate index-generated signals.</p></section><section><h2>Every trade</h2><div class="scroll"><table><thead>{{TRADEHEAD}}</thead><tbody>{{TRADES}}</tbody></table></div><p>Peak uses completed 1m futures closes during the trade plus actual entry/exit marks, floored at zero. Giveback = peak − final futures P&amp;L; close-MAE is a separate CSV/JSON field. Peaks are hindsight, not executable targets. Drawdown uses closed trades only.</p></section><section><h2>All 125 completed candles and decisions</h2><div class="scroll"><table><thead>{{AUDITHEAD}}</thead><tbody>{{AUDIT}}</tbody></table></div></section><section><h2>Provenance and assumptions</h2><pre>{{MANIFEST}}</pre></section></main></html>'''
    substitutions={'SESSION':data['manifest']['session_date'],'CONTRACT':data['manifest']['contract']['trading_symbol'],'TRADEHEAD':th(['Direction','Signal IST','Entry IST','Futures entry','Exit IST','Futures exit','Futures points','Index points','Peak futures points','Peak IST','Giveback','Signal EMA9','Signal VWAP','Exit reason']),'TRADES':tr,'AUDITHEAD':th(['Candle start → end','Open','High','Low','Close','Volume','OHLC4','EMA9','VWAP','Bull signal','Bear signal','Position','Decision','Execution']),'AUDIT':ar,'MANIFEST':esc(json.dumps(data['manifest'],indent=2))}
    # Replace explicit placeholder tokens before short summary placeholders.
    for k,v in substitutions.items():page=page.replace('{{'+k+'}}',str(v))
    for key,value in [('N',summary['trades']),('W',summary['winners']),('L',summary['losers']),('FP',fmt(summary['futures_points'])),('IP',fmt(summary['index_points'])),('DD',f"{summary['closed_drawdown']:.2f}"),('WORST',fmt(summary['worst_trade'])),('WITHOUT',fmt(summary['without_largest_winner'])),('ENDCOUNT',summary['session_end_closes'])]:
        page=page.replace('{{'+key+'}}',str(value))
    (output/'report.html').write_text(page)
    with ZipFile(output/'results.zip','x',ZIP_DEFLATED) as z:
        for p in sorted(output.iterdir()):
            if p.is_file() and p.name!='results.zip':z.write(p,p.name)
    print('\n'.join(lines));print('UPLOAD:',output/'results.zip')
