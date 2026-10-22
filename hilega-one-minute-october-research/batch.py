"""Resumable October5m/1m research; no live changes, orders or service operations."""
import argparse
from copy import deepcopy
from datetime import datetime,date,time
import hashlib
import json
from pathlib import Path
import tempfile
import one_day as study
from prepared_core import run_prepared
core=study.core

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def signature(result):
    return sorted((t['direction'],t['entry_time'],t['exit_time'],round(t['entry_price'],5),round(t['exit_price'],5),round(t['points'],5),t['exit_reason'],t.get('setup'),t.get('qualified')) for t in result['trades'])

class WarmPool:
    def __init__(self,policy,legacy,warm,interval):
        self.c=legacy.ExitFirstCanonical();self.tracker=policy.PriceFrames()
        self.warm=warm;self.interval=interval;self.index=0;self.count=0;self.last_day=None
    def prepare(self,day):
        if self.last_day and day<self.last_day:raise ValueError('WARMUP_DAYS_MUST_BE_SORTED')
        while self.index<len(self.warm) and self.warm[self.index][0]<day:
            d,rows=self.warm[self.index]
            end=datetime.combine(date.fromisoformat(d),time(15,30),core.IST)
            for bar in core.aggregate(rows,d,self.interval,end):
                self.c.on_bar(bar);self.tracker.seed(bar)
            self.count+=1;self.index+=1
        self.last_day=day
        # run_prepared deep-copies before a session can mutate any state.
        return self.c,self.tracker,self.count

def stats(trades):
    equity=peak=drawdown=0
    for t in sorted(trades,key=lambda t:t['exit_time']):
        equity+=t['points'];peak=max(peak,equity);drawdown=max(drawdown,peak-equity)
    return dict(trades=len(trades),winning_points=sum(max(t['points'],0) for t in trades),losing_points=sum(min(t['points'],0) for t in trades),net_points=equity,winners=sum(t['points']>0 for t in trades),losers=sum(t['points']<0 for t in trades),drawdown=drawdown)

def write_summary(output,rows):
    done=[r for r in rows if r['status']=='COMPLETE']
    lines=['# October5m versus1m','',f'Completed: {len(done)}/{len(rows)} selected sessions',
        'Historical control parity is against installed independent5m replay. Recorded-live parity is additionally required where same-day records exist.',
        'Gross NIFTY points; no option fills/costs. Numeric periods retain counts at each cadence. No live changes.','',
        '| Policy | Trades | Winning points | Losing points | Net points | Winners | Losers | Drawdown |','|---|---:|---:|---:|---:|---:|---:|---:|']
    for name in ('DEPLOYED_5M','RESEARCH_1M'):
        st=stats([t for row in done for t in row['policies'][name]['trades']])
        lines.append(f"| {name} | {st['trades']} | {st['winning_points']:+.2f} | {st['losing_points']:+.2f} | {st['net_points']:+.2f} | {st['winners']} | {st['losers']} | {st['drawdown']:.2f} |")
    lines+=['','| Date |5m points |1m points | Change |','|---|---:|---:|---:|']
    trades=['# Daily trade details','', '| Date | Policy | Direction | Setup | Qualified | Entry–exit IST | NIFTY points | Exit reason |','|---|---|---|---|---|---|---:|---|']
    hm=lambda v:v[11:16] if v else '—'
    for r in done:
        p=r['policies'];a=stats(p['DEPLOYED_5M']['trades'])['net_points'];b=stats(p['RESEARCH_1M']['trades'])['net_points']
        lines.append(f"| {r['session_date']} | {a:+.2f} | {b:+.2f} | {b-a:+.2f} |")
        for name,result in p.items():
            for t in result['trades']:
                trades.append(f"| {r['session_date']} | {name} | {t['direction']} | {hm(t.get('setup'))} | {hm(t.get('qualified'))} | {hm(t['entry_time'])}–{hm(t['exit_time'])} | {t['points']:+.2f} | {t['exit_reason']} |")
    (output/'summary.md').write_text('\n'.join(lines)+'\n')
    (output/'daily-trade-comparison.md').write_text('\n'.join(trades)+'\n')
    (output/'coverage.json').write_text(json.dumps([dict(session_date=r['session_date'],status=r['status'],issues=r.get('issues')) for r in rows],indent=2))

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input-zip',type=Path,required=True)
    ap.add_argument('--session-input',type=Path)
    ap.add_argument('--month',default='2026-10')
    ap.add_argument('--date',action='append')
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    if core.policy5.VERSION!='bullish-gap2-full-wma2-2.0.0-wma40-reversal':raise ValueError('DEPLOYED_VERSION_MISMATCH')
    from market_lab import hilega_combined_replay_v1 as replay
    warm,records=core.read_inputs(args.input_zip);raws=dict(warm)
    if args.session_input:
        data=json.loads(args.session_input.read_text());d=data['session_date']
        if d in raws and raws[d]!=data['candles']:raise ValueError('CONFLICTING_SESSION_INPUT:'+d)
        raws[d]=data['candles']
    days=sorted(set(args.date or [d for d in raws if d.startswith(args.month+'-')]))
    if not days:raise ValueError('NO_SELECTED_SESSIONS')
    args.output.mkdir(parents=True,exist_ok=True)
    source_root=Path(core.policy5.__file__).parent
    sources={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(source_root.rglob('*.py'))}
    sources.update({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')})
    rows=[];verified=False
    with tempfile.TemporaryDirectory(prefix='hilega-oct1m-') as directory:
        p1,l1=study.isolated_one(Path(directory))
        pools={5:WarmPool(core.policy5,core.legacy5,warm,5),1:WarmPool(p1,l1,warm,1)}
        for day in days:
            path=args.output/(day+'.json')
            try:
                raw=raws[day];until=datetime.fromisoformat(day+'T14:55:00+05:30')
                saved_records=[r for r in records if str((r.get('payload') or {}).get('decision_timestamp') or r.get('event_time','')).startswith(day)]
                key=digest(dict(day=day,raw=raw,warm=[(d,r) for d,r in warm if d<day],sources=sources,records=saved_records))
                if path.exists():
                    saved=json.loads(path.read_text())
                    if saved.get('status')=='COMPLETE' and saved.get('fingerprint')==key and saved.get('payload_sha256')==digest(saved['policies']):
                        rows.append(saved);print(json.dumps(dict(session_date=day,status='CACHED_COMPLETE')),flush=True);write_summary(args.output,rows);continue
                print(day+': preparing5m warmup...',flush=True)
                five=run_prepared(core.policy5,core.legacy5,pools[5].prepare(day),raw,day,5,until)
                print(day+': validating independent5m parity...',flush=True)
                independent=replay.replay(day,raw,[(d,r) for d,r in warm if d<day])
                # Independent replay has no research setup/qualified fields in its signature.
                basic=lambda result:sorted(t[:7] for t in signature(result))
                if basic(five)!=basic(independent):raise ValueError('HISTORICAL_CONTROL_PARITY_FAILED')
                liveproof=core.parity(five,saved_records,until) if saved_records else None
                if liveproof and liveproof['status']!='PASS':raise ValueError('RECORDED_LIVE_PARITY_FAILED:'+json.dumps(liveproof['issues']))
                print(day+': preparing1m warmup (first date is the slowest)...',flush=True)
                one=run_prepared(p1,l1,pools[1].prepare(day),raw,day,1,until)
                if not verified:
                    print(day+': one-time prepared-runner equivalence check...',flush=True)
                    slow=core.run(p1,l1,warm,raw,day,1,until)
                    if digest(one)!=digest(slow):raise ValueError('PREPARED_1M_RUNNER_PARITY_FAILED')
                    verified=True
                policies={'DEPLOYED_5M':five,'RESEARCH_1M':one}
                if any(v['open_trade'] for v in policies.values()):raise ValueError('UNRESOLVED_POSITION')
                row=dict(session_date=day,status='COMPLETE',baseline_parity='PASS',recorded_live_parity=liveproof,fingerprint=key,policies=policies,payload_sha256=digest(policies))
                temp=path.with_suffix('.tmp');temp.write_text(json.dumps(row,indent=2));temp.replace(path)
                print(json.dumps(dict(session_date=day,status='COMPLETE',baseline_parity='PASS',points={n:round(stats(v['trades'])['net_points'],2) for n,v in policies.items()})),flush=True)
            except Exception as exc:
                row=dict(session_date=day,status='INCOMPLETE',issues=[type(exc).__name__+': '+str(exc)])
                print(json.dumps(row),flush=True)
            rows.append(row);write_summary(args.output,rows)
    print((args.output/'summary.md').read_text())
    if any(r['status']!='COMPLETE' for r in rows):raise SystemExit('INCOMPLETE_COVERAGE: inspect coverage.json')

if __name__=='__main__':main()
