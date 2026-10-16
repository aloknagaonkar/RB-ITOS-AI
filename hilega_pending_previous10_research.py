"""Research-only batch: ten frozen sessions plus today's complete 14:55 session.

Requires hilega_pending_confirmation_research.py and the prior monthly cache
helpers in repository root. No strategy installation, orders, services or control
changes. --fetch-today performs one read-only analytics candle request.
"""
import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import unittest

POLICIES=('CURRENT','CONFIRMED_OPPOSITE_ONLY')

def signature(trades):
    out=[]
    for t in trades:
        direction=t['direction'];entry=float(t['entry_price']);exit_price=float(t['exit_price']);points=float(t['points'])
        if direction not in ('BULLISH','BEARISH') or not all(math.isfinite(v) for v in (entry,exit_price,points)):raise ValueError('INVALID_TRADE')
        if abs((exit_price-entry)*(1 if direction=='BULLISH' else -1)-points)>1e-5:raise ValueError('TRADE_POINTS_MISMATCH')
        out.append((direction,t['entry_time'],t['exit_time'],round(entry,5),round(exit_price,5),round(points,5)))
    return sorted(out,key=lambda t:t[1])

def stats(trades):
    values=[float(t['points']) for t in sorted(trades,key=lambda t:t['entry_time'])]
    equity=peak=dd=0
    for v in values:equity+=v;peak=max(peak,equity);dd=max(dd,peak-equity)
    return dict(trades=len(values),points=round(sum(values),4),winners=sum(v>0 for v in values),losers=sum(v<0 for v in values),
       flat=sum(v==0 for v in values),win_rate_percent=round(100*sum(v>0 for v in values)/len(values),2) if values else None,
       gross_winning_points=round(sum(v for v in values if v>0),4),gross_losing_points=round(-sum(v for v in values if v<0),4),
       max_closed_trade_drawdown_points=round(dd,4))

def frozen_parity(saved,current):
    issues=[]
    if signature(saved['trades'])!=signature(current['trades']):issues.append('FROZEN_TRADE_SIGNATURE_MISMATCH')
    replay={r['checkpoint']:r for r in current['audit']}
    for old in saved['audit']:
        at=old['checkpoint'];new=replay.get(at)
        if not new:issues.append('FROZEN_CHECKPOINT_MISSING:'+at);continue
        if old['owner_after']!=new['owner_after']:issues.append('FROZEN_OWNER_MISMATCH:'+at)
        if abs(float(old['nifty_close'])-float(new['nifty_close']))>1e-5:issues.append('FROZEN_PRICE_MISMATCH:'+at)
        for key in ('rsi9','ema3','wma21'):
            a=(old.get('completed_5m_indicators') or {}).get(key);b=(new.get('completed_5m_indicators') or {}).get(key)
            if a is None or b is None:
                if a!=b:issues.append('FROZEN_INDICATOR_MISSING:'+at+':'+key)
            elif abs(float(a)-float(b))>1e-5:issues.append('FROZEN_INDICATOR_MISMATCH:'+at+':'+key)
    return dict(status='PASS' if not issues else 'MISMATCH',issues=issues,compared=len(saved['audit']))

def recorded_overrides(raw,audit,day,dt):
    rows={dt(r['timestamp']).isoformat():dict(r,timestamp=dt(r['timestamp']).isoformat()) for r in raw}
    if len(rows)!=len(raw):raise ValueError('DUPLICATE_RAW_MINUTES')
    observed={};cutoffs=[]
    with audit.open() as stream:
        for line in stream:
            if not line.strip() or not line.endswith('\n'):continue
            row=json.loads(line);p=row.get('payload') or {}
            if row.get('status')!='PROCESSED':continue
            if row.get('stage')=='DIRECTIONAL_SESSION_CUTOFF' and str(p.get('cutoff_timestamp','')).startswith(day):cutoffs.append(p)
            if row.get('stage')!='DIRECTIONAL_DECISION' or p.get('strategy_id')!='HILEGA_V2_ALIGNMENT_DUAL_EXIT':continue
            at=p.get('minute_timestamp','');c=p.get('minute_ohlcv')
            if not at.startswith(day) or not c:continue
            value=dict(timestamp=dt(at).isoformat(),**{k:c[k] for k in ('open','high','low','close','volume')})
            if value['timestamp'] in observed and observed[value['timestamp']]!=value:raise ValueError('CONFLICTING_RECORDED_MINUTE:'+at)
            observed[value['timestamp']]=value
    changed=0
    for at,value in observed.items():
        if at in rows:
            changed+=any(rows[at][k]!=value[k] for k in ('open','high','low','close'))
            rows[at]=value
    if not cutoffs:raise ValueError('PROCESSED_LIVE_CUTOFF_REQUIRED')
    # Cutoff exit price is the observed 14:55 open; do not alter any OHLC range.
    prices={float(e['price']) for p in cutoffs for e in p.get('event_details',[]) if e.get('exit_reason')=='SESSION_CUTOFF_1455'}
    if len(prices)>1:raise ValueError('CONFLICTING_CUTOFF_EXIT_PRICES')
    if prices:
        at=day+'T14:55:00+05:30';price=next(iter(prices))
        if at not in rows:raise ValueError('EXACT_1455_CANDLE_MISSING')
        if not float(rows[at]['low'])<=price<=float(rows[at]['high']):raise ValueError('RECORDED_CUTOFF_OPEN_OUTSIDE_FETCHED_OHLC')
        rows[at]['open']=price
    return sorted(rows.values(),key=lambda r:r['timestamp']),dict(
        input_basis='RECORDED_LIVE_WHERE_AVAILABLE_OTHERWISE_LATER_API',recorded_minutes=len(set(rows)&set(observed)),
        substituted_ohlc_changes=changed,recorded_minute_timestamps=sorted(set(rows)&set(observed)),cutoff_payloads=cutoffs,
        limitation='Unrecorded minute inputs remain later API data. Checkpoint parity does not fully verify counterfactual entry inputs.')

def cutoff_parity(result,cutoffs):
    expected=[t for t in result['trades'] if t.get('exit_reason')=='SESSION_CUTOFF_1455'];actual=[]
    for p in cutoffs:
        events=p.get('event_details') or []
        for e in events:
            if e.get('exit_reason')=='SESSION_CUTOFF_1455':
                actual.append((e['entry_time'],round(float(e['price']),5)))
    actual=set(actual);wanted={(t['entry_time'],round(float(t['exit_price']),5)) for t in expected}
    return [] if actual==wanted else ['LIVE_CUTOFF_TRADE_MISMATCH']

class Checks(unittest.TestCase):
    def test_stats_counts_winners_and_losers(self):
        rows=[dict(entry_time=str(i),points=v) for i,v in enumerate((20,-30,15,0))]
        s=stats(rows);self.assertEqual((s['trades'],s['points'],s['winners'],s['losers'],s['flat']),(4,5,2,1,1));self.assertEqual(s['max_closed_trade_drawdown_points'],30)
    def test_signature_rejects_inconsistent_points(self):
        with self.assertRaises(ValueError):signature([dict(direction='BEARISH',entry_price=100,exit_price=90,points=-10,entry_time='a',exit_time='b')])
    def test_no_cutoff_trade_when_flat(self):self.assertEqual(cutoff_parity({'trades':[]},[{'event_details':[]}]),[])
    def test_cutoff_mismatch(self):
        self.assertTrue(cutoff_parity({'trades':[dict(exit_reason='SESSION_CUTOFF_1455',entry_time='a',exit_price=100)]},[{'event_details':[]}]))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--date',default='2026-10-16');p.add_argument('--sessions',type=int,default=10)
    p.add_argument('--research-root',type=Path,default=Path('data/research/hilega-vwap-monthly-20261015'))
    p.add_argument('--output',type=Path,default=Path('data/research/hilega-pending-previous10-plus-today-20261016'))
    p.add_argument('--today-input',type=Path,default=Path('data/research/hilega-pending-confirmation-20261016/captured-nifty-1m.json'))
    p.add_argument('--audit',type=Path,default=Path('data/live-observation/hilega-directional-v1/step-audit.jsonl'))
    p.add_argument('--fetch-today',action='store_true');p.add_argument('--test',action='store_true');a=p.parse_args()
    if a.test:
        r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks));raise SystemExit(0 if r.wasSuccessful() else 1)
    if a.sessions<1:p.error('--sessions must be positive')
    os.environ['HILEGA_PENDING_OPPOSITE_SWITCH_ENABLED']='1'
    import hilega_pending_confirmation_research as policy
    import hilega_vwap_confirmed36_research as support
    from hilega_vwap_wait_alignment_research import source_data
    from market_lab import hilega_v2_alignment_replay_v1 as engine
    if engine.RULES['version']!=policy.VERSION:raise ValueError('ENGINE_VERSION_MISMATCH')
    end=policy.dt(a.date+'T14:55:00+05:30')
    if end>policy.datetime.now(policy.IST):raise ValueError('FULL_STRATEGY_SESSION_NOT_COMPLETE')
    parent=json.loads((a.research_root/'3-month/report.json').read_text())
    if parent['strategy_version']!=policy.VERSION:raise ValueError('SOURCE_VERSION_MISMATCH')
    sessions,grouped=source_data(a.research_root,parent,support)
    days=[d for d in sessions if parent['start_date']<=d<a.date and d<=parent['end_date']][-a.sessions:]
    if len(days)!=a.sessions:raise ValueError('INSUFFICIENT_PREVIOUS_SESSIONS')
    a.output.mkdir(parents=True,exist_ok=True);coverage=[];evaluated={};provenance={}
    for day in days+[a.date]:
        row=dict(session_date=day,status='INCOMPLETE',issues=[])
        try:
            if day==a.date:
                raw,warm,hashes=policy.inputs(engine,day,a.today_input,a.fetch_today,a.output)
                raw,source=recorded_overrides(raw,a.audit,day,policy.dt)
                merged=a.output/'today-recorded-overrides.json';merged.write_text(json.dumps(dict(session_date=day,underlying='NSE_INDEX|Nifty 50',candles=raw,provenance=source),indent=2)+'\n')
                source['input_sha256']=hashlib.sha256(merged.read_bytes()).hexdigest();source['warmup_sources_sha256']=hashes
            else:
                raw=grouped[day];warm=[(d,grouped[d]) for d in sessions if d<day and grouped.get(d)][-30:]
                if len(warm)<20:raise ValueError('TWENTY_WARMUP_SESSIONS_REQUIRED')
                baseline_path=a.research_root/'replays'/(day+'.json');saved=json.loads(baseline_path.read_text())
                if saved['strategy_version']!=policy.VERSION or saved['session_date']!=day:raise ValueError('FROZEN_BASELINE_IDENTITY_MISMATCH')
                source=dict(input_basis='FROZEN_RESEARCH_CACHE',baseline_sha256=hashlib.sha256(baseline_path.read_bytes()).hexdigest(),warmup_sessions=len(warm))
            asof=policy.dt(day+'T14:55:00+05:30');raw=[r for r in raw if policy.dt(r['timestamp'])<=asof]
            result={k:policy.simulate(engine,day,raw,warm,asof,k) for k in POLICIES}
            for k,r in result.items():
                signature(r['trades']);dest=a.output/'sessions'/day/(k+'.json');dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(json.dumps(r,indent=2,default=str)+'\n')
            if day==a.date:
                parity=policy.audit_parity(a.audit,day,asof,result['CURRENT'])
                parity['issues'].extend(cutoff_parity(result['CURRENT'],source['cutoff_payloads']))
                if parity['issues']:parity['status']='MISMATCH'
            else:parity=frozen_parity(saved,result['CURRENT'])
            row.update(parity=parity,warmup_sessions=len(warm),input_basis=source['input_basis'])
            if parity['status']!='PASS':raise ValueError('BASELINE_PARITY_NOT_PASS')
            if day==a.date:
                recorded=set(source['recorded_minute_timestamps'])
                for trade in result['CONFIRMED_OPPOSITE_ONLY']['trades']:
                    check=trade.get('entry_checks') or {}
                    trade['confirmation_input_coverage']={key:check.get(key) in recorded for key in ('minute_timestamp','previous_timestamp')}
            evaluated[day]=result;provenance[day]=source;row['status']='COMPLETE'
        except Exception as exc:row['issues'].append(str(exc))
        coverage.append(row);print(json.dumps(row,default=str),flush=True)
        (a.output/'progress.json').write_text(json.dumps(coverage,indent=2,default=str)+'\n')
    periods={}
    for name,selected in (('PREVIOUS_10',days),('TODAY',[a.date]),('COMBINED',days+[a.date])):
        valid=[d for d in selected if d in evaluated];summary={}
        for k in POLICIES:summary[k]=stats([t for d in valid for t in evaluated[d][k]['trades']])
        periods[name]=dict(requested=len(selected),comparable=len(valid),status='COMPLETE' if len(valid)==len(selected) else 'INCOMPLETE',comparisons=summary,
                           change_points=round(summary[POLICIES[1]]['points']-summary[POLICIES[0]]['points'],4))
    payload=dict(model='HILEGA_PENDING_CONFIRMED_OPPOSITE_BATCH_RESEARCH_V1',status='COMPLETE' if len(evaluated)==len(days)+1 else 'INCOMPLETE',
        strategy_version=policy.VERSION,session_dates=days+[a.date],coverage=coverage,periods=periods,provenance=provenance,
        rule_changes=policy.RULE_CHANGES,observation_only=True,orders_sent=False,
        policy_runner_sha256=hashlib.sha256(Path(policy.__file__).read_bytes()).hexdigest(),replay_engine_sha256=hashlib.sha256(Path(engine.__file__).read_bytes()).hexdigest(),
        daily=[dict(session_date=d,comparisons={k:stats(v['trades']) for k,v in evaluated[d].items()}) for d in sorted(evaluated)],
        warning='Gross NIFTY points, not option P&L; costs excluded. Only parity-passing sessions enter totals; review coverage. Historical baselines are frozen research reconstructions. Today uses recorded candles where available, later API candles elsewhere: checkpoint parity does not verify all counterfactual minute inputs. Same 14:55 cutoff and exits; no live changes.')
    (a.output/'report.json').write_text(json.dumps(payload,indent=2,default=str)+'\n')
    with (a.output/'trades.csv').open('w',newline='') as h:
        fields=['session_date','policy','direction','signal_time','entry_time','entry_price','exit_time','exit_price','points','exit_reason','confirmation_input_coverage']
        writer=csv.DictWriter(h,fields,extrasaction='ignore');writer.writeheader()
        for d in sorted(evaluated):
            for k in POLICIES:
                for t in evaluated[d][k]['trades']:writer.writerow(dict(t,session_date=d,policy=k))
    lines=['# Confirmed-opposite pending policy: previous ten sessions and today','',payload['warning'],'','Status: '+payload['status'],'',
       '| Period | Coverage | Policy | Trades | Points | Winners | Losers | Win rate % | Closed-trade drawdown |','|---|---|---|---:|---:|---:|---:|---:|---:|']
    for name,pd in periods.items():
        for k,s in pd['comparisons'].items():lines.append(f"| {name} | {pd['comparable']}/{pd['requested']} | {k} | {s['trades']} | {s['points']:.2f} | {s['winners']} | {s['losers']} | {s['win_rate_percent']} | {s['max_closed_trade_drawdown_points']:.2f} |")
    lines+=['','| Date | Current trades | Current pts | Research trades | Research pts | Change |','|---|---:|---:|---:|---:|---:|']
    for row in payload['daily']:
        b=row['comparisons']['CURRENT'];n=row['comparisons']['CONFIRMED_OPPOSITE_ONLY']
        lines.append(f"| {row['session_date']} | {b['trades']} | {b['points']:.2f} | {n['trades']} | {n['points']:.2f} | {n['points']-b['points']:.2f} |")
    lines+=['','Incomplete sessions: '+json.dumps([r for r in coverage if r['status']!='COMPLETE'],default=str)]
    text='\n'.join(lines)+'\n';(a.output/'summary.md').write_text(text);print(text);print('REPORT:',a.output/'report.json')
    raise SystemExit(0 if payload['status']=='COMPLETE' else 2)

if __name__=='__main__':main()
