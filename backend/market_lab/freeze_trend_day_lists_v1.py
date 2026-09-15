from __future__ import annotations

import argparse
import json
from pathlib import Path

VERSION = "FREEZE_TREND_DAY_LISTS_V1"
EXPECTED_CLASSIFIER = "DAY_TREND_CLASSIFICATION_90D_V1"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--classification", required=True)
    ap.add_argument("--bullish-output", required=True)
    ap.add_argument("--bearish-output", required=True)
    ap.add_argument("--manifest-output", required=True)
    args = ap.parse_args()

    src = Path(args.classification)
    data = json.loads(src.read_text(encoding="utf-8"))

    if data.get("research_version") != EXPECTED_CLASSIFIER:
        raise RuntimeError(
            f"Expected {EXPECTED_CLASSIFIER}, got {data.get('research_version')}"
        )

    sessions = data.get("sessions", [])
    bullish = sorted(
        r["session_date"]
        for r in sessions
        if r.get("day_class") == "BULLISH_TREND_DAY"
    )
    bearish = sorted(
        r["session_date"]
        for r in sessions
        if r.get("day_class") == "BEARISH_TREND_DAY"
    )

    if not bullish or not bearish:
        raise RuntimeError("Bullish/bearish selected day lists are empty.")

    overlap = sorted(set(bullish) & set(bearish))
    if overlap:
        raise RuntimeError(f"Date overlap between bullish and bearish lists: {overlap}")

    bp = Path(args.bullish_output)
    rp = Path(args.bearish_output)
    mp = Path(args.manifest_output)

    for p in (bp, rp, mp):
        p.parent.mkdir(parents=True, exist_ok=True)

    bp.write_text("\n".join(bullish) + "\n", encoding="utf-8")
    rp.write_text("\n".join(bearish) + "\n", encoding="utf-8")

    manifest = {
        "research_version": VERSION,
        "source_research_version": data.get("research_version"),
        "source_classification": str(src),
        "scope": data.get("scope"),
        "methodology": data.get("methodology"),
        "bullish_count": len(bullish),
        "bearish_count": len(bearish),
        "bullish_dates": bullish,
        "bearish_dates": bearish,
        "integrity": {
            "lists_derived_only_from_frozen_price_classifier": True,
            "oi_used_to_choose_dates": False,
            "pcr_used_to_choose_dates": False,
            "manual_date_additions": False,
            "manual_date_removals": False,
            "oos_e_f_g_h_used": False,
            "strategy_rule_changed": False,
            "paper_or_live_action": False
        }
    }
    mp.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "research_version": VERSION,
        "bullish_count": len(bullish),
        "bearish_count": len(bearish),
        "bullish_dates": bullish,
        "bearish_dates": bearish,
        "bullish_output": str(bp),
        "bearish_output": str(rp),
        "manifest_output": str(mp),
    }, indent=2))

if __name__ == "__main__":
    main()
