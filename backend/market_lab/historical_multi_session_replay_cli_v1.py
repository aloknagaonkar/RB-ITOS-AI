from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict
from pathlib import Path

from .historical_multi_session_replay_v1 import (
    DEFAULT_FUTURES_CSV,
    discover_canonical_90_dates,
    run_canonical_replay,
)


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m market_lab.historical_multi_session_replay_cli_v1"
    )
    parser.add_argument("--data-root", default="data")
    parser.add_argument(
        "--futures-csv",
        default=str(DEFAULT_FUTURES_CSV),
    )
    parser.add_argument(
        "--allow-non90",
        action="store_true",
        help="Diagnostic only. Do not use for canonical conclusions.",
    )
    parser.add_argument(
        "--session-csv",
        default="data/historical-evidence/p3h5-canonical-90-session-replay-v1.csv",
    )
    parser.add_argument(
        "--json-output",
        default="data/historical-evidence/p3h5-canonical-90-session-replay-v1.json",
    )
    parser.add_argument(
        "--universe-only",
        action="store_true",
    )
    args = parser.parse_args()

    require_exact_90 = not args.allow_non90

    if args.universe_only:
        dates = discover_canonical_90_dates(
            data_root=args.data_root,
            futures_csv=args.futures_csv,
            require_exact_90=require_exact_90,
        )
        print(json.dumps({
            "status": "PASS",
            "count": len(dates),
            "dates": dates,
        }, indent=2))
        return

    report = run_canonical_replay(
        data_root=args.data_root,
        futures_csv=args.futures_csv,
        require_exact_90=require_exact_90,
    )

    payload = {
        "research_version": "P3H5_CANONICAL_90_SESSION_REPLAY_V1",
        "governance": {
            "population": "TRAIN+OOS_A/B/C/D",
            "start": "2026-05-04",
            "end": "2026-09-08",
            "expected_sessions": 90,
            "oos_e_f_g_h_excluded": True,
            "execution_model": "OPTION_1M_OHLC_INTRABAR_NEXT_MINUTE_OPEN_V1",
            "entry_fill": "NEXT_MINUTE_OPTION_OPEN_PROXY",
            "production_fill_parity": False,
            "live_execution": False,
        },
        "summary": report.summary(),
        "universe_dates": report.universe_dates,
        "sessions": [asdict(row) for row in report.session_rows],
    }

    json_path = Path(args.json_output)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2) + "\n")

    _write_csv(
        Path(args.session_csv),
        [asdict(row) for row in report.session_rows],
    )

    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
