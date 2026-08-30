from datetime import date

from red_bar_lab.config import RedBarSettings
from red_bar_lab.services.historical_service import RedBarHistoricalService
from red_bar_lab.services.red_bar_v2_futures_replay_service import (
    run_monitored_red_bar_v2_futures_replay,
)
from red_bar_lab.storage.artifacts import ArtifactLayout


TRADING_DATE = date(2026, 8, 18)

INDEX_KEY = "NSE_INDEX|Nifty 50"
FUTURES_KEY = "NSE_FO|58072"
FUTURES_SYMBOL = "NIFTY FUT 25 AUG 26"
FUTURES_EXPIRY = "2026-08-25"


def main() -> None:
    settings = RedBarSettings.from_env()
    layout = ArtifactLayout(settings)
    layout.ensure()

    historical = RedBarHistoricalService(
        provider=None,  # Local cache read only
        layout=layout,
    )

    index_candles = historical.read_day(
        INDEX_KEY,
        TRADING_DATE,
        interval_minutes=1,
    )
    futures_candles = historical.read_day(
        FUTURES_KEY,
        TRADING_DATE,
        interval_minutes=1,
    )

    print("Index rows:", len(index_candles))
    print("Futures rows:", len(futures_candles))

    if index_candles.empty:
        raise ValueError(
            f"Index candles are missing for {TRADING_DATE}: {INDEX_KEY}"
        )

    if futures_candles.empty:
        raise ValueError(
            f"Futures candles are missing for {TRADING_DATE}: {FUTURES_KEY}"
        )

    result = run_monitored_red_bar_v2_futures_replay(
        index_candles,
        futures_candles,
        instrument_key=INDEX_KEY,
        vwap_instrument_key=FUTURES_KEY,
        artifacts_root=settings.artifacts_root,
        futures_symbol=FUTURES_SYMBOL,
        futures_expiry=FUTURES_EXPIRY,
    )

    print("\nVWAP source health")
    print("------------------")
    for key, value in result.health.to_dict().items():
        print(f"{key}: {value}")

    replay = result.replay

    print("\nReplay result")
    print("-------------")
    print("Trading date:", replay.trading_date)
    print("Reference timestamp:", replay.reference_timestamp)
    print("Reference midpoint:", replay.reference_midpoint)
    print("Admitted candidates:", replay.admitted_candidates)
    print("Blocked candidates:", replay.blocked_candidates)
    print("Closed trades:", replay.closed_trades)
    print("Final trade state:", replay.final_trade_state)
    print("Events:", len(replay.events))
    print("Health file:", result.health_path)

    print("\nReplay events")
    print("-------------")
    for event in replay.events:
        print(
            event.timestamp,
            event.event_type,
            event.direction,
            event.option_side,
            event.admission_code,
            event.candidate_allowed,
        )


if __name__ == "__main__":
    main()
