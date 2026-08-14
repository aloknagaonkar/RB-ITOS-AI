from pathlib import Path
import pandas as pd

from red_bar_lab.execution.directional_regime_background import (
    DirectionalRegimeBackgroundCycle,
)


def candles(count=240, step=1.0):
    price = 24000.0
    rows = []
    for index, timestamp in enumerate(
        pd.date_range(
            "2026-08-14 09:15",
            periods=count,
            freq="1min",
            tz="Asia/Kolkata",
        )
    ):
        wave = 0.8 if index % 12 < 8 else -0.2
        close = price + step + wave
        rows.append(
            {
                "timestamp": timestamp,
                "open": price,
                "high": max(price, close) + 0.5,
                "low": min(price, close) - 0.5,
                "close": close,
                "volume": 0,
            }
        )
        price = close
    return pd.DataFrame(rows)


class Provider:
    def historical_candles(self, *args, **kwargs):
        return pd.DataFrame()

    def intraday_candles(self, *args, **kwargs):
        return candles()


class Adapter:
    provider = Provider()
    underlying_key = "NSE_INDEX|Nifty 50"


def test_background_cycle_creates_current_artifacts(tmp_path: Path):
    result = DirectionalRegimeBackgroundCycle(
        adapter=Adapter(),
        runs_root=tmp_path,
        now_provider=lambda: pd.Timestamp(
            "2026-08-14 13:20:00",
            tz="Asia/Kolkata",
        ),
    ).run()
    assert result.status in {"READY", "NO_SIGNAL"}
    assert (tmp_path / "stateful_regime_v43" / "NSE_INDEX_Nifty_50.jsonl").exists()
    assert (tmp_path / "transition_sequence_v43" / "NSE_INDEX_Nifty_50.jsonl").exists()


def test_background_cycle_is_safe_to_run_repeatedly(tmp_path: Path):
    cycle = DirectionalRegimeBackgroundCycle(
        adapter=Adapter(),
        runs_root=tmp_path,
        now_provider=lambda: pd.Timestamp(
            "2026-08-14 13:20:00",
            tz="Asia/Kolkata",
        ),
    )
    assert cycle.run().status in {"READY", "NO_SIGNAL"}
    assert cycle.run().status in {"READY", "NO_SIGNAL"}


def test_missing_provider_is_fail_open(tmp_path: Path):
    class Missing:
        provider = None
        underlying_key = None

    result = DirectionalRegimeBackgroundCycle(
        adapter=Missing(),
        runs_root=tmp_path,
    ).run()
    assert result.status == "UNAVAILABLE"
    assert result.reason == "UNDERLYING_CANDLE_PROVIDER_UNAVAILABLE"
