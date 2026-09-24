from __future__ import annotations

import argparse
import json
from datetime import date

from .hilega_directional_ce_historical_shadow_v1 import (
    replay_ce_shadow_from_directional_summary,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m market_lab.hilega_directional_ce_historical_shadow_cli_v1"
    )
    parser.add_argument("--dates", nargs="+", required=True)
    parser.add_argument(
        "--directional-summary-path",
        default="data/historical-evidence/hilega-directional-replay-v1/multi-session-directional-summary.json",
    )
    parser.add_argument(
        "--output-root",
        default="data/historical-evidence/hilega-directional-ce-shadow-v1",
    )
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--expected-expiry")
    parser.add_argument("--strike-step", type=float, default=50.0)
    args = parser.parse_args()

    result = replay_ce_shadow_from_directional_summary(
        directional_summary_path=args.directional_summary_path,
        output_root=args.output_root,
        data_root=args.data_root,
        dates=[date.fromisoformat(x) for x in args.dates],
        expected_expiry=args.expected_expiry,
        strike_step=args.strike_step,
    )
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
