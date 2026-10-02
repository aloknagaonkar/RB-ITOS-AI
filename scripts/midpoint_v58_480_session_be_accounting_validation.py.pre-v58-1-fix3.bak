#!/usr/bin/env python3
from __future__ import annotations

import csv, importlib.util, json, statistics, tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from market_lab.midpoint_strategy.live_shadow_v1 import MidpointLiveShadowCoordinatorV1

V55 = Path('scripts/midpoint_v55_boundary_selection_replay.py')
V52 = Path('scripts/midpoint_mature_boundary_robustness_v52_1.py')
CANON = Path('scripts/midpoint_vwap_60_session_setup_family_validation_v1_1.py')
OUTDIR = Path('data/historical-evidence/hilega-pcr-oi-support-research-v1/midpoint-v58-480-session-be-accounting')
TRADE_CSV = OUTDIR / 'trade-accounting-v58.csv'
FAMILY_CSV = OUTDIR / 'family-summary-v58.csv'
CLASSIFIER_CSV = OUTDIR / 'classifier-summary-v58.csv'
REPORT_JSON = OUTDIR / 'report-v58.json'
SUMMARY_TXT = OUTDIR / 'summary-v58.txt'

EXPECTED_OWNERSHIP = {
    'B1_2024-08-16_to_2025-02-05': {'E': 51, 'B': 30, 'OTHER_FRESH_A': 101},
    'B2_2025-02-06_to_2025-07-16': {'E': 61, 'B': 41, 'OTHER_FRESH_A': 70},
    'B3_2025-07-17_to_2025-12-11': {'E': 56, 'B': 39, 'OTHER_FRESH_A': 82},
    'B4_2025-12-12_to_2026-09-08': {'E': 103, 'B': 78, 'OTHER_FRESH_A': 148},
}
REENTRY_EVENTS = {'POST_CAP20_REENTRY_TRIGGERED','POST_RESCUE_REENTRY_TRIGGERED','REENTRY_COUNT_1'}

class DummySources: pass

def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def dt(ts): return datetime.fromisoformat(ts)

def candle(ts,row):
    return SimpleNamespace(timestamp=dt(ts), open=float(row.get('open',row['close'])), high=float(row.get('high',row['close'])), low=float(row.get('low',row['close'])), close=float(row['close']), volume=float(row.get('volume',0) or 0))

def dpoints(direction,a,b): return b-a if direction=='BULLISH' else a-b

def fav(direction,entry,row): return dpoints(direction,entry,float(row['high'] if direction=='BULLISH' else row['low']))

def adv(direction,entry,row): return dpoints(direction,entry,float(row['low'] if direction=='BULLISH' else row['high']))

def first(seg, types):
    types = {types} if isinstance(types,str) else set(types)
    return next((r for r in seg if r.get('event_type') in types), None)

def replay(day,u,fut):
    with tempfile.TemporaryDirectory(prefix='v58-') as td:
        ap=Path(td)/'audit.jsonl'
        c=MidpointLiveShadowCoordinatorV1(market_sources=DummySources(), audit_path=ap)
        c._reset_session(dt(day+'T09:15:00+05:30').date())
        ub={dt(ts):candle(ts,r) for ts,r in u.items()}
        for ts_s in sorted(set(u).intersection(fut), key=dt):
            ts=dt(ts_s); fr=fut[ts_s]
            c._process_minute(ts=ts, underlying=ub[ts], futures_close=float(fr['close']), futures_vwap=float(fr['vwap']), underlying_by_ts=ub)
        return [json.loads(x) for x in ap.read_text().splitlines() if x.strip()] if ap.exists() else []

def bars(u,start,end=None):
    s=dt(start); e=dt(end) if end else None
    return [(ts,u[ts]) for ts in sorted(u,key=dt) if dt(ts)>=s and (e is None or dt(ts)<=e)]

def summarize_exc(direction,entry,bs):
    if not bs: return None,None
    return max(fav(direction,entry,r) for _,r in bs), min(adv(direction,entry,r) for _,r in bs)

def reconstruct(block,day,audit,u):
    entries=[(i,r) for i,r in enumerate(audit) if r.get('event_type') in ('B_ENTRY','E_ENTRY')]
    out=[]
    for seq,(idx,en) in enumerate(entries,1):
        next_idx=entries[seq][0] if seq<len(entries) else len(audit)
        seg=audit[idx:next_idx]
        family=en.get('family'); direction=en.get('direction'); ets=en['event_timestamp']; ep=float(en['underlying_price'])
        plus20=first(seg,'PLUS20_PROOF'); cls=first(seg,'RUNNER_CLASSIFICATION'); cls_u=first(seg,'RUNNER_CLASSIFICATION_UNAVAILABLE')
        strengthen=first(seg,'RUNNER_STRENGTHENING'); degraded=first(seg,'DEGRADED_STARTED')
        rescue=first(seg,{'CAP20_RESCUE_TRIGGERED','CAP20_SHADOW_EXIT'})
        reentry=first(seg,REENTRY_EVENTS); richer=first(seg,{'POST_CAP20_REENTRY_TRIGGERED','POST_RESCUE_REENTRY_TRIGGERED'})
        if richer is not None: reentry=richer
        term=first(seg,'STRUCTURAL_TERMINAL')
        endts=term['event_timestamp'] if term else max(u,key=dt)
        mfe,mae=summarize_exc(direction,ep,bars(u,ets,endts))
        baseline=dpoints(direction,ep,float(term['underlying_price'])) if term and term.get('underlying_price') is not None else None
        caponly=baseline
        if rescue and rescue.get('underlying_price') is not None: caponly=dpoints(direction,ep,float(rescue['underlying_price']))
        second=None; full=caponly
        if reentry:
            if term and reentry.get('underlying_price') is not None:
                second=dpoints(direction,float(reentry['underlying_price']),float(term['underlying_price']))
                full=(caponly+second) if caponly is not None else None
            else: full=None
        rescue_imp=(caponly-baseline) if rescue and caponly is not None and baseline is not None else None
        reentry_imp=(full-caponly) if reentry and full is not None and caponly is not None else None
        pre_mfe=None; later_new=None
        if rescue:
            pre_mfe,_=summarize_exc(direction,ep,bars(u,ets,rescue['event_timestamp']))
            post=bars(u,rescue['event_timestamp'],endts)
            if pre_mfe is not None and post:
                post_peak=max(fav(direction,ep,r) for _,r in post); later_new=post_peak>pre_mfe
        cls_result=''
        if cls: cls_result=str(cls.get('result') or cls.get('reason') or '')
        elif strengthen: cls_result='RUNNER_STRENGTHENING'
        out.append({
            'block':block,'session_date':day,'trade_seq':seq,'family':family,'direction':direction,'entry_timestamp':ets,'entry_price':ep,
            'mfe':mfe,'mae':mae,'hit20':mfe is not None and mfe>=20,'hit30':mfe is not None and mfe>=30,'hit50':mfe is not None and mfe>=50,'hit75':mfe is not None and mfe>=75,'hit100':mfe is not None and mfe>=100,
            'plus20_event':plus20 is not None,'classifier_event':cls is not None,'classifier_result':cls_result,'classifier_unavailable':cls_u is not None,'runner_strengthening':strengthen is not None or cls_result=='RUNNER_STRENGTHENING','degraded':degraded is not None,
            'cap20_rescue':rescue is not None,'reentry':reentry is not None,'structural_terminal':term is not None,'open_at_session_end':term is None,
            'baseline_points':baseline,'cap20_only_points':caponly,'second_leg_points':second,'full_points':full,'rescue_improvement':rescue_imp,'reentry_improvement':reentry_imp,
            'rescue_beneficial':rescue_imp is not None and rescue_imp>0,'rescue_harmful':rescue_imp is not None and rescue_imp<0,'later_new_mfe_after_rescue':later_new,
        })
    return out

def pct(n,d): return round(100*n/d,2) if d else None

def mean(xs):
    xs=[float(x) for x in xs if x is not None]; return statistics.mean(xs) if xs else None

def median(xs):
    xs=[float(x) for x in xs if x is not None]; return statistics.median(xs) if xs else None

def sumv(xs):
    xs=[float(x) for x in xs if x is not None]; return sum(xs) if xs else None

def mdd(xs):
    eq=0; peak=0; dd=0
    for x in xs:
        if x is None: continue
        eq+=x; peak=max(peak,eq); dd=min(dd,eq-peak)
    return dd

def summary(label,trades):
    resc=[t for t in trades if t['cap20_rescue']]; comp=[t for t in resc if t['rescue_improvement'] is not None]
    rei=[t for t in trades if t['reentry']]; reic=[t for t in rei if t['reentry_improvement'] is not None]
    base=[t['baseline_points'] for t in trades if t['baseline_points'] is not None]
    capo=[t['cap20_only_points'] for t in trades if t['cap20_only_points'] is not None]
    full=[t['full_points'] for t in trades if t['full_points'] is not None]
    return {
      'group':label,'entries':len(trades),'closed':len(base),'open_session_end':sum(t['open_at_session_end'] for t in trades),
      'hit20':sum(t['hit20'] for t in trades),'hit20_pct':pct(sum(t['hit20'] for t in trades),len(trades)),
      'hit30':sum(t['hit30'] for t in trades),'hit30_pct':pct(sum(t['hit30'] for t in trades),len(trades)),
      'hit50':sum(t['hit50'] for t in trades),'hit50_pct':pct(sum(t['hit50'] for t in trades),len(trades)),
      'hit75':sum(t['hit75'] for t in trades),'hit75_pct':pct(sum(t['hit75'] for t in trades),len(trades)),
      'hit100':sum(t['hit100'] for t in trades),'hit100_pct':pct(sum(t['hit100'] for t in trades),len(trades)),
      'mfe_mean':mean(t['mfe'] for t in trades),'mfe_median':median(t['mfe'] for t in trades),'mae_mean':mean(t['mae'] for t in trades),'mae_median':median(t['mae'] for t in trades),
      'classifier':sum(t['classifier_event'] for t in trades),'classifier_unavailable':sum(t['classifier_unavailable'] for t in trades),'runner_strengthening':sum(t['runner_strengthening'] for t in trades),'degraded':sum(t['degraded'] for t in trades),
      'cap20_rescue':len(resc),'cap20_comparable':len(comp),'cap20_beneficial':sum(t['rescue_beneficial'] for t in comp),'cap20_harmful':sum(t['rescue_harmful'] for t in comp),'cap20_neutral':sum(t['rescue_improvement']==0 for t in comp),
      'rescue_improvement_sum':sumv(t['rescue_improvement'] for t in comp),'rescue_improvement_mean':mean(t['rescue_improvement'] for t in comp),'rescue_improvement_median':median(t['rescue_improvement'] for t in comp),'rescue_improvement_best':max((t['rescue_improvement'] for t in comp),default=None),'rescue_improvement_worst':min((t['rescue_improvement'] for t in comp),default=None),
      'later_new_mfe_after_rescue':sum(t['later_new_mfe_after_rescue'] is True for t in resc),'later_new_mfe_pct':pct(sum(t['later_new_mfe_after_rescue'] is True for t in resc),sum(t['later_new_mfe_after_rescue'] is not None for t in resc)),
      'reentry':len(rei),'reentry_comparable':len(reic),'reentry_improvement_sum':sumv(t['reentry_improvement'] for t in reic),'reentry_improvement_mean':mean(t['reentry_improvement'] for t in reic),'reentry_improvement_median':median(t['reentry_improvement'] for t in reic),
      'baseline_sum':sumv(base),'cap20_only_sum':sumv(capo),'full_sum':sumv(full),'baseline_mdd':mdd(base),'cap20_only_mdd':mdd(capo),'full_mdd':mdd(full),
    }

def classifier_rows(label,trades):
    cls=[t for t in trades if t['classifier_event']]
    groups={'RUNNER_STRENGTHENING':[t for t in cls if t['runner_strengthening']], 'NON_STRENGTHENING':[t for t in cls if not t['runner_strengthening']]}
    out=[]
    for name,xs in groups.items():
        out.append({'group':label,'classifier_group':name,'n':len(xs),'hit30_pct':pct(sum(t['hit30'] for t in xs),len(xs)),'hit50_pct':pct(sum(t['hit50'] for t in xs),len(xs)),'hit75_pct':pct(sum(t['hit75'] for t in xs),len(xs)),'hit100_pct':pct(sum(t['hit100'] for t in xs),len(xs)),'mfe_mean':mean(t['mfe'] for t in xs),'mfe_median':median(t['mfe'] for t in xs)})
    return out

def write_csv(path,rows):
    fields=[]
    for r in rows:
        for k in r:
            if k not in fields: fields.append(k)
    with path.open('w',newline='') as fh:
        w=csv.DictWriter(fh,fieldnames=fields); w.writeheader(); w.writerows(rows)

def f(x): return 'NA' if x is None else (f'{x:.2f}' if isinstance(x,float) else str(x))

def main():
    v55=load_module(V55,'v55_v58'); v52=load_module(V52,'v52_v58'); canon=load_module(CANON,'canon_v58')
    all_trades=[]; total_sessions=0
    for block in v52.BLOCKS:
        u,fut,framework=v55.load_block(block,v52,canon); sessions=sorted(set(u).intersection(fut)); total_sessions+=len(sessions); owners=Counter(); bt=[]
        for day in sessions:
            audit=replay(day,u[day],fut[day])
            for r in audit:
                if r.get('event_type')=='BOUNDARY_CLASSIFIED': owners[str(r.get('result'))]+=1
            trs=reconstruct(block['name'],day,audit,u[day]); bt.extend(trs); all_trades.extend(trs)
        actual={'E':owners['E'],'B':owners['B'],'OTHER_FRESH_A':owners['OTHER_FRESH_A']}
        if actual!=EXPECTED_OWNERSHIP[block['name']]: raise SystemExit(f"STOP ownership parity {block['name']} actual={actual}")
        s=summary(block['name'],bt)
        print(block['name'], 'sessions=',len(sessions),'entries=',len(bt),'ownership=PASS','+20=',s['hit20_pct'],'CAP20=',s['cap20_rescue'],'rescue_delta=',f(s['rescue_improvement_sum']))
    if total_sessions!=480: raise SystemExit(f'STOP expected 480 sessions got {total_sessions}')
    groups={'B':[t for t in all_trades if t['family']=='B'],'E':[t for t in all_trades if t['family']=='E'],'B+E':all_trades}
    fam=[summary(k,v) for k,v in groups.items()]; cls=[]
    for k,v in groups.items(): cls.extend(classifier_rows(k,v))
    OUTDIR.mkdir(parents=True,exist_ok=True); write_csv(TRADE_CSV,all_trades); write_csv(FAMILY_CSV,fam); write_csv(CLASSIFIER_CSV,cls)
    report={'model':'MIDPOINT_V58_480_SESSION_BE_ACCOUNTING_VALIDATION','sessions':480,'trades':len(all_trades),'family_summaries':fam,'classifier_summaries':cls,'accounting':{'baseline':'entry to structural terminal','cap20_only':'CAP20 rescue exit, ignore re-entry','full':'CAP20 first leg + one re-entry leg to structural terminal','rescue_improvement':'cap20_only - baseline','reentry_improvement':'full - cap20_only'},'safety':{'live_mutation':False,'orders':False,'option_pnl':False,'quantity':None}}
    REPORT_JSON.write_text(json.dumps(report,indent=2,sort_keys=True))
    lines=['MIDPOINT V58 — 480-SESSION B+E ACCOUNTING VALIDATION','='*104,'Family-B style CAP20 rescue + one post-rescue re-entry accounting','Underlying directional shadow points only; no option P&L','']
    for s in fam:
        lines += [s['group'],'-'*104,f"entries={s['entries']} closed={s['closed']} open_session_end={s['open_session_end']}",f"+20={s['hit20']} ({f(s['hit20_pct'])}%) +30={s['hit30']} ({f(s['hit30_pct'])}%) +50={s['hit50']} ({f(s['hit50_pct'])}%) +75={s['hit75']} ({f(s['hit75_pct'])}%) +100={s['hit100']} ({f(s['hit100_pct'])}%)",f"MFE mean/median={f(s['mfe_mean'])}/{f(s['mfe_median'])} MAE mean/median={f(s['mae_mean'])}/{f(s['mae_median'])}",f"classifier={s['classifier']} unavailable={s['classifier_unavailable']} runner_strengthening={s['runner_strengthening']} degraded={s['degraded']}",f"CAP20={s['cap20_rescue']} comparable={s['cap20_comparable']} beneficial={s['cap20_beneficial']} harmful={s['cap20_harmful']} neutral={s['cap20_neutral']}",f"rescue improvement sum/mean/median={f(s['rescue_improvement_sum'])}/{f(s['rescue_improvement_mean'])}/{f(s['rescue_improvement_median'])} best/worst={f(s['rescue_improvement_best'])}/{f(s['rescue_improvement_worst'])}",f"later new MFE after rescue={s['later_new_mfe_after_rescue']} ({f(s['later_new_mfe_pct'])}%)",f"reentry={s['reentry']} comparable={s['reentry_comparable']} improvement sum/mean/median={f(s['reentry_improvement_sum'])}/{f(s['reentry_improvement_mean'])}/{f(s['reentry_improvement_median'])}",f"baseline sum={f(s['baseline_sum'])} CAP20-only sum={f(s['cap20_only_sum'])} full sum={f(s['full_sum'])}",f"max drawdown baseline/CAP20/full={f(s['baseline_mdd'])}/{f(s['cap20_only_mdd'])}/{f(s['full_mdd'])}",'']
    lines += ['CLASSIFIER SEPARATION','-'*104]
    for r in cls:
        if r['group']=='B+E': lines.append(f"{r['classifier_group']}: n={r['n']} +30={f(r['hit30_pct'])}% +50={f(r['hit50_pct'])}% +75={f(r['hit75_pct'])}% +100={f(r['hit100_pct'])}% MFE mean/median={f(r['mfe_mean'])}/{f(r['mfe_median'])}")
    lines += ['','ACCEPTANCE','- 480 sessions: PASS','- V55 ownership parity all blocks: PASS','- no live mutation / no orders / no option P&L','',f'TRADE CSV={TRADE_CSV}',f'FAMILY CSV={FAMILY_CSV}',f'CLASSIFIER CSV={CLASSIFIER_CSV}',f'REPORT JSON={REPORT_JSON}',f'SUMMARY={SUMMARY_TXT}']
    SUMMARY_TXT.write_text('\n'.join(lines)+'\n'); print('\n'.join(lines))

if __name__=='__main__': main()
