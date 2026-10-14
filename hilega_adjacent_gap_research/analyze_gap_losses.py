"""Describe existing research outcomes; never changes entry or exit rules."""
import argparse
import json
from pathlib import Path


def metrics(rows, field):
    values = [float(r[field]) for r in rows if r.get(field) is not None]
    gained = sum(v for v in values if v > 0)
    lost = -sum(v for v in values if v < 0)
    return dict(entries=len(values), winners=sum(v > 0 for v in values),
                losers=sum(v < 0 for v in values), breakeven=sum(v == 0 for v in values),
                gains=round(gained, 4), losses=round(lost, 4), net=round(gained-lost, 4),
                gain_loss_ratio=gained/lost if lost else None)


def membership(row):
    c = row.get('control_points') is not None
    n = row.get('candidate_points') is not None
    return 'BOTH_ENTERED' if c and n else 'EARLIER_RULE_ONLY' if n else 'WAITING_RULE_ONLY' if c else 'BOTH_DENIED'


def band(value, cuts):
    if value is None:
        return 'UNAVAILABLE'
    value = float(value)
    for lower, upper in zip(cuts, cuts[1:]):
        if lower <= value < upper:
            return f'[{lower},{upper})'
    return f'>={cuts[-1]}' if value >= cuts[-1] else f'<{cuts[0]}'


def analyze(report):
    rows = report['trades']
    groups = []
    bins = []
    detailed = []
    for row in rows:
        check = row.get('entry_check') or {}
        copy = dict(row)
        copy['membership'] = membership(row)
        copy['net_delta_vs_waiting'] = (row.get('candidate_points') or 0)-(row.get('control_points') or 0)
        copy['entry_gap_band'] = band(check.get('current_gap'), [0, 2, 5, 10, 20])
        copy['entry_expansion_band'] = band(check.get('gap_delta'), [0, .1, .25, .5, 1, 2])
        detailed.append(copy)
    dates = sorted({r['session_date'] for r in rows})
    cohorts = [('ALL_DEVELOPMENT_EVIDENCE', set(dates))]
    if len(dates) == 490:
        cohorts += [('DEVELOPMENT_480', set(dates[:480])), ('PREVIOUSLY_OBSERVED_10', set(dates[480:]))]
        cohorts += [(f'DEVELOPMENT_BLOCK_{i+1}', set(dates[i*160:(i+1)*160])) for i in range(3)]
    for cohort, selected_dates in cohorts:
        for direction in ['ALL', 'BULLISH', 'BEARISH']:
            selected = [r for r in detailed if r['session_date'] in selected_dates and (direction == 'ALL' or r['direction'] == direction)]
            for category in ['BOTH_ENTERED', 'EARLIER_RULE_ONLY', 'WAITING_RULE_ONLY', 'BOTH_DENIED']:
                subset = [r for r in selected if r['membership'] == category]
                groups.append(dict(cohort=cohort, direction=direction, membership=category, signals=len(subset),
                    waiting=metrics(subset,'control_points'), earlier=metrics(subset,'candidate_points'),
                    net_delta=round(sum(r['net_delta_vs_waiting'] for r in subset),4)))
            for dimension in ['entry_gap_band', 'entry_expansion_band']:
                for label in sorted({r[dimension] for r in selected if r.get('candidate_points') is not None}):
                    subset = [r for r in selected if r.get('candidate_points') is not None and r[dimension] == label]
                    bins.append(dict(cohort=cohort,direction=direction,dimension=dimension,band=label,
                        earlier=metrics(subset,'candidate_points'), waiting=metrics(subset,'control_points'),
                        earlier_only=sum(r['membership']=='EARLIER_RULE_ONLY' for r in subset)))
    return dict(model='ADJACENT_GAP_LOSS_DIAGNOSTICS_V1', groups=groups, gap_bands=bins,
        trades=sorted(detailed,key=lambda r:r['net_delta_vs_waiting']),
        source_history_reconciliation=report.get('history_reconciliation'), execution_enabled=False,
        warning='Descriptive development analysis, not a validated entry threshold. Bands describe gap at candidate entry, not all signals or first WMA touch. Shared trades isolate entry timing with the same canonical exit. Zero means no trade when calculating policy net differences; denied trades are excluded from trade metrics. Fees and option fills excluded.')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--report',type=Path,default=Path('data/historical-evidence/hilega-adjacent-gap-reconciled-490-v1/report.json'))
    parser.add_argument('--output-root',type=Path,default=Path('data/historical-evidence/hilega-adjacent-gap-loss-diagnostics-v1'))
    parser.add_argument('--self-test',action='store_true')
    args=parser.parse_args()
    if args.self_test:
        rows=[dict(session_date='2026-01-01',direction='BULLISH',control_points=10,candidate_points=8),dict(session_date='2026-01-01',direction='BEARISH',control_points=None,candidate_points=-4)]
        result=analyze({'trades':rows})
        groups=[r for r in result['groups'] if r['direction']=='ALL']
        assert sum(r['net_delta'] for r in groups)==-6
        assert metrics(rows,'control_points')['entries']==1
        assert membership(rows[1])=='EARLIER_RULE_ONLY'
        assert band(.25,[0,.1,.25,.5])=='[0.25,0.5)'
        print('PASS: membership, net reconciliation, denied exclusion and band boundaries')
        return
    if args.output_root.exists():
        raise SystemExit('STOP: output exists; use a new --output-root')
    report=json.loads(args.report.read_text())
    result=analyze(report)
    groups=[r for r in result['groups'] if r['cohort']=='ALL_DEVELOPMENT_EVIDENCE' and r['direction']=='ALL']
    expected=sum((r.get('candidate_points') or 0)-(r.get('control_points') or 0) for r in report['trades'])
    assert abs(sum(r['net_delta'] for r in groups)-expected)<.01
    args.output_root.mkdir(parents=True)
    (args.output_root/'report.json').write_text(json.dumps(result,indent=2))
    for row in result['groups']:
        if row['cohort']=='ALL_DEVELOPMENT_EVIDENCE':
            print(json.dumps(row))
    print('Output:',args.output_root/'report.json')
    print('Read only: strategy, exits, cache and orders unchanged.')

if __name__=='__main__':
    main()
