from __future__ import annotations
import argparse,json
from pathlib import Path

def m(v):
    return "NA" if v is None else f"{v/1_000_000:+.2f}M"

def p(v):
    return "NA" if v is None else f"{v:+.2f}%"

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--input",required=True)
    ap.add_argument("--last",type=int,default=12)
    a=ap.parse_args()
    x=json.loads(Path(a.input).read_text())
    rows=x["matches"][-a.last:]
    for item in rows:
        c=item["current"]
        print("\n"+"="*120)
        print(
            f"{c['session_date']} {c['time']}  ATM={c['moving_atm']:.0f}  "
            f"family={c['pattern_family']}"
        )
        print(
            f"±2 CE Δ {m(c['m_ce_delta'])} ({p(c['m_ce_pct'])}) | "
            f"PE Δ {m(c['m_pe_delta'])} ({p(c['m_pe_pct'])}) | "
            f"activity {m(c['m_activity'])} | PCR {c['m_pcr']:.3f} | "
            f"states {c['ce_state']} / {c['pe_state']}"
        )
        print("Nearest historical:")
        for i,h in enumerate(item["nearest_historical"][:5],1):
            print(
                f" {i}. {h['session_date']} {h['time']} d={h['distance']:.3f} "
                f"{h['pattern_family']} activity={m(h['m_activity'])} "
                f"CE={m(h['m_ce_delta'])} PE={m(h['m_pe_delta'])} "
                f"states={h['ce_state']}/{h['pe_state']} "
                f"fwd5={h['forward_5m_points']} "
                f"fwd10={h['forward_10m_points']} "
                f"fwd15={h['forward_15m_points']}"
            )

if __name__=="__main__":
    main()
