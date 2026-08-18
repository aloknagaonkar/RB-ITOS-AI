from types import SimpleNamespace

import pandas as pd

from red_bar_lab.execution import red_bar_v2_legacy_adapter as legacy_module
from red_bar_lab.services import red_bar_v2_shadow_worker as worker_module
from red_bar_lab.services.red_bar_v2_parity import (
    NormalizedParityDecision,
    compare_normalized,
    normalize_replay_candidate,
    run_legacy_worker_parity,
)
from red_bar_lab.services.red_bar_v2_shadow_worker import RedBarV2WorkerState
from red_bar_lab.strategy.red_bar_v2 import (
    RedBarV2DirectionDecision,
    RedBarV2EventType,
    RedBarV2State,
)

IST = "Asia/Kolkata"


def _candles():
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


def _decision(
    *,
    event=RedBarV2EventType.INITIAL_BULLISH_ALIGNMENT,
    state=RedBarV2State.CONFIRMED_BULLISH,
    direction="BULLISH",
    side="CE",
    entry_type="INITIAL",
    provisional=False,
):
    return RedBarV2DirectionDecision(
        event_type=event,
        state=state,
        direction=direction,
        option_side=side,
        entry_type=entry_type,
        trend_strength="PROVISIONAL" if provisional else "CONFIRMED" if direction else None,
        context_timestamp=pd.Timestamp("2026-08-21 09:34", tz=IST).to_pydatetime(),
        reference_timestamp=pd.Timestamp("2026-08-21 09:20", tz=IST).to_pydatetime(),
        close_price=105.0 if direction == "BULLISH" else 95.0,
        rsi_value=60.0 if direction == "BULLISH" else 40.0,
        vwap_value=102.0 if direction == "BULLISH" else 98.0,
        rsi_aligned=direction is not None,
        vwap_aligned=direction is not None,
        midpoint_aligned=not provisional and direction is not None,
        context_fresh=True,
        reason="parity-test",
    )


def _patch(monkeypatch, *, initial=None, reversal=None, upgrade=None):
    for module in (legacy_module, worker_module):
        monkeypatch.setattr(module, "build_red_bar_v2_reference", lambda *a, **k: object())
        monkeypatch.setattr(module, "build_latest_snapshot", lambda *a, **k: object())
        if initial is not None:
            monkeypatch.setattr(module, "evaluate_initial_direction", lambda *a, **k: initial)
        if reversal is not None:
            monkeypatch.setattr(module, "evaluate_reversal_direction", lambda *a, **k: reversal)
        if upgrade is not None:
            monkeypatch.setattr(module, "evaluate_midpoint_upgrade", lambda *a, **k: upgrade)


def test_initial_bullish_legacy_worker_parity(monkeypatch):
    _patch(monkeypatch, initial=_decision())
    report = run_legacy_worker_parity(
        candles=_candles(),
        instrument_key="NIFTY",
        evaluation_time=pd.Timestamp("2026-08-21 09:35", tz=IST),
        trade_rows=[],
    )
    assert report.matched is True
    assert report.mismatches == ()
    assert report.legacy.option_side == "CE"
    assert report.legacy.admission_code == "INITIAL_BULLISH_ALIGNMENT"


def test_initial_bearish_active_trade_block_parity(monkeypatch):
    bearish = _decision(
        event=RedBarV2EventType.INITIAL_BEARISH_ALIGNMENT,
        state=RedBarV2State.CONFIRMED_BEARISH,
        direction="BEARISH",
        side="PE",
    )
    _patch(monkeypatch, initial=bearish)
    report = run_legacy_worker_parity(
        candles=_candles(),
        instrument_key="NIFTY",
        evaluation_time=pd.Timestamp("2026-08-21 09:35", tz=IST),
        trade_rows=[
            {
                "trade_id": "CE-1",
                "instrument_key": "NIFTY",
                "option_side": "CE",
                "status": "ACTIVE",
                "entry_timestamp": "2026-08-21T09:25:00+05:30",
            }
        ],
    )
    assert report.matched is True
    assert report.legacy.candidate_allowed is False
    assert report.legacy.admission_code == "ACTIVE_TRADE_BLOCK"
    assert report.legacy.trade_lifecycle_state == "ACTIVE"


def test_reversal_admission_parity(monkeypatch):
    reversal = _decision(
        event=RedBarV2EventType.BULLISH_REVERSAL_DETECTED,
        state=RedBarV2State.PROVISIONAL_BULLISH,
        direction="BULLISH",
        side="CE",
        entry_type="REVERSAL",
        provisional=True,
    )
    _patch(monkeypatch, reversal=reversal)
    state = RedBarV2WorkerState(
        directional_state=RedBarV2State.CONFIRMED_BEARISH,
        previous_direction="BEARISH",
    )
    report = run_legacy_worker_parity(
        candles=_candles(),
        instrument_key="NIFTY",
        evaluation_time=pd.Timestamp("2026-08-21 09:35", tz=IST),
        trade_rows=[
            {
                "trade_id": "PE-1",
                "instrument_key": "NIFTY",
                "option_side": "PE",
                "status": "CLOSED",
                "exit_timestamp": "2026-08-21T09:30:00+05:30",
            }
        ],
        state=state,
    )
    assert report.matched is True
    assert report.legacy.admission_code == "REVERSAL_CONTEXT_ALIGNED_FLAT"
    assert report.legacy.reversal_event_id == report.worker.reversal_event_id


def test_midpoint_upgrade_is_normalized_as_state_event(monkeypatch):
    upgrade = _decision(
        event=RedBarV2EventType.FULL_DIRECTIONAL_ALIGNMENT,
        state=RedBarV2State.CONFIRMED_BULLISH,
        direction="BULLISH",
        side="CE",
        entry_type="STATE_UPGRADE",
    )
    _patch(monkeypatch, upgrade=upgrade)
    state = RedBarV2WorkerState(
        directional_state=RedBarV2State.PROVISIONAL_BULLISH,
        previous_direction="BULLISH",
    )
    report = run_legacy_worker_parity(
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
    assert report.matched is True
    assert report.legacy.semantic_status == "STATE_EVENT"
    assert report.worker.semantic_status == "STATE_EVENT"
    assert report.legacy.candidate_allowed is False


def test_compare_normalized_reports_exact_mismatch_field():
    base = NormalizedParityDecision(
        event_type="INITIAL_BULLISH_ALIGNMENT",
        directional_state="CONFIRMED_BULLISH",
        direction="BULLISH",
        option_side="CE",
        entry_type="INITIAL",
        trend_strength="CONFIRMED",
        candidate_allowed=True,
        admission_code="INITIAL_BULLISH_ALIGNMENT",
        decision_id="A",
        reversal_event_id=None,
        trade_lifecycle_state="FLAT",
        semantic_status="CANDIDATE_ADMITTED",
    )
    changed = NormalizedParityDecision(**{**base.to_record(), "option_side": "PE"})
    report = compare_normalized(
        base,
        changed,
        evaluated_at=pd.Timestamp("2026-08-21 09:35", tz=IST),
    )
    assert report.matched is False
    assert len(report.mismatches) == 1
    assert report.mismatches[0].field == "option_side"
    assert report.to_record()["mismatches"][0]["worker_value"] == "PE"


def test_replay_candidate_normalization_is_exportable():
    event = SimpleNamespace(
        direction="BEARISH",
        option_side="PE",
        candidate_allowed=True,
        admission_code="REVERSAL_CONTEXT_ALIGNED_FLAT",
        details={
            "event_type": "BEARISH_REVERSAL_DETECTED",
            "directional_state": "PROVISIONAL_BEARISH",
            "entry_type": "REVERSAL",
            "trend_strength": "PROVISIONAL",
            "decision_id": "D1",
            "reversal_event_id": "R1",
            "trade_lifecycle_state": "CLOSED",
            "midpoint_aligned": False,
        },
    )
    normalized = normalize_replay_candidate(event)
    assert normalized.option_side == "PE"
    assert normalized.semantic_status == "CANDIDATE_ADMITTED"
    assert normalized.to_record()["reversal_event_id"] == "R1"
