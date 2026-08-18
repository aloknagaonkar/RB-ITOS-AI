from types import SimpleNamespace

import pandas as pd

from red_bar_lab.execution import red_bar_v2_legacy_adapter as legacy
from red_bar_lab.execution.red_bar_v2_admission_policy import AdmissionCode
from red_bar_lab.execution.red_bar_v2_legacy_adapter import (
    RedBarV2LegacyAdapter,
    RedBarV2LegacyConfig,
)
from red_bar_lab.strategy.red_bar_v2 import (
    RedBarV2DirectionDecision,
    RedBarV2EventType,
    RedBarV2State,
)

IST = "Asia/Kolkata"


def _candles():
    timestamps = pd.date_range("2026-08-21 09:15", periods=20, freq="1min", tz=IST)
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": [100.0] * 20,
            "high": [101.0] * 20,
            "low": [99.0] * 20,
            "close": [100.0] * 20,
            "volume": [1000.0] * 20,
        }
    )


def _direction():
    stamp = pd.Timestamp("2026-08-21 09:34", tz=IST).to_pydatetime()
    return RedBarV2DirectionDecision(
        event_type=RedBarV2EventType.INITIAL_BULLISH_ALIGNMENT,
        state=RedBarV2State.CONFIRMED_BULLISH,
        direction="BULLISH",
        option_side="CE",
        entry_type="INITIAL",
        trend_strength="CONFIRMED",
        context_timestamp=stamp,
        reference_timestamp=pd.Timestamp("2026-08-21 09:20", tz=IST).to_pydatetime(),
        close_price=105.0,
        rsi_value=60.0,
        vwap_value=102.0,
        rsi_aligned=True,
        vwap_aligned=True,
        midpoint_aligned=True,
        context_fresh=True,
        reason="test",
    )


def _patch_direction(monkeypatch):
    monkeypatch.setattr(legacy, "build_red_bar_v2_reference", lambda *a, **k: object())
    monkeypatch.setattr(legacy, "build_latest_snapshot", lambda *a, **k: object())
    monkeypatch.setattr(legacy, "evaluate_initial_direction", lambda *a, **k: _direction())


def test_adapter_is_disabled_by_default():
    result = RedBarV2LegacyAdapter().evaluate(
        candles=_candles(),
        instrument_key="NIFTY",
        evaluation_time=pd.Timestamp("2026-08-21 09:35", tz=IST),
        trade_rows=[],
    )
    assert result.status == "DISABLED"
    assert result.direction_decision is None
    assert result.admission_decision is None


def test_enabled_adapter_admits_in_shadow_without_opening_order(monkeypatch):
    _patch_direction(monkeypatch)
    adapter = RedBarV2LegacyAdapter(
        config=RedBarV2LegacyConfig(enabled=True, execution_enabled=False)
    )
    result = adapter.evaluate(
        candles=_candles(),
        instrument_key="NIFTY",
        evaluation_time=pd.Timestamp("2026-08-21 09:35", tz=IST),
        trade_rows=[],
    )
    assert result.status == "SHADOW_ADMITTED"
    assert result.admission_decision.candidate_allowed is True
    assert result.admission_decision.admission_code == AdmissionCode.INITIAL_BULLISH_ALIGNMENT
    assert result.order is None


def test_active_legacy_trade_blocks_candidate(monkeypatch):
    _patch_direction(monkeypatch)
    adapter = RedBarV2LegacyAdapter(config=RedBarV2LegacyConfig(enabled=True))
    result = adapter.evaluate(
        candles=_candles(),
        instrument_key="NIFTY",
        evaluation_time=pd.Timestamp("2026-08-21 09:35", tz=IST),
        trade_rows=[
            {
                "order_id": "PAPER-1",
                "instrument_key": "NIFTY",
                "option_side": "PE",
                "status": "OPEN",
                "entry_timestamp": "2026-08-21T09:20:00+05:30",
            }
        ],
    )
    assert result.status == "BLOCKED"
    assert result.admission_decision.admission_code == AdmissionCode.ACTIVE_TRADE_BLOCK


def test_execution_opt_in_uses_existing_open_long_option(monkeypatch):
    _patch_direction(monkeypatch)
    adapter = RedBarV2LegacyAdapter(
        config=RedBarV2LegacyConfig(enabled=True, execution_enabled=True)
    )
    evaluated = adapter.evaluate(
        candles=_candles(),
        instrument_key="NIFTY",
        evaluation_time=pd.Timestamp("2026-08-21 09:35", tz=IST),
        trade_rows=[],
    )

    calls = []

    class Engine:
        def open_long_option(self, **kwargs):
            calls.append(kwargs)
            return {"order_id": "PAPER-RBV2", "status": "OPEN"}

        def close_position(self, **kwargs):
            raise AssertionError("Legacy adapter must not close positions")

    contract = SimpleNamespace(lot_size=50)
    result = adapter.execute_admitted(
        result=evaluated,
        paper_engine=Engine(),
        zerodha=object(),
        contract=contract,
        quantity=50,
        underlying_name="NIFTY 50",
        underlying_price=25000.0,
    )

    assert result.status == "ORDER_OPENED"
    assert result.order["order_id"] == "PAPER-RBV2"
    assert len(calls) == 1
    assert calls[0]["signal_id"] == evaluated.admission_decision.decision_id
    assert calls[0]["reason"].startswith("RED_BAR_V2:")
    assert calls[0]["policy_metadata"]["execution_strategy_source"] == "RED_BAR_V2"


def test_execution_disabled_never_calls_engine(monkeypatch):
    _patch_direction(monkeypatch)
    adapter = RedBarV2LegacyAdapter(
        config=RedBarV2LegacyConfig(enabled=True, execution_enabled=False)
    )
    evaluated = adapter.evaluate(
        candles=_candles(),
        instrument_key="NIFTY",
        evaluation_time=pd.Timestamp("2026-08-21 09:35", tz=IST),
        trade_rows=[],
    )

    class Engine:
        def open_long_option(self, **kwargs):
            raise AssertionError("Execution must remain disabled")

    result = adapter.execute_admitted(
        result=evaluated,
        paper_engine=Engine(),
        zerodha=object(),
        contract=SimpleNamespace(lot_size=50),
        quantity=50,
        underlying_name="NIFTY 50",
        underlying_price=25000.0,
    )
    assert result.status == "SHADOW_ADMITTED"
    assert result.order is None
