from __future__ import annotations
import argparse,json
from pathlib import Path

def m(v):
    return "NA" if v is None else f"{v/1_000_000:+.2f}M"
def pct(v):
    return "NA" if v is None else f"{v:+.2f}%"
def dec(v):
    return "NA" if v is None else f"{v:.3f}"

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--input",required=True)
    args=ap.parse_args()
    x=json.loads(Path(args.input).read_text())

    print("Research:",x["research_version"])
    print("Mode:",x["discovery_mode"])
    print("Population:",x["population"])

    for dc in ("BULLISH_TREND_DAY","BEARISH_TREND_DAY"):
        print()
        print("="*128)
        print(dc)
        print("="*128)
        print(f"{'Offset':>6} {'Days':>4} {'CE Δ':>10} {'CE %':>9} {'PE Δ':>10} {'PE %':>9} "
              f"{'Activity':>10} {'Imbal':>10} {'Imbal +%':>9} {'Imbal -%':>9} "
              f"{'PCR prev':>9} {'PCR cur':>9} {'PCR Δ':>9}")
        for e in x["candidate_template_evidence"][dc]:
            print(
                f"{e['offset_minutes']:>+6} {e['day_count']:>4} "
                f"{m(e['median_ce_delta']):>10} {pct(e['median_ce_pct']):>9} "
                f"{m(e['median_pe_delta']):>10} {pct(e['median_pe_pct']):>9} "
                f"{m(e['median_activity']):>10} {m(e['median_imbalance']):>10} "
                f"{pct(e['positive_imbalance_pct']):>9} {pct(e['negative_imbalance_pct']):>9} "
                f"{dec(e['median_pcr_previous']):>9} {dec(e['median_pcr_current']):>9} "
                f"{dec(e['median_pcr_change']):>9}"
            )
        print("\nSign-combo percentages:")
        for e in x["candidate_template_evidence"][dc]:
            combos=", ".join(f"{k}={v:.1f}%" for k,v in sorted(e["sign_combo_pct"].items()))
            print(f"  {e['offset_minutes']:+}m: {combos}")

if __name__=="__main__":
    main()
