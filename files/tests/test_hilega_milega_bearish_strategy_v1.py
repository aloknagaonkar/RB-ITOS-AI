from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from market_lab.hilega_milega_bearish_strategy_v1 import (
    EXECUTION_ENABLED,
    OBSERVATION_ONLY,
    PAPER_ORDER_ENABLED,
    HilegaMilegaBearishEngineV1,
)
from market_lab.hilega_milega_strategy_v1 import FiveMinuteBar, IndicatorSnapshot
from market_lab.live_shadow_step_audit_v1 import ShadowStepAuditStoreV1

IST = ZoneInfo("Asia/Kolkata")


def bar(hhmm: str, close: float = 100.0, *, open_: float | None = None, day: int = 17) -> FiveMinuteBar:
    h, m = map(int, hhmm.split(":"))
    o = close if open_ is None else open_
    return FiveMinuteBar(
        ts=datetime(2026, 9, day, h, m, tzinfo=IST),
        open=o,
        high=max(o, close) + 1,
        low=min(o, close) - 1,
        close=close,
    )


def ind(rsi: float, ema: float, wma: float) -> IndicatorSnapshot:
    return IndicatorSnapshot(rsi, ema, wma)


def event_types(events):
    return [e.event_type for e in events]


def test_bearish_safety_flags_are_hard_disabled():
    assert OBSERVATION_ONLY is True
    assert EXECUTION_ENABLED is False
    assert PAPER_ORDER_ENABLED is False


def test_bearish_route_a_enters_on_fresh_cross_down_below_50_and_wma():
    e = HilegaMilegaBearishEngineV1()
    e.process_enriched_bar_for_test(bar("10:00"), ind(52, 50, 55))
    events = e.process_enriched_bar_for_test(bar("10:05", 99), ind(45, 48, 51))

    assert event_types(events) == ["ENTRY_BEARISH_ROUTE_A_CROSS_RSI50_BELOW_WMA21"]
    assert e.session.active is True
    assert e.session.source == "BEARISH_ROUTE_A_CROSS_RSI50_BELOW_WMA21"
    assert e.session.entry_price == 99


def test_bearish_route_b_can_confirm_on_same_cross_candle_when_route_a_fails():
    e = HilegaMilegaBearishEngineV1()
    e.process_enriched_bar_for_test(bar("10:00"), ind(70, 68, 71))
    events = e.process_enriched_bar_for_test(bar("10:05", 99), ind(65, 67, 66))

    # RSI remains above 50 so Route A fails; Route B structure/falling passes.
    assert event_types(events) == [
        "BEARISH_PATH1_ARMED_RSI_CROSS_EMA3_DOWN",
        "ENTRY_BEARISH_ROUTE_B_STRUCTURAL",
    ]
    assert e.session.active is True
    assert e.session.source == "BEARISH_ROUTE_B_STRUCTURAL"


def test_bearish_armed_state_persists_until_later_route_b_confirmation():
    e = HilegaMilegaBearishEngineV1()
    e.process_enriched_bar_for_test(bar("10:00"), ind(70, 68, 60))
    first = e.process_enriched_bar_for_test(bar("10:05"), ind(65, 67, 60))
    assert event_types(first) == ["BEARISH_PATH1_ARMED_RSI_CROSS_EMA3_DOWN"]
    assert e.session.armed is True

    second = e.process_enriched_bar_for_test(bar("10:10", 97), ind(59, 63, 60))
    assert event_types(second) == ["ENTRY_BEARISH_ROUTE_B_STRUCTURAL"]
    assert e.session.active is True


def test_bearish_immediate_structural_exit_on_first_rsi_cross_above_wma():
    e = HilegaMilegaBearishEngineV1()
    e.process_enriched_bar_for_test(bar("10:00"), ind(52, 50, 55))
    e.process_enriched_bar_for_test(bar("10:05", 100), ind(45, 48, 51))
    e.process_enriched_bar_for_test(bar("10:10", 92), ind(46, 47, 50))
    events = e.process_enriched_bar_for_test(bar("10:15", 95), ind(51, 49, 50))

    assert event_types(events)[0] == "STRUCTURAL_EXIT_BEARISH_RSI_CROSS_ABOVE_WMA21"
    assert events[0].points == pytest.approx(5.0)
    assert e.session.active is False


def test_bearish_opening_path_0915_0920_0925():
    e = HilegaMilegaBearishEngineV1()
    ev1 = e.process_enriched_bar_for_test(bar("09:15", 100), ind(35, 40, 45))
    ev2 = e.process_enriched_bar_for_test(bar("09:20", 99), ind(37, 39, 44))
    ev3 = e.process_enriched_bar_for_test(bar("09:25", 98), ind(38, 40, 43))

    assert event_types(ev1) == ["OPENING_BEARISH_CANDIDATE_0915"]
    assert event_types(ev2) == ["OPENING_BEARISH_HOLD_0920"]
    assert event_types(ev3) == ["ENTRY_OPENING_BEARISH_CONFIRMED"]
    assert e.session.source == "BEARISH_OPENING_PATH"


def test_bearish_1455_closes_active_at_open_locks_and_blocks_entries():
    e = HilegaMilegaBearishEngineV1()
    e.process_enriched_bar_for_test(bar("14:40"), ind(52, 50, 55))
    e.process_enriched_bar_for_test(bar("14:45", 100), ind(45, 48, 51))

    events = e.process_enriched_bar_for_test(bar("14:55", 94, open_=95), ind(44, 47, 50))
    assert event_types(events) == ["BEARISH_SESSION_CUTOFF_EXIT_1455_OPEN", "BEARISH_SESSION_LOCKED_1455"]
    assert events[0].points == pytest.approx(5.0)
    assert e.session.session_locked is True
    assert e.session.active is False

    later = e.process_enriched_bar_for_test(bar("15:00", 90), ind(40, 45, 50))
    assert later == []
    assert e.session.session_locked is True


def test_bearish_1455_cancels_armed_setup():
    e = HilegaMilegaBearishEngineV1()
    e.process_enriched_bar_for_test(bar("14:45"), ind(70, 68, 60))
    e.process_enriched_bar_for_test(bar("14:50"), ind(65, 67, 60))
    assert e.session.armed is True

    events = e.process_enriched_bar_for_test(bar("14:55"), ind(62, 65, 60))
    assert event_types(events) == ["BEARISH_SESSION_CUTOFF_ARM_CANCELLED", "BEARISH_SESSION_LOCKED_1455"]
    assert e.session.armed is False
    assert e.session.session_locked is True


def test_bearish_new_session_resets_strategy_state():
    e = HilegaMilegaBearishEngineV1()
    e.process_enriched_bar_for_test(bar("14:55", day=17), ind(40, 45, 50))
    assert e.session.session_locked is True

    e.process_enriched_bar_for_test(bar("09:15", day=18), ind(60, 58, 55))
    assert e.session.session_date.isoformat() == "2026-09-18"
    assert e.session.session_locked is False
    assert e.session.active is False


def test_bearish_decision_audit_contains_failure_reasons_and_chain(tmp_path: Path):
    store = ShadowStepAuditStoreV1(tmp_path / "bearish-step-audit.jsonl")
    e = HilegaMilegaBearishEngineV1(audit_store=store)
    e.process_enriched_bar_for_test(bar("10:00"), ind(55, 54, 50))
    e.process_enriched_bar_for_test(bar("10:05", 99), ind(53, 54.5, 50))

    rows = store.read_all()
    results = [r for r in rows if r["stage"] == "STRATEGY_DECISION_RESULT"]
    assert results
    p = results[-1]["payload"]
    assert p["direction"] == "BEARISH"
    assert p["route_a_eligible"] is True
    assert p["route_a_pass"] is False
    assert "RSI_NOT_BELOW_50" in p["route_a_fail_reasons"]
    assert p["route_b_eligible"] is True
    assert p["route_b_pass"] is False
    assert "NEITHER_RSI_NOR_EMA_BELOW_WMA21" in p["route_b_fail_reasons"]
    ok, issue = store.verify_chain()
    assert ok is True and issue is None
