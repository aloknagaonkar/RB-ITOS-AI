"""Resumable wider-session comparison; no live writes or orders."""
import argparse,hashlib,json
from pathlib import Path
from datetime import datetime,date,time
import run as study
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
    done=[r for r in rows if r['status']=='COMPLETE'];names=('DEPLOYED_5M','BODY50_1M_WAIT')
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
    for name,content in [('summary.md',lines),('daily-trades.md',details),('signal-comparison.md',signals)]:
        (output/name).write_text('\n'.join(content)+'\n')
    (output/'coverage.json').write_text(json.dumps([dict(session_date=r['session_date'],status=r['status'],issues=r.get('issues',[])) for r in rows],indent=2))

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--input-zip',type=Path,required=True);ap.add_argument('--session-input',type=Path);ap.add_argument('--month',default='2026-10');ap.add_argument('--date',action='append');ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    if core.policy5.VERSION!='bullish-gap2-full-wma2-2.0.0-wma40-reversal':raise ValueError('POLICY_VERSION_MISMATCH')
    warm,records=core.read_inputs(a.input_zip);raws=dict(warm)
    if a.session_input:
        extra=json.loads(a.session_input.read_text());day=extra['session_date']
        if day in raws and raws[day]!=extra['candles']:raise ValueError('CONFLICTING_SESSION_INPUT')
        raws[day]=extra['candles']
    days=sorted(set(a.date or [d for d in raws if d.startswith(a.month+'-')]))
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
            policies=dict(DEPLOYED_5M=base,BODY50_1M_WAIT=tested)
            row=dict(session_date=day,status='COMPLETE',control_parity=proof,fingerprint=key,policies=policies,payload_sha256=digest(policies))
            tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(row,indent=2,default=str));tmp.replace(path)
            print(json.dumps(dict(session_date=day,status='COMPLETE',points={n:round(sum(t['points'] for t in v['trades']),2) for n,v in policies.items()})),flush=True)
        except Exception as exc:
            row=dict(session_date=day,status='INCOMPLETE',issues=[type(exc).__name__+': '+str(exc)]);print(json.dumps(row),flush=True)
        rows.append(row);write(a.output,rows)
    print((a.output/'summary.md').read_text())
    if any(r['status']!='COMPLETE' for r in rows):raise SystemExit('INCOMPLETE_COVERAGE')
if __name__=='__main__':main()
