from pathlib import Path
import pandas as pd

from red_bar_lab.execution.directional_regime_background import (
    DirectionalRegimeBackgroundCycle,
    _normalize_one_minute,
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


def test_current_incomplete_one_minute_candle_is_excluded():
    frame = candles(count=3)
    now = frame.iloc[-1]["timestamp"] + pd.Timedelta(seconds=30)
    normalized = _normalize_one_minute([frame], now)
    assert len(normalized) == 2
    assert normalized["timestamp"].max() < now.floor("min")


def test_rsi_artifacts_are_not_generated_for_bank_nifty(tmp_path: Path):
    class BankAdapter:
        provider = Provider()
        underlying_key = "NSE_INDEX|Nifty Bank"

    DirectionalRegimeBackgroundCycle(
        adapter=BankAdapter(),
        runs_root=tmp_path,
        now_provider=lambda: pd.Timestamp(
            "2026-08-14 13:20:00",
            tz="Asia/Kolkata",
        ),
    ).run()
    assert not (tmp_path / "rsi_extreme_reversal_v1").exists()


def test_rsi_can_be_ready_before_dri_five_minute_readiness(tmp_path: Path):
    closes = [100.0] * 8 + [98, 96, 94, 92, 90, 88, 86, 89]
    timestamps = pd.date_range(
        "2026-08-14 09:15",
        periods=len(closes),
        freq="1min",
        tz="Asia/Kolkata",
    )
    rows = []
    previous = closes[0]
    for timestamp, close in zip(timestamps, closes):
        rows.append({
            "timestamp": timestamp,
            "open": previous,
            "high": max(previous, close) + 0.5,
            "low": min(previous, close) - 0.5,
            "close": close,
            "volume": 1000,
        })
        previous = close

    class EarlyRsiProvider:
        def historical_candles(self, *args, **kwargs):
            return pd.DataFrame()

        def intraday_candles(self, *args, **kwargs):
            return pd.DataFrame(rows)

    class EarlyRsiAdapter:
        provider = EarlyRsiProvider()
        underlying_key = "NSE_INDEX|Nifty 50"

    result = DirectionalRegimeBackgroundCycle(
        adapter=EarlyRsiAdapter(),
        runs_root=tmp_path,
        now_provider=lambda: pd.Timestamp(
            "2026-08-14 09:32:00",
            tz="Asia/Kolkata",
        ),
    ).run()

    assert result.status == "READY"
    assert result.reason == "RSI_READY_DRI_UNAVAILABLE"
    assert result.latest_rsi_signal_id
    assert (
        tmp_path
        / "rsi_extreme_reversal_v1"
        / "NSE_INDEX_Nifty_50.jsonl"
    ).exists()
