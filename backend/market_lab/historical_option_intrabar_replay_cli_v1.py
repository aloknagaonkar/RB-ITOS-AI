from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from .historical_option_intrabar_replay_v1 import replay_intrabar_date


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m market_lab.historical_option_intrabar_replay_cli_v1"
    )
    parser.add_argument("--session-date", required=True)
    parser.add_argument("--data-root", default="data")
    parser.add_argument(
        "--futures-csv",
        default="data/historical-evidence/midpoint-v2-nifty-futures-vwap-v1-development.csv",
    )
    parser.add_argument(
        "--events",
        choices=("all", "exits", "none"),
        default="exits",
    )
    args = parser.parse_args()

    result = replay_intrabar_date(
        args.session_date,
        data_root=args.data_root,
        futures_csv=args.futures_csv,
    )

    payload = {
        "status": "PASS",
        "summary": result.summary(),
        "ohlc_source": result.ohlc_source,
        "trades": [asdict(trade) for trade in result.trades],
    }

    if args.events == "all":
        payload["events"] = [asdict(event) for event in result.events]
    elif args.events == "exits":
        payload["events"] = [
            asdict(event)
            for event in result.events
            if event.event_type == "POSITION_CLOSED"
        ]

    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
