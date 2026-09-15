from __future__ import annotations
import argparse,json
from pathlib import Path

def M(v): return "NA" if v is None else f"{v/1_000_000:.2f}M"
def P(v): return "NA" if v is None else f"{v:.1f}%"
def N(v): return "NA" if v is None else f"{v:.2f}"
def med(s): return None if not s else s.get("median")

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--input",required=True); a=ap.parse_args()
    x=json.loads(Path(a.input).read_text())
    print("Research:",x["research_version"])
    print("Population:",x["population"])
    print("Bullish:",x["definitions"]["candidate_bullish"])
    print("Bearish:",x["definitions"]["candidate_bearish"])
    print()

    print("="*150)
    print("GROUP SUMMARY")
    print("="*150)
    print(f"{'Day class':<22} {'Signal':<8} {'Events':>6} {'Days':>5} {'P2':>7} {'P3':>7} {'P4':>7} "
          f"{'5mAct':>9} {'|5mImb|':>9} {'SessAct':>9} {'|SessImb|':>10} "
          f"{'+5m':>8} {'+10m':>8} {'+15m':>8} {'+20m':>8}")
    for dc in ("BULLISH_TREND_DAY","BEARISH_TREND_DAY","MIXED_DAY"):
        for sig in ("BULLISH","BEARISH"):
            s=x["group_summary"][dc][sig]
            print(f"{dc:<22} {sig:<8} {s['event_count']:>6} {s['session_count']:>5} "
                  f"{P(s['persists_2cp_pct']):>7} {P(s['persists_3cp_pct']):>7} {P(s['persists_4cp_pct']):>7} "
                  f"{M(med(s['activity_5m'])):>9} {M(med(s['abs_imbalance_5m'])):>9} "
                  f"{M(med(s['session_activity'])):>9} {M(med(s['abs_session_imbalance'])):>10} "
                  f"{N(med(s['directional_move_5m_points'])):>8} "
                  f"{N(med(s['directional_move_10m_points'])):>8} "
                  f"{N(med(s['directional_move_15m_points'])):>8} "
                  f"{N(med(s['directional_move_20m_points'])):>8}")

    print("\n"+"="*150)
    print("PER-DAY FIRST DETECTION + NUMBER OF OCCURRENCES")
    print("="*150)
    print(f"{'Date':<12} {'Class':<20} {'Bull#':>5} {'First bull candle':>17} {'Bear#':>5} {'First bear candle':>17}")
    for s in sorted(x["session_summary"],key=lambda r:r["session_date"]):
        print(f"{s['session_date']:<12} {s['day_class']:<20} {s['bullish_occurrences']:>5} "
              f"{str(s['first_bullish_candle'] or '-'):>17} {s['bearish_occurrences']:>5} "
              f"{str(s['first_bearish_candle'] or '-'):>17}")

    print("\n"+"="*190)
    print("EVENT DETAIL FOR CHART VALIDATION")
    print("="*190)
    print(f"{'Date':<12} {'Class':<19} {'Signal':<8} {'#':>2} {'Candle':>6} {'Spot':>9} {'ATM':>8} "
          f"{'CE5mΔ':>10} {'PE5mΔ':>10} {'5mImb':>10} {'PCR5mΔ':>9} "
          f"{'CEdayΔ':>10} {'PEdayΔ':>10} {'SessImb':>10} {'PCRdayΔ':>9} "
          f"{'P2':>3} {'P3':>3} {'P4':>3} {'+10m':>8} {'+20m':>8}")
    for e in sorted(x["events"],key=lambda r:(r["session_date"],r["timestamp"],r["direction"])):
        def mm(v): return "NA" if v is None else f"{v/1_000_000:+.2f}M"
        def dd(v): return "NA" if v is None else f"{v:+.3f}"
        def yy(v): return "Y" if v else "-"
        print(f"{e['session_date']:<12} {e['day_class']:<19} {e['direction']:<8} {e['occurrence_number']:>2} "
              f"{e['candle_time']:>6} {N(e['spot_close']):>9} {N(e['moving_atm']):>8} "
              f"{mm(e['ce_delta_5m']):>10} {mm(e['pe_delta_5m']):>10} {mm(e['imbalance_5m']):>10} "
              f"{dd(e['pcr_change_5m']):>9} {mm(e['ce_session_delta']):>10} {mm(e['pe_session_delta']):>10} "
              f"{mm(e['session_imbalance']):>10} {dd(e['pcr_session_change']):>9} "
              f"{yy(e['persists_2cp']):>3} {yy(e['persists_3cp']):>3} {yy(e['persists_4cp']):>3} "
              f"{N(e.get('directional_move_10m_points')):>8} {N(e.get('directional_move_20m_points')):>8}")

if __name__=="__main__":
    main()
