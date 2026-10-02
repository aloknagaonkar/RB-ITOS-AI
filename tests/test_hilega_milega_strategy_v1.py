from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from market_lab.hilega_milega_strategy_v1 import (
    EXECUTION_ENABLED,
    OBSERVATION_ONLY,
    PAPER_ORDER_ENABLED,
    FiveMinuteBar,
    HilegaMilegaBullishEngineV1,
    HilegaMilegaIndicatorEngineV1,
    IndicatorSnapshot,
)
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


def test_shadow_safety_flags_are_hard_disabled():
    assert OBSERVATION_ONLY is True
    assert EXECUTION_ENABLED is False
    assert PAPER_ORDER_ENABLED is False


def test_route_a_enters_on_fresh_rsi_ema_cross_with_rsi_above_50_and_wma():
    e = HilegaMilegaBullishEngineV1()
    e.process_enriched_bar_for_test(bar("10:00"), ind(48, 50, 45))
    events = e.process_enriched_bar_for_test(bar("10:05", 101), ind(55, 52, 49))

    assert event_types(events) == ["ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21"]
    assert e.session.active is True
    assert e.session.source == "PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21"
    assert e.session.entry_price == 101


def test_route_b_can_confirm_on_same_cross_candle_when_route_a_fails():
    e = HilegaMilegaBullishEngineV1()
    e.process_enriched_bar_for_test(bar("10:00"), ind(30, 32, 29))
    events = e.process_enriched_bar_for_test(bar("10:05", 101), ind(35, 33, 34))

    # RSI is below 50 so Route A fails, but Route B structure/rising passes.
    assert event_types(events) == [
        "PATH1_ARMED_RSI_CROSS_EMA3_UP",
        "ENTRY_PATH1_ROUTE_B_STRUCTURAL",
    ]
    assert e.session.active is True
    assert e.session.source == "PATH1_ROUTE_B_STRUCTURAL"


def test_armed_state_persists_until_later_route_b_confirmation():
    e = HilegaMilegaBullishEngineV1()
    e.process_enriched_bar_for_test(bar("10:00"), ind(30, 32, 40))
    first = e.process_enriched_bar_for_test(bar("10:05"), ind(35, 33, 40))
    assert event_types(first) == ["PATH1_ARMED_RSI_CROSS_EMA3_UP"]
    assert e.session.armed is True

    second = e.process_enriched_bar_for_test(bar("10:10", 103), ind(41, 37, 40))
    assert event_types(second) == ["ENTRY_PATH1_ROUTE_B_STRUCTURAL"]
    assert e.session.active is True


def test_immediate_structural_exit_on_first_rsi_cross_below_wma():
    e = HilegaMilegaBullishEngineV1()
    e.process_enriched_bar_for_test(bar("10:00"), ind(48, 50, 45))
    e.process_enriched_bar_for_test(bar("10:05", 100), ind(55, 52, 49))
    e.process_enriched_bar_for_test(bar("10:10", 110), ind(54, 53, 50))
    events = e.process_enriched_bar_for_test(bar("10:15", 97), ind(49, 51, 50))

    assert event_types(events)[0] == "STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21"
    assert events[0].points == pytest.approx(-3.0)
    assert e.session.active is False


def test_opening_path_0915_0920_0925():
    e = HilegaMilegaBullishEngineV1()
    ev1 = e.process_enriched_bar_for_test(bar("09:15", 100), ind(65, 60, 55))
    ev2 = e.process_enriched_bar_for_test(bar("09:20", 101), ind(63, 61, 56))
    ev3 = e.process_enriched_bar_for_test(bar("09:25", 102), ind(62, 60, 57))

    assert event_types(ev1) == ["OPENING_CANDIDATE_0915"]
    assert event_types(ev2) == ["OPENING_HOLD_0920"]
    assert event_types(ev3) == ["ENTRY_OPENING_BULLISH_CONFIRMED"]
    assert e.session.source == "OPENING_PATH"


def test_1455_closes_active_at_bar_open_locks_session_and_blocks_new_entries():
    e = HilegaMilegaBullishEngineV1()
    e.process_enriched_bar_for_test(bar("14:40"), ind(48, 50, 45))
    e.process_enriched_bar_for_test(bar("14:45", 100), ind(55, 52, 49))

    events = e.process_enriched_bar_for_test(bar("14:55", 104, open_=103), ind(56, 53, 50))
    assert event_types(events) == ["SESSION_CUTOFF_EXIT_1455_OPEN", "SESSION_LOCKED_1455"]
    assert events[0].points == pytest.approx(3.0)
    assert e.session.session_locked is True
    assert e.session.active is False

    later = e.process_enriched_bar_for_test(bar("15:00", 108), ind(60, 55, 51))
    assert later == []
    assert e.session.session_locked is True


def test_1455_cancels_armed_setup():
    e = HilegaMilegaBullishEngineV1()
    e.process_enriched_bar_for_test(bar("14:45"), ind(30, 32, 40))
    e.process_enriched_bar_for_test(bar("14:50"), ind(35, 33, 40))
    assert e.session.armed is True

    events = e.process_enriched_bar_for_test(bar("14:55"), ind(38, 35, 40))
    assert event_types(events) == ["SESSION_CUTOFF_ARM_CANCELLED", "SESSION_LOCKED_1455"]
    assert e.session.armed is False
    assert e.session.session_locked is True


def test_new_session_resets_strategy_state_but_indicator_engine_is_separate():
    e = HilegaMilegaBullishEngineV1()
    e.process_enriched_bar_for_test(bar("14:55", day=17), ind(60, 55, 50))
    assert e.session.session_locked is True

    e.process_enriched_bar_for_test(bar("09:15", day=18), ind(40, 42, 45))
    assert e.session.session_date.isoformat() == "2026-09-18"
    assert e.session.session_locked is False
    assert e.session.active is False


def batch_rsi(closes, n=9):
    out = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains = [0.0] * len(closes)
    losses = [0.0] * len(closes)
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains[i] = max(d, 0.0)
        losses[i] = max(-d, 0.0)
    ag = sum(gains[1:n + 1]) / n
    al = sum(losses[1:n + 1]) / n

    def calc(g, l):
        if l == 0:
            return 100.0 if g > 0 else 50.0
        rs = g / l
        return 100.0 - 100.0 / (1.0 + rs)

    out[n] = calc(ag, al)
    for i in range(n + 1, len(closes)):
        ag = ((n - 1) * ag + gains[i]) / n
        al = ((n - 1) * al + losses[i]) / n
        out[i] = calc(ag, al)
    return out


def batch_ema(values):
    out = [None] * len(values)
    s = None
    for i, x in enumerate(values):
        if x is None:
            continue
        s = x if s is None else 0.5 * x + 0.5 * s
        out[i] = s
    return out


def batch_wma(values, n=21):
    out = [None] * len(values)
    den = n * (n + 1) / 2
    for i in range(n - 1, len(values)):
        window = values[i - n + 1:i + 1]
        if any(x is None for x in window):
            continue
        out[i] = sum((j + 1) * x for j, x in enumerate(window)) / den
    return out


def test_streaming_indicators_match_validated_batch_formulas():
    closes = [100 + ((i * 7) % 19) - ((i * 3) % 11) for i in range(70)]
    expected_rsi = batch_rsi(closes)
    expected_ema = batch_ema(expected_rsi)
    expected_wma = batch_wma(expected_rsi)

    engine = HilegaMilegaIndicatorEngineV1()
    actual = [engine.update(x) for x in closes]

    for i, snap in enumerate(actual):
        if expected_rsi[i] is None:
            assert snap.rsi9 is None
        else:
            assert snap.rsi9 == pytest.approx(expected_rsi[i], abs=1e-12)
        if expected_ema[i] is None:
            assert snap.ema3_rsi is None
        else:
            assert snap.ema3_rsi == pytest.approx(expected_ema[i], abs=1e-12)
        if expected_wma[i] is None:
            assert snap.wma21_rsi is None
        else:
            assert snap.wma21_rsi == pytest.approx(expected_wma[i], abs=1e-12)


def test_every_strategy_step_is_hash_chain_audited(tmp_path: Path):
    store = ShadowStepAuditStoreV1(tmp_path / "hilega-step-audit.jsonl")
    e = HilegaMilegaBullishEngineV1(audit_store=store)
    e.process_enriched_bar_for_test(bar("10:00"), ind(48, 50, 45))
    e.process_enriched_bar_for_test(bar("10:05", 101), ind(55, 52, 49))

    rows = store.read_all()
    stages = [row["stage"] for row in rows]
    assert "STRATEGY_DECISION" in stages
    assert "STRATEGY_TRANSITION" in stages
    assert any(row["status"] == "ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21" for row in rows)
    ok, issue = store.verify_chain()
    assert ok is True and issue is None


def test_decision_result_audit_contains_route_failure_reasons(tmp_path):
    from market_lab.live_shadow_step_audit_v1 import ShadowStepAuditStoreV1

    store = ShadowStepAuditStoreV1(tmp_path / "audit.jsonl")
    engine = HilegaMilegaBullishEngineV1(audit_store=store)
    # Seed previous enriched bar, then fresh cross where Route A and B fail.
    engine.process_enriched_bar_for_test(
        bar("10:00", 100), IndicatorSnapshot(45, 46, 50)
    )
    engine.process_enriched_bar_for_test(
        bar("10:05", 101), IndicatorSnapshot(47, 46.5, 50)
    )
    rows = [x for x in store.read_all() if x["stage"] == "STRATEGY_DECISION_RESULT"]
    assert rows
    p = rows[-1]["payload"]
    assert p["route_a_eligible"] is True
    assert p["route_a_pass"] is False
    assert "RSI_NOT_ABOVE_50" in p["route_a_fail_reasons"]
    assert p["route_b_eligible"] is True
    assert p["route_b_pass"] is False
