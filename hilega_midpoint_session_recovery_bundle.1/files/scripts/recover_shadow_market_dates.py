"""Download exact NIFTY sessions to isolated recovery evidence, never order APIs."""
import argparse
import json
import os
from datetime import date
from pathlib import Path
from dotenv import dotenv_values
from market_lab.upstox_live_shadow_sources_v1 import UpstoxLiveShadowSourcesV1
from market_lab.hilega_milega_historical_replay_v1 import (
    UNDERLYING, aggregate_exact_5m, _write_cache,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dates", nargs="+", type=date.fromisoformat, required=True)
    parser.add_argument("--output-root", type=Path,
                        default=Path("data/recovery/october-2026/nifty-cache"))
    args = parser.parse_args()
    if "historical-evidence" in args.output_root.parts or "live-observation" in args.output_root.parts:
        raise SystemExit("STOP: use a separate recovery directory")
    token = dotenv_values(".env").get("UPSTOX_ACCESS_TOKEN") or os.getenv("UPSTOX_ACCESS_TOKEN")
    if not token:
        raise SystemExit("STOP: analytics token missing")
    sources = UpstoxLiveShadowSourcesV1(token)
    try:
        for day in sorted(set(args.dates)):
            candles = sources.historical_candles(UNDERLYING, day)
            bars = aggregate_exact_5m(candles, day, require_full_session=True)
            path = args.output_root / (day.isoformat() + ".json")
            if path.exists():
                raise SystemExit(f"STOP: existing recovery file: {path}")
            _write_cache(path, UNDERLYING, day, candles)
            print(json.dumps({"date": day.isoformat(), "bars": len(bars),
                              "minutes": len(candles), "path": str(path),
                              "source": "BROKER_HISTORICAL_RECOVERY_NOT_RECORDED_LIVE"}))
    finally:
        sources.close()


if __name__ == "__main__":
    main()
