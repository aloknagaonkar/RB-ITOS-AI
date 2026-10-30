from __future__ import annotations
import argparse,json
from pathlib import Path
OFFSETS=(-10,-5,0,5,10,15,20)

def m(v): return "NA" if v is None else f"{v/1_000_000:+.2f}M"
def p(v): return "NA" if v is None else f"{v:+.2f}%"
def d(v): return "NA" if v is None else f"{v:.3f}"
def med(s): return None if not s else s.get("median")

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--input",required=True); a=ap.parse_args()
    x=json.loads(Path(a.input).read_text())
    print("Research:",x["research_version"])
    print("Population:",x["population"])
    print("Short-term:",x["definitions"]["short_term_primary"])
    print("Session context:",x["definitions"]["session_context_primary"])
    for dc in ("BULLISH_TREND_DAY","BEARISH_TREND_DAY"):
        print("\n"+"="*190); print(dc); print("="*190)
        print(f"{'Off':>4} {'Days':>4} {'Mov CE OI':>11} {'Mov PE OI':>11} "
              f"{'CE5mΔ':>9} {'CE5m%':>8} {'PE5mΔ':>9} {'PE5m%':>8} "
              f"{'5mAct':>9} {'5mImb':>9} {'09:20CE':>10} {'09:20PE':>10} "
              f"{'CEdayΔ':>10} {'CEday%':>9} {'PEdayΔ':>10} {'PEday%':>9} "
              f"{'SessAct':>9} {'SessImb':>9} {'PCR09:20':>9} {'PCRnow':>8} {'PCRdayΔ':>8}")
        for off in OFFSETS:
            s=x["by_class_offset"][dc][str(off)]
            print(f"{off:>+4} {s['day_count']:>4} "
                  f"{m(med(s['ce_current_oi'])):>11} {m(med(s['pe_current_oi'])):>11} "
                  f"{m(med(s['ce_delta_5m'])):>9} {p(med(s['ce_pct_5m'])):>8} "
                  f"{m(med(s['pe_delta_5m'])):>9} {p(med(s['pe_pct_5m'])):>8} "
                  f"{m(med(s['activity_5m'])):>9} {m(med(s['imbalance_5m'])):>9} "
                  f"{m(med(s['ce_0920_oi'])):>10} {m(med(s['pe_0920_oi'])):>10} "
                  f"{m(med(s['ce_session_delta'])):>10} {p(med(s['ce_session_pct'])):>9} "
                  f"{m(med(s['pe_session_delta'])):>10} {p(med(s['pe_session_pct'])):>9} "
                  f"{m(med(s['session_activity'])):>9} {m(med(s['session_imbalance'])):>9} "
                  f"{d(med(s['pcr_0920'])):>9} {d(med(s['pcr_current_fixed'])):>8} "
                  f"{d(med(s['pcr_session_change'])):>8}")
    print("\n"+"="*120); print("PERSISTENCE / MINIMUM EVIDENCE"); print("="*120)
    print(f"{'Class':<20} {'Ncp':>3} {'Match%':>8} {'Current OI':>12} {'5m activity':>12} "
          f"{'|5m imbalance|':>15} {'Session activity':>16} {'|Session imbalance|':>19}")
    for dc in ("BULLISH_TREND_DAY","BEARISH_TREND_DAY"):
        for n in ("1","2","3","4"):
            s=x["persistence_evidence"][dc][n]
            print(f"{dc:<20} {n:>3} {p(s['matching_endpoint_pct']):>8} "
                  f"{m(med(s['current_total_oi'])):>12} {m(med(s['activity_5m'])):>12} "
                  f"{m(med(s['abs_imbalance_5m'])):>15} {m(med(s['session_activity'])):>16} "
                  f"{m(med(s['abs_session_imbalance'])):>19}")

if __name__=="__main__":
    main()
