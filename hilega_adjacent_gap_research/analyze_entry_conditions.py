"""Entry-time condition diagnostics on already selected adjacent-gap entries."""
import argparse
import json
from pathlib import Path
from analyze_gap_losses import metrics, membership, band


def features(row):
    check=row.get('entry_check') or {}
    current=check.get('current') or {}; previous=check.get('previous') or {}
    sign=1 if row['direction']=='BULLISH' else -1
    rsi,ema,wma=(current.get(k) for k in ('rsi9','ema3','wma21'))
    aligned=None if None in (rsi,ema,wma) else (rsi>ema>wma if sign==1 else rsi<ema<wma)
    ema_delta=None if ema is None or previous.get('ema3') is None else sign*(ema-previous['ema3'])
    return dict(gap=check.get('current_gap'), expansion=check.get('gap_delta'),
        wma_strength=check.get('directional_wma_strength'), alignment=aligned, ema_delta=ema_delta)


def analyze(report):
    entries=[dict(r,features=features(r),membership=membership(r)) for r in report['trades'] if r.get('candidate_points') is not None]
    dates=sorted({r['session_date'] for r in report['trades']})
    cohorts=[('ALL_DEVELOPMENT_EVIDENCE',set(dates))]
    if len(dates)==490:
        cohorts += [(f'DEVELOPMENT_BLOCK_{i+1}',set(dates[i*160:(i+1)*160])) for i in range(3)]
        cohorts += [('PREVIOUSLY_OBSERVED_10',set(dates[480:]))]
    bands=[]
    for cohort,days in cohorts:
        for direction in ('BULLISH','BEARISH'):
            selected=[r for r in entries if r['session_date'] in days and r['direction']==direction]
            dimensions={'gap':[0,2,5,10,20], 'expansion':[0,.1,.25,.5,1,2], 'wma_strength':[.75,1,1.5,2,3]}
            for dimension,cuts in dimensions.items():
                for label in sorted({band(r['features'][dimension],cuts) for r in selected}):
                    subset=[r for r in selected if band(r['features'][dimension],cuts)==label]
                    bands.append(dict(cohort=cohort,direction=direction,condition=dimension,value=label,
                        all_entries=metrics(subset,'candidate_points'),
                        shared=metrics([r for r in subset if r['membership']=='BOTH_ENTERED'],'candidate_points'),
                        additional=metrics([r for r in subset if r['membership']=='EARLIER_RULE_ONLY'],'candidate_points')))
            for dimension in ('alignment','ema_continuing'):
                for label in ('PASS','FAIL','UNAVAILABLE'):
                    def status(r):
                        value=r['features']['alignment'] if dimension=='alignment' else r['features']['ema_delta']
                        return 'UNAVAILABLE' if value is None else 'PASS' if (value if dimension=='alignment' else value>0) else 'FAIL'
                    subset=[r for r in selected if status(r)==label]
                    bands.append(dict(cohort=cohort,direction=direction,condition=dimension,value=label,
                        all_entries=metrics(subset,'candidate_points'),shared=metrics([r for r in subset if r['membership']=='BOTH_ENTERED'],'candidate_points'),
                        additional=metrics([r for r in subset if r['membership']=='EARLIER_RULE_ONLY'],'candidate_points')))
    return dict(model='ENTRY_CONDITION_DIAGNOSTICS_V1',condition_tables=bands,entry_details=entries,execution_enabled=False,
        warning='Descriptive entry-time evidence only. No best rule selected. Membership uses later outcomes solely for diagnosis, never as an entry gate. Bands are fixed exploratory ranges, not fitted thresholds. Filtering first selected entries does not simulate waiting for later confirmation or a new strategy. Previously observed 10 sessions are not independent validation. Canonical exits retained; fees and option fills excluded.')


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--report',type=Path,default=Path('data/historical-evidence/hilega-adjacent-gap-reconciled-490-v1/report.json'))
    p.add_argument('--output-root',type=Path,default=Path('data/historical-evidence/hilega-entry-condition-diagnostics-v1'))
    p.add_argument('--self-test',action='store_true')
    a=p.parse_args()
    if a.self_test:
        for direction,rsi,ema,wma in [('BULLISH',60,55,50),('BEARISH',40,45,50)]:
            row={'direction':direction,'entry_check':{'current':dict(rsi9=rsi,ema3=ema,wma21=wma),'previous':{'ema3':ema-(1 if direction=='BULLISH' else -1)}}}
            f=features(row);assert f['alignment'] is True and f['ema_delta']==1
        assert features({'direction':'BULLISH'})['alignment'] is None
        print('PASS: bullish/bearish alignment, directional EMA change and missing data')
        return
    if a.output_root.exists():raise SystemExit('STOP: output exists; choose a new output root')
    result=analyze(json.loads(a.report.read_text()))
    a.output_root.mkdir(parents=True)
    (a.output_root/'report.json').write_text(json.dumps(result,indent=2))
    for row in result['condition_tables']:
        if row['cohort']=='ALL_DEVELOPMENT_EVIDENCE':print(json.dumps(row))
    print('Output:',a.output_root/'report.json')
    print('No strategy, exit, cache or order changes.')

if __name__=='__main__':main()
