import json,html
from datetime import datetime,timedelta
from zipfile import ZipFile,ZIP_DEFLATED
import core

def signature(p):
    return [[t['direction'],t['entry_time'],t['entry_price'],t['exit_time'],t['exit_price'],t['exit_reason'],t.get('route','EXISTING')] for t in p['trades']]

def enrich(p,raw,day,until):
    minutes={b.ts+timedelta(minutes=1):float(b.close) for b in core.aggregate(raw,day,1,until)}
    for t in p['trades']:
        sg=1 if t['direction']=='BULLISH' else -1;peak=0;stamp=None
        start=datetime.fromisoformat(t['entry_time']);end=datetime.fromisoformat(t['exit_time'])
        path=[(at,px) for at,px in minutes.items() if start<at<=end]
        if len(path)!=int((end-start).total_seconds()/60):raise ValueError('MISSING_PEAK_MINUTES')
        for at,px in path:
            value=sg*(px-t['entry_price'])
            if value>peak:peak=value;stamp=at.isoformat()
        t.update(peak_profit=peak,peak_time=stamp,giveback=peak-t['points'])

def stats(p):
    tt=p['trades'];eq=peak=dd=0
    for t in tt:eq+=t['points'];peak=max(peak,eq);dd=max(dd,peak-eq)
    wins=[t['points'] for t in tt if t['points']>0]
    return dict(trades=len(tt),winners=len(wins),losers=sum(t['points']<0 for t in tt),net_points=eq,closed_drawdown=dd,
        bullish_trades=sum(t['direction']=='BULLISH' for t in tt),bullish_points=sum(t['points'] for t in tt if t['direction']=='BULLISH'),
        bearish_points=sum(t['points'] for t in tt if t['direction']=='BEARISH'),
        midpoint_exits=sum(t['exit_reason']=='POST_ENTRY_1M_SIGNAL_MIDPOINT_REVERSED' for t in tt),
        profit_exits=sum(t['exit_reason'].startswith('BULLISH_PROFIT_PROTECTION_') for t in tt),
        worst_trade=min((t['points'] for t in tt),default=0),
        without_largest_winner=eq-max(wins,default=0))

def reports(output,report):
    report['summary']={k:stats(p) for k,p in report['policies'].items()}
    (output/'report.json').write_text(json.dumps(report,indent=2))
    lines=['# Bullish optimization candidates: October 26','',
        'COMMON_LATER_API. Full-state VM replay. Signal interval in policy key; existing route/exits remain 5m. Bearish qualification and midpoint rules unchanged, but different bullish holding periods can alter later bearish opportunities. Gross index marks; no fees/slippage/options.',
        '', '| Policy | Trades | Wins | Bullish pts | Bearish pts | Total pts | Closed DD | Profit exits | Without largest winner |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for k,s in report['summary'].items():lines.append(f"| {k} | {s['trades']} | {s['winners']} | {s['bullish_points']:+.2f} | {s['bearish_points']:+.2f} | {s['net_points']:+.2f} | {s['closed_drawdown']:.2f} | {s['profit_exits']} | {s['without_largest_winner']:+.2f} |")
    (output/'comparison.md').write_text('\n'.join(lines))
    esc=lambda s:html.escape(str(s));f=lambda x:f'{x:+.2f}'
    summary_rows=''
    for k,s in report['summary'].items():
        vals=[k,s['trades'],s['winners'],f(s['bullish_points']),f(s['bearish_points']),f(s['net_points']),f'{s["closed_drawdown"]:.2f}',s['profit_exits'],f(s['without_largest_winner'])]
        summary_rows+='<tr>'+''.join('<td>'+esc(v)+'</td>' for v in vals)+'</tr>'
    sections=[]
    for k,p in report['policies'].items():
        rows=''
        for t in p['trades']:
            e=t.get('evidence') or {};route=e.get('qualification_route') or t.get('route','EXISTING')
            vals=[t['direction'],route,(t.get('setup') or '')[11:16],t['entry_time'][11:16],t['entry_price'],t['exit_time'][11:16],t['exit_price'],f(t['points']),f(t['peak_profit']),(t['peak_time'] or '')[11:16],f(t['giveback']),t['exit_reason']]
            rows+='<tr>'+''.join('<td>'+esc(v)+'</td>' for v in vals)+'</tr>'
        headers=['Direction','Qualification','Signal IST','Entry IST','Entry price','Exit IST','Exit price','Final points','Peak profit','Peak IST','Giveback','Exit reason']
        sections.append('<section><h2>'+esc(k)+'</h2><div class="scroll"><table><thead><tr>'+''.join('<th>'+h+'</th>' for h in headers)+'</tr></thead><tbody>'+rows+'</tbody></table></div><details><summary>Full audit / values</summary><pre>'+esc(json.dumps(p['audit'],indent=2))+'</pre></details></section>')
    text='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Bullish optimization research</title><style>body{font:15px/1.55 system-ui;background:#f1f5fa;color:#19334b;margin:0}main{max-width:1450px;margin:auto;padding:28px}section{background:white;padding:22px;margin:20px 0;border-radius:12px}table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:9px;border-bottom:1px solid #dce4ee;white-space:nowrap;text-align:right}th:first-child,td:first-child{text-align:left}th{background:#e8f0fa}.scroll{overflow:auto}pre{white-space:pre-wrap;font-size:12px}summary{cursor:pointer;font-weight:bold}.note{padding:14px;background:#fff3d9}</style><main><h1>Bullish optimization: controlled candidates</h1><p>October 26, 2026 · full-state VM replay · all times IST · gross NIFTY index points</p><p>Two independent entry rules (strict body cross versus cross OR already above EMA10) × three independent bullish exit profiles (midpoint only, +20 activation / 10-point giveback, +40 activation / 20-point giveback). Every signal still needs a green candle, body &gt;60%, rising EMA10 and a later completed 1m close above signal high. Fixed signal midpoint protection remains enabled. New profit exits apply only to independent bullish positions.</p><p>Profit protection uses a peak known at a prior completed 1m close, then exits at the observed current close. Equality at the giveback threshold triggers; equality at the fixed signal midpoint holds. Overshoot is possible. The 14:55 cutoff overrides at exact minute-open pricing. Original 5m structural exits/reversal remain active. Different exits/entries can change later trades in either direction.</p><p class="note">Candidate rules, not production recommendations. One already-examined session is insufficient to select an optimum. Peaks are hindsight diagnostics, not assumed achievable exits. Closed-trade drawdown excludes intratrade excursions; no fees, latency, slippage or option fills.</p><p>Recorded-bar reproduction: PROOF. API/live parity: DRIFT. Uploaded baseline regressions: REGRESSION. Input basis remains common later API, not original live minute recovery.</p><section><h2>Comparison</h2><div class="scroll"><table><thead><tr><th>Policy</th><th>Trades</th><th>Wins</th><th>Bullish points</th><th>Bearish points</th><th>Total points</th><th>Closed DD</th><th>Profit exits</th><th>Without largest winner</th></tr></thead><tbody>ROWS</tbody></table></div></section>SECTIONS</main></html>'''
    text=text.replace('PROOF',esc(report['recorded_bar_parity']['status'])).replace('DRIFT',esc(report['api_live_parity']['status'])).replace('REGRESSION',esc(report['baseline_regression'])).replace('ROWS',summary_rows).replace('SECTIONS',''.join(sections))
    (output/'report.html').write_text(text)
    with ZipFile(output/'results.zip','x',ZIP_DEFLATED) as z:
        for p in sorted(output.iterdir()):
            if p.is_file() and p.name!='results.zip':z.write(p,p.name)
    print('\n'.join(lines));print('UPLOAD:',output/'results.zip',flush=True)
