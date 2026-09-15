from __future__ import annotations
import argparse,json
from pathlib import Path
def n(v): return 'NA' if v is None else f'{v:.2f}'
def yn(v): return 'Y' if v else '-'
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--input',required=True); ap.add_argument('--date'); ap.add_argument('--crosses-only',action='store_true'); a=ap.parse_args(); x=json.loads(Path(a.input).read_text())
    print('Research:',x['research_version']); print('Canonical population:',x['scope']['class_counts']); print('\nCLASS SUMMARY')
    print(f"{'Class':<23}{'Days':>6}{'Above%':>10}{'Below%':>10}{'Crosses':>10}{'|Dist|':>10}{'VWAP↑%':>10}{'VWAP↓%':>10}{'3cp days':>10}")
    for c,s in x['class_summary'].items(): print(f"{c:<23}{s['session_count']:>6}{n(s['median_above_pct']):>10}{n(s['median_below_pct']):>10}{n(s['median_cross_count']):>10}{n(s['median_abs_distance_points']):>10}{n(s['median_rising_vwap_pct']):>10}{n(s['median_falling_vwap_pct']):>10}{s['sessions_with_3cp_aligned_acceptance']:>10}")
    if a.date:
        s=next((z for z in x['sessions'] if z['session_date']==a.date),None)
        if not s: raise SystemExit(f'Date {a.date} not present')
        print(f"\nCHART VALIDATION: {a.date} {s['day_class']}"); print('Candle = 5m START label; Available = after candle has closed.')
        print(f"{'Candle':>7}{'Available':>11}{'Close':>11}{'VWAP':>11}{'Dist':>9}{'Side':>8}{'Cross':>13}{'Slope':>10}{'P2':>4}{'P3':>4}{'P4':>4}")
        for b in s['candles']:
            if a.crosses_only and b['cross']=='NONE': continue
            av=b['decision_available_at'][11:16]
            print(f"{b['candle_label']:>7}{av:>11}{n(b['close']):>11}{n(b['vwap']):>11}{n(b['distance_points']):>9}{b['side']:>8}{b['cross']:>13}{b['vwap_slope']:>10}{yn(b['accept_2cp']):>4}{yn(b['accept_3cp']):>4}{yn(b['accept_4cp']):>4}")
if __name__=='__main__': main()
