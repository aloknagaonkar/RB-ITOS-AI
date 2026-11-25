"""Offline monthly report. Trade direction and observed day trend are separate filters."""
import calendar
from datetime import date,timedelta
import html,json


def requested_days(days,month,through,today):
    if days:
        selected=sorted(set(date.fromisoformat(d) for d in days))
    else:
        start=date.fromisoformat(month+'-01');end=date.fromisoformat(through)
        if (end.year,end.month)!=(start.year,start.month):raise ValueError('THROUGH_MUST_BE_IN_MONTH')
        selected=[start+timedelta(days=i) for i in range((end-start).days+1)]
    if not selected:raise ValueError('NO_DATES_SELECTED')
    if any(d>today for d in selected):raise ValueError('FUTURE_SESSION_NOT_ALLOWED')
    return [d.isoformat() for d in selected]


def totals(trades):
    return dict(trades=len(trades),winners=sum(t['points']>0 for t in trades),losers=sum(t['points']<0 for t in trades),
        breakeven=sum(t['points']==0 for t in trades),net_points=sum(t['points'] for t in trades),
        peak_positive_points=sum(t['peak_positive_points'] for t in trades),giveback_points=sum(t['giveback_points'] for t in trades))


def daily_rows(results):
    rows=[]
    for r in results:
        rows.append(dict(session_date=r['session_date'],status=r.get('status','REPLAYED'),error=r.get('error',''),
            market_trend=r.get('market_trend','UNAVAILABLE'),session_kind=r.get('session_kind',''),**totals(r.get('trades',[]))))
    return rows


def page(results,updated=True):
    esc=lambda v:html.escape(str(v),quote=True)
    num=lambda v:'—' if v is None else f'{v:.2f}' if isinstance(v,(int,float)) and not isinstance(v,bool) else str(v)
    def table(headers,rows):return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+esc(h)+'</th>' for h in headers)+'</tr></thead><tbody>'+''.join(rows)+'</tbody></table></div>'
    def cells(values):return ''.join('<td>'+esc(v)+'</td>' for v in values)
    sections=[]
    for r in results:
        d=r['session_date'];trend=r.get('market_trend','UNAVAILABLE')
        parts=[f'<section data-date="{esc(d)}" data-trend="{trend}"><h2>{d} · {trend}</h2>']
        if r.get('status'):
            parts.append('<p>'+esc(r['status']+' '+r.get('error',''))+'</p></section>');sections.extend(parts);continue
        parts.append('<p>'+esc(r.get('session_kind','REGULAR'))+' · Open '+num(r.get('session_open'))+' → Close '+num(r.get('session_close'))+'</p><p class="day-stats"></p>')
        rows=[]
        for t in r['trades']:
            side=t['side'];detail=[]
            for phase in ['entry','exit']:
                f=t[phase+'_frame'];detail.append('<h4>'+phase.title()+' indicators</h4>'+table(['Indicator','Value'],['<tr>'+cells([k,num(v)])+'</tr>' for k,v in f.items()]))
            detail.append('<p>Entry checks: '+esc(json.dumps(t['entry_checks']))+'</p><p>Exit checks: '+esc(json.dumps(t['exit_checks']))+'</p>')
            values=[t['route_name'],side+' · '+('BULLISH' if side=='CE' else 'BEARISH'),t['entry_signal_time'][11:16],t['entry_time'][11:16],t['exit_time'][11:16],num(t['entry_price']),num(t['exit_price']),num(t['points']),num(t['peak_positive_points']),num(t['giveback_points']),'; '.join(t['exit_reasons'])]
            rows.append('<tr class="trade" data-side="'+side+'" data-route="'+esc(t['route_name'])+'">'+cells(values)+'<td><details><summary>Indicators</summary>'+''.join(detail)+'</details></td></tr>')
        parts.append(table(['Entry route','Direction','Signal IST','Entry IST','Exit IST','Entry NIFTY','Exit NIFTY','Net','Peak +','Giveback','Exit reason','Details'],rows))
        parts.append('<h3>Every completed 3-minute candle</h3>')
        for a in r['audit']:
            f=a['frame'];parts.append('<details class="candle"><summary>'+esc(a['decision_time'][11:16]+' IST · '+str(a['owner_before'])+' → '+str(a['owner_after']))+'</summary><p>Signal candle '+esc(f['start'][11:16])+' · O/H/L/C '+esc(' / '.join(num(f[k]) for k in ['open','high','low','close']))+'</p>')
            for side,v in a['entry_evaluation'].items():
                bull=side=='CE';rows=[]
                for key,passed in v['checks'].items():
                    if key.startswith('close_vs_'):actual='close '+num(f['close'])+'; EMA '+num(f['ema30_high' if bull else 'ema30_low']);req='close > EMA30 High' if bull else 'close < EMA30 Low'
                    elif key=='signal_candle_colour':actual='open '+num(f['open'])+'; close '+num(f['close']);req='Green: close > open' if bull else 'Red: close < open'
                    elif key.startswith('candle_'):
                        strength=v.get('candle_strength',{});metric={'candle_body_strength':'body_pct','candle_upper_wick':'upper_wick_pct','candle_lower_wick':'lower_wick_pct'}[key];actual=num(strength.get(metric))+'%';req='>=70%' if key=='candle_body_strength' else '<=15%'
                    elif key.startswith('wma'):actual=num(f['wma21_rsi9']);req='> 50' if bull else '< 50'
                    else:actual=num(f.get(key.replace('_threshold','')));req='> 55' if bull else '< 45'
                    label='PASS' if passed is True else 'FAIL' if passed is False else 'NOT READY'
                    rows.append('<tr><td>'+esc(key)+'</td><td class="'+('pass' if passed is True else 'fail')+'">'+label+'</td>'+cells([actual,req])+'</tr>')
                if 'route_checks' in v:
                    parts.append('<div class="direction" data-side="'+side+'"><p>RSI votes: '+str(v['rsi_pass_count'])+'/5; selected route: '+esc(v['selected_route'] or 'NONE')+'</p><p>Individual RSI/WMA failures below are diagnostics; the route gates determine entry.</p><pre>'+esc(json.dumps(dict(route_checks=v['route_checks'],route_blockers=v['route_blockers']),indent=2))+'</pre></div>')
                parts.append('<div class="direction" data-side="'+side+'"><h4>'+side+' · '+('BULLISH' if bull else 'BEARISH')+' · '+esc(v['status'])+'</h4><p>Entry blockers: '+esc('; '.join(v['blockers']) or 'NONE')+'</p>'+table(['Entry rule','Result','Actual','Required'],rows)+'</div>')
            parts.append('<h4>Active-position exit checks</h4><pre>'+esc(json.dumps(a['exit_evaluation'],indent=2))+'</pre><h4>Accepted events and fills</h4><pre>'+esc(json.dumps(a['events'],indent=2))+'</pre></details>')
        parts.append('</section>');sections.extend(parts)
    payload=json.dumps([dict(session_date=r['session_date'],status=r.get('status','REPLAYED'),market_trend=r.get('market_trend','UNAVAILABLE'),trades=[{k:t[k] for k in ['side','route_name','points','peak_positive_points','giveback_points']} for t in r.get('trades',[])]) for r in results],allow_nan=False).replace('<','\\u003c')
    opts=''.join('<option value="'+esc(r['session_date'])+'">'+esc(r['session_date'])+'</option>' for r in results)
    doc='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Normal Route · November validation</title><style>body{font:14px/1.5 system-ui;background:#11252e;color:#e0edf3;margin:20px}section{border-top:2px solid #466573;margin-top:28px}table{border-collapse:collapse;width:100%}td,th{padding:10px;border-bottom:1px solid #40545e;text-align:left;vertical-align:top}th{background:#233b48}.scroll{overflow:auto}details{background:#19313c;border:1px solid #40545e;margin:10px 0;padding:10px}summary{cursor:pointer;font-weight:bold}pre{white-space:pre-wrap;overflow-wrap:anywhere}.pass{color:#48e4a6}.fail{color:#ff96a1}select,button{padding:9px;background:#233b48;color:white;border:1px solid #78909c;margin:5px}#filters{position:sticky;top:0;background:#11252e;padding:8px;z-index:2}#totals{font-weight:bold;font-size:16px}label{display:inline-block}[hidden]{display:none!important}</style></head><body><h1>Normal Route · November validation</h1><p>RSI5/9/14/21/28 + EMA30 High/Low + WMA21(RSI9). Completed 3m candles; next 1m open simulated NIFTY fills. CE green and all five RSIs >55, WMA >50, close >EMA30 High. PE red and all five RSIs <45, WMA <50, close <EMA30 Low. All eight entry gates required. Exit requires RSI5 and RSI9 across 50, WMA across 50, and opposite EMA30 boundary together. Independent 15:30 close. No costs or option-premium fills.</p><p>Trade direction means CE/bullish or PE/bearish. Day trend is descriptive only: session close versus session open; it uses the full session and is never an entry filter. Peak + is each trade’s best unrealized directional gain; giveback = peak − final net. Summed peaks are not a realizable portfolio return.</p><p>8 November: 70 observed minutes, 14:20–15:29; only 23 complete 3m bars from 14:21 are evaluated. The incomplete leading minute is not padded. Each replay uses exactly 20 verified prior sessions.</p><div id="filters"><label>Date <select id="date"><option value="ALL">All dates</option>'''+opts+'''</select></label><label>Trade / audit direction <select id="side"><option value="ALL">Both directions</option><option value="CE">Bullish / Buy CE</option><option value="PE">Bearish / Buy PE</option></select></label><label>Entry route (trades only) <select id="route"><option value="ALL">All routes</option><option>Normal Route</option><option>WMA_bypass</option></select></label><label>Day trend <select id="trend"><option value="ALL">All day trends</option><option>BULLISH</option><option>BEARISH</option><option>FLAT</option><option>UNAVAILABLE</option></select></label><button id="expand">Expand visible candles</button><button id="collapse">Collapse candles</button><button id="reset">Reset filters</button></div><p id="coverage"></p><p id="totals"></p><h2>Daily totals · selected direction</h2><div class="scroll"><table><thead><tr><th>Date</th><th>Status</th><th>Day trend</th><th>Trades</th><th>Wins</th><th>Losses</th><th>Net points</th><th>Peak +</th><th>Giveback</th></tr></thead><tbody id="daily"></tbody></table></div>'''+''.join(sections)+'''<script id="data" type="application/json">'''+payload+'''</script><script>
const data=JSON.parse(document.getElementById('data').textContent);
const route=document.getElementById('route');const date=document.getElementById('date'),side=document.getElementById('side'),trend=document.getElementById('trend');
function aggregate(ts){return [ts.length,ts.filter(t=>t.points>0).length,ts.filter(t=>t.points<0).length,...['points','peak_positive_points','giveback_points'].map(k=>ts.reduce((s,t)=>s+t[k],0))]}
function selected(r){return (date.value==='ALL'||r.session_date===date.value)&&(trend.value==='ALL'||r.market_trend===trend.value)}
function trades(r){return r.trades.filter(t=>(side.value==='ALL'||t.side===side.value)&&(route.value==='ALL'||t.route_name===route.value))}
function apply(){const rs=data.filter(selected),ts=rs.flatMap(trades),s=aggregate(ts);
document.getElementById('totals').textContent=`Selected trades: ${s[0]} | Wins: ${s[1]} | Losses: ${s[2]} | Net: ${s[3].toFixed(2)} | Peak +: ${s[4].toFixed(2)} | Giveback: ${s[5].toFixed(2)}`;
document.getElementById('coverage').textContent=`Scope: ${data[0]?.session_date||''} to ${data.at(-1)?.session_date||''}. Selected dates: ${rs.length}; replayed: ${rs.filter(r=>r.status==='REPLAYED').length}; failed: ${rs.filter(r=>r.status==='REPLAY_FAILED').length}; non-trading: ${rs.filter(r=>r.status==='NON_TRADING_DAY').length}. Failed dates are not zero-trade validation passes.`;
const body=document.getElementById('daily');body.replaceChildren();for(const r of rs){const tr=document.createElement('tr'),a=aggregate(trades(r));for(const v of [r.session_date,r.status,r.market_trend,...a.slice(0,3),...a.slice(3).map(x=>x.toFixed(2))]){const td=document.createElement('td');td.textContent=v;tr.append(td)}body.append(tr)}
for(const el of document.querySelectorAll('section[data-date]')){const r=data.find(r=>r.session_date===el.dataset.date);el.hidden=!selected(r);el.querySelectorAll('[data-side]').forEach(x=>x.hidden=(side.value!=='ALL'&&x.dataset.side!==side.value)||(x.classList.contains('trade')&&route.value!=='ALL'&&x.dataset.route!==route.value));const st=el.querySelector('.day-stats');if(st){const a=aggregate(trades(r));st.textContent=`Selected direction: ${a[0]} trades | Net ${a[3].toFixed(2)} | Peak + ${a[4].toFixed(2)} | Giveback ${a[5].toFixed(2)}`}}}
for(const x of [date,side,trend,route])x.addEventListener('change',apply);
document.getElementById('expand').onclick=()=>document.querySelectorAll('section:not([hidden]) details.candle').forEach(x=>x.open=true);
document.getElementById('collapse').onclick=()=>document.querySelectorAll('details').forEach(x=>x.open=false);
document.getElementById('reset').onclick=()=>{date.value=side.value=trend.value=route.value='ALL';apply()};apply();
</script></body></html>'''

    if updated:
        doc=doc.replace('Normal Route · November validation','Two-route strategy · November validation')
        start=doc.index('<p>RSI5/9/14/21/28');end=doc.index('</p>',start)+4
        doc=doc[:start]+"<p>Updated research rules: CE close &gt; EMA30 High and green; PE close &lt; EMA30 Low and red. Every entry requires body &ge;70% of range, upper wick &le;15%, lower wick &le;15%. Normal Route: at least 2 of RSI5/9/14/21/28 above 55 (CE) or below 45 (PE), plus WMA21(RSI9) above/below 50. WMA_bypass: all 5 RSIs pass; WMA threshold bypassed. All indicator values must be ready. Normal Route has priority. A qualified opposite entry independently closes the held trade, then opens the opposite direction. Otherwise the all-three momentum/WMA/price exit remains. Mandatory 15:30 close, no entry then. Next-minute-open simulated NIFTY fills; no costs or option premium fills.</p>"+doc[end:]
    else:doc=doc.replace('Normal Route · November validation','Original baseline · November validation')
    return doc
