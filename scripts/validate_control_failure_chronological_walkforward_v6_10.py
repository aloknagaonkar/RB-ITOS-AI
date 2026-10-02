from __future__ import annotations

import argparse, csv, json, math, statistics
from pathlib import Path
from typing import Any

MODEL = 'CONTROL_FAILURE_CHRONOLOGICAL_WALKFORWARD_V6_10'
MIN_TRAIN_SESSIONS = 8
TOP_K = 6
RANK_CUTS = (0.05, 0.10, 0.20)
PRIMARY_VARIANT = 'A'


def _f(v: Any) -> float | None:
    if v in (None, '', 'None'): return None
    try: return float(v)
    except Exception: return None


def median(xs): return float(statistics.median(xs)) if xs else None

def mean(xs): return sum(xs)/len(xs) if xs else None

def mad(xs):
    m=median(xs)
    return None if m is None else median([abs(x-m) for x in xs])


def direction_sign(direction: str) -> int:
    return 1 if direction == 'BULLISH' else -1


def normalized_features(r: dict[str, Any]) -> dict[str, float | None]:
    s=direction_sign(r['direction']); out={}
    for h in (5,10,15):
        st=_f(r.get(f'spot_trend_{h}m')); oi=_f(r.get(f'imbalance_{h}m')); pc=_f(r.get(f'pcr_change_{h}m'))
        out[f'opposite_spot_pressure_{h}m']=None if st is None else -s*st
        out[f'opposite_oi_pressure_{h}m']=None if oi is None else -s*oi
        out[f'opposite_pcr_pressure_{h}m']=None if pc is None else -s*pc
    vel=_f(r.get('imbalance_velocity_5m')); acc=_f(r.get('imbalance_acceleration_5m'))
    out['opposite_oi_velocity_5m']=None if vel is None else -s*vel
    out['opposite_oi_acceleration_5m']=None if acc is None else -s*acc
    for f in ('failure_count_5m','max_consecutive_failure_count','decay_count_5m'):
        out[f]=_f(r.get(f))
    ff=_f(r.get('first_failure_minute'))
    out['failure_earliness']=None if ff is None else 6.0-ff
    return out


def load_rows(path: Path):
    with path.open(newline='', encoding='utf-8') as fh: rows=list(csv.DictReader(fh))
    for r in rows:
        r.update(normalized_features(r))
        r['label']=1 if r.get('population')=='NEAR_MOVE' else 0
    return rows


def feature_stats(train, feature):
    near=[_f(r.get(feature)) for r in train if r['label']==1]; non=[_f(r.get(feature)) for r in train if r['label']==0]
    near=[x for x in near if x is not None]; non=[x for x in non if x is not None]
    if len(near)<5 or len(non)<30: return None
    scale=mad(near+non)
    if scale in (None,0): return None
    mn,mf=median(near),median(non)
    return {'feature':feature,'near_median':mn,'non_median':mf,'scale':scale,'separation':(mn-mf)/scale,'near_n':len(near),'non_n':len(non)}


def score_row(r, stats):
    vals=[]
    for st in stats:
        x=_f(r.get(st['feature']))
        if x is None: continue
        vals.append((abs(x-float(st['non_median']))-abs(x-float(st['near_median'])))/float(st['scale']))
    return sum(vals)/len(vals) if vals else None


def auc(labels, scores):
    pairs=[(s,l) for s,l in zip(scores,labels) if s is not None]
    pos=[s for s,l in pairs if l==1]; neg=[s for s,l in pairs if l==0]
    if not pos or not neg: return None
    wins=ties=0
    for p in pos:
        for n in neg:
            if p>n: wins+=1
            elif p==n: ties+=1
    return (wins+0.5*ties)/(len(pos)*len(neg))


def rank_cut(rows, cut):
    xs=[r for r in rows if r.get('score') is not None]
    if not xs: return []
    xs=sorted(xs,key=lambda r:float(r['score']),reverse=True)
    return xs[:max(1,math.ceil(len(xs)*cut))]


def hit_rate(xs, key):
    vals=[_f(r.get(key)) for r in xs]; vals=[x for x in vals if x is not None]
    return 100.0*sum(x>0 for x in vals)/len(vals) if vals else None


def metric_summary(xs, prefix=''):
    out={}
    for h in (5,10,15,30):
        vals=[_f(r.get(f'move_{h}m')) for r in xs]; vals=[x for x in vals if x is not None]
        out[f'{prefix}median_{h}m']=median(vals); out[f'{prefix}mean_{h}m']=mean(vals); out[f'{prefix}hit_{h}m_pct']=hit_rate(xs,f'move_{h}m')
    mfe=[_f(r.get('mfe_30m')) for r in xs]; mfe=[x for x in mfe if x is not None]
    mae=[_f(r.get('mae_30m')) for r in xs]; mae=[x for x in mae if x is not None]
    out[f'{prefix}median_mfe_30m']=median(mfe); out[f'{prefix}median_mae_30m']=median(mae)
    return out


def write_csv(path, rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    if not rows: path.write_text('',encoding='utf-8'); return
    fields=[]
    for r in rows:
        for k in r:
            if k not in fields: fields.append(k)
    with path.open('w',newline='',encoding='utf-8') as fh:
        w=csv.DictWriter(fh,fieldnames=fields); w.writeheader(); w.writerows(rows)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--enriched',default='data/historical-evidence/control-failure-context-discrimination-v6-8/context-enriched-candidates-v6-8.csv')
    ap.add_argument('--output-dir',default='data/historical-evidence/control-failure-chronological-walkforward-v6-10')
    ap.add_argument('--min-train-sessions',type=int,default=MIN_TRAIN_SESSIONS)
    args=ap.parse_args()
    rows=load_rows(Path(args.enriched))
    sessions=sorted({r['session_date'] for r in rows}); variants=sorted({r['variant'] for r in rows})
    norm_features=list(normalized_features(rows[0]).keys())
    folds=[]; scored=[]

    for i,test_session in enumerate(sessions):
        prior=sessions[:i]
        if len(prior)<args.min_train_sessions: continue
        for variant in variants:
            train=[r for r in rows if r['variant']==variant and r['session_date'] in prior]
            test=[dict(r) for r in rows if r['variant']==variant and r['session_date']==test_session]
            stats=[x for f in norm_features if (x:=feature_stats(train,f)) is not None]
            stats.sort(key=lambda x:abs(float(x['separation'])),reverse=True); chosen=stats[:TOP_K]
            status='OK' if chosen else 'NO_ELIGIBLE_FEATURES'
            for r in test:
                r['score']=score_row(r,chosen) if chosen else None
                r['test_session']=test_session; r['train_session_count']=len(prior); r['selected_features']=';'.join(x['feature'] for x in chosen)
                scored.append(r)
            labels=[int(r['label']) for r in test]; scores=[r.get('score') for r in test]
            fr={'variant':variant,'test_session':test_session,'train_start':prior[0] if prior else None,'train_end':prior[-1] if prior else None,
                'train_session_count':len(prior),'test_rows':len(test),'near_rows':sum(labels),'status':status,'auc':auc(labels,scores),'features':';'.join(x['feature'] for x in chosen)}
            for cut in RANK_CUTS:
                sel=rank_cut(test,cut); tag=f'top{int(cut*100)}'; near=sum(int(r['label']) for r in sel); total_near=sum(labels)
                base=(total_near/len(test)) if test else 0; precision=(near/len(sel)) if sel else None
                fr[f'{tag}_selected']=len(sel); fr[f'{tag}_near_selected']=near; fr[f'{tag}_precision']=precision
                fr[f'{tag}_recall']=(near/total_near) if total_near else None; fr[f'{tag}_lift']=(precision/base) if precision is not None and base>0 else None
                fr.update(metric_summary(sel,prefix=f'{tag}_'))
            folds.append(fr)

    summaries=[]
    for v in variants:
        xs=[r for r in scored if r['variant']==v and r.get('score') is not None]
        labels=[int(r['label']) for r in xs]; scores=[r.get('score') for r in xs]
        s={'variant':v,'primary_variant':v==PRIMARY_VARIANT,'walkforward_test_sessions':len({r['session_date'] for r in xs}),
           'rows':len(xs),'near_rows':sum(labels),'pooled_walkforward_auc':auc(labels,scores)}
        fold_aucs=[_f(r.get('auc')) for r in folds if r['variant']==v and _f(r.get('auc')) is not None]
        s['median_fold_auc']=median(fold_aucs); s['folds_with_auc']=len(fold_aucs)
        s.update(metric_summary(xs,prefix='all_'))
        for cut in RANK_CUTS:
            tag=f'top{int(cut*100)}'; sel=rank_cut(xs,cut); near=sum(int(r['label']) for r in sel); base=(sum(labels)/len(xs)) if xs else 0; precision=(near/len(sel)) if sel else None
            s[f'{tag}_selected']=len(sel); s[f'{tag}_near_selected']=near; s[f'{tag}_precision']=precision
            s[f'{tag}_recall']=(near/sum(labels)) if sum(labels) else None; s[f'{tag}_lift']=(precision/base) if precision is not None and base>0 else None
            s.update(metric_summary(sel,prefix=f'{tag}_'))
        summaries.append(s)

    out=Path(args.output_dir); out.mkdir(parents=True,exist_ok=True)
    write_csv(out/'walkforward-fold-results-v6-10.csv',folds)
    write_csv(out/'walkforward-scored-candidates-v6-10.csv',scored)
    write_csv(out/'walkforward-summary-v6-10.csv',summaries)
    (out/'walkforward-summary-v6-10.json').write_text(json.dumps({'model':MODEL,'chronological_only':True,'minimum_prior_sessions':args.min_train_sessions,'top_k_features_per_fold':TOP_K,'fixed_rank_cuts':RANK_CUTS,'session_count':len(sessions),'sessions':sessions,'summary':summaries},indent=2,allow_nan=False)+'\n',encoding='utf-8')

    print(f'model={MODEL} sessions={len(sessions)} min_train_sessions={args.min_train_sessions} walkforward_test_sessions={max(0,len(sessions)-args.min_train_sessions)} rows={len(rows)}')
    print('\n=== CHRONOLOGICAL WALK-FORWARD GENERALIZATION ===')
    for s in summaries:
        print(f"{s['variant']}: tests={s['walkforward_test_sessions']} rows={s['rows']} near={s['near_rows']} auc={s['pooled_walkforward_auc']} median_fold_auc={s['median_fold_auc']} "
              f"top5_lift={s['top5_lift']} top10_lift={s['top10_lift']} top20_lift={s['top20_lift']} "
              f"top10_med15={s['top10_median_15m']} top10_med30={s['top10_median_30m']} top10_hit15={s['top10_hit_15m_pct']} top10_hit30={s['top10_hit_30m_pct']}")
    print('\nPRIMARY_VARIANT=A. Rank cuts are evaluation diagnostics only; no live threshold is selected.')
    print(f"SUMMARY_CSV: {out/'walkforward-summary-v6-10.csv'}")
    print(f"FOLDS_CSV: {out/'walkforward-fold-results-v6-10.csv'}")
    return 0

if __name__=='__main__': raise SystemExit(main())
