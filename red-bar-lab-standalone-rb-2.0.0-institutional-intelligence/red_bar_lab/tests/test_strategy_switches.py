import json
from pathlib import Path

from red_bar_lab.execution.directional_regime_native_signal import (
    DirectionalNativeSignalDatabaseProxy,
)
from red_bar_lab.execution.rsi_extreme_reversal import (
    RsiExtremeReversalEngine,
)
from red_bar_lab.tests.test_rsi_extreme_reversal_signal import (
    reversal_candles,
)


NOW = "2026-08-14T09:33:00+05:30"


class StrategyDatabase:
    def __init__(self):
        self.read_count = 0

    def read_signal_attempts(self, *args, **kwargs):
        self.read_count += 1
        return [{
            "signal_id": "REF-1",
            "direction": "BULLISH",
            "confirmation_timestamp":
                "2026-08-14T09:30:00+05:30",
            "signal_source": "REFERENCE_LEVEL",
        }]

    def read_paper_execution_orders(self, *args, **kwargs):
        return []


def write_dri(root: Path):
    folder = root / "fresh_setup_bundles_v43"
    folder.mkdir(parents=True)
    (folder / "NIFTY.jsonl").write_text(
        json.dumps({
            "bundle_id": "BND-1",
            "direction": "BULLISH",
            "current_regime": "BULLISH",
            "detected_at":
                "2026-08-14T09:31:00+05:30",
            "fresh_until":
                "2026-08-14T09:40:00+05:30",
            "primary_setup_type":
                "BULLISH_STRUCTURE_BREAK",
            "trigger_level": 24000,
            "invalidation_level": 23980,
        }) + "\n",
        encoding="utf-8",
    )


def write_rsi(root: Path):
    folder = root / "rsi_extreme_reversal_v1"
    folder.mkdir(parents=True)
    row = RsiExtremeReversalEngine().detect(
        reversal_candles(),
        instrument_key="NSE_INDEX|Nifty 50",
    )[0].as_record()
    row.update({
        "confirmation_timestamp":
            "2026-08-14T09:32:00+05:30",
        "detected_at":
            "2026-08-14T09:32:00+05:30",
        "entry_ready_timestamp":
            "2026-08-14T09:32:00+05:30",
        "fresh_until":
            "2026-08-14T09:37:00+05:30",
    })
    (folder / "NIFTY.jsonl").write_text(
        json.dumps(row) + "\n",
        encoding="utf-8",
    )


def sources(rows):
    result = set()
    for row in rows:
        result.update(row.get("signal_sources") or [])
        source = row.get("signal_source")
        if source:
            result.add(source)
    return result


def test_red_bar_only(tmp_path: Path):
    db = StrategyDatabase()
    rows = DirectionalNativeSignalDatabaseProxy(
        db,
        runs_root=tmp_path,
        now_provider=lambda: NOW,
        enable_red_bar_strategy=True,
        enable_dri_strategy=False,
        enable_rsi_strategy=False,
    ).read_signal_attempts()

    assert len(rows) == 1
    assert rows[0]["signal_source"] == "REFERENCE_LEVEL"


def test_dri_only_does_not_read_red_bar(tmp_path: Path):
    write_dri(tmp_path)
    db = StrategyDatabase()

    rows = DirectionalNativeSignalDatabaseProxy(
        db,
        runs_root=tmp_path,
        now_provider=lambda: NOW,
        enable_red_bar_strategy=False,
        enable_dri_strategy=True,
        enable_rsi_strategy=False,
    ).read_signal_attempts()

    assert db.read_count == 0
    assert len(rows) == 1
    assert rows[0]["signal_source"] == (
        "DIRECTIONAL_REGIME_INTELLIGENCE"
    )


def test_rsi_only(tmp_path: Path):
    write_rsi(tmp_path)

    rows = DirectionalNativeSignalDatabaseProxy(
        StrategyDatabase(),
        runs_root=tmp_path,
        now_provider=lambda: NOW,
        enable_red_bar_strategy=False,
        enable_dri_strategy=False,
        enable_rsi_strategy=True,
    ).read_signal_attempts()

    assert len(rows) == 1
    assert rows[0]["signal_source"] == (
        "RSI_EXTREME_REVERSAL_V1"
    )


def test_all_strategies_form_triple_alignment(tmp_path: Path):
    write_dri(tmp_path)
    write_rsi(tmp_path)

    rows = DirectionalNativeSignalDatabaseProxy(
        StrategyDatabase(),
        runs_root=tmp_path,
        now_provider=lambda: NOW,
        enable_red_bar_strategy=True,
        enable_dri_strategy=True,
        enable_rsi_strategy=True,
    ).read_signal_attempts()

    assert len(rows) == 1
    assert rows[0]["merge_status"] == (
        "TRIPLE_SOURCE_ALIGNED"
    )
    assert rows[0]["source_count"] == 3


def test_all_strategies_disabled_returns_no_signals(
    tmp_path: Path,
):
    write_dri(tmp_path)
    write_rsi(tmp_path)
    db = StrategyDatabase()

    rows = DirectionalNativeSignalDatabaseProxy(
        db,
        runs_root=tmp_path,
        now_provider=lambda: NOW,
        enable_red_bar_strategy=False,
        enable_dri_strategy=False,
        enable_rsi_strategy=False,
    ).read_signal_attempts()

    assert rows == []
    assert db.read_count == 0


def test_environment_switches(monkeypatch, tmp_path: Path):
    write_dri(tmp_path)
    write_rsi(tmp_path)

    monkeypatch.setenv(
        "RB_ENABLE_RED_BAR_STRATEGY", "false"
    )
    monkeypatch.setenv(
        "RB_ENABLE_DRI_STRATEGY", "false"
    )
    monkeypatch.setenv(
        "RB_ENABLE_RSI_STRATEGY", "true"
    )

    rows = DirectionalNativeSignalDatabaseProxy(
        StrategyDatabase(),
        runs_root=tmp_path,
        now_provider=lambda: NOW,
    ).read_signal_attempts()

    assert len(rows) == 1
    assert rows[0]["signal_source"] == (
        "RSI_EXTREME_REVERSAL_V1"
    )


def test_rsi_only_backend_source_gate_blocks_red_bar(tmp_path: Path):
    proxy = DirectionalNativeSignalDatabaseProxy(
        StrategyDatabase(),
        runs_root=tmp_path,
        enable_red_bar_strategy=False,
        enable_dri_strategy=False,
        enable_rsi_strategy=True,
    )

    assert proxy.execution_source_enabled(
        "RSI_EXTREME_REVERSAL_V1"
    ) is True
    assert proxy.execution_source_enabled(
        "REFERENCE_LEVEL"
    ) is False
    assert proxy.execution_source_enabled("RED_BAR") is False
    assert proxy.execution_source_enabled(
        "DIRECTIONAL_REGIME_INTELLIGENCE"
    ) is False


def test_red_bar_only_backend_source_gate_blocks_rsi(tmp_path: Path):
    proxy = DirectionalNativeSignalDatabaseProxy(
        StrategyDatabase(),
        runs_root=tmp_path,
        enable_red_bar_strategy=True,
        enable_dri_strategy=False,
        enable_rsi_strategy=False,
    )

    assert proxy.execution_source_enabled(
        "REFERENCE_LEVEL"
    ) is True
    assert proxy.execution_source_enabled(
        "RSI_EXTREME_REVERSAL_V1"
    ) is False


def test_dri_only_backend_source_gate_isolated(tmp_path: Path):
    proxy = DirectionalNativeSignalDatabaseProxy(
        StrategyDatabase(),
        runs_root=tmp_path,
        enable_red_bar_strategy=False,
        enable_dri_strategy=True,
        enable_rsi_strategy=False,
    )

    assert proxy.execution_source_enabled(
        "DIRECTIONAL_REGIME_INTELLIGENCE"
    ) is True
    assert proxy.execution_source_enabled(
        "REFERENCE_LEVEL"
    ) is False
    assert proxy.execution_source_enabled(
        "RSI_EXTREME_REVERSAL_V1"
    ) is False

