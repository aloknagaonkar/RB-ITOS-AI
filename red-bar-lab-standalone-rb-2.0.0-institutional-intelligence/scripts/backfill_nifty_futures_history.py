from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from red_bar_lab.config import RedBarSettings
from red_bar_lab.services.historical_service import RedBarHistoricalService
from red_bar_lab.services.nifty_futures_history_backfill import (
    NIFTY_INDEX_KEY,
    UpstoxExpiredFuturesGateway,
    backfill_nifty_futures_history,
    load_upstox_nse_instruments,
)
from red_bar_lab.services.upstox_service import (
    RedBarUpstoxService,
    resolve_access_token,
)
from red_bar_lab.storage.artifacts import ArtifactLayout


def _optional_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill exact NIFTY monthly futures one-minute candles for cached "
            "NIFTY index dates and create a Red Bar V2 validation manifest."
        )
    )
    parser.add_argument("--start", help="First trading date, YYYY-MM-DD")
    parser.add_argument("--end", help="Last trading date, YYYY-MM-DD")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Refresh existing completed futures cache files",
    )
    parser.add_argument(
        "--manifest-name",
        default="red_bar_v2_validation_manifest.csv",
        help="Output manifest filename",
    )
    args = parser.parse_args()

    start = _optional_date(args.start)
    end = _optional_date(args.end)
    if start and end and end < start:
        raise ValueError("--end must be on or after --start")

    settings = RedBarSettings.from_env()
    layout = ArtifactLayout(settings)
    layout.ensure()

    provider = RedBarUpstoxService(resolve_access_token())
    historical = RedBarHistoricalService(provider=provider, layout=layout)
    index_dates = [
        item
        for item in historical.available_dates(NIFTY_INDEX_KEY, interval_minutes=1)
        if (start is None or item >= start) and (end is None or item <= end)
    ]
    if not index_dates:
        raise ValueError("No cached NIFTY index dates match the requested range.")

    print("Loading current Upstox NSE instrument master...")
    active_instruments = load_upstox_nse_instruments()
    print("Cached NIFTY index dates:", len(index_dates))
    print("Range:", index_dates[0], "to", index_dates[-1])
    print()

    result = backfill_nifty_futures_history(
        index_dates,
        historical=historical,
        active_instruments=active_instruments,
        expired_gateway=UpstoxExpiredFuturesGateway(provider),
        artifacts_root=settings.artifacts_root,
        force=args.force,
        manifest_name=args.manifest_name,
    )

    print("NIFTY futures history backfill")
    print("------------------------------")
    print("Requested days:", len(result.days))
    print("Downloaded:", result.downloaded_days)
    print("Existing:", result.existing_days)
    print("Blocked:", result.blocked_days)
    print("Rows available:", result.rows_stored)
    print("Manifest:", result.manifest_path)
    print()

    print("Per-day results")
    print("---------------")
    for item in result.days:
        detail = (
            f"{item.trading_date} {item.status} {item.source_type} "
            f"{item.instrument_key or '-'} rows={item.rows}"
        )
        if item.reason:
            detail += f" reason={item.reason}"
        print(detail)

    if result.blocked_days:
        print()
        print(
            "Some dates were blocked. Expired futures endpoints require Upstox "
            "Plus; blocked details above are retained without changing existing cache."
        )


if __name__ == "__main__":
    main()
