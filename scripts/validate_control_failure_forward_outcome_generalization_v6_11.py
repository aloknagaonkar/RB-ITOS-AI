from __future__ import annotations

import argparse, csv, json, math, statistics
from pathlib import Path
from typing import Any

MODEL = 'CONTROL_FAILURE_FORWARD_OUTCOME_GENERALIZATION_V6_11'
MIN_TRAIN_SESSIONS = 8
TOP_K = 6
RANK_CUTS = (0.05, 0.10, 0.20, 0.50)
PRIMARY_VARIANT = 'A'
MIN_FEATURE_N = 100


def _f(v: Any) -> float | None:
    if v in (None, '', 'None'): return None
    try: return float(v)
    except Exception: return None


def median(xs): return float(statistics.median(xs)) if xs else None

def mean(xs): return sum(xs)/len(xs) if xs else None

def mad(xs):
    m = median(xs)
    return None if m is None else median([abs(x-m) for x in xs])


def direction_sign(direction: str) -> int:
    return 1 if direction == 'BULLISH' else -1


def normalized_features(r: dict[str, Any]) -> dict[str, float | None]:
    s = direction_sign(r['direction']); out = {}
    for h in (5, 10, 15):
        st = _f(r.get(f'spot_trend_{h}m')); oi = _f(r.get(f'imbalance_{h}m')); pc = _f(r.get(f'pcr_change_{h}m'))
        out[f'opposite_spot_pressure_{h}m'] = None if st is None else -s * st
        out[f'opposite_oi_pressure_{h}m'] = None if oi is None else -s * oi
        out[f'opposite_pcr_pressure_{h}m'] = None if pc is None else -s * pc
    vel = _f(r.get('imbalance_velocity_5m')); acc = _f(r.get('imbalance_acceleration_5m'))
    out['opposite_oi_velocity_5m'] = None if vel is None else -s * vel
    out['opposite_oi_acceleration_5m'] = None if acc is None else -s * acc
    for f in ('failure_count_5m', 'max_consecutive_failure_count', 'decay_count_5m'):
        out[f] = _f(r.get(f))
    ff = _f(r.get('first_failure_minute'))
    out['failure_earliness'] = None if ff is None else 6.0 - ff
    return out


def outcome_target(r: dict[str, Any]) -> float | None:
    a, b = _f(r.get('move_15m')), _f(r.get('move_30m'))
    if a is None or b is None: return None
    return (a + b) / 2.0


def load_rows(path: Path):
    with path.open(newline='', encoding='utf-8') as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        r.update(normalized_features(r))
        r['outcome_target_15_30'] = outcome_target(r)
    return rows


def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i + 1
        while j < len(order) and values[order[j]] == values[order[i]]:
            j += 1
        rank = (i + 1 + j) / 2.0
        for k in range(i, j): ranks[order[k]] = rank
        i = j
    return ranks


def pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3 or len(xs) != len(ys): return None
    mx, my = mean(xs), mean(ys)
    dx = [x-mx for x in xs]; dy = [y-my for y in ys]
    den = math.sqrt(sum(x*x for x in dx) * sum(y*y for y in dy))
    if den == 0: return None
    return sum(x*y for x,y in zip(dx,dy)) / den


def spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3: return None
    return pearson(_ranks(xs), _ranks(ys))


def feature_stats(train: list[dict[str, Any]], feature: str):
    pairs=[]
    for r in train:
        x=_f(r.get(feature)); y=_f(r.get('outcome_target_15_30'))
        if x is not None and y is not None: pairs.append((x,y))
    if len(pairs) < MIN_FEATURE_N: return None
    xs=[x for x,_ in pairs]; ys=[y for _,y in pairs]
    rho=spearman(xs,ys); scale=mad(xs); center=median(xs)
    if rho is None or scale in (None,0) or center is None: return None
    return {'feature':feature,'n':len(pairs),'rho':rho,'abs_rho':abs(rho),'center':center,'scale':scale}


def score_row(r: dict[str, Any], stats: list[dict[str, Any]]) -> float | None:
    vals=[]
    for st in stats:
        x=_f(r.get(st['feature']))
        if x is None: continue
        # Robust centered feature, clipped to prevent a single extreme context field dominating.
        z=max(-5.0,min(5.0,(x-float(st['center']))/float(st['scale'])))
        vals.append(z * float(st['rho']))
    return sum(vals)/len(vals) if vals else None


def rank_cut(rows, cut):
    xs=[r for r in rows if _f(r.get('score')) is not None]
    xs=sorted(xs,key=lambda r:float(r['score']),reverse=True)
    return xs[:max(1,math.ceil(len(xs)*cut))] if xs else []


def hit_rate(rows, key):
    vals=[_f(r.get(key)) for r in rows]; vals=[x for x in vals if x is not None]
    return 100.0*sum(x>0 for x in vals)/len(vals) if vals else None


def metric_summary(rows, prefix=''):
    out={}
    for h in (5,10,15,30):
        vals=[_f(r.get(f'move_{h}m')) for r in rows]; vals=[x for x in vals if x is not None]
        out[f'{prefix}median_{h}m']=median(vals); out[f'{prefix}mean_{h}m']=mean(vals); out[f'{prefix}hit_{h}m_pct']=hit_rate(rows,f'move_{h}m')
    mfe=[_f(r.get('mfe_30m')) for r in rows]; mfe=[x for x in mfe if x is not None]
    mae=[_f(r.get('mae_30m')) for r in rows]; mae=[x for x in mae if x is not None]
    out[f'{prefix}median_mfe_30m']=median(mfe); out[f'{prefix}median_mae_30m']=median(mae)
    return out


def rank_correlation(rows, score_key='score', outcome_key='outcome_target_15_30'):
    pairs=[]
    for r in rows:
        s=_f(r.get(score_key)); y=_f(r.get(outcome_key))
        if s is not None and y is not None: pairs.append((s,y))
    return spearman([x for x,_ in pairs],[y for _,y in pairs]) if pairs else None


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
    ap.add_argument('--output-dir',default='data/historical-evidence/control-failure-forward-outcome-v6-11')
    ap.add_argument('--min-train-sessions',type=int,default=MIN_TRAIN_SESSIONS)
    args=ap.parse_args()

    rows=load_rows(Path(args.enriched))
    sessions=sorted({r['session_date'] for r in rows}); variants=sorted({r['variant'] for r in rows})
    features=list(normalized_features(rows[0]).keys())
    folds=[]; scored=[]

    for i,test_session in enumerate(sessions):
        prior=sessions[:i]
        if len(prior)<args.min_train_sessions: continue
        for variant in variants:
            train=[r for r in rows if r['variant']==variant and r['session_date'] in prior and _f(r.get('outcome_target_15_30')) is not None]
            test=[dict(r) for r in rows if r['variant']==variant and r['session_date']==test_session]
            stats=[x for f in features if (x:=feature_stats(train,f)) is not None]
            stats.sort(key=lambda x:float(x['abs_rho']),reverse=True); chosen=stats[:TOP_K]
            for r in test:
                r['score']=score_row(r,chosen) if chosen else None
                r['test_session']=test_session; r['train_session_count']=len(prior)
                r['selected_features']=';'.join(x['feature'] for x in chosen)
                r['selected_training_rhos']=';'.join(f"{x['feature']}={x['rho']:.6f}" for x in chosen)
                scored.append(r)
            valid=[r for r in test if _f(r.get('score')) is not None and _f(r.get('outcome_target_15_30')) is not None]
            fr={'variant':variant,'test_session':test_session,'train_start':prior[0],'train_end':prior[-1],
                'train_session_count':len(prior),'train_rows':len(train),'test_rows':len(test),'scored_rows':len(valid),
                'status':'OK' if chosen else 'NO_ELIGIBLE_FEATURES','features':';'.join(x['feature'] for x in chosen),
                'score_outcome_spearman':rank_correlation(valid)}
            fr.update(metric_summary(valid,prefix='all_'))
            for cut in RANK_CUTS:
                tag=f'top{int(cut*100)}'; sel=rank_cut(valid,cut)
                fr[f'{tag}_selected']=len(sel); fr[f'{tag}_score_outcome_spearman']=rank_correlation(sel)
                fr.update(metric_summary(sel,prefix=f'{tag}_'))
            folds.append(fr)

    summaries=[]
    for v in variants:
        xs=[r for r in scored if r['variant']==v and _f(r.get('score')) is not None and _f(r.get('outcome_target_15_30')) is not None]
        s={'variant':v,'primary_variant':v==PRIMARY_VARIANT,'walkforward_test_sessions':len({r['session_date'] for r in xs}),
           'rows':len(xs),'pooled_score_outcome_spearman':rank_correlation(xs)}
        fold_corr=[_f(r.get('score_outcome_spearman')) for r in folds if r['variant']==v and _f(r.get('score_outcome_spearman')) is not None]
        s['median_fold_score_outcome_spearman']=median(fold_corr); s['folds_with_correlation']=len(fold_corr)
        s.update(metric_summary(xs,prefix='all_'))
        for cut in RANK_CUTS:
            tag=f'top{int(cut*100)}'; sel=rank_cut(xs,cut)
            s[f'{tag}_selected']=len(sel); s[f'{tag}_score_outcome_spearman']=rank_correlation(sel)
            s.update(metric_summary(sel,prefix=f'{tag}_'))
        # top10 vs bottom50 is a frozen descriptive contrast, not a threshold selection.
        ordered=sorted(xs,key=lambda r:float(r['score']))
        bottom50=ordered[:max(1,math.ceil(len(ordered)*0.50))] if ordered else []
        s.update(metric_summary(bottom50,prefix='bottom50_'))
        summaries.append(s)

    out=Path(args.output_dir); out.mkdir(parents=True,exist_ok=True)
    write_csv(out/'forward-outcome-fold-results-v6-11.csv',folds)
    write_csv(out/'forward-outcome-scored-candidates-v6-11.csv',scored)
    write_csv(out/'forward-outcome-summary-v6-11.csv',summaries)
    (out/'forward-outcome-summary-v6-11.json').write_text(json.dumps({
        'model':MODEL,'chronological_only':True,'minimum_prior_sessions':args.min_train_sessions,
        'training_target':'mean(move_15m, move_30m)','top_k_features_per_fold':TOP_K,
        'fixed_rank_cuts':RANK_CUTS,'primary_variant':PRIMARY_VARIANT,'session_count':len(sessions),
        'sessions':sessions,'summary':summaries},indent=2,allow_nan=False)+'\n',encoding='utf-8')

    print(f'model={MODEL} sessions={len(sessions)} min_train_sessions={args.min_train_sessions} walkforward_test_sessions={max(0,len(sessions)-args.min_train_sessions)} rows={len(rows)}')
    print('\n=== CHRONOLOGICAL FORWARD-OUTCOME GENERALIZATION ===')
    for s in summaries:
        print(f"{s['variant']}: tests={s['walkforward_test_sessions']} rows={s['rows']} rho={s['pooled_score_outcome_spearman']} median_fold_rho={s['median_fold_score_outcome_spearman']} "
              f"all_med15={s['all_median_15m']} all_med30={s['all_median_30m']} "
              f"top10_med15={s['top10_median_15m']} top10_med30={s['top10_median_30m']} "
              f"top10_hit15={s['top10_hit_15m_pct']} top10_hit30={s['top10_hit_30m_pct']} "
              f"top10_MFE={s['top10_median_mfe_30m']} top10_MAE={s['top10_median_mae_30m']} "
              f"bottom50_med15={s['bottom50_median_15m']} bottom50_med30={s['bottom50_median_30m']}")
    print('\nPRIMARY_VARIANT=A. Continuous forward outcome is the learning target; no profitable-trade cutoff or live threshold is selected.')
    print(f"SUMMARY_CSV: {out/'forward-outcome-summary-v6-11.csv'}")
    print(f"FOLDS_CSV: {out/'forward-outcome-fold-results-v6-11.csv'}")
    return 0

if __name__=='__main__': raise SystemExit(main())
