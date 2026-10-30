
from __future__ import annotations
import argparse, json
from collections import defaultdict
from pathlib import Path

BULL="BULLISH_TREND_DAY"
BEAR="BEARISH_TREND_DAY"

def m(v):
    return "NA" if v is None else f"{v/1_000_000:+.2f}M"
def n(v):
    return "NA" if v is None else f"{v:.2f}"
def y(v): return "Y" if v else "-"

def render_session(date, day_class, rows):
    out=[]
    label="BULLISH TREND DAY" if day_class==BULL else "BEARISH TREND DAY"
    out.append("="*170)
    out.append(f"{date}  {label}  P1 EVENTS={len(rows)}")
    out.append("="*170)
    out.append(
        f"{'P1':>5} {'Dir':>5} {'Spot':>9} {'ATM':>8} "
        f"{'CEΔ5':>9} {'PEΔ5':>9} {'Imb5':>9} {'PCR':>6} {'PCRΔ':>7} {'SessImb':>10} "
        f"{'P2':>3} {'P3':>3} {'P4':>3} | "
        f"{'VW candle':>9} {'Avail':>5} {'O':>9} {'H':>9} {'L':>9} {'C':>9} {'VWAP':>9} {'Dist':>8} {'Side':>6} {'Slope':>7} {'A':>2} {'AS':>3} | "
        f"{'+5':>7} {'+10':>7} {'+15':>7} {'+20':>7}"
    )
    for r in rows:
        out.append(
            f"{r['p1_time']:>5} {r['direction'][:4]:>5} {n(r['spot_close']):>9} {n(r['moving_atm']):>8} "
            f"{m(r['ce_delta_5m']):>9} {m(r['pe_delta_5m']):>9} {m(r['imbalance_5m']):>9} "
            f"{n(r['pcr_current_5m']):>6} {n(r['pcr_change_5m']):>7} {m(r['session_imbalance']):>10} "
            f"{y(r['p2']):>3} {y(r['p3']):>3} {y(r['p4']):>3} | "
            f"{r['vwap_candle']:>9} {r['vwap_available']:>5} "
            f"{n(r['fut_open']):>9} {n(r['fut_high']):>9} {n(r['fut_low']):>9} {n(r['fut_close']):>9} "
            f"{n(r['vwap']):>9} {n(r['vwap_distance']):>8} {r['vwap_side']:>6} {r['vwap_slope']:>7} "
            f"{y(r['vwap_side_aligned']):>2} {y(r['vwap_full_aligned']):>3} | "
            f"{n(r['plus_5m']):>7} {n(r['plus_10m']):>7} {n(r['plus_15m']):>7} {n(r['plus_20m']):>7}"
        )
    out.append("")
    return out

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output")
    ap.add_argument("--date")
    args=ap.parse_args()

    x=json.loads(Path(args.input).read_text())
    sessions=defaultdict(list)
    classes={}
    for r in x["events"]:
        sessions[r["session_date"]].append(r)
        classes[r["session_date"]]=r["day_class"]

    for rows in sessions.values():
        rows.sort(key=lambda r:r["p1_time"])

    bulls=sorted(d for d,c in classes.items() if c==BULL)
    bears=sorted(d for d,c in classes.items() if c==BEAR)

    if len(bulls)!=18 or len(bears)!=18:
        raise RuntimeError(f"Expected 18 bullish + 18 bearish sessions; got {len(bulls)} + {len(bears)}")

    out=[]
    out.append("OI P1 + VWAP — 36 SESSION DETAILED CHART VALIDATION")
    out.append("")
    out.append("BULLISH TREND SESSIONS (18)")
    out.append(", ".join(bulls))
    out.append("")
    out.append("BEARISH TREND SESSIONS (18)")
    out.append(", ".join(bears))
    out.append("")
    out.append("Timing: VW candle is the LAST COMPLETED 5m futures candle available at the P1 timestamp.")
    out.append("A=VWAP side aligned with OI direction. AS=VWAP side + VWAP slope aligned.")
    out.append("Forward +5/+10/+15/+20 are direction-adjusted underlying points from the P1 event.")
    out.append("")

    selected = [args.date] if args.date else bulls+bears
    for d in selected:
        if d not in sessions:
            raise RuntimeError(f"Session not found: {d}")
        out.extend(render_session(d, classes[d], sessions[d]))

    text="\n".join(out)
    print(text)
    if args.output:
        Path(args.output).write_text(text+"\n")
        print(f"\nSaved: {args.output}")

if __name__=="__main__":
    main()
