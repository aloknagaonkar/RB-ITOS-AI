
from __future__ import annotations
import argparse,json
from pathlib import Path

def n(v):
    return "NA" if v is None else f"{v:.2f}"

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--input",required=True)
    a=ap.parse_args()
    x=json.loads(Path(a.input).read_text())

    print("Research:",x["research_version"])
    print("Purpose:",x["purpose"])
    print("\nSUMMARY")
    for k,s in x["summary"].items():
        print(
            f"{k}: days={s['day_count']} "
            f"anchor_aligned={s['anchor_vwap_aligned_count']}/{s['day_count']} "
            f"({s['anchor_vwap_aligned_pct']:.1f}%) "
            f"slope_aligned={s['anchor_slope_aligned_count']}/{s['day_count']} "
            f"({s['anchor_slope_aligned_pct']:.1f}%) "
            f"aligned_cross+P3_days={s['aligned_cross_p3_days']} "
            f"median_P3_lead={n(s['median_p3_lead_minutes_to_move_start'])}m "
            f"median_run_start_lead={n(s['median_run_start_lead_minutes_to_move_start'])}m"
        )

    print("\n36 CONCRETE EXAMPLES")
    print(
        f"{'Date':<11}{'Class':<8}{'Move':>7}{'Pts':>9}"
        f"{'P3':>7}{'P3Avail':>9}{'P3Lead':>9}"
        f"{'CrossP3':>9}{'RunStart':>10}"
        f"{'Anchor':>8}{'Dist':>9}{'Slope':>10}{'Aligned':>9}"
    )
    for r in x["examples"]:
        cls="BULL" if r["direction"]=="BULLISH" else "BEAR"
        print(
            f"{r['session_date']:<11}{cls:<8}{r['move_start_candle']:>7}"
            f"{r['move_points_from_anchor']:>9.2f}"
            f"{str(r['first_p3_candle'] or '-'):>7}"
            f"{str(r['first_p3_available'] or '-'):>9}"
            f"{n(r['p3_lead_minutes_to_move_start']):>9}"
            f"{str(r['first_aligned_cross_p3_candle'] or '-'):>9}"
            f"{str(r['aligned_run_start_candle'] or '-'):>10}"
            f"{str(r['anchor_vwap_side'] or '-'):>8}"
            f"{n(r['anchor_distance_points']):>9}"
            f"{str(r['anchor_vwap_slope'] or '-'):>10}"
            f"{('Y' if r['anchor_aligned'] else 'N'):>9}"
        )

    print("\nCAUSALITY NOTE")
    print("VWAP candle states are causal at Available time.")
    print("Trend-day class and move-start anchor are retrospective research labels, not live signals.")

if __name__=="__main__":
    main()
