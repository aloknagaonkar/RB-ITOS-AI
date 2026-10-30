from __future__ import annotations
import argparse,json
from pathlib import Path
def med(s):return None if not s else s.get('median')
def M(v):return 'NA' if v is None else f'{v/1_000_000:.2f}M'
def P(v):return 'NA' if v is None else f'{v:.1f}%'
def N(v):return 'NA' if v is None else f'{v:.2f}'
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--input',required=True);ap.add_argument('--example-date');a=ap.parse_args();x=json.loads(Path(a.input).read_text());ac=x['aligned_transition_comparison']
 print('Research:',x['research_version']);print('Counts:',x['overall_counts']);print('\nALIGNED TREND-DAY TRANSITIONS')
 print(f"{'Group':<12}{'Events':>7}{'CurrOI':>10}{'5mAct':>10}{'|5mImb|':>10}{'SessAct':>10}{'|SessImb|':>10}{'P2':>8}{'P3':>8}{'P4':>8}{'+10m':>9}{'+20m':>9}")
 for label,key in (('SUCCESS','successful'),('FAILED','failed')):
  s=ac[key];print(f"{label:<12}{s['event_count']:>7}{M(med(s['current_total_oi'])):>10}{M(med(s['activity_5m'])):>10}{M(med(s['abs_imbalance_5m'])):>10}{M(med(s['session_activity'])):>10}{M(med(s['abs_session_imbalance'])):>10}{P(s['persists_2cp_pct']):>8}{P(s['persists_3cp_pct']):>8}{P(s['persists_4cp_pct']):>8}{N(med(s['directional_move_10m_points'])):>9}{N(med(s['directional_move_20m_points'])):>9}")
 print('\nFIRST OPPOSITE OI CANDIDATE')
 print(f"{'Origin':<12}{'Events':>7}{'WithOpp':>9}{'MinOpp':>9}{'PtsOpp':>9}{'OppAct':>10}{'|OppImb|':>10}{'OppSess':>10}{'OppWorks':>10}{'OppFails':>10}")
 for label,key in (('SUCCESS','successful_first_opposite'),('FAILED','failed_first_opposite')):
  s=ac[key];print(f"{label:<12}{s['event_count']:>7}{s['with_opposite_count']:>9}{N(med(s['minutes_to_opposite'])):>9}{N(med(s['directional_points_until_opposite'])):>9}{M(med(s['opposite_5m_activity'])):>10}{M(med(s['abs_opposite_5m_imbalance'])):>10}{M(med(s['opposite_session_activity'])):>10}{P(s['opposite_continues_20m_pct']):>10}{P(s['opposite_fails_20m_pct']):>10}")
 if a.example_date:
  print(f'\nEVENT LIFECYCLE {a.example_date}');print(f"{'Time':>6} {'Sig':<8} {'Outcome':<13} {'Spot':>9} {'5mAct':>9} {'5mImb':>9} {'SessImb':>9} {'P2':>3} {'P3':>3} {'P4':>3} {'+10m':>8} {'+20m':>8} {'Opp':>6} {'Min':>5} {'PtsOpp':>8} {'OppImb':>9} {'Opp20m':>8}")
  for e in x['events']:
   if e['session_date']!=a.example_date:continue
   yn=lambda v:'Y' if v else '-'
   print(f"{e['candle_time']:>6} {e['direction']:<8} {e['outcome_20m']:<13} {N(e['spot_close']):>9}{M(e.get('activity_5m')):>9}{M(e.get('imbalance_5m')):>9}{M(e.get('session_imbalance')):>9}{yn(e.get('persists_2cp')):>3}{yn(e.get('persists_3cp')):>3}{yn(e.get('persists_4cp')):>3}{N(e.get('directional_move_10m_points')):>8}{N(e.get('directional_move_20m_points')):>8}{str(e.get('first_opposite_candidate_time') or '-'):>6}{N(e.get('minutes_to_first_opposite_candidate')):>5}{N(e.get('directional_points_until_first_opposite_candidate')):>8}{M(e.get('opposite_imbalance_5m')):>9}{N(e.get('opposite_directional_move_20m_points')):>8}")
if __name__=='__main__':main()
