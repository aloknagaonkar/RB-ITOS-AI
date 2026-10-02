from __future__ import annotations

import argparse
import json
from datetime import date

from .hilega_directional_pe_historical_shadow_v1 import (
    replay_pe_shadow_from_directional_summary,
)


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="python -m market_lab.hilega_directional_pe_historical_shadow_cli_v1"
    )
    ap.add_argument(
        "--directional-summary",
        default="data/historical-evidence/hilega-directional-replay-v1/multi-session-directional-summary.json",
    )
    ap.add_argument(
        "--output-root",
        default="data/historical-evidence/hilega-directional-pe-shadow-v1",
    )
    ap.add_argument("--data-root", default="data")
    ap.add_argument("--dates", nargs="*")
    ap.add_argument("--expected-expiry")
    ap.add_argument("--strike-step", type=float, default=50.0)
    args = ap.parse_args()

    result = replay_pe_shadow_from_directional_summary(
        directional_summary_path=args.directional_summary,
        output_root=args.output_root,
        data_root=args.data_root,
        dates=[date.fromisoformat(x) for x in args.dates] if args.dates else None,
        expected_expiry=args.expected_expiry,
        strike_step=args.strike_step,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
