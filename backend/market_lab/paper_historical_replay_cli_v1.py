from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m market_lab.paper_historical_replay_cli_v1"
    )
    parser.add_argument("--config-id", type=int, required=True)
    parser.add_argument("--session-date", action="append", required=True)
    parser.add_argument("--futures-json", required=True)
    args = parser.parse_args()

    print(json.dumps({
        "status": "READY_FOR_ADAPTER",
        "config_id": args.config_id,
        "session_dates": args.session_date,
        "futures_json": str(Path(args.futures_json)),
        "message": (
            "Replay core installed. Repository-specific historical futures/option "
            "adapter must be wired after inspecting the actual stored file format."
        ),
    }, indent=2))


if __name__ == "__main__":
    main()
