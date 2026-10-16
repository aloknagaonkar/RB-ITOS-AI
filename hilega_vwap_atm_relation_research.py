"""Offline VWAP distance and fixed/moving ATM research. No network or orders.
Requires the existing hilega_vwap_ema10_research.py cache reader in repo root.
"""
import argparse
import csv
import hashlib
import json
import math
import unittest
from datetime import timedelta
from pathlib import Path

RULES=('CURRENT','VWAP_ALIGNMENT','VWAP_AND_ATM_CHANGED','VWAP_AND_ATM_WITH_SIGNAL','VWAP_OR_ATM_WITH_SIGNAL')


def atm(price,interval=50):
    if not math.isfinite(price) or price<=0 or interval<=0:raise ValueError('INVALID_ATM_INPUT')
    return interval*math.ceil(price/interval-.5)


def distance_band(distance):
    d=abs(distance)
    return '0_TO_10' if d<10 else '10_TO_25' if d<25 else '25_TO_50' if d<50 else '50_TO_100' if d<100 else '100_PLUS'


def features(trade,minutes,dt):
    day=trade['session_date'];at=dt(trade['entry_time']);side=trade['direction']
    if side not in ('BULLISH','BEARISH'):raise ValueError('INVALID_DIRECTION')
    opening=dt(day+'T09:15:00+05:30');open_row=minutes[opening]
    available=dt(trade['candle_available_at'])
    if available.date()!=at.date() or not 0<=(at-available).total_seconds()<300:raise ValueError('STALE_OR_FUTURE_VWAP')
    # Require all five underlying minutes corresponding to the futures close.
    keys=[available-timedelta(minutes=i) for i in range(1,6)]
    if any(key not in minutes for key in keys):raise ValueError('INCOMPLETE_MATCHED_NIFTY_5M_CANDLE')
    spot_close=minutes[available-timedelta(minutes=1)][4]
    entry_row=minutes[at-timedelta(minutes=1)]
    if abs(entry_row[4]-trade['entry_price'])>1e-5:raise ValueError('ENTRY_PRICE_RAW_CACHE_MISMATCH')
    if opening>at:raise ValueError('OPENING_REFERENCE_NOT_YET_AVAILABLE')
    fixed=atm(open_row[1]);moving=atm(trade['entry_price']);sign=1 if side=='BULLISH' else -1
    shift=moving-fixed;supporting_shift=sign*shift
    distance=float(trade['futures_close'])-float(trade['vwap'])
    if not math.isfinite(distance):raise ValueError('INVALID_VWAP_DISTANCE')
    if abs(distance-float(trade['vwap_distance']))>1e-6:raise ValueError('VWAP_DISTANCE_MISMATCH')
    agrees=sign*distance>0
    if trade.get('alignment') is not agrees:raise ValueError('SOURCE_ALIGNMENT_MISMATCH')
    basis=trade['futures_close']-spot_close
    proxy=trade['vwap']-basis
    prior_available=available-timedelta(minutes=5)
    prior_keys=[prior_available-timedelta(minutes=i) for i in range(1,6)]
    prior_atm=atm(minutes[prior_available-timedelta(minutes=1)][4]) if prior_keys[-1]>=opening and all(key in minutes for key in prior_keys) else None
    return dict(fixed_atm=fixed,fixed_atm_reference_time=opening.isoformat(),fixed_atm_reference_price=open_row[1],
                moving_atm=moving,moving_atm_reference_time=at.isoformat(),moving_atm_reference_price=trade['entry_price'],
                atm_shift_points=shift,atm_shift_strikes=shift/50,directional_atm_shift_points=supporting_shift,
                migration='WITH_SIGNAL' if supporting_shift>0 else 'AGAINST_SIGNAL' if supporting_shift<0 else 'UNCHANGED',
                candidate_windows_overlap_count=max(0,11-int(abs(shift)/50)),
                completed_5m_moving_atm=atm(spot_close),previous_completed_5m_atm=prior_atm,
                completed_5m_atm_step=(atm(spot_close)-prior_atm) if prior_atm is not None else None,
                vwap_distance_points=distance,directional_vwap_distance_points=sign*distance,
                vwap_distance_band=distance_band(distance),distance_in_50_point_strike_steps=abs(distance)/50,
                matched_nifty_5m_close=spot_close,futures_spot_basis_points=basis,
                basis_adjusted_futures_vwap_proxy=proxy,
                fixed_atm_minus_vwap_proxy=fixed-proxy,moving_atm_minus_vwap_proxy=moving-proxy,
                proxy_basis='SAME_COMPLETED_5M_FUTURES_BASIS_REMOVED_NOT_TRUE_SPOT_VWAP',
                policies=dict(CURRENT=True,VWAP_ALIGNMENT=agrees,VWAP_AND_ATM_CHANGED=agrees and shift!=0,
                              VWAP_AND_ATM_WITH_SIGNAL=agrees and supporting_shift>0,VWAP_OR_ATM_WITH_SIGNAL=agrees or supporting_shift>0))


def stats(rows):
    points=[float(r['points']) for r in rows];profit=sum(v for v in points if v>0);loss=-sum(v for v in points if v<0)
    equity=peak=drawdown=0.
    for value in points:
        equity+=value;peak=max(peak,equity);drawdown=max(drawdown,peak-equity)
    return dict(trades=len(rows),points=round(sum(points),4),winners=sum(v>0 for v in points),losers=sum(v<0 for v in points),
                profit_factor=profit/loss if loss else None,closed_trade_drawdown=round(drawdown,4))


def summarize(rows):
    known=[r for r in rows if 'policies' in r];rules=[]
    for name in RULES:
        passed=[r for r in known if r['policies'][name]];blocked=[r for r in known if not r['policies'][name]]
        rules.append(dict(rule=name,unknown=len(rows)-len(known),baseline_same_coverage=stats(known),passed=stats(passed),blocked=stats(blocked),
                          losers_blocked=sum(r['points']<0 for r in blocked),loss_points_avoided=round(-sum(r['points'] for r in blocked if r['points']<0),4),
                          winners_blocked=sum(r['points']>0 for r in blocked),profit_points_missed=round(sum(r['points'] for r in blocked if r['points']>0),4)))
    groups=[]
    for aligned in (True,False):
        for migration in ('WITH_SIGNAL','UNCHANGED','AGAINST_SIGNAL'):
            group=[r for r in known if r['alignment'] is aligned and r['migration']==migration]
            groups.append(dict(vwap_alignment=aligned,atm_migration=migration,**stats(group)))
    distances=[]
    for band in ('0_TO_10','10_TO_25','25_TO_50','50_TO_100','100_PLUS'):
        for aligned in (True,False):
            group=[r for r in known if r['alignment'] is aligned and r['vwap_distance_band']==band]
            distances.append(dict(band=band,vwap_alignment=aligned,**stats(group)))
    return dict(rules=rules,atm_vwap_groups=groups,distance_groups=distances)


class Checks(unittest.TestCase):
    def fixture(self):
        from datetime import datetime
        dt=datetime.fromisoformat;start=dt('2026-10-15T09:15:00+05:30')
        minutes={start+timedelta(minutes=i):['',20010.,20110.,20000.,20100.] for i in range(7)}
        trade=dict(session_date='2026-10-15',entry_time='2026-10-15T09:22:00+05:30',direction='BULLISH',
                   entry_price=20100.,candle_available_at='2026-10-15T09:20:00+05:30',
                   futures_close=20120.,vwap=20100.,vwap_distance=20.,alignment=True)
        return trade,minutes,dt
    def test_futures_basis_removed_before_strike_comparison(self):
        trade,minutes,dt=self.fixture();f=features(trade,minutes,dt)
        self.assertEqual((f['fixed_atm'],f['moving_atm'],f['basis_adjusted_futures_vwap_proxy']),(20000,20100,20080))
        self.assertEqual(f['candidate_windows_overlap_count'],9)
    def test_future_vwap_rejected(self):
        trade,minutes,dt=self.fixture();trade['candle_available_at']='2026-10-15T09:25:00+05:30'
        with self.assertRaises(ValueError):features(trade,minutes,dt)
    def test_raw_entry_price_mismatch_rejected(self):
        trade,minutes,dt=self.fixture();trade['entry_price']=20200.
        with self.assertRaises(ValueError):features(trade,minutes,dt)
    def test_tie_rounds_lower(self):self.assertEqual(atm(22525),22500)
    def test_atm_step(self):self.assertEqual(atm(22526),22550)
    def test_band_boundaries(self):self.assertEqual([distance_band(v) for v in (0,10,25,50,100)],['0_TO_10','10_TO_25','25_TO_50','50_TO_100','100_PLUS'])
    def test_invalid_price(self):
        with self.assertRaises(ValueError):atm(float('nan'))
    def test_loss_and_winner_blocked(self):
        rows=[dict(points=v,alignment=True,migration='UNCHANGED',vwap_distance_band='0_TO_10',policies={k:k!='VWAP_AND_ATM_CHANGED' for k in RULES}) for v in (10,-20)]
        rule=summarize(rows)['rules'][2]
        self.assertEqual((rule['losers_blocked'],rule['winners_blocked'],rule['baseline_same_coverage']['points']),(1,1,-10))
    def test_unknown_not_blocked(self):self.assertEqual(summarize([dict(points=-10)])['rules'][1]['blocked']['trades'],0)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--research-root',type=Path,action='append')
    p.add_argument('--output',type=Path,default=Path('data/research/hilega-vwap-atm-relation-20261016'))
    p.add_argument('--test',action='store_true');args=p.parse_args()
    if args.test:
        result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
        raise SystemExit(0 if result.wasSuccessful() else 1)
    if not args.research_root:p.error('--research-root required; may repeat')
    import hilega_vwap_ema10_research as cache
    results=[];failures=[];args.output.mkdir(parents=True,exist_ok=True)
    for root in args.research_root:
        paths=[root/'report.json'] if (root/'report.json').exists() else [root/n/'report.json' for n in ('3-month','1-month','prior-two-months')]
        for path in paths:
            try:
                report=json.loads(path.read_text())
                if report['strategy_version']!=cache.VERSION:raise ValueError('STRATEGY_VERSION_MISMATCH')
                _,minutes=cache.load_minutes(root,report);rows=[]
                for trade in sorted(report['trades'],key=lambda r:cache.dt(r['entry_time'])):
                    row=dict(trade)
                    expected=(row['exit_price']-row['entry_price'])*(1 if row['direction']=='BULLISH' else -1)
                    if not math.isfinite(expected) or abs(expected-row['points'])>1e-5:raise ValueError('TRADE_POINTS_MISMATCH')
                    try:row.update(features(row,minutes,cache.dt))
                    except (ValueError,KeyError,TypeError) as exc:row['feature_issue']=str(exc)
                    rows.append(row)
                item=dict(period=report['period'],source_report=str(path),source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                          status='COMPLETE' if report['status']=='COMPLETE' and all('policies' in r for r in rows) else 'INCOMPLETE',
                          **summarize(rows),trades=rows)
                results.append(item)
            except (ValueError,KeyError,TypeError,OSError) as exc:failures.append(dict(source_report=str(path),error=str(exc)))
    payload=dict(model='HILEGA_VWAP_DISTANCE_FIXED_MOVING_ATM_RESEARCH_V1',status='COMPLETE' if results and not failures and all(r['status']=='COMPLETE' for r in results) else 'INCOMPLETE',
                 observation_only=True,orders_sent=False,results=results,failures=failures,
                 definitions=dict(fixed_atm='Nearest 50-point strike to exact 09:15 NIFTY open; ties lower.',moving_atm='Nearest 50-point strike to confirmed-entry NIFTY price; ties lower.',
                                  vwap_distance='Same-contract futures close minus completed-5m cumulative session futures VWAP.',
                                  proxy='Futures VWAP minus same-boundary futures-minus-NIFTY basis. A translated reference only; not actual spot VWAP.'),
                 warning='Exploratory fixed-baseline filter study, not stateful entry/exit replay or option P&L. ATM movement is a price-derived feature, not OI or option demand. Fixed-vs-moving candidate-window overlap does not establish best strike. Samples overlap; cohort selected retrospectively. Bands and rules require independent forward validation.')
    (args.output/'report.json').write_text(json.dumps(payload,indent=2)+'\n')
    lines=['# VWAP distance and fixed/moving ATM','',payload['warning'],'',
           '| Period | Rule | Taken | Blocked | Unknown | Current points, matched | Rule points | Losers blocked | Winners blocked |',
           '|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for result in results:
        for r in result['rules']:
            lines.append(f"| {result['period']} | {r['rule']} | {r['passed']['trades']} | {r['blocked']['trades']} | {r['unknown']} | {r['baseline_same_coverage']['points']:.2f} | {r['passed']['points']:.2f} | {r['losers_blocked']} | {r['winners_blocked']} |")
        lines+=['','## '+result['period']+' — VWAP × ATM migration','',
                '| VWAP agrees | ATM shift vs signal | Trades | Points | Winners | Losers |','|---|---|---:|---:|---:|---:|']
        for g in result['atm_vwap_groups']:lines.append(f"| {g['vwap_alignment']} | {g['atm_migration']} | {g['trades']} | {g['points']:.2f} | {g['winners']} | {g['losers']} |")
        lines+=['','## '+result['period']+' — distance bands','',
                '| Absolute futures VWAP distance | VWAP agrees | Trades | Points | Winners | Losers |','|---|---|---:|---:|---:|---:|']
        for g in result['distance_groups']:lines.append(f"| {g['band']} | {g['vwap_alignment']} | {g['trades']} | {g['points']:.2f} | {g['winners']} | {g['losers']} |")
        with (args.output/(result['period']+'-trades.csv')).open('w',newline='') as stream:
            fields=['session_date','direction','entry_time','exit_time','points','fixed_atm','moving_atm','atm_shift_strikes','migration','candidate_windows_overlap_count',
                    'vwap_distance_points','vwap_distance_band','fixed_atm_minus_vwap_proxy','moving_atm_minus_vwap_proxy','feature_issue']
            writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(result['trades'])
    lines+=['','Status: '+payload['status'],'','Failures: '+json.dumps(failures)]
    text='\n'.join(lines)+'\n';(args.output/'summary.md').write_text(text);print(text);print('REPORT:',args.output/'report.json')
    raise SystemExit(0 if payload['status']=='COMPLETE' else 2)


if __name__=='__main__':main()
