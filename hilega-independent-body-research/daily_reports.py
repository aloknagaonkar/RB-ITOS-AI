"""Human-readable per-day execution and every recorded tested decision."""
import json

def safe(value):
    return str(value).replace('|','/').replace('\n',' ')

def write_daily(output,row):
    folder=output/'daily-reports';folder.mkdir(exist_ok=True)
    day=row['session_date'];policies=row['policies']
    lines=['# '+day+' — daily strategy comparison','',
        'Times IST; gross NIFTY points; no costs. Original existing entry route retained. Informational setups are not confirmed entries. A failed check does not prove a candidate was discarded; inspect the waiting action.','',
        '| Policy | Direction | Setup | Qualified | Entry / price | Exit / price | NIFTY points | Route | Exit reason |',
        '|---|---|---|---|---|---|---:|---|---|']
    for name,result in policies.items():
        for t in result['trades']:
            values=[name,t['direction'],(t.get('setup') or t.get('signal_time') or '')[11:16],(t.get('qualified') or '')[11:16],t['entry_time'][11:16]+' / '+format(t['entry_price'],'.2f'),t['exit_time'][11:16]+' / '+format(t['exit_price'],'.2f'),format(t['points'],'+.2f'),t.get('route','EXISTING'),t['exit_reason']]
            lines.append('| '+' | '.join(safe(v) for v in values)+' |')
    lines+=['','## Every recorded tested signal and evaluation','',
        'Includes every5m evaluation and every1m waiting decision. Setup, entry, exit and opposite-monitor details are included when recorded. Indicator values below are5m only. A1m waiting row intentionally has no new indicators.', '',
        '| Time | Stage | Direction | Close | RSI9 / EMA3 RSI / WMA21 | Price EMA10 / previous | Body signal high / low / midpoint | Setup / entry / exit / checks / reasons |',
        '|---|---|---|---:|---|---|---|---|']
    for a in policies['INDEPENDENT_BODY_1M_WAIT']['audit']:
        f=a.get('frame') or {};s=a.get('signal') or {}
        indicators=' / '.join(f'{f[k]:.3f}' if f.get(k) is not None else '—' for k in ('rsi9','ema3_rsi','wma21_rsi'))
        ema=' / '.join(f'{f[k]:.3f}' if f.get(k) is not None else '—' for k in ('ema10','previous_ema10'))
        levels=' / '.join(f'{s[k]:.3f}' if s.get(k) is not None else '—' for k in ('high','low','midpoint'))
        evidence={k:a[k] for k in ('setups','entries','exits','checks','policy_events','exit_validation','opposite_confirmation') if a.get(k)}
        if s:evidence['waiting_signal']=s
        if a.get('action','').startswith('EXISTING_'):evidence['support_observation']=a
        values=[a['time'][11:16],a['action'],s.get('direction','—'),a.get('close',f.get('close','—')),indicators,ema,levels,json.dumps(evidence,default=str,separators=(',',':'))]
        lines.append('| '+' | '.join(safe(v) for v in values)+' |')
    lines+=['','## Existing baseline — recorded replay audit','',
        'Full existing-baseline evaluation records are retained below; schemas can differ from the tested audit. These are research replay records, not a claim of historical live execution.','']
    for a in policies['DEPLOYED_5M'].get('audit',[]):
        lines+=['```json',json.dumps(a,default=str,separators=(',',':')),'```']
    (folder/(day+'.md')).write_text('\n'.join(lines)+'\n')
