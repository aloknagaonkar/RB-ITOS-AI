
from __future__ import annotations
import argparse,json
from pathlib import Path

def M(v):
    return "NA" if v is None else f"{v/1_000_000:+.2f}M"
def N(v):
    return "NA" if v is None else f"{v:.2f}"
def Y(v): return "Y" if v else "-"

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--input",required=True)
    ap.add_argument("--date")
    ap.add_argument("--aligned-only",action="store_true")
    a=ap.parse_args()
    x=json.loads(Path(a.input).read_text())

    print("Research:",x["research_version"])
    print("Events:",x["event_count"])
    print("CAUSAL rule: VWAP candle must already be completed at P1 time.")
    print("Same-label candle is chart-reference only and is NOT used for P1 alignment.\n")

    print("SUMMARY")
    for d,s in x["summary"].items():
        print(f"{d}: {s['vwap_aligned_count']}/{s['events']} aligned ({s['vwap_aligned_pct']:.1f}%) "
              f"med|imb| aligned={M(s['median_abs_imbalance_aligned'])} "
              f"med+10={N(s['median_plus10_aligned'])} med+20={N(s['median_plus20_aligned'])}")

    rows=x["events"]
    if a.date:
        rows=[r for r in rows if r["session_date"]==a.date]
    if a.aligned_only:
        rows=[r for r in rows if r["vwap_aligned_at_p1"]]

    print("\nEVENT / CHART VALIDATION")
    print(f"{'Date':<11}{'Class':<7}{'P1':>6}{'Dir':>6}{'CE5Δ':>9}{'PE5Δ':>9}{'Imb':>9}{'PCRΔ':>8}"
          f"{'P2':>4}{'P3':>4}{'P4':>4}"
          f"{'VWbar':>7}{'Avail':>7}{'FutC':>10}{'VWAP':>10}{'Dist':>8}{'Side':>7}{'Cross':>12}{'Slope':>9}{'Align':>7}"
          f"{'SameLbl':>9}{'SameAv':>8}{'+10':>8}{'+20':>8}")
    for r in rows:
        cls="BULL" if r["day_class"]=="BULLISH_TREND_DAY" else ("BEAR" if r["day_class"]=="BEARISH_TREND_DAY" else "MIX")
        print(f"{r['session_date']:<11}{cls:<7}{r['event_time']:>6}{r['direction'][:4]:>6}"
              f"{M(r.get('ce_5m_delta')):>9}{M(r.get('pe_5m_delta')):>9}{M(r.get('imbalance')):>9}{N(r.get('pcr_5m_change')):>8}"
              f"{Y(r.get('p2')):>4}{Y(r.get('p3')):>4}{Y(r.get('p4')):>4}"
              f"{r['causal_vwap_candle']:>7}{r['causal_vwap_available']:>7}{N(r['causal_fut_close']):>10}{N(r['causal_vwap']):>10}"
              f"{N(r['causal_vwap_distance']):>8}{r['causal_vwap_side']:>7}{r['causal_vwap_cross']:>12}{r['causal_vwap_slope']:>9}"
              f"{Y(r['vwap_aligned_at_p1']):>7}"
              f"{str(r.get('same_label_candle') or '-'):>9}{str(r.get('same_label_close_available') or '-'):>8}"
              f"{N(r.get('plus_10m')):>8}{N(r.get('plus_20m')):>8}")

if __name__=="__main__":
    main()
