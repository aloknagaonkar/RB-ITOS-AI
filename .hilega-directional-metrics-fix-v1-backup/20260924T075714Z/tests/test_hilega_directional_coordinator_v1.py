from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from market_lab.hilega_directional_coordinator_v1 import HilegaDirectionalCoordinatorV1
from market_lab.hilega_milega_strategy_v1 import FiveMinuteBar, IndicatorSnapshot

IST = ZoneInfo("Asia/Kolkata")


def bar(hhmm: str, close: float = 100.0) -> FiveMinuteBar:
    h, m = map(int, hhmm.split(":"))
    return FiveMinuteBar(
        datetime(2026, 9, 24, h, m, tzinfo=IST),
        close, close + 1, close - 1, close, 100,
    )


def ind(rsi: float, ema: float, wma: float) -> IndicatorSnapshot:
    return IndicatorSnapshot(rsi, ema, wma)


def types(decision):
    return [e.event_type for e in decision.accepted_events]


def suppressed(decision):
    return [e.event_type for e in decision.suppressed_events]


def test_single_active_owner_and_opposite_arm_may_coexist():
    c = HilegaDirectionalCoordinatorV1()

    # Seed bullish cross-up -> Route A entry.
    c.process_enriched_bar_for_test(bar("10:00"), ind(45, 47, 40))
    d = c.process_enriched_bar_for_test(bar("10:05"), ind(55, 50, 45))
    assert d.trade_owner_after == "BULLISH"
    assert c.bullish.session.active is True

    # Fresh bearish cross-down, but not yet bearish route A/B entry:
    # opposite side may become informational ARMED while bullish remains ACTIVE.
    d = c.process_enriched_bar_for_test(bar("10:10"), ind(53, 54, 45))
    assert d.trade_owner_after == "BULLISH"
    assert c.bullish.session.active is True
    assert c.bearish.session.armed is True
    assert "BEARISH_PATH1_ARMED_RSI_CROSS_EMA3_DOWN" in types(d)


def test_opposite_entry_is_blocked_and_preserved_as_armed():
    c = HilegaDirectionalCoordinatorV1()

    c.process_enriched_bar_for_test(bar("10:00"), ind(45, 47, 40))
    c.process_enriched_bar_for_test(bar("10:05"), ind(55, 50, 45))
    assert c.trade_owner == "BULLISH"

    # First arm bearish while RSI is still above WMA, so bullish does not exit.
    c.process_enriched_bar_for_test(bar("10:10"), ind(53, 54, 45))
    assert c.trade_owner == "BULLISH"
    assert c.bearish.session.armed is True

    # Route B becomes eligible through EMA<WMA while RSI itself remains >WMA.
    # Bullish is therefore still active, so bearish entry must be suppressed.
    d = c.process_enriched_bar_for_test(bar("10:15"), ind(48, 44, 46))
    assert c.trade_owner == "BULLISH"
    assert "ENTRY_BEARISH_ROUTE_B_STRUCTURAL" in suppressed(d)
    assert c.bearish.session.active is False
    assert c.bearish.session.armed is True


def test_exit_candle_blocks_opposite_entry_but_next_bar_can_continue():
    c = HilegaDirectionalCoordinatorV1()

    # Bullish Route A entry.
    c.process_enriched_bar_for_test(bar("10:00"), ind(45, 47, 40))
    c.process_enriched_bar_for_test(bar("10:05"), ind(55, 50, 45))
    assert c.trade_owner == "BULLISH"

    # Arm bearish while bullish remains active.
    c.process_enriched_bar_for_test(bar("10:10"), ind(53, 54, 45))
    assert c.bearish.session.armed is True

    # Bearish Route B becomes eligible through EMA<WMA, but RSI stays >WMA,
    # so bullish remains active and the bearish entry is suppressed.
    c.process_enriched_bar_for_test(bar("10:15"), ind(48, 44, 46))
    assert c.trade_owner == "BULLISH"
    assert c.bearish.session.armed is True

    # RSI now crosses below WMA => bullish structural exit.
    # Bearish remains structurally eligible, but same-candle new entry is blocked.
    d = c.process_enriched_bar_for_test(bar("10:20"), ind(44, 45, 46))
    assert "STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21" in types(d)
    assert c.trade_owner == "NONE"
    assert c.bearish.session.active is False
    assert c.bearish.session.armed is True

    # Next completed candle can continue from preserved bearish ARMED.
    d = c.process_enriched_bar_for_test(bar("10:25"), ind(40, 43, 45))
    assert c.trade_owner == "BEARISH"
    assert "ENTRY_BEARISH_ROUTE_B_STRUCTURAL" in types(d)
    assert c.bearish.session.active is True


def test_never_both_active():
    c = HilegaDirectionalCoordinatorV1()

    seq = [
        ("10:00", ind(45, 47, 40)),
        ("10:05", ind(55, 50, 45)),
        ("10:10", ind(53, 54, 45)),
        ("10:15", ind(48, 44, 46)),
        ("10:20", ind(44, 45, 46)),
        ("10:25", ind(40, 43, 45)),
    ]
    for t, i in seq:
        c.process_enriched_bar_for_test(bar(t), i)
        assert not (c.bullish.session.active and c.bearish.session.active)
