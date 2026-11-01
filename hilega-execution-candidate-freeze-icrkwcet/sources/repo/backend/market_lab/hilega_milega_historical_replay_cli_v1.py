from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from .gateways import UpstoxGateway
from .hilega_milega_historical_replay_v1 import UNDERLYING, replay_sessions


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m market_lab.hilega_milega_historical_replay_cli_v1"
    )
    parser.add_argument("--dates", nargs="+", required=True)
    parser.add_argument("--underlying", default=UNDERLYING)
    parser.add_argument("--warmup-calendar-days", type=int, default=45)
    parser.add_argument(
        "--cache-root",
        default="data/historical-evidence/hilega-milega-underlying-cache-v1",
    )
    parser.add_argument(
        "--output-root",
        default="data/historical-evidence/hilega-milega-replay-v1",
    )
    parser.add_argument("--refresh-cache", action="store_true")
    args = parser.parse_args()

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    token = os.getenv("UPSTOX_ACCESS_TOKEN", "")
    gateway = UpstoxGateway(token)
    try:
        payload = replay_sessions(
            gateway=gateway,
            dates=[date.fromisoformat(x) for x in args.dates],
            underlying=args.underlying,
            warmup_calendar_days=args.warmup_calendar_days,
            cache_root=args.cache_root,
            output_root=args.output_root,
            refresh_cache=args.refresh_cache,
        )
    finally:
        gateway.close()

    print(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    main()
