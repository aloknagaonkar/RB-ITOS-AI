from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import sys

# Allow direct execution from the repository root:
# python .\scripts\run_red_bar_v2_multiday_validation.py <manifest>
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from red_bar_lab.config import RedBarSettings
from red_bar_lab.services.historical_service import RedBarHistoricalService
from red_bar_lab.services.red_bar_v2_multiday_validation import (
    RedBarV2ValidationDay,
    run_red_bar_v2_multiday_validation,
)
from red_bar_lab.storage.artifacts import ArtifactLayout


INDEX_KEY = "NSE_INDEX|Nifty 50"


def _optional_text(value: object) -> str | None:
    """Return trimmed manifest text, treating blank/NaN values as absent."""
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _parse_exit_timestamps(value: object) -> tuple[pd.Timestamp, ...]:
    text = _optional_text(value)
    if text is None:
        return ()
    return tuple(
        pd.Timestamp(item.strip())
        for item in text.split(";")
        if item.strip()
    )


def _required(row: pd.Series, name: str) -> str:
    value = _optional_text(row.get(name))
    if value is None:
        raise ValueError(f"Manifest row is missing required column value: {name}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run historical-only Red Bar V2 futures/VWAP validation across cached dates."
    )
    parser.add_argument("manifest", type=Path, help="CSV validation manifest")
    parser.add_argument(
        "--index-key",
        default=INDEX_KEY,
        help="Underlying index instrument key",
    )
    args = parser.parse_args()

    manifest = pd.read_csv(args.manifest)
    required_columns = {"trading_date", "futures_instrument_key"}
    missing = sorted(required_columns - set(manifest.columns))
    if missing:
        raise ValueError(f"Manifest is missing columns: {', '.join(missing)}")

    settings = RedBarSettings.from_env()
    layout = ArtifactLayout(settings)
    layout.ensure()
    historical = RedBarHistoricalService(provider=None, layout=layout)

    days: list[RedBarV2ValidationDay] = []
    for _, row in manifest.iterrows():
        trading_date = date.fromisoformat(_required(row, "trading_date"))
        futures_key = _required(row, "futures_instrument_key")
        index_candles = historical.read_day(
            args.index_key,
            trading_date,
            interval_minutes=1,
        )
        futures_candles = historical.read_day(
            futures_key,
            trading_date,
            interval_minutes=1,
        )
        if index_candles.empty:
            raise ValueError(f"Missing index cache for {trading_date}: {args.index_key}")
        if futures_candles.empty:
            raise ValueError(f"Missing futures cache for {trading_date}: {futures_key}")

        days.append(
            RedBarV2ValidationDay(
                trading_date=trading_date.isoformat(),
                index_candles=index_candles,
                futures_candles=futures_candles,
                futures_instrument_key=futures_key,
                futures_symbol=_optional_text(row.get("futures_symbol")),
                futures_expiry=_optional_text(row.get("futures_expiry")),
                exit_timestamps=_parse_exit_timestamps(row.get("exit_timestamps")),
                expected_regime=_optional_text(row.get("expected_regime")),
            )
        )

    result = run_red_bar_v2_multiday_validation(
        days,
        instrument_key=args.index_key,
        artifacts_root=settings.artifacts_root,
    )

    print("Red Bar V2 multi-day validation")
    print("--------------------------------")
    print("Days:", result.total_days)
    print("READY:", result.ready_days)
    print("Blocked:", result.blocked_days)
    print("Regimes:", ", ".join(result.regimes))
    print("Admitted candidates:", result.total_admitted_candidates)
    print("Blocked candidates:", result.total_blocked_candidates)
    print("Closed trades:", result.total_closed_trades)
    print("Admitted reversals:", result.total_admitted_reversals)
    print("JSON report:", result.json_path)
    print("CSV report:", result.csv_path)

    print("\nPer-day results")
    print("---------------")
    for item in result.days:
        print(
            item.trading_date,
            item.regime,
            item.health_status,
            f"1M={item.aligned_rows}/{item.index_rows}",
            f"5M={item.completed_5m_aligned_rows}",
            f"admitted={item.admitted_candidates}",
            f"reversals={item.admitted_reversals}",
            f"closed={item.closed_trades}",
        )


if __name__ == "__main__":
    main()
