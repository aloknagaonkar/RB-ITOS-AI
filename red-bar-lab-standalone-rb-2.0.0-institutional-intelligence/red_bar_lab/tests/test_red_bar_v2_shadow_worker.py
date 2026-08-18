from __future__ import annotations

import pandas as pd

from red_bar_lab.execution.red_bar_v2_admission_policy import AdmissionCode
from red_bar_lab.services import red_bar_v2_shadow_worker as worker_module
from red_bar_lab.services.red_bar_v2_shadow_worker import (
    RedBarV2ShadowWorker,
    RedBarV2WorkerConfig,
    RedBarV2WorkerState,
)
from red_bar_lab.strategy.red_bar_v2 import (
    RedBarV2DirectionDecision,
    RedBarV2EventType,
    RedBarV2State,
)

IST = "Asia/Kolkata"


def _candles() -> pd.DataFrame:
    timestamps = pd.date_range("2026-08-21 09:15", periods=25, freq="1min", tz=IST)
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": [100.0] * 25,
            "high": [101.0] * 25,
            "low": [99.0] * 25,
            "close": [100.0] * 25,
            "volume": [1000.0] * 25,
        }
    )


def _direction(
    *,
    event: RedBarV2EventType = RedBarV2EventType.INITIAL_BULLISH_ALIGNMENT,
    state: RedBarV2State = RedBarV2State.CONFIRMED_BULLISH,
    direction: str | None = "BULLISH",
    option_side: str | None = "CE",
    entry_type: str | None = "INITIAL",
    midpoint_aligned: bool = True,
) -> RedBarV2DirectionDecision:
    return RedBarV2DirectionDecision(
        event_type=event,
        state=state,
        direction=direction,
        option_side=option_side,
        entry_type=entry_type,
        trend_strength="CONFIRMED" if midpoint_aligned else "PROVISIONAL",
        context_timestamp=pd.Timestamp("2026-08-21 09:34", tz=IST).to_pydatetime(),
        reference_timestamp=pd.Timestamp("2026-08-21 09:20", tz=IST).to_pydatetime(),
        close_price=105.0,
        rsi_value=60.0,
        vwap_value=102.0,
        rsi_aligned=True,
        vwap_aligned=True,
        midpoint_aligned=midpoint_aligned,
        context_fresh=True,
        reason="test",
    )


def _patch_initial(monkeypatch, direction=None):
    selected = direction or _direction()
    monkeypatch.setattr(worker_module, "build_red_bar_v2_reference", lambda *a, **k: object())
    monkeypatch.setattr(worker_module, "build_latest_snapshot", lambda *a, **k: object())
    monkeypatch.setattr(worker_module, "evaluate_initial_direction", lambda *a, **k: selected)


def test_worker_is_disabled_by_default():
    state = RedBarV2WorkerState()
    event = RedBarV2ShadowWorker().evaluate(
        candles=_candles(),
        instrument_key="NIFTY",
        evaluation_time=pd.Timestamp("2026-08-21 09:35", tz=IST),
        trade_rows=[],
        state=state,
    )
    assert event.status == "DISABLED"
    assert event.next_state is state
    assert event.execution_requested is False


def test_shadow_worker_admits_without_requesting_execution(monkeypatch):
    _patch_initial(monkeypatch)
    worker = RedBarV2ShadowWorker(config=RedBarV2WorkerConfig(enabled=True))
    event = worker.evaluate(
        candles=_candles(),
        instrument_key="NIFTY",
        evaluation_time=pd.Timestamp("2026-08-21 09:35", tz=IST),
        trade_rows=[],
    )
    assert event.status == "SHADOW_ADMITTED"
    assert event.execution_requested is False
    assert event.admission_decision.candidate_allowed is True
    assert event.next_state.previous_direction == "BULLISH"
    assert event.admission_decision.decision_id in event.next_state.processed_candidate_ids


def test_non_shadow_worker_emits_execution_request_only(monkeypatch):
    _patch_initial(monkeypatch)
    worker = RedBarV2ShadowWorker(
        config=RedBarV2WorkerConfig(enabled=True, shadow_only=False)
    )
    event = worker.evaluate(
        candles=_candles(),
        instrument_key="NIFTY",
        evaluation_time=pd.Timestamp("2026-08-21 09:35", tz=IST),
        trade_rows=[],
    )
    assert event.status == "EXECUTION_REQUESTED"
    assert event.execution_requested is True
    assert not hasattr(event, "order")


def test_active_trade_blocks_independent_worker(monkeypatch):
    _patch_initial(monkeypatch)
    worker = RedBarV2ShadowWorker(config=RedBarV2WorkerConfig(enabled=True))
    event = worker.evaluate(
        candles=_candles(),
        instrument_key="NIFTY",
        evaluation_time=pd.Timestamp("2026-08-21 09:35", tz=IST),
        trade_rows=[
            {
                "trade_id": "PE-1",
                "instrument_key": "NIFTY",
                "option_side": "PE",
                "status": "ACTIVE",
                "entry_timestamp": "2026-08-21T09:25:00+05:30",
            }
        ],
    )
    assert event.status == "BLOCKED"
    assert event.admission_decision.admission_code == AdmissionCode.ACTIVE_TRADE_BLOCK
    assert event.next_state.processed_candidate_ids == frozenset()


def test_processed_identity_blocks_duplicate_without_mutating_input(monkeypatch):
    _patch_initial(monkeypatch)
    worker = RedBarV2ShadowWorker(config=RedBarV2WorkerConfig(enabled=True))
    first = worker.evaluate(
        candles=_candles(),
        instrument_key="NIFTY",
        evaluation_time=pd.Timestamp("2026-08-21 09:35", tz=IST),
        trade_rows=[],
    )
    original = RedBarV2WorkerState(
        processed_candidate_ids=first.next_state.processed_candidate_ids,
        consumed_reversal_ids=first.next_state.consumed_reversal_ids,
    )
    second = worker.evaluate(
        candles=_candles(),
        instrument_key="NIFTY",
        evaluation_time=pd.Timestamp("2026-08-21 09:35", tz=IST),
        trade_rows=[],
        state=original,
    )
    assert second.admission_decision.admission_code == AdmissionCode.DUPLICATE_SIGNAL
    assert second.status == "BLOCKED"
    assert original.processed_candidate_ids == first.next_state.processed_candidate_ids


def test_midpoint_upgrade_changes_state_without_execution_request(monkeypatch):
    upgrade = _direction(
        event=RedBarV2EventType.FULL_DIRECTIONAL_ALIGNMENT,
        state=RedBarV2State.CONFIRMED_BULLISH,
        entry_type="STATE_UPGRADE",
    )
    monkeypatch.setattr(worker_module, "build_red_bar_v2_reference", lambda *a, **k: object())
    monkeypatch.setattr(worker_module, "build_latest_snapshot", lambda *a, **k: object())
    monkeypatch.setattr(worker_module, "evaluate_midpoint_upgrade", lambda *a, **k: upgrade)
    state = RedBarV2WorkerState(
        directional_state=RedBarV2State.PROVISIONAL_BULLISH,
        previous_direction="BULLISH",
        processed_candidate_ids=frozenset({"ORIGINAL"}),
    )
    worker = RedBarV2ShadowWorker(
        config=RedBarV2WorkerConfig(enabled=True, shadow_only=False)
    )
    event = worker.evaluate(
        candles=_candles(),
        instrument_key="NIFTY",
        evaluation_time=pd.Timestamp("2026-08-21 09:35", tz=IST),
        trade_rows=[
            {
                "trade_id": "CE-1",
                "instrument_key": "NIFTY",
                "option_side": "CE",
                "status": "ACTIVE",
            }
        ],
        state=state,
    )
    assert event.status == "STATE_UPGRADED"
    assert event.execution_requested is False
    assert event.next_state.directional_state == RedBarV2State.CONFIRMED_BULLISH
    assert event.next_state.processed_candidate_ids == frozenset({"ORIGINAL"})
    assert event.to_record()["next_state"]["directional_state"] == "CONFIRMED_BULLISH"
