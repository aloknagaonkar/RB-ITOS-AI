
from __future__ import annotations
import argparse, json
from pathlib import Path

def M(v):
    return "NA" if v is None else f"{v/1_000_000:+.2f}M"
def N(v):
    return "NA" if v is None else f"{v:.2f}"
def P(v):
    return "NA" if v is None else f"{v:.1f}%"
def Y(v): return "Y" if v else "-"

def print_summary(x):
    print("SUMMARY")
    print(
        f"{'Group':<36}{'N':>5}{'|Imb|':>9}{'PCRΔ':>8}"
        f"{'P2':>8}{'P3':>8}{'P4':>8}"
        f"{'+10 win':>10}{'med+10':>9}{'+20 win':>10}{'med+20':>9}"
    )
    for k,s in x["summary"].items():
        print(
            f"{k:<36}{s['events']:>5}{M(s['median_abs_imbalance_5m']):>9}"
            f"{N(s['median_pcr_change_5m']):>8}"
            f"{P(s['p2_pct']):>8}{P(s['p3_pct']):>8}{P(s['p4_pct']):>8}"
            f"{P(s['plus10_positive_pct']):>10}{N(s['median_plus10']):>9}"
            f"{P(s['plus20_positive_pct']):>10}{N(s['median_plus20']):>9}"
        )

def print_events(rows):
    print("\nP1 + CAUSAL VWAP CHART TABLE")
    print(
        f"{'Date':<11}{'Day':<6}{'P1':>6}{'Dir':>6}"
        f"{'CEΔ':>9}{'PEΔ':>9}{'Imb':>9}{'PCR':>7}{'PCRΔ':>8}{'SessImb':>10}"
        f"{'P2':>4}{'P3':>4}{'P4':>4}"
        f"{'VWbar':>7}{'Avail':>7}{'FutC':>10}{'VWAP':>10}{'Dist':>8}{'Side':>7}{'Slope':>9}"
        f"{'A':>3}{'AS':>4}"
        f"{'+5':>8}{'+10':>8}{'+15':>8}{'+20':>8}"
    )
    for r in rows:
        day="BULL" if r["day_class"]=="BULLISH_TREND_DAY" else "BEAR"
        print(
            f"{r['session_date']:<11}{day:<6}{r['p1_time']:>6}{r['direction'][:4]:>6}"
            f"{M(r['ce_delta_5m']):>9}{M(r['pe_delta_5m']):>9}{M(r['imbalance_5m']):>9}"
            f"{N(r['pcr_current_5m']):>7}{N(r['pcr_change_5m']):>8}{M(r['session_imbalance']):>10}"
            f"{Y(r['p2']):>4}{Y(r['p3']):>4}{Y(r['p4']):>4}"
            f"{r['vwap_candle']:>7}{r['vwap_available']:>7}"
            f"{N(r['fut_close']):>10}{N(r['vwap']):>10}{N(r['vwap_distance']):>8}"
            f"{r['vwap_side']:>7}{r['vwap_slope']:>9}"
            f"{Y(r['vwap_side_aligned']):>3}{Y(r['vwap_full_aligned']):>4}"
            f"{N(r['plus_5m']):>8}{N(r['plus_10m']):>8}{N(r['plus_15m']):>8}{N(r['plus_20m']):>8}"
        )

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--input",required=True)
    ap.add_argument("--date")
    ap.add_argument("--aligned-only",action="store_true")
    args=ap.parse_args()

    x=json.loads(Path(args.input).read_text())
    print("Research:",x["research_version"])
    print("Population:",x["population"])
    print("Integrity:",x["integrity"])
    print()
    print_summary(x)

    rows=x["events"]
    if args.date:
        rows=[r for r in rows if r["session_date"]==args.date]
    if args.aligned_only:
        rows=[r for r in rows if r["vwap_side_aligned"]]
    print_events(rows)

    print("\nLegend: A=VWAP side aligned; AS=VWAP side + slope aligned.")
    print("VWbar is the last fully completed 5m futures candle usable at P1.")
    print("Same-label P1 candle is stored in JSON/CSV for visual chart checking, but is not causal at P1.")

if __name__=="__main__":
    main()
