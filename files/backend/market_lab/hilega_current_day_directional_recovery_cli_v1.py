from __future__ import annotations

import argparse
import json
from datetime import date

from .hilega_current_day_directional_recovery_v1 import (
    recover_current_day_directional_timeline,
)


def main() -> None:
    p = argparse.ArgumentParser(
        prog="python -m market_lab.hilega_current_day_directional_recovery_cli_v1"
    )
    p.add_argument("--date", required=True, type=date.fromisoformat)
    p.add_argument(
        "--source-audit",
        default="data/live-observation/hilega-milega-v1/step-audit.jsonl",
    )
    p.add_argument(
        "--supplemental-evidence",
        default=None,
        help=(
            "Recorded market-evidence JSONL. Default: "
            "data/live-observation/hilega-directional-market-evidence-v1/<date>.jsonl"
        ),
    )
    p.add_argument(
        "--output-root",
        default="data/historical-evidence/hilega-directional-replay-v1",
    )
    p.add_argument(
        "--cache-root",
        default="data/historical-evidence/hilega-milega-underlying-cache-v1",
    )
    p.add_argument("--warmup-calendar-days", type=int, default=45)
    p.add_argument("--force", action="store_true")
    a = p.parse_args()

    result = recover_current_day_directional_timeline(
        session_date=a.date,
        source_audit=a.source_audit,
        supplemental_evidence=a.supplemental_evidence,
        output_root=a.output_root,
        cache_root=a.cache_root,
        warmup_calendar_days=a.warmup_calendar_days,
        force=a.force,
    )
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
