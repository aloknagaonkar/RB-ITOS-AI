import json
from pathlib import Path

import pandas as pd
import pytest

from red_bar_lab.execution.directional_regime_native_signal import (
    DirectionalNativeSignalDatabaseProxy,
    decide_native_signal,
    read_fresh_rsi_signals,
)
from red_bar_lab.execution.rsi_extreme_reversal import (
    RsiExtremeReversalEngine,
    _rsi,
    append_rsi_signals_once,
)


def reversal_candles() -> pd.DataFrame:
    # RSI arms during the decline and confirms only when the completed bullish
    # candle closes above the previous candle high without making a lower low.
    closes = [100.0] * 8 + [98, 96, 94, 92, 95]
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
    return pd.DataFrame(rows)


def bearish_reversal_candles() -> pd.DataFrame:
    frame = reversal_candles().copy()
    for column in ("open", "high", "low", "close"):
        frame[column] = 200.0 - frame[column]
    original_high = frame["high"].copy()
    frame["high"] = frame["low"]
    frame["low"] = original_high
    return frame


def test_wilder_rsi_uses_sma_seed_and_recursive_smoothing():
    closes = pd.Series([44, 44.15, 43.9, 44.35, 44.7, 44.5, 44.9, 45.1, 44.8])
    result = _rsi(closes, 7)
    assert pd.isna(result.iloc[6])
    gains = closes.diff().clip(lower=0).iloc[1:8]
    losses = (-closes.diff().clip(upper=0)).iloc[1:8]
    expected = 100 - 100 / (1 + gains.mean() / losses.mean())
    assert result.iloc[7] == pytest.approx(expected)


def test_oversold_recovery_emits_one_ce_signal():
    signals = RsiExtremeReversalEngine().detect(
        reversal_candles(), instrument_key="NSE_INDEX|Nifty 50"
    )
    assert len(signals) == 1
    row = signals[0].as_record()
    assert row["direction"] == "BULLISH"
    assert row["option_type"] == "CE"
    assert row["signal_source"] == "RSI_EXTREME_REVERSAL_V1"
    assert row["rsi_armed_value"] <= 20.0
    assert row["rsi_confirmation_value"] > 20.0
    assert row["confirmation_close"] > row["previous_candle_high"]
    assert row["confirmation_low"] >= row["previous_candle_low"]
    assert row["rsi_lifecycle_state"] == "REVERSAL_CONFIRMED"
    assert row["structure_reclaim_confirmed"] is True
    assert row["entry_ready_timestamp"] == row["confirmation_timestamp"]
    assert row["strategy_stop_loss_pct"] == 7.0
    assert row["fixed_profit_target"] is False


def test_overbought_rejection_emits_one_pe_signal():
    signals = RsiExtremeReversalEngine().detect(
        bearish_reversal_candles(), instrument_key="NSE_INDEX|Nifty 50"
    )
    assert len(signals) == 1
    row = signals[0].as_record()
    assert row["direction"] == "BEARISH"
    assert row["option_type"] == "PE"
    assert row["rsi_armed_value"] >= 80.0
    assert row["rsi_confirmation_value"] < 80.0
    assert row["confirmation_close"] < row["previous_candle_low"]
    assert row["confirmation_high"] <= row["previous_candle_high"]


def test_bullish_rsi_crossback_without_previous_high_reclaim_is_not_executable(monkeypatch):
    frame = reversal_candles().iloc[-4:].reset_index(drop=True)
    monkeypatch.setattr(
        "red_bar_lab.execution.rsi_extreme_reversal._rsi",
        lambda close, period: pd.Series([50.0, 19.0, 18.0, 21.0]),
    )
    frame.loc[3, "open"] = 92.0
    frame.loc[3, "close"] = 93.0
    frame.loc[3, "high"] = 94.0
    frame.loc[3, "low"] = frame.loc[2, "low"]
    assert RsiExtremeReversalEngine().detect(
        frame, instrument_key="NSE_INDEX|Nifty 50"
    ) == []


def test_bullish_rsi_crossback_with_fresh_lower_low_is_not_executable(monkeypatch):
    frame = reversal_candles().iloc[-4:].reset_index(drop=True)
    monkeypatch.setattr(
        "red_bar_lab.execution.rsi_extreme_reversal._rsi",
        lambda close, period: pd.Series([50.0, 19.0, 18.0, 21.0]),
    )
    frame.loc[3, "open"] = 92.0
    frame.loc[3, "close"] = frame.loc[2, "high"] + 1.0
    frame.loc[3, "high"] = frame.loc[3, "close"] + 0.5
    frame.loc[3, "low"] = frame.loc[2, "low"] - 0.1
    assert RsiExtremeReversalEngine().detect(
        frame, instrument_key="NSE_INDEX|Nifty 50"
    ) == []


def test_bearish_rsi_crossback_without_previous_low_reclaim_is_not_executable(monkeypatch):
    frame = bearish_reversal_candles().iloc[-4:].reset_index(drop=True)
    monkeypatch.setattr(
        "red_bar_lab.execution.rsi_extreme_reversal._rsi",
        lambda close, period: pd.Series([50.0, 81.0, 82.0, 79.0]),
    )
    frame.loc[3, "open"] = 108.0
    frame.loc[3, "close"] = frame.loc[2, "low"] + 0.1
    frame.loc[3, "low"] = frame.loc[2, "low"]
    frame.loc[3, "high"] = frame.loc[2, "high"]
    assert RsiExtremeReversalEngine().detect(
        frame, instrument_key="NSE_INDEX|Nifty 50"
    ) == []


def test_bearish_rsi_crossback_with_fresh_higher_high_is_not_executable(monkeypatch):
    frame = bearish_reversal_candles().iloc[-4:].reset_index(drop=True)
    monkeypatch.setattr(
        "red_bar_lab.execution.rsi_extreme_reversal._rsi",
        lambda close, period: pd.Series([50.0, 81.0, 82.0, 79.0]),
    )
    frame.loc[3, "open"] = 108.0
    frame.loc[3, "close"] = frame.loc[2, "low"] - 1.0
    frame.loc[3, "low"] = frame.loc[3, "close"] - 0.5
    frame.loc[3, "high"] = frame.loc[2, "high"] + 0.1
    assert RsiExtremeReversalEngine().detect(
        frame, instrument_key="NSE_INDEX|Nifty 50"
    ) == []


def test_exact_boundary_values_arm_but_do_not_confirm_until_crossed(monkeypatch):
    frame = reversal_candles().iloc[:4].copy()
    values = pd.Series([50.0, 20.0, 20.0, 21.0])
    monkeypatch.setattr(
        "red_bar_lab.execution.rsi_extreme_reversal._rsi",
        lambda close, period: values,
    )
    frame.loc[3, "open"] = frame.loc[3, "close"] - 1.0
    frame.loc[3, "close"] = frame.loc[2, "high"] + 1.0
    frame.loc[3, "high"] = frame.loc[3, "close"] + 0.5
    frame.loc[3, "low"] = frame.loc[2, "low"]
    signals = RsiExtremeReversalEngine().detect(
        frame, instrument_key="NSE_INDEX|Nifty 50"
    )
    assert len(signals) == 1
    assert signals[0].as_record()["rsi_armed_value"] == 20.0


def test_exact_80_boundary_arms_pe(monkeypatch):
    frame = bearish_reversal_candles().iloc[:3].copy()
    values = pd.Series([50.0, 80.0, 79.0])
    monkeypatch.setattr(
        "red_bar_lab.execution.rsi_extreme_reversal._rsi",
        lambda close, period: values,
    )
    frame.loc[2, "open"] = frame.loc[2, "close"] + 1.0
    frame.loc[2, "close"] = frame.loc[1, "low"] - 1.0
    frame.loc[2, "low"] = frame.loc[2, "close"] - 0.5
    frame.loc[2, "high"] = frame.loc[1, "high"]
    signals = RsiExtremeReversalEngine().detect(
        frame, instrument_key="NSE_INDEX|Nifty 50"
    )
    assert len(signals) == 1
    assert signals[0].as_record()["rsi_armed_value"] == 80.0


def test_rsi_artifact_append_is_idempotent(tmp_path: Path):
    rows = [signal.as_record() for signal in RsiExtremeReversalEngine().detect(
        reversal_candles(), instrument_key="NSE_INDEX|Nifty 50"
    )]
    path = tmp_path / "signals.jsonl"
    assert append_rsi_signals_once(path, rows) == 1
    assert append_rsi_signals_once(path, rows) == 0
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


def test_historical_rsi_artifact_is_not_executable_before_entry_ready(tmp_path: Path):
    folder = tmp_path / "rsi_extreme_reversal_v1"
    folder.mkdir()
    row = RsiExtremeReversalEngine().detect(
        reversal_candles(), instrument_key="NSE_INDEX|Nifty 50"
    )[0].as_record()
    (folder / "NIFTY.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    ready = pd.Timestamp(row["entry_ready_timestamp"])
    assert read_fresh_rsi_signals(tmp_path, now=ready - pd.Timedelta(seconds=1)) == []
    assert len(read_fresh_rsi_signals(tmp_path, now=ready)) == 1


def test_opposing_source_conflict_holds_entire_bundle():
    rsi = {
        "signal_id": "RSI-1",
        "direction": "BULLISH",
        "signal_source": "RSI_EXTREME_REVERSAL_V1",
        "confirmation_timestamp": "2026-08-14T09:31:00+05:30",
    }
    red_bar = {
        "signal_id": "REF-1",
        "direction": "BEARISH",
        "signal_source": "REFERENCE_LEVEL",
        "confirmation_timestamp": "2026-08-14T09:30:00+05:30",
    }
    decision = decide_native_signal(rsi, [red_bar])
    assert decision.action == "SOURCE_CONFLICT"
    assert decision.native_signal is None
    assert decision.related_signal_id == "REF-1"


class FakeDatabase:
    def read_signal_attempts(self, *args, **kwargs):
        return [{
            "signal_id": "REF-1",
            "direction": "BULLISH",
            "confirmation_timestamp": "2026-08-14T09:30:00+05:30",
            "signal_source": "REFERENCE_LEVEL",
        }]

    def read_paper_execution_orders(self, *args, **kwargs):
        return []


def test_rsi_can_form_triple_source_alignment(tmp_path: Path):
    dri_folder = tmp_path / "fresh_setup_bundles_v43"
    dri_folder.mkdir(parents=True)
    (dri_folder / "NIFTY.jsonl").write_text(json.dumps({
        "bundle_id": "BND-1",
        "direction": "BULLISH",
        "current_regime": "BULLISH",
        "detected_at": "2026-08-14T09:31:00+05:30",
        "fresh_until": "2026-08-14T09:40:00+05:30",
        "primary_setup_type": "BULLISH_STRUCTURE_BREAK",
        "trigger_level": 24000,
        "invalidation_level": 23980,
    }) + "\n", encoding="utf-8")

    rsi_folder = tmp_path / "rsi_extreme_reversal_v1"
    rsi_folder.mkdir(parents=True)
    rsi = RsiExtremeReversalEngine().detect(
        reversal_candles(), instrument_key="NSE_INDEX|Nifty 50"
    )[0].as_record()
    rsi.update({
        "confirmation_timestamp": "2026-08-14T09:32:00+05:30",
        "detected_at": "2026-08-14T09:32:00+05:30",
        "entry_ready_timestamp": "2026-08-14T09:32:00+05:30",
        "fresh_until": "2026-08-14T09:37:00+05:30",
    })
    (rsi_folder / "NIFTY.jsonl").write_text(json.dumps(rsi) + "\n", encoding="utf-8")

    rows = DirectionalNativeSignalDatabaseProxy(
        FakeDatabase(),
        runs_root=tmp_path,
        now_provider=lambda: "2026-08-14T09:33:00+05:30",
        enable_reference_signals=True,
    ).read_signal_attempts()

    assert len(rows) == 1
    assert rows[0]["merge_status"] == "TRIPLE_SOURCE_ALIGNED"
    assert rows[0]["source_count"] == 3
    assert rows[0]["rsi_signal_id"] == rsi["signal_id"]
    assert rows[0]["directional_bundle_id"] == "BND-1"
