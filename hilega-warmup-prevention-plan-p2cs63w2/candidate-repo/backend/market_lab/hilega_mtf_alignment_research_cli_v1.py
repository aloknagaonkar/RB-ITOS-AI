from __future__ import annotations

import argparse
import json
from datetime import date

from .hilega_mtf_alignment_research_v1 import run_research


DEFAULT_DATES = [
    "2026-09-04",
    "2026-09-07",
    "2026-09-08",
    "2026-09-09",
    "2026-09-10",
    "2026-09-11",
    "2026-09-14",
    "2026-09-15",
    "2026-09-16",
    "2026-09-17",
    "2026-09-18",
    "2026-09-21",
    "2026-09-22",
    "2026-09-23",
]


def main() -> None:
    p = argparse.ArgumentParser(
        prog="python -m market_lab.hilega_mtf_alignment_research_cli_v1",
        description="Research-only 5m/10m/15m Hilega entry alignment comparison.",
    )
    p.add_argument("--dates", nargs="+", default=DEFAULT_DATES)
    p.add_argument(
        "--cache-root",
        default="data/historical-evidence/hilega-milega-underlying-cache-v1",
    )
    p.add_argument(
        "--replay-root",
        default="data/historical-evidence/hilega-directional-replay-v1",
    )
    p.add_argument(
        "--output-root",
        default="data/historical-evidence/hilega-mtf-alignment-research-v1/14-session-v1",
    )
    p.add_argument("--warmup-calendar-days", type=int, default=45)
    args = p.parse_args()

    result = run_research(
        dates=[date.fromisoformat(x) for x in args.dates],
        cache_root=args.cache_root,
        replay_root=args.replay_root,
        output_root=args.output_root,
        warmup_calendar_days=args.warmup_calendar_days,
    )
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
