from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

from .historical_paper_replay_date_v1 import (
    DEFAULT_FUTURES_CSV,
    HistoricalReplayError,
    discover_available_dates,
    replay_date,
    summarize,
)


def _dates_from_args(args) -> list[str]:
    if args.session_date:
        return sorted(set(args.session_date))

    if not args.from_date or not args.to_date:
        raise SystemExit(
            "Provide --session-date, or both --from-date and --to-date."
        )

    start = date.fromisoformat(args.from_date)
    end = date.fromisoformat(args.to_date)
    if end < start:
        raise SystemExit("--to-date must be on or after --from-date")

    available = discover_available_dates(
        data_root=args.data_root,
        futures_csv=args.futures_csv,
    )
    return [
        value for value in available
        if start <= date.fromisoformat(value) <= end
    ]


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m market_lab.paper_historical_replay_cli_v1"
    )
    parser.add_argument("--session-date", action="append")
    parser.add_argument("--from-date")
    parser.add_argument("--to-date")
    parser.add_argument("--data-root", default="data")
    parser.add_argument(
        "--futures-csv",
        default=str(DEFAULT_FUTURES_CSV),
    )
    parser.add_argument(
        "--events",
        choices=("all", "signals", "none"),
        default="signals",
    )
    args = parser.parse_args()

    dates = _dates_from_args(args)
    if not dates:
        print(json.dumps({
            "status": "NO_AVAILABLE_SESSIONS",
            "sessions": [],
        }, indent=2))
        return

    results = []
    failures = []

    for session_date in dates:
        try:
            result = replay_date(
                session_date,
                data_root=args.data_root,
                futures_csv=args.futures_csv,
            )
            results.append(result)
        except Exception as exc:
            failures.append({
                "session_date": session_date,
                "reason": type(exc).__name__,
                "detail": str(exc),
            })

    payload = {
        "status": "PASS" if results and not failures else (
            "PARTIAL" if results else "FAIL"
        ),
        "summary": summarize(results),
        "sessions": [],
        "failures": failures,
    }

    for result in results:
        item = {
            "session_date": result.session_date,
            "positioning_source": result.positioning_source,
            "futures_source": result.futures_source,
            "option_expiry": result.option_expiry,
            "p1_count": result.p1_count,
            "wait_p2_count": result.wait_p2_count,
            "p2_confirmed_count": result.p2_confirmed_count,
            "p2_failed_count": result.p2_failed_count,
            "vwap_reject_count": result.vwap_reject_count,
            "feature_block_count": result.feature_block_count,
        }

        if args.events != "none":
            events = result.events
            if args.events == "signals":
                events = [
                    e for e in events
                    if e.event_type != "P1_NOT_DETECTED"
                ]
            item["events"] = [asdict(event) for event in events]

        payload["sessions"].append(item)

    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
