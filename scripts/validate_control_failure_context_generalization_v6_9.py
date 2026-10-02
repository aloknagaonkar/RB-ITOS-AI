from __future__ import annotations

import argparse, csv, json, math, statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

MODEL = 'CONTROL_FAILURE_CONTEXT_GENERALIZATION_V6_9'
BASE_FEATURES = (
    'spot_trend_5m','spot_trend_10m','spot_trend_15m',
    'imbalance_5m','imbalance_10m','imbalance_15m',
    'pcr_change_5m','pcr_change_10m','pcr_change_15m',
    'imbalance_velocity_5m','imbalance_acceleration_5m',
    'failure_count_5m','max_consecutive_failure_count','first_failure_minute','decay_count_5m',
)
TOP_K = 6
RANK_CUTS = (0.05, 0.10, 0.20)


def _f(v: Any) -> float | None:
    if v in (None, '', 'None'): return None
    try: return float(v)
    except Exception: return None


def median(xs): return float(statistics.median(xs)) if xs else None


def mad(xs):
    m = median(xs)
    return None if m is None else median([abs(x-m) for x in xs])


def direction_sign(direction: str) -> int:
    return 1 if direction == 'BULLISH' else -1


def normalized_features(r: dict[str, Any]) -> dict[str, float | None]:
    s = direction_sign(r['direction'])
    out: dict[str, float | None] = {}
    for h in (5,10,15):
        st = _f(r.get(f'spot_trend_{h}m'))
        oi = _f(r.get(f'imbalance_{h}m'))
        pc = _f(r.get(f'pcr_change_{h}m'))
        out[f'opposite_spot_pressure_{h}m'] = None if st is None else -s * st
        out[f'opposite_oi_pressure_{h}m'] = None if oi is None else -s * oi
        out[f'opposite_pcr_pressure_{h}m'] = None if pc is None else -s * pc
    vel = _f(r.get('imbalance_velocity_5m')); acc = _f(r.get('imbalance_acceleration_5m'))
    out['opposite_oi_velocity_5m'] = None if vel is None else -s * vel
    out['opposite_oi_acceleration_5m'] = None if acc is None else -s * acc
    for f in ('failure_count_5m','max_consecutive_failure_count','decay_count_5m'):
        out[f] = _f(r.get(f))
    ff = _f(r.get('first_failure_minute'))
    out['failure_earliness'] = None if ff is None else 6.0 - ff  # minute1 => 5, minute5 => 1
    return out


def load_rows(path: Path) -> list[dict[str, Any]]:
    with path.open(newline='', encoding='utf-8') as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        r.update(normalized_features(r))
        r['label'] = 1 if r.get('population') == 'NEAR_MOVE' else 0
    return rows


def feature_stats(train: list[dict[str, Any]], feature: str) -> dict[str, Any] | None:
    near = [_f(r.get(feature)) for r in train if r['label'] == 1]
    non = [_f(r.get(feature)) for r in train if r['label'] == 0]
    near = [x for x in near if x is not None]; non = [x for x in non if x is not None]
    if len(near) < 5 or len(non) < 30: return None
    pooled = near + non; scale = mad(pooled)
    if scale in (None, 0): return None
    mn, mf = median(near), median(non)
    sep = (mn - mf) / scale
    return {'feature': feature, 'near_median': mn, 'non_median': mf, 'scale': scale, 'separation': sep,
            'near_n': len(near), 'non_n': len(non)}


def score_row(r: dict[str, Any], stats: list[dict[str, Any]]) -> float | None:
    vals=[]
    for st in stats:
        x=_f(r.get(st['feature']))
        if x is None: continue
        scale=float(st['scale'])
        # Positive means closer to the training NEAR_MOVE median than NON_MOVE median.
        vals.append((abs(x-float(st['non_median'])) - abs(x-float(st['near_median']))) / scale)
    return sum(vals)/len(vals) if vals else None


def auc(labels, scores) -> float | None:
    pairs=[(s,l) for s,l in zip(scores,labels) if s is not None]
    pos=[s for s,l in pairs if l==1]; neg=[s for s,l in pairs if l==0]
    if not pos or not neg: return None
    wins=ties=0
    for p in pos:
        for n in neg:
            if p>n: wins+=1
            elif p==n: ties+=1
    return (wins+0.5*ties)/(len(pos)*len(neg))


def rank_cut_metrics(rows: list[dict[str, Any]], cut: float) -> dict[str, Any]:
    scored=[r for r in rows if r.get('score') is not None]
    if not scored: return {'selected':0,'near_selected':0,'precision':None,'recall':None,'lift':None}
    scored.sort(key=lambda r: float(r['score']), reverse=True)
    n=max(1, math.ceil(len(scored)*cut)); sel=scored[:n]
    total_near=sum(int(r['label']) for r in scored); near=sum(int(r['label']) for r in sel)
    base=total_near/len(scored) if scored else 0
    precision=near/n; recall=near/total_near if total_near else None
    lift=(precision/base) if base>0 else None
    return {'selected':n,'near_selected':near,'precision':precision,'recall':recall,'lift':lift}


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows: path.write_text('',encoding='utf-8'); return
    fields=[]
    for r in rows:
        for k in r:
            if k not in fields: fields.append(k)
    with path.open('w',newline='',encoding='utf-8') as fh:
        w=csv.DictWriter(fh,fieldnames=fields); w.writeheader(); w.writerows(rows)


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--enriched', default='data/historical-evidence/control-failure-context-discrimination-v6-8/context-enriched-candidates-v6-8.csv')
    ap.add_argument('--output-dir', default='data/historical-evidence/control-failure-context-generalization-v6-9')
    args=ap.parse_args()
    path=Path(args.enriched)
    if not path.exists(): raise FileNotFoundError(path)
    rows=load_rows(path)
    sessions=sorted({r['session_date'] for r in rows})
    variants=sorted({r['variant'] for r in rows})
    norm_features=list(normalized_features(rows[0]).keys())
    fold_rows=[]; scored_rows=[]

    for variant in variants:
        vr=[r for r in rows if r['variant']==variant]
        for held in sessions:
            train=[r for r in vr if r['session_date']!=held]
            test=[dict(r) for r in vr if r['session_date']==held]
            stats=[x for f in norm_features if (x:=feature_stats(train,f)) is not None]
            stats.sort(key=lambda x: abs(float(x['separation'])), reverse=True)
            chosen=stats[:TOP_K]
            for r in test:
                r['score']=score_row(r,chosen); r['heldout_session']=held
                r['selected_features']=';'.join(s['feature'] for s in chosen)
                scored_rows.append(r)
            labels=[int(r['label']) for r in test]; scores=[r.get('score') for r in test]
            fr={'variant':variant,'heldout_session':held,'test_rows':len(test),'near_rows':sum(labels),'auc':auc(labels,scores),
                'features':';'.join(s['feature'] for s in chosen)}
            for cut in RANK_CUTS:
                m=rank_cut_metrics(test,cut); tag=f'top{int(cut*100)}'
                for k,v in m.items(): fr[f'{tag}_{k}']=v
            fold_rows.append(fr)

    # pooled held-out evaluation: every score here came from a model that excluded that row's session.
    summary=[]
    for v in variants:
        xs=[r for r in scored_rows if r['variant']==v]
        labels=[int(r['label']) for r in xs]; scores=[r.get('score') for r in xs]
        s={'variant':v,'sessions':len({r['session_date'] for r in xs}),'rows':len(xs),'near_rows':sum(labels),'pooled_loso_auc':auc(labels,scores)}
        for cut in RANK_CUTS:
            m=rank_cut_metrics(xs,cut); tag=f'top{int(cut*100)}'
            for k,val in m.items(): s[f'{tag}_{k}']=val
        fold_aucs=[_f(r['auc']) for r in fold_rows if r['variant']==v and _f(r['auc']) is not None]
        s['median_fold_auc']=median(fold_aucs); s['folds_with_auc']=len(fold_aucs)
        summary.append(s)

    out=Path(args.output_dir); out.mkdir(parents=True,exist_ok=True)
    write_csv(out/'loso-fold-results-v6-9.csv',fold_rows)
    write_csv(out/'loso-scored-candidates-v6-9.csv',scored_rows)
    write_csv(out/'loso-summary-v6-9.csv',summary)
    (out/'loso-summary-v6-9.json').write_text(json.dumps({'model':MODEL,'sessions':sessions,'session_count':len(sessions),'top_k_features_per_fold':TOP_K,'fixed_rank_cuts':RANK_CUTS,'summary':summary},indent=2,allow_nan=False)+'\n',encoding='utf-8')

    print(f'model={MODEL} sessions={len(sessions)} rows={len(rows)} variants={len(variants)}')
    print('\n=== LEAVE-ONE-SESSION-OUT GENERALIZATION ===')
    for s in summary:
        print(f"{s['variant']}: rows={s['rows']} near={s['near_rows']} pooled_auc={s['pooled_loso_auc']} median_fold_auc={s['median_fold_auc']} "
              f"top5_lift={s['top5_lift']} top5_recall={s['top5_recall']} top10_lift={s['top10_lift']} top10_recall={s['top10_recall']} top20_lift={s['top20_lift']} top20_recall={s['top20_recall']}")
    print('\nInterpretation: AUC 0.5 = no ranking separation; >0.5 means training-session context tends to rank held-out NEAR_MOVE candidates above held-out NON_MOVE candidates.')
    print('No live threshold or trade rule is selected by V6.9.')
    print(f"SUMMARY_CSV: {out/'loso-summary-v6-9.csv'}")
    print(f"FOLDS_CSV: {out/'loso-fold-results-v6-9.csv'}")
    return 0

if __name__=='__main__': raise SystemExit(main())
