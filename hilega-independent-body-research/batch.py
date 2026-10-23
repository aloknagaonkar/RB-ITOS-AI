"""Resumable wider-session comparison; no live writes or orders."""
import argparse,hashlib,json
from pathlib import Path
from datetime import datetime,date,time
import run as study
from daily_reports import write_daily
core=study.core

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def signature(trades):
    return sorted((t['direction'],t['entry_time'],t['exit_time'],round(t['entry_price'],5),round(t['exit_price'],5),round(t['points'],5),t['exit_reason']) for t in trades)

def stats(trades):
    eq=peak=dd=0
    for t in sorted(trades,key=lambda t:t['exit_time']):
        eq+=t['points'];peak=max(peak,eq);dd=max(dd,peak-eq)
    return [len(trades),sum(max(0,t['points']) for t in trades),sum(min(0,t['points']) for t in trades),eq,sum(t['points']>0 for t in trades),sum(t['points']<0 for t in trades),dd]

def write(output,rows):
    done=[r for r in rows if r['status']=='COMPLETE'];names=('DEPLOYED_5M','INDEPENDENT_BODY_1M_WAIT')
    for row in done:
        daily=output/'daily-reports'/(row['session_date']+'.md')
        if not daily.exists():write_daily(output,row)
    index=['# Daily reports','', 'Coverage is supplied saved sessions only. Each report includes executions and all recorded tested5m decisions/1m waiting decisions.','']
    for row in done:
        day=row['session_date'];index.append(f'- [{day}](daily-reports/{day}.md)')
    (output/'daily-report-index.md').write_text('\n'.join(index)+'\n')
    lines=['# Wider body-breakout replay','',f'Coverage: {len(done)}/{len(rows)} selected saved sessions','Gross NIFTY points; no fills/costs. Existing route retained. No live changes.','', '| Policy | Trades | Winning points | Losing points | Net points | Winners | Losers | Drawdown |','|---|---:|---:|---:|---:|---:|---:|---:|']
    for name in names:
        s=stats([t for r in done for t in r['policies'][name]['trades']]);lines.append('| '+name+' | '+' | '.join(f'{v:.2f}' if isinstance(v,float) else str(v) for v in s)+' |')
    lines+=['','Impact = tested net points minus baseline net points. Positive means improvement, not necessarily profit.','', '| Date | Existing points | Tested points | Impact |','|---|---:|---:|---:|']
    details=['# All executed trades','', '| Date | Policy | Direction | Setup | Entry–exit IST | Route | Points | Exit reason |','|---|---|---|---|---|---|---:|---|']
    signals=['# Signal-wise comparison','', 'A dash means no executed trade from that exact setup; consult JSON audits for rejection/cancellation reasons.','', '| Date | Direction | Setup | Existing entry–exit / points | Tested entry–exit / points | Setup impact |','|---|---|---|---|---|---:|']
    for r in done:
        p=r['policies'];a,b=[sum(t['points'] for t in p[n]['trades']) for n in names]
        lines.append(f"| {r['session_date']} | {a:+.2f} | {b:+.2f} | {b-a:+.2f} |")
        for n in names:
            for t in p[n]['trades']:
                details.append(f"| {r['session_date']} | {n} | {t['direction']} | {(t.get('setup') or '')[11:16]} | {t['entry_time'][11:16]}–{t['exit_time'][11:16]} | {t.get('route','EXISTING')} | {t['points']:+.2f} | {t['exit_reason']} |")
        ids=sorted({(t['direction'],t.get('setup') or '') for n in names for t in p[n]['trades']})
        for side,setup in ids:
            cells=[];points=[]
            for n in names:
                ts=[t for t in p[n]['trades'] if t['direction']==side and (t.get('setup') or '')==setup]
                cells.append('; '.join(t['entry_time'][11:16]+'–'+t['exit_time'][11:16]+' / '+format(t['points'],'+.2f') for t in ts) or '—');points.append(sum(t['points'] for t in ts))
            signals.append(f"| {r['session_date']} | {side} | {setup[11:16]} | {cells[0]} | {cells[1]} | {points[1]-points[0]:+.2f} |")
    lines+=['','## Separate monthly totals','', '| Month | Saved sessions | Existing points | Tested points | Impact |','|---|---:|---:|---:|---:|']
    for month in sorted({r['session_date'][:7] for r in done}):
        selected=[r for r in done if r['session_date'].startswith(month)]
        totals=[sum(t['points'] for r in selected for t in r['policies'][n]['trades']) for n in names]
        lines.append(f'| {month} | {len(selected)} | {totals[0]:+.2f} | {totals[1]:+.2f} | {totals[1]-totals[0]:+.2f} |')
    values=['# Signal values and entry evidence','',
        'Times IST. Signal values are completed5m values; the 1m follow-up checks price only. No 1m RSI/EMA/WMA filters. Missing evidence is —. Same-setup matching does not imply identical execution paths. Gross NIFTY points, no costs.', '',
        '| Date | Direction | Setup available | Signal qualified | Existing entry–exit / points | Tested entry–exit / points | Route / decision | Signal RSI9 / EMA3 RSI / WMA21 | Signal strength / gap / expansion | Body % / body beyond EMA10 % / close location % | Signal price EMA10 / slope | Signal high / low / midpoint | 1m entry close / breakout level |',
        '|---|---|---|---|---|---|---|---|---|---|---|---|---|']
    fmt=lambda v:'—' if v is None else f'{v:.3f}'
    for row in done:
        policies=row['policies'];tested=policies['INDEPENDENT_BODY_1M_WAIT'];base=policies['DEPLOYED_5M']
        for t in tested['trades']:
            side=t['direction'];sign=1 if side=='BULLISH' else -1
            evidence=t.get('evidence') or {};entry=t.get('entry_evidence') or {}
            signal=t.get('qualified') or evidence.get('signal_time')
            frame=evidence.get('signal_frame')
            if frame is None and signal:
                frame=next((r['frame'] for r in tested['audit'] if r.get('action')=='FIVE_MINUTE_EVALUATION' and r['time']==signal),None)
            frame=frame or {}
            number=lambda k:frame.get(k)
            rsi,ema,wma=[number(k) for k in ('rsi9','ema3_rsi','wma21_rsi')]
            strength=sign*(wma-frame['previous_wma21_rsi']) if wma is not None and frame.get('previous_wma21_rsi') is not None else None
            gap=sign*(ema-wma) if ema is not None and wma is not None else None
            expansion=gap-sign*(frame['previous_ema3_rsi']-frame['previous_wma21_rsi']) if gap is not None and frame.get('previous_ema3_rsi') is not None and frame.get('previous_wma21_rsi') is not None else None
            slope=frame['ema10']-frame['previous_ema10'] if frame.get('ema10') is not None and frame.get('previous_ema10') is not None else None
            matches=[b for b in base['trades'] if b['direction']==side and b.get('setup')==t.get('setup')]
            old='; '.join(b['entry_time'][11:16]+'–'+b['exit_time'][11:16]+' / '+format(b['points'],'+.2f') for b in matches) or '—'
            current=t['entry_time'][11:16]+'–'+t['exit_time'][11:16]+' / '+format(t['points'],'+.2f')
            ratios=' / '.join(fmt(evidence[k]*100) if evidence.get(k) is not None else '—' for k in ('body_ratio','body_beyond_ema','close_location'))
            levels=' / '.join(fmt(evidence.get(k)) for k in ('high','low','midpoint'))
            follow=fmt((t.get('followup') or {}).get('close'))+' / '+fmt(evidence.get('high' if sign==1 else 'low'))
            values.append('| '+' | '.join([row['session_date'],side,(t.get('setup') or '')[11:16],(signal or '')[11:16],old,current,t.get('route','EXISTING'),' / '.join(fmt(v) for v in (rsi,ema,wma)),' / '.join(fmt(v) for v in (strength,gap,expansion)),ratios,fmt(frame.get('ema10'))+' / '+fmt(slope),levels,follow])+' |')
    for name,content in [('summary.md',lines),('daily-trades.md',details),('signal-comparison.md',signals),('signal-values.md',values)]:
        (output/name).write_text('\n'.join(content)+'\n')
    (output/'coverage.json').write_text(json.dumps([dict(session_date=r['session_date'],status=r['status'],issues=r.get('issues',[])) for r in rows],indent=2))

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--input-zip',type=Path,required=True);ap.add_argument('--session-input',type=Path);ap.add_argument('--month',action='append');ap.add_argument('--date',action='append');ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    if core.policy5.VERSION!='bullish-gap2-full-wma2-2.0.0-wma40-reversal':raise ValueError('POLICY_VERSION_MISMATCH')
    warm,records=core.read_inputs(a.input_zip);raws=dict(warm)
    if a.session_input:
        extra=json.loads(a.session_input.read_text());day=extra['session_date']
        if day in raws and raws[day]!=extra['candles']:raise ValueError('CONFLICTING_SESSION_INPUT')
        raws[day]=extra['candles']
    months=a.month or ['2026-10']
    if not a.date:
        missing=[m for m in months if not any(d.startswith(m+'-') for d in raws)]
        if missing:raise ValueError('NO_SAVED_INPUTS_FOR_MONTH:'+','.join(missing))
    days=sorted(set(a.date or [d for d in raws if any(d.startswith(m+'-') for m in months)]))
    if not days:raise ValueError('NO_SAVED_SESSIONS')
    a.output.mkdir(parents=True,exist_ok=True)
    sources={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for root in (Path(core.policy5.__file__).parent,Path(__file__).parent) for p in root.rglob('*.py')}
    from market_lab import hilega_combined_replay_v1 as independent
    c=core.legacy5.ExitFirstCanonical();tracker=core.policy5.PriceFrames();index=count=0;rows=[]
    for day in days:
        path=a.output/(day+'.json')
        try:
            raw=raws[day];until=datetime.fromisoformat(day+'T14:55:00+05:30')
            rec=[r for r in records if str((r.get('payload') or {}).get('decision_timestamp') or r.get('event_time','')).startswith(day)]
            key=digest(dict(raw=raw,warm=[(d,r) for d,r in warm if d<day],records=rec,sources=sources))
            if path.exists():
                old=json.loads(path.read_text())
                if old.get('fingerprint')==key and old.get('payload_sha256')==digest(old['policies']) and old.get('status')=='COMPLETE':
                    rows.append(old);write(a.output,rows);print(day+': CACHED_COMPLETE',flush=True);continue
            print(day+': independent baseline replay...',flush=True)
            base=independent.replay(day,raw,[(d,r) for d,r in warm if d<day])
            base=json.loads(json.dumps(base,default=str))
            for trade in base['trades']:
                trade.setdefault('setup',trade.get('signal_time'))
            if rec:
                # Recorded proof needs timing-core audit schema; only recorded days pay this extra cost.
                check=core.run(core.policy5,core.legacy5,warm,raw,day,5,until)
                proof=core.parity(check,rec,until)
                if proof['status']!='PASS' or signature(check['trades'])!=signature(base['trades']):raise ValueError('RECORDED_CONTROL_PARITY_FAILED')
            else:proof=dict(status='PASS',basis='INSTALLED_INDEPENDENT_REPLAY')
            while index<len(warm) and warm[index][0]<day:
                d,rs=warm[index]
                for bar in core.aggregate(rs,d,5,datetime.combine(date.fromisoformat(d),time(15,30),core.IST)):
                    c.on_bar(bar);tracker.seed(bar)
                count+=1;index+=1
            print(day+': mixed5m/1m replay...',flush=True)
            tested=study.replay(warm,raw,day,prepared=(c,tracker,count))
            policies=dict(DEPLOYED_5M=base,INDEPENDENT_BODY_1M_WAIT=tested)
            row=dict(session_date=day,status='COMPLETE',control_parity=proof,fingerprint=key,policies=policies,payload_sha256=digest(policies))
            tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(row,indent=2,default=str));tmp.replace(path)
            print(json.dumps(dict(session_date=day,status='COMPLETE',points={n:round(sum(t['points'] for t in v['trades']),2) for n,v in policies.items()})),flush=True)
        except Exception as exc:
            row=dict(session_date=day,status='INCOMPLETE',issues=[type(exc).__name__+': '+str(exc)]);print(json.dumps(row),flush=True)
        rows.append(row);write(a.output,rows)
    print((a.output/'summary.md').read_text())
    if any(r['status']!='COMPLETE' for r in rows):raise SystemExit('INCOMPLETE_COVERAGE')
if __name__=='__main__':main()
