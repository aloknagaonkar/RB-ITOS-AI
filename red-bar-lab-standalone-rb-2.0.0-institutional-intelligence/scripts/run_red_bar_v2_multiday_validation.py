from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from red_bar_lab.config import RedBarSettings
from red_bar_lab.services.historical_service import RedBarHistoricalService
from red_bar_lab.services.red_bar_v2_derived_exits import (
    resolve_red_bar_v2_derived_exits,
)
from red_bar_lab.services.red_bar_v2_multiday_validation import (
    RedBarV2ValidationDay,
    run_red_bar_v2_multiday_validation,
)
from red_bar_lab.services.red_bar_v2_validation_diagnostics import (
    deterministic_research_exit_timestamps,
)
from red_bar_lab.storage.artifacts import ArtifactLayout


INDEX_KEY = "NSE_INDEX|Nifty 50"

DERIVED = "derived"
CLOCKWORK = "clockwork"
NONE = "none"


def _optional_text(value: object) -> str | None:
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


def _fallback_exits(
    source: str,
    trading_date: date,
    index_candles: pd.DataFrame,
    futures_candles: pd.DataFrame,
    *,
    index_key: str,
    futures_key: str,
) -> tuple[tuple[pd.Timestamp, ...], str]:
    """Exits for a day the manifest left blank, plus a line describing them.

    ``derived`` runs the exit policy over the day and hands back the moments it
    actually closed on, so the report measures the strategy. ``clockwork`` is the
    old five-minute grid, kept only for reproducing earlier reports. ``none``
    feeds nothing, which leaves the day holding its first position to the close --
    every later candidate refused ACTIVE_TRADE_BLOCK -- and is almost never what
    a reader wants.
    """
    if source == NONE:
        return (), "none"
    if source == CLOCKWORK:
        exits = deterministic_research_exit_timestamps(trading_date)
        return exits, f"clockwork({len(exits)})"

    resolution = resolve_red_bar_v2_derived_exits(
        index_candles,
        futures_candles,
        instrument_key=index_key,
        vwap_instrument_key=futures_key,
    )
    held = sum(1 for trade in resolution.trades if trade.exit_timestamp is None)
    detail = f"derived({len(resolution.exit_timestamps)}/{resolution.iterations}p"
    if held:
        detail += f",{held} open at end"
    return resolution.exit_timestamps, detail + ")"


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
    parser.add_argument(
        "--exits",
        choices=(DERIVED, CLOCKWORK, NONE),
        default=DERIVED,
        help=(
            "Where a day's exits come from when the manifest row has no explicit "
            "exit_timestamps. 'derived' (default) runs the exit policy -- stop, "
            "trail, structure, session flat -- and uses the moments it closed on. "
            "'clockwork' injects the old validation-only grid every five minutes "
            "from 09:30 to 15:25 IST, which is a clock and not a policy; it is "
            "kept only for reproducing earlier reports. 'none' feeds no exits, so "
            "each day holds its first position to the close."
        ),
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
    exit_sources: list[str] = []
    print(f"Preparing {len(manifest)} day(s), fallback exits: {args.exits}")
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

        exits = _parse_exit_timestamps(row.get("exit_timestamps"))
        if exits:
            source = f"manifest({len(exits)})"
        else:
            # Deriving replays the day once per resolved entry, so a long manifest
            # is minutes of work. Report each day as it lands rather than going
            # quiet for the whole run.
            exits, source = _fallback_exits(
                args.exits,
                trading_date,
                index_candles,
                futures_candles,
                index_key=args.index_key,
                futures_key=futures_key,
            )
        exit_sources.append(source)
        print(f"  {trading_date} exits={source}", flush=True)

        days.append(
            RedBarV2ValidationDay(
                trading_date=trading_date.isoformat(),
                index_candles=index_candles,
                futures_candles=futures_candles,
                futures_instrument_key=futures_key,
                futures_symbol=_optional_text(row.get("futures_symbol")),
                futures_expiry=_optional_text(row.get("futures_expiry")),
                exit_timestamps=exits,
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
    print("Complete sessions:", result.complete_days)
    print("Partial sessions:", result.partial_days)
    print("Regimes:", ", ".join(result.regimes))
    print("Fallback exits:", args.exits)
    print("Admitted candidates:", result.total_admitted_candidates)
    print("Blocked candidates:", result.total_blocked_candidates)
    print("Closed trades:", result.total_closed_trades)
    print("Admitted reversals:", result.total_admitted_reversals)
    print("JSON report:", result.json_path)
    print("CSV report:", result.csv_path)

    print("\nPer-day results")
    print("---------------")
    for item, source in zip(result.days, exit_sources):
        print(
            item.trading_date,
            item.regime,
            item.regime_reason,
            item.health_status,
            item.session_completeness_status,
            f"coverage={item.session_coverage_pct:.1f}%",
            f"net={item.net_return_pct:.3f}%" if item.net_return_pct is not None else "net=n/a",
            f"eff={item.directional_efficiency:.3f}" if item.directional_efficiency is not None else "eff=n/a",
            f"admitted={item.admitted_candidates}",
            f"reversals={item.admitted_reversals}",
            f"closed={item.closed_trades}",
            # Which clock closed this day's trades. A block count or an R-multiple
            # read without it says nothing: the same day measured against the
            # clockwork grid and against the policy are different experiments.
            f"exits={source}",
        )


if __name__ == "__main__":
    main()
