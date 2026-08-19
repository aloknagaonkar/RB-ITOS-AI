from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from red_bar_lab.operations.red_bar_v2_ui_snapshot import (
    RedBarV2UISnapshot,
    persist_red_bar_v2_ui_snapshot,
    read_red_bar_v2_ui_snapshot,
)
from red_bar_lab.services import red_bar_v2_current_session as module


class _Database:
    def read_paper_execution_orders(self, account_id):
        assert account_id == "PAPER-STD"
        return [
            {
                "execution_strategy_source": "RED_BAR_V2",
                "exit_timestamp": "2026-08-19T09:45:00+05:30",
            },
            {
                "execution_strategy_source": "REFERENCE_LEVEL",
                "exit_timestamp": "2026-08-19T10:00:00+05:30",
            },
        ]


class _Upstox:
    def intraday_candles(self, instrument_key, interval_minutes=1):
        assert interval_minutes == 1
        return pd.DataFrame(
            {"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1.0]},
            index=pd.DatetimeIndex(["2026-08-19T09:20:00+05:30"]),
        )


def test_current_session_blocks_without_futures_key(tmp_path, monkeypatch):
    monkeypatch.delenv("NIFTY_FUTURES_INSTRUMENT_KEY", raising=False)
    result = module.evaluate_current_session_red_bar_v2(
        upstox=_Upstox(),
        database=_Database(),
        settings=SimpleNamespace(artifacts_root=tmp_path),
        instrument_key="NSE_INDEX|Nifty 50",
    )
    assert result.status == "BLOCKED"
    assert result.reason == "NIFTY_FUTURES_INSTRUMENT_KEY_UNAVAILABLE"


def test_current_session_refreshes_snapshot_for_paper(tmp_path, monkeypatch):
    monkeypatch.delenv("NIFTY_FUTURES_INSTRUMENT_KEY", raising=False)
    persist_red_bar_v2_ui_snapshot(
        RedBarV2UISnapshot(
            futures_instrument_key="NSE_FO|12345",
            futures_symbol="NIFTY26AUGFUT",
            futures_expiry="2026-08-27",
        ),
        artifacts_root=tmp_path,
    )
    captured = {}

    def fake_run(index_candles, futures_candles, **kwargs):
        captured.update(kwargs)
        persist_red_bar_v2_ui_snapshot(
            RedBarV2UISnapshot(
                alignment_status="READY",
                admission_allowed=True,
                direction="BULLISH",
                option_side="CE",
                last_evaluation_timestamp="2026-08-19T09:20:00+05:30",
                futures_instrument_key=kwargs["vwap_instrument_key"],
            ),
            artifacts_root=kwargs["artifacts_root"],
        )
        return SimpleNamespace(
            health=SimpleNamespace(status="READY", reason="FULL_TIMESTAMP_ALIGNMENT"),
            replay=SimpleNamespace(admitted_candidates=1, closed_trades=1),
        )

    monkeypatch.setattr(module, "run_monitored_red_bar_v2_futures_replay", fake_run)
    result = module.evaluate_current_session_red_bar_v2(
        upstox=_Upstox(),
        database=_Database(),
        settings=SimpleNamespace(artifacts_root=tmp_path),
        instrument_key="NSE_INDEX|Nifty 50",
    )

    assert result.status == "READY"
    assert result.admitted_candidates == 1
    assert captured["exit_timestamps"] == ["2026-08-19T09:45:00+05:30"]
    snapshot = read_red_bar_v2_ui_snapshot(tmp_path)
    assert snapshot is not None
    assert snapshot.mode == "PAPER"
    assert snapshot.execution_scope == "PAPER_TRADING_ONLY"
