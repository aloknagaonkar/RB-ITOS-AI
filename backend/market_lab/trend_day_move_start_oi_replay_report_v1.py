from __future__ import annotations
import argparse, json
from pathlib import Path

def m(v):
    if v is None: return "NA"
    return f"{v/1_000_000:+.2f}M"

def p(v):
    if v is None: return "NA"
    return f"{v:+.2f}%"

def pcr(a,b):
    if a is None or b is None: return "NA"
    return f"{a:.3f}→{b:.3f}"

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--input",required=True)
    ap.add_argument("--class-filter", choices=["BULLISH_TREND_DAY","BEARISH_TREND_DAY","ALL"], default="ALL")
    ap.add_argument("--mode", choices=["ATM","Moving ±2","Fixed ±2","ALL"], default="ALL")
    args=ap.parse_args()

    x=json.loads(Path(args.input).read_text())
    summaries={d["session_date"]:d for d in x["day_summaries"]}

    for ds in sorted(summaries):
        d=summaries[ds]
        if d.get("status")!="AVAILABLE":
            continue
        if args.class_filter!="ALL" and d["day_class"]!=args.class_filter:
            continue
        print()
        print("="*110)
        print(f"{ds}  {d['day_class']}  MOVE START={d['move_start_time']}  move_from_anchor={d['move_points_from_anchor']:+.2f} pts")
        print("="*110)
        print(f"{'Time':<7} {'Mode':<11} {'CE OI change':>13} {'CE %':>9} {'PE OI change':>13} {'PE %':>9} {'Activity':>11} {'PCR':>15}")
        rows=[r for r in x["rows"] if r["session_date"]==ds]
        rows.sort(key=lambda r:(r["timestamp"], {"ATM":0,"Moving ±2":1,"Fixed ±2":2}.get(r["mode"],9)))
        for r in rows:
            if args.mode!="ALL" and r["mode"]!=args.mode:
                continue
            star="*" if r["offset_minutes"]==0 else " "
            print(
                f"{star}{r['time']:<6} {r['mode']:<11} "
                f"{m(r['ce_delta']):>13} {p(r['ce_pct']):>9} "
                f"{m(r['pe_delta']):>13} {p(r['pe_pct']):>9} "
                f"{m(r['activity']):>11} "
                f"{pcr(r['pcr_previous'],r['pcr_current']):>15}"
            )

if __name__=="__main__":
    main()
