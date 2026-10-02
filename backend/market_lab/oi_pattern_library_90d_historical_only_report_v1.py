from __future__ import annotations
import argparse, json
from pathlib import Path

def m(v):
    return "NA" if v is None else f"{v/1_000_000:.2f}M"

def pct(n,d):
    return None if not d else n/d*100.0

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--input",required=True)
    a=ap.parse_args()

    x=json.loads(Path(a.input).read_text())

    print("Research:",x["research_version"])
    print("Sessions:",x["scope"]["selected_session_count"],
          x["scope"]["first_session"],"to",x["scope"]["last_session"])
    print("Checkpoints:",x["checkpoint_count"])
    print("Primary strength:",x["primary_strength"]["source"])

    print("\nPATTERN FAMILY SUMMARY")
    for fam,s in sorted(
        x["pattern_family_outcomes"].items(),
        key=lambda kv: kv[1]["count"],
        reverse=True,
    ):
        c=s["count"]
        p5=pct(s["forward_5m_positive_count"],s["forward_5m_positive_count"]+s["forward_5m_negative_count"])
        p10=pct(s["forward_10m_positive_count"],s["forward_10m_positive_count"]+s["forward_10m_negative_count"])
        p15=pct(s["forward_15m_positive_count"],s["forward_15m_positive_count"]+s["forward_15m_negative_count"])
        print(
            f"{fam:34} n={c:4d} med_activity={m(s['median_activity']):>8} "
            f"spot_up_5m={p5 if p5 is not None else 'NA'} "
            f"spot_up_10m={p10 if p10 is not None else 'NA'} "
            f"spot_up_15m={p15 if p15 is not None else 'NA'}"
        )

if __name__=="__main__":
    main()
