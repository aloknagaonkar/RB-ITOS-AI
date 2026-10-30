from __future__ import annotations
import argparse,json
from pathlib import Path

def fmt(v):
    return "NA" if v is None else f"{v:.2f}"

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--input",required=True)
    a=ap.parse_args()
    x=json.loads(Path(a.input).read_text())
    print("Research:",x["research_version"])
    print("Frozen days:",x["frozen_inputs"]["bullish_count"],"bullish +",x["frozen_inputs"]["bearish_count"],"bearish")
    print("Checkpoints:",x["checkpoint_count"])

    for dc in ("BULLISH_TREND_DAY","BEARISH_TREND_DAY"):
        print("\n",dc)
        for n in ("1","2","3","4"):
            s=x["overall"][dc][n]
            print(
                f"{n} checkpoints: same-sign={s['same_sign_persistence_count']}/{s['available_count']} "
                f"({fmt(s['same_sign_persistence_pct'])}%) "
                f"class-aligned={fmt(s['class_aligned_pct_of_same_sign'])}% "
                f"PCR-agree={fmt(s['pcr_same_sign_agreement_pct_of_same_sign'])}% "
                f"median|imbalance|={s['median_abs_imbalance']}"
            )

    print("\nEARLY WINDOWS")
    for w in ("09:20-10:00","10:00-11:00"):
        print("\n",w)
        for dc in ("BULLISH_TREND_DAY","BEARISH_TREND_DAY"):
            print(dc)
            for n in ("1","2","3","4"):
                s=x["by_time_window"][dc][w][n]
                print(
                    f"  {n}cp aligned={fmt(s['class_aligned_pct_of_same_sign'])}% "
                    f"same-sign={s['same_sign_persistence_count']} "
                    f"PCR-agree={fmt(s['pcr_same_sign_agreement_pct_of_same_sign'])}%"
                )

if __name__=="__main__":
    main()
