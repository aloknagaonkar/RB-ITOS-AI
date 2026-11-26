#!/usr/bin/env python3
"""Render blocked-entry diagnostics from an existing 14-run research report.
Offline: no broker calls, replay, service changes or live file edits.
"""
import argparse,csv,html,json
from pathlib import Path

def records(day,policy,base,filtered):
    by_time={a['decision_time']:a for a in filtered['audit']}
    entries={(t['side'],t['entry_time']):t for t in filtered['trades']}
    comparison=[];candidates=[]
    for t in base['trades']:
        side=t['side'];a=by_time.get(t['entry_time'],{})
        ev=(a.get('entry_evaluation') or {}).get(side,{})
        strength=ev.get('moderate_entry_strength') or {}
        failed=[k for k,v in (strength.get('checks') or {}).items() if v is False]
        matching=entries.get((side,t['entry_time']))
        blockers=ev.get('blockers') or []
        if matching:status='SAME_ENTRY_RETAINED'
        elif a.get('owner_before')==side:status='ALREADY_ACTIVE_SAME_SIDE'
        elif failed and 'SESSION_CLOSED' not in blockers:status='STRENGTH_BLOCKED_BASELINE_ENTRY'
        else:status='OTHER_GATE_OR_CHANGED_SEQUENCE'
        later=next((x for x in sorted(filtered['trades'],key=lambda x:x['entry_time'])
                    if x['side']==side and t['entry_time']<x['entry_time']<t['exit_time']),None) if not matching else None
        frame=a.get('frame') or {}
        row=dict(day=day,policy=policy,side=side,route=t['route_name'],setup_start=t['entry_candle_start'][11:16],
                 decision_candle_start=str(frame.get('start',''))[11:16],entry=t['entry_time'][11:16],exit=t['exit_time'][11:16],
                 baseline_net=t['points'],baseline_peak=t['peak_positive_points'],baseline_outcome='WIN' if t['points']>0 else 'LOSS' if t['points']<0 else 'BREAKEVEN',
                 status=status,body_pct=strength.get('body_pct'),upper_wick_pct=strength.get('upper_wick_pct'),lower_wick_pct=strength.get('lower_wick_pct'),
                 failed_checks='; '.join(failed),blockers='; '.join(blockers),owner_before=a.get('owner_before'),owner_after=a.get('owner_after'),
                 candle_open=frame.get('open'),candle_high=frame.get('high'),candle_low=frame.get('low'),candle_close=frame.get('close'),
                 filtered_same_entry_net=matching['points'] if matching else None,
                 later_same_side_entry=later['entry_time'][11:16] if later else '',later_same_side_net=later['points'] if later else None)
        comparison.append(row)
    for a in filtered['audit']:
        for side,ev in a.get('entry_evaluation',{}).items():
            s=ev.get('moderate_entry_strength') or {};failed=[k for k,v in s.get('checks',{}).items() if v is False]
            if (not ev.get('route_before_entry_strength') or not failed or a.get('owner_before')==side
                    or 'SESSION_CLOSED' in (ev.get('blockers') or [])):continue
            candidates.append(dict(day=day,policy=policy,side=side,decision=a['decision_time'][11:16],
                candle_start=a['frame']['start'][11:16],body_pct=s.get('body_pct'),upper_wick_pct=s.get('upper_wick_pct'),lower_wick_pct=s.get('lower_wick_pct'),
                failed_checks='; '.join(failed),blockers='; '.join(ev.get('blockers') or []),owner_before=a.get('owner_before')))
    return comparison,candidates

def number(v):return '—' if v is None else f'{float(v):.2f}'
def escaped(v):return html.escape(str(v))
def render(comparison,candidates):
    payload=json.dumps(dict(comparison=comparison,candidates=candidates),allow_nan=False).replace('<','\\u003c')
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Research blocked-entry audit</title><style>body{font:14px/1.5 system-ui;background:#10232d;color:#e2edf3;margin:24px}h1,h2{color:#85e3b5}select,button{background:#203b49;color:white;padding:9px;margin:5px;border:1px solid #567080}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;white-space:nowrap}td,th{padding:10px;border-bottom:1px solid #3d5765;text-align:left}th{background:#203b49}.note{background:#203b49;padding:15px;border-left:3px solid #dfbd74}details{white-space:normal;min-width:260px}pre{white-space:pre-wrap}.pos{color:#85e3b5}.neg{color:#ff9ba3}@media print{body{background:white;color:black}.scroll{overflow:visible}select,button{display:none}}</style><h1>Blocked entry audit · moderate filter on every entry</h1><p class="note">The original trade ledger lists accepted trades only. This report compares each baseline entry with the filtered run and reads its actual candle checks. STRENGTH_BLOCKED_BASELINE_ENTRY means a baseline entry is absent at that boundary, the filtered run was not already holding the same direction, and its entry strength check failed. It does not mean the whole baseline profit/loss is an achievable saving: later entries, exits and ownership can change.</p><p>Filter: body ≥50% of range, either wick ≤body, CE upper wick / PE lower wick ≤20%. Numerical percentages below come from the recorded entry candle audit. No replay, broker requests or live changes.</p><div><label>Date <select id="day"><option value="">All dates</option></select></label><label>Configuration <select id="policy"><option value="">All seven</option></select></label><label>Show <select id="status"><option value="STRENGTH_BLOCKED_BASELINE_ENTRY">Baseline entries rejected by strength</option><option value="ABSENT">All absent baseline entries</option><option value="">Every baseline entry</option><option value="SAME_ENTRY_RETAINED">Retained entries</option></select></label><button onclick="window.print()">Print / Save PDF</button></div><h2>Baseline entry comparison</h2><p id="count"></p><div class="scroll"><table><thead><tr><th>Date</th><th>Configuration</th><th>Side / route</th><th>Decision candle</th><th>Entry boundary</th><th>Baseline exit</th><th>Baseline result</th><th>Body %</th><th>Upper wick %</th><th>Lower wick %</th><th>Status / failed checks</th><th>Actual blockers / details</th><th>Later same-side entry</th></tr></thead><tbody id="rows"></tbody></table></div><h2>All strength-failing candidate candles</h2><p>These passed the original RSI/EMA30/route entry checks before strength filtering and were not already active in the same direction. Other zone/confirmation gates may independently block them, so this count is not the number of prevented baseline trades.</p><div class="scroll"><table><tr><th>Date</th><th>Configuration</th><th>Side</th><th>Candle</th><th>Decision</th><th>Body %</th><th>Upper %</th><th>Lower %</th><th>Failed strength checks</th><th>All recorded blockers</th></tr><tbody id="candidates"></tbody></table></div><p>Times IST. Baseline outcomes are hindsight context, not live entry knowledge. This report uses completed research data; it does not change live strategy behaviour.</p><script>const D=PAYLOAD;const $=id=>document.getElementById(id),esc=v=>String(v??'—').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;'),f=v=>v==null?'—':Number(v).toFixed(2),cell=v=>'<td>'+v+'</td>';function options(id,a){a.forEach(v=>{const o=document.createElement('option');o.value=v;o.textContent=v;$(id).append(o)})}options('day',[...new Set(D.comparison.map(r=>r.day))]);options('policy',[...new Set(D.comparison.map(r=>r.policy))]);function common(r){return (!$('day').value||r.day===$('day').value)&&(!$('policy').value||r.policy===$('policy').value)}function render(){const a=D.comparison.filter(r=>common(r)&&(!$('status').value||($('status').value==='ABSENT'?r.status!=='SAME_ENTRY_RETAINED':r.status===$('status').value)));$('count').textContent=a.length+' baseline entries shown. The original accepted trade is absent from the filtered ledger when rejected.';$('rows').innerHTML=a.map(r=>'<tr>'+[r.day,r.policy,r.side+' / '+r.route,r.decision_candle_start,r.entry,r.exit,f(r.baseline_net)+' · '+r.baseline_outcome,f(r.body_pct),f(r.upper_wick_pct),f(r.lower_wick_pct),r.status+' · '+r.failed_checks].map(v=>cell(esc(v))).join('')+cell('<details><summary>Inspect</summary><p>'+esc(r.blockers)+'</p><pre>'+esc(JSON.stringify(r,null,2))+'</pre></details>')+cell(esc(r.later_same_side_entry?r.later_same_side_entry+' · net '+f(r.later_same_side_net):'None before baseline exit'))+'</tr>').join('');$('candidates').innerHTML=D.candidates.filter(common).map(r=>'<tr>'+[r.day,r.policy,r.side,r.candle_start,r.decision,f(r.body_pct),f(r.upper_wick_pct),f(r.lower_wick_pct),r.failed_checks,r.blockers].map(v=>cell(esc(v))).join('')+'</tr>').join('')}['day','policy','status'].forEach(id=>$(id).addEventListener('change',render));render();</script></html>'''.replace('PAYLOAD',payload)

def self_test():
    t=dict(side='PE',entry_time='2026-11-06T09:18:00+05:30',exit_time='2026-11-06T09:33:00+05:30',entry_candle_start='2026-11-06T09:15:00+05:30',route_name='Normal Route',points=-44.5,peak_positive_points=26.1)
    a=dict(decision_time=t['entry_time'],owner_before=None,owner_after=None,frame=dict(start=t['entry_candle_start'],open=100,high=110,low=90,close=95),entry_evaluation={'PE':dict(route_before_entry_strength='Normal Route',moderate_entry_strength=dict(checks=dict(body_at_least_50pct=False),body_pct=25,upper_wick_pct=50,lower_wick_pct=25),blockers=['body_at_least_50pct'])})
    base=dict(trades=[t]);filtered=dict(trades=[],audit=[a]);c,k=records('2026-11-06','CURRENT_STRATEGY',base,filtered)
    assert c[0]['status']=='STRENGTH_BLOCKED_BASELINE_ENTRY' and len(k)==1
    a['owner_before']='PE';c,k=records('2026-11-06','CURRENT_STRATEGY',base,filtered)
    assert c[0]['status']=='ALREADY_ACTIVE_SAME_SIDE' and not k
    filtered['trades']=[t];c,k=records('2026-11-06','CURRENT_STRATEGY',base,filtered)
    assert c[0]['status']=='SAME_ENTRY_RETAINED'
    print('PASS: actual strength rejection, same-side ownership and retained baseline entries are distinguished.')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--report',type=Path);p.add_argument('--self-test',action='store_true');a=p.parse_args()
    if a.self_test:self_test();return
    if not a.report:p.error('--report is required')
    root=a.report.resolve()
    if not root.is_dir():raise SystemExit('REPORT_DIRECTORY_NOT_FOUND')
    paths=sorted((root/'days').glob('*/comparison.json'))
    if not paths:raise SystemExit('NO_COMPLETED_DAILY_COMPARISONS_FOUND')
    comparison=[];candidates=[]
    for path in paths:
        body=json.loads(path.read_text());results=body['results'];day=body['metadata']['day']
        for key,base in results.items():
            if not key.endswith('__BASE'):continue
            policy=key[:-6];other=results.get(policy+'__MODERATE_EVERY_ENTRY')
            if other is None:raise ValueError('FILTERED_PAIR_MISSING:'+policy)
            c,k=records(day,policy,base,other);comparison.extend(c);candidates.extend(k)
    if not comparison:raise SystemExit('NO_BASELINE_TRADES_FOUND')
    for filename,data in [('baseline-entry-comparison.csv',comparison),('strength-failing-candidates.csv',candidates)]:
        with (root/filename).open('w',newline='') as f:
            if data:
                w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
    (root/'blocked-entries.html').write_text(render(comparison,candidates))
    blocked=[r for r in comparison if r['status']=='STRENGTH_BLOCKED_BASELINE_ENTRY']
    print('BASELINE ENTRIES REJECTED BY STRENGTH')
    print('Date | Configuration | Side | Entry | Baseline net | Body % | Upper wick % | Lower wick % | Failed checks')
    for r in blocked:
        print(f"{r['day']} | {r['policy']} | {r['side']} | {r['entry']} | {r['baseline_net']:+.2f} | {number(r['body_pct'])} | {number(r['upper_wick_pct'])} | {number(r['lower_wick_pct'])} | {r['failed_checks']}")
    print('\nBlocked baseline entry records:',len(blocked))
    print('HTML:',root/'blocked-entries.html')
    print('CSV:',root/'baseline-entry-comparison.csv')
    print('Offline report only. No strategy rerun or live changes.')

if __name__=='__main__':main()
