
from __future__ import annotations
import argparse, json
from pathlib import Path

def M(v):
    return "NA" if v is None else f"{v/1_000_000:+.2f}M"
def N(v):
    return "NA" if v is None else f"{v:.2f}"
def Y(v): return "Y" if v else "-"

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--date")
    ap.add_argument("--aligned-only", action="store_true")
    args=ap.parse_args()

    x=json.loads(Path(args.input).read_text())
    print("Research:", x["research_version"])
    print("Population:", x["population"])
    print("Integrity:", x["integrity"])
    print("\nSUMMARY")
    for k,s in x["summary"].items():
        print(
            f"{k:<22} n={s['events']:>4} "
            f"med|imb|={M(s['median_abs_imbalance']):>8} "
            f"P2={N(s['p2_pct']):>6}% P3={N(s['p3_pct']):>6}% P4={N(s['p4_pct']):>6}% "
            f"+10pos={N(s['plus10_positive_pct']):>6}% med10={N(s['median_plus10']):>7} "
            f"+20pos={N(s['plus20_positive_pct']):>6}% med20={N(s['median_plus20']):>7}"
        )

    rows=x["events"]
    if args.date:
        rows=[r for r in rows if r["session_date"]==args.date]
    if args.aligned_only:
        rows=[r for r in rows if r["vwap_aligned_at_p1"]]

    print("\nP1 + VWAP CHART VALIDATION")
    print(
        f"{'Date':<11}{'Day':<6}{'P1':>6}{'Dir':>6}"
        f"{'CE5Δ':>9}{'PE5Δ':>9}{'Imb':>9}{'PCR':>7}{'PCRΔ':>8}{'SessImb':>10}"
        f"{'P2':>4}{'P3':>4}{'P4':>4}"
        f"{'VWbar':>7}{'Avail':>7}{'FutC':>10}{'VWAP':>10}{'Dist':>8}{'Side':>7}{'Cross':>12}{'Slope':>9}{'Align':>7}"
        f"{'+5':>8}{'+10':>8}{'+15':>8}{'+20':>8}{'Outcome':>16}"
    )
    for r in rows:
        day = "BULL" if r["day_class"]=="BULLISH_TREND_DAY" else "BEAR"
        print(
            f"{r['session_date']:<11}{day:<6}{r['event_time']:>6}{r['direction'][:4]:>6}"
            f"{M(r.get('ce_5m_delta')):>9}{M(r.get('pe_5m_delta')):>9}{M(r.get('imbalance')):>9}"
            f"{N(r.get('pcr_now')):>7}{N(r.get('pcr_5m_change')):>8}{M(r.get('session_imbalance')):>10}"
            f"{Y(r.get('p2')):>4}{Y(r.get('p3')):>4}{Y(r.get('p4')):>4}"
            f"{r['causal_vwap_candle']:>7}{r['causal_vwap_available']:>7}"
            f"{N(r['causal_fut_close']):>10}{N(r['causal_vwap']):>10}{N(r['causal_vwap_distance']):>8}"
            f"{r['causal_vwap_side']:>7}{r['causal_vwap_cross']:>12}{r['causal_vwap_slope']:>9}{Y(r['vwap_aligned_at_p1']):>7}"
            f"{N(r.get('plus_5m')):>8}{N(r.get('plus_10m')):>8}{N(r.get('plus_15m')):>8}{N(r.get('plus_20m')):>8}"
            f"{str(r.get('outcome_20m') or '-'):>16}"
        )

if __name__=="__main__":
    main()
