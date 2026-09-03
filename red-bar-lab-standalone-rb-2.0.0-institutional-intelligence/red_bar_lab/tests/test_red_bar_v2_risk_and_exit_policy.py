"""Behaviour tests for the Red Bar V2 risk plan and its exit policy.

These are behaviour tests, not implementation mirrors: each one states a
property a replay must have for its R-multiples to mean anything.
"""

from datetime import datetime, time, timedelta, timezone

import pytest

from red_bar_lab.domain.red_bar_v2 import (
    Bar,
    Direction,
    ExitReason,
    RiskPlanRejected,
    RiskPlanRejection,
    StopTrigger,
    StopTriggerCandle,
    TriggerResolution,
    advance,
    build_risk_plan,
    find_stop_trigger,
    open_position,
)

IST = timezone(timedelta(hours=5, minutes=30))


def _ts(hour: int, minute: int) -> datetime:
    return datetime(2026, 9, 2, hour, minute, tzinfo=IST)


def _bar(hour: int, minute: int, open_: float, high: float, low: float, close: float) -> Bar:
    return Bar(timestamp=_ts(hour, minute), open=open_, high=high, low=low, close=close)


def _plan(
    direction: Direction = Direction.BULLISH,
    *,
    entry: float = 100.0,
    stop: float = 90.0,
    reward_multiple: float | None = 2.0,
    trail_activation_r: float = 1.0,
    session_flat_time: time = time(15, 15),
):
    bullish = direction is Direction.BULLISH
    candle = StopTriggerCandle(
        trigger=StopTrigger.MIDPOINT_CROSS,
        timestamp=_ts(9, 25),
        index_high=stop if not bullish else stop + 20.0,
        index_low=stop if bullish else stop - 20.0,
    )
    return build_risk_plan(
        direction=direction,
        entry_timestamp=_ts(9, 30),
        entry_price=entry,
        trigger_candle=candle,
        reward_multiple=reward_multiple,
        trail_activation_r=trail_activation_r,
        session_flat_time=session_flat_time,
    )


def _run(plan, bars):
    """Walk the bars, returning the first outcome produced."""
    position = open_position(plan)
    for bar in bars:
        position, outcome = advance(position, bar)
        if outcome is not None:
            return outcome
    return None


def test_long_plan_prices_target_trail_and_risk_from_the_stop():
    plan = _plan(entry=100.0, stop=90.0)
    assert plan.risk_points == pytest.approx(10.0)
    assert plan.target_price == pytest.approx(120.0)
    assert plan.trail_activation_price == pytest.approx(110.0)
    assert plan.trail_distance_points == pytest.approx(10.0)
    assert plan.r_multiple_at(120.0) == pytest.approx(2.0)
    assert plan.r_multiple_at(90.0) == pytest.approx(-1.0)


def test_short_plan_mirrors_every_level_below_the_entry():
    plan = _plan(Direction.BEARISH, entry=100.0, stop=110.0)
    assert plan.risk_points == pytest.approx(10.0)
    assert plan.target_price == pytest.approx(80.0)
    assert plan.trail_activation_price == pytest.approx(90.0)
    assert plan.r_multiple_at(80.0) == pytest.approx(2.0)
    assert plan.r_multiple_at(110.0) == pytest.approx(-1.0)


def test_no_target_is_priced_unless_a_reward_multiple_is_asked_for():
    """The default plan has no target, so nothing above entry pre-empts the trail.

    A 2R target with a 1R trail activation confines the trail to the 1R-to-2R
    window, where the target always fires first, so the trail can never do the
    thing it exists for. A study that wants a target asks for one.
    """
    candle = StopTriggerCandle(
        trigger=StopTrigger.MIDPOINT_CROSS,
        timestamp=_ts(9, 25),
        index_high=110.0,
        index_low=90.0,
    )
    common = dict(
        direction=Direction.BULLISH,
        entry_timestamp=_ts(9, 30),
        entry_price=100.0,
        trigger_candle=candle,
    )

    default = build_risk_plan(**common)
    assert default.target_price is None
    assert default.reward_multiple is None
    # Everything the trail needs is still priced.
    assert default.trail_activation_price == pytest.approx(110.0)
    assert default.trail_distance_points == pytest.approx(10.0)

    assert build_risk_plan(**common, reward_multiple=2.0).target_price == pytest.approx(
        120.0
    )


def test_an_untargeted_position_rides_the_trail_past_two_r():
    """The same series that a 2R target would cap at +2R runs to +3R instead.

    It gives back one trail width doing so. That trade -- a fixed +2.0 for an
    average that can exceed it -- is the whole reason the default target is gone.
    """
    plan = _plan(entry=100.0, stop=90.0, reward_multiple=None)
    outcome = _run(
        plan,
        [
            _bar(9, 35, 100.0, 140.0, 99.0, 139.0),
            _bar(9, 40, 139.0, 139.0, 129.0, 130.0),
        ],
    )
    assert outcome.exit_reason is ExitReason.TRAILING_STOP
    assert outcome.exit_price == pytest.approx(130.0)
    assert outcome.r_multiple == pytest.approx(3.0)
    assert outcome.target_price is None


def test_a_missing_trigger_candle_is_rejected_with_a_reason_code():
    with pytest.raises(RiskPlanRejected) as caught:
        build_risk_plan(
            direction=Direction.BULLISH,
            entry_timestamp=_ts(9, 30),
            entry_price=100.0,
            trigger_candle=None,
        )
    assert caught.value.rejection is RiskPlanRejection.NO_TRIGGER_CANDLE


@pytest.mark.parametrize(
    ("stop", "rejection"),
    [
        (105.0, RiskPlanRejection.STOP_ON_WRONG_SIDE),
        (100.0, RiskPlanRejection.STOP_ON_WRONG_SIDE),
        (95.0, RiskPlanRejection.RISK_BELOW_FLOOR),
        (30.0, RiskPlanRejection.RISK_ABOVE_CAP),
    ],
)
def test_untradable_risk_is_rejected_rather_than_sized(stop, rejection):
    with pytest.raises(RiskPlanRejected) as caught:
        _plan(entry=100.0, stop=stop)
    assert caught.value.rejection is rejection


MIDPOINT = 100.0

# The two series sit on different instruments: the futures trade ~140 points
# above the index, which is why a stop may never be read off a futures bar.
_INDEX_UP = [
    _bar(9, 20, 102.0, 103.0, 97.0, 98.0),
    _bar(9, 25, 98.0, 104.0, 96.0, 103.0),
    _bar(9, 30, 103.0, 108.0, 102.0, 107.0),
]
_FUTURES_UP = [
    _bar(9, 20, 240.0, 241.0, 237.0, 238.0),
    _bar(9, 25, 238.0, 240.0, 237.0, 239.0),
    _bar(9, 30, 239.0, 246.0, 238.0, 245.0),
]
_VWAP_UP = {_ts(9, 20): 240.0, _ts(9, 25): 240.0, _ts(9, 30): 241.0}


def _trigger(**overrides):
    kwargs = dict(
        direction=Direction.BULLISH,
        index_bars=_INDEX_UP,
        futures_bars=_FUTURES_UP,
        futures_vwap=_VWAP_UP,
        reference_midpoint=MIDPOINT,
        reference_timestamp=_ts(9, 20),
        entry_timestamp=_ts(9, 35),
    )
    kwargs.update(overrides)
    return find_stop_trigger(**kwargs)


def test_a_futures_vwap_cross_still_reads_its_stop_off_the_index_candle():
    candle = _trigger()
    assert candle is not None
    assert candle.trigger is StopTrigger.FUTURES_VWAP_CROSS
    assert candle.timestamp == _ts(9, 30)
    # The 09:30 index low, not the 09:30 futures low of 238.0.
    assert candle.stop_for(Direction.BULLISH) == pytest.approx(102.0)
    assert candle.index_low < 200.0


def test_latest_and_widest_resolve_a_double_crossing_differently():
    latest = _trigger(resolution=TriggerResolution.LATEST)
    widest = _trigger(resolution=TriggerResolution.WIDEST)
    assert latest.timestamp == _ts(9, 30)
    assert latest.stop_for(Direction.BULLISH) == pytest.approx(102.0)
    assert widest.timestamp == _ts(9, 25)
    assert widest.trigger is StopTrigger.MIDPOINT_CROSS
    assert widest.stop_for(Direction.BULLISH) == pytest.approx(96.0)


def test_no_bar_after_the_entry_can_set_the_stop():
    candle = _trigger(entry_timestamp=_ts(9, 25))
    assert candle is not None
    assert candle.timestamp == _ts(9, 25)
    assert candle.trigger is StopTrigger.MIDPOINT_CROSS


def test_the_bar_the_entry_sits_inside_is_taken_as_handed_over():
    """The slot holding the entry is eligible, and its price is the caller's job.

    The entry fires on a one-minute close, so the 5-minute slot that crossed the
    level has not finished -- excluding it here would leave a real entry with no
    stop at all. What must not happen is the caller resampling the whole day and
    handing over the finished bar; see ``_bars_known_at`` in the decision log.
    """
    full = _trigger(entry_timestamp=_ts(9, 25))
    known_at_entry = _trigger(
        entry_timestamp=_ts(9, 25),
        # 09:25-09:25 only: the 96.0 low printed later in that slot.
        index_bars=[_INDEX_UP[0], _bar(9, 25, 98.0, 100.8, 97.5, 100.5)],
    )
    assert full.stop_for(Direction.BULLISH) == pytest.approx(96.0)
    assert known_at_entry.stop_for(Direction.BULLISH) == pytest.approx(97.5)


def test_the_reference_bar_itself_is_not_a_crossing_candidate():
    assert _trigger(entry_timestamp=_ts(9, 20)) is None


def test_a_futures_cross_with_no_index_bar_in_that_slot_is_skipped():
    candle = _trigger(index_bars=_INDEX_UP[:2])
    assert candle is not None
    assert candle.trigger is StopTrigger.MIDPOINT_CROSS
    assert candle.timestamp == _ts(9, 25)


def test_an_unreachable_level_yields_no_trigger():
    assert _trigger(reference_midpoint=500.0, futures_vwap={}) is None


def test_a_bearish_crossing_takes_the_index_high_as_its_stop():
    index_bars = [
        _bar(9, 20, 98.0, 103.0, 97.0, 102.0),
        _bar(9, 25, 102.0, 103.0, 95.0, 97.0),
        _bar(9, 30, 97.0, 99.0, 93.0, 94.0),
    ]
    futures_bars = [
        _bar(9, 20, 240.0, 244.0, 239.0, 243.0),
        _bar(9, 25, 243.0, 244.0, 241.0, 242.0),
        _bar(9, 30, 242.0, 243.0, 237.0, 238.0),
    ]
    vwap = {_ts(9, 20): 240.0, _ts(9, 25): 240.0, _ts(9, 30): 241.0}
    latest = _trigger(
        direction=Direction.BEARISH,
        index_bars=index_bars,
        futures_bars=futures_bars,
        futures_vwap=vwap,
    )
    assert latest.timestamp == _ts(9, 30)
    assert latest.stop_for(Direction.BEARISH) == pytest.approx(99.0)
    widest = _trigger(
        direction=Direction.BEARISH,
        index_bars=index_bars,
        futures_bars=futures_bars,
        futures_vwap=vwap,
        resolution=TriggerResolution.WIDEST,
    )
    assert widest.stop_for(Direction.BEARISH) == pytest.approx(103.0)


def test_a_clean_target_hit_pays_exactly_the_reward_multiple():
    plan = _plan(entry=100.0, stop=90.0)
    outcome = _run(plan, [_bar(9, 35, 101.0, 121.0, 100.0, 120.5)])
    assert outcome.exit_reason is ExitReason.TARGET
    assert outcome.exit_price == pytest.approx(120.0)
    assert outcome.r_multiple == pytest.approx(2.0)
    assert outcome.bars_held == 1
    assert outcome.holding_minutes == pytest.approx(5.0)


def test_a_stop_before_activation_is_recorded_as_the_initial_stop():
    plan = _plan(entry=100.0, stop=90.0)
    outcome = _run(plan, [_bar(9, 35, 99.0, 101.0, 89.0, 91.0)])
    assert outcome.exit_reason is ExitReason.STOP_LOSS
    assert outcome.exit_price == pytest.approx(90.0)
    assert outcome.r_multiple == pytest.approx(-1.0)


def test_a_bar_holding_both_the_stop_and_the_target_is_scored_as_a_loss():
    """OHLC cannot order two intra-bar touches, so ambiguity costs the strategy."""
    plan = _plan(entry=100.0, stop=90.0)
    outcome = _run(plan, [_bar(9, 35, 100.0, 121.0, 89.0, 110.0)])
    assert outcome.exit_reason is ExitReason.STOP_LOSS
    assert outcome.r_multiple == pytest.approx(-1.0)
    # The excursion is still recorded; it is simply not paid.
    assert outcome.mfe_points == pytest.approx(21.0)
    assert outcome.mae_points == pytest.approx(11.0)


def test_reaching_activation_moves_the_stop_to_breakeven():
    plan = _plan(entry=100.0, stop=90.0)
    outcome = _run(
        plan,
        [
            _bar(9, 35, 100.0, 110.0, 99.0, 109.0),
            _bar(9, 40, 109.0, 109.5, 99.5, 100.0),
        ],
    )
    assert outcome.exit_reason is ExitReason.TRAILING_STOP
    assert outcome.exit_price == pytest.approx(100.0)
    assert outcome.r_multiple == pytest.approx(0.0)
    assert outcome.bars_held == 2


def test_a_favourable_wick_cannot_rescue_a_bar_that_already_stopped_out():
    """The trail is advanced only after the bar is tested against the stop in force.

    Advancing first would fill this exit at 120.0 for +2R instead of 102.0 for
    +0.2R, which is the most common way a replay flatters itself.
    """
    plan = _plan(entry=100.0, stop=90.0, reward_multiple=4.0)
    outcome = _run(
        plan,
        [
            _bar(9, 35, 100.0, 112.0, 95.0, 111.0),
            _bar(9, 40, 103.0, 130.0, 101.0, 129.0),
        ],
    )
    assert outcome.exit_reason is ExitReason.TRAILING_STOP
    assert outcome.exit_price == pytest.approx(102.0)
    assert outcome.r_multiple == pytest.approx(0.2)
    assert outcome.mfe_r == pytest.approx(3.0)


def test_the_trailing_stop_never_retreats():
    plan = _plan(entry=100.0, stop=90.0, reward_multiple=4.0)
    position = open_position(plan)
    position, outcome = advance(position, _bar(9, 35, 100.0, 125.0, 99.0, 124.0))
    assert outcome is None
    assert position.trailing_active is True
    assert position.stop_in_force == pytest.approx(115.0)
    position, outcome = advance(position, _bar(9, 40, 124.0, 118.0, 116.0, 117.0))
    assert outcome is None
    assert position.stop_in_force == pytest.approx(115.0)
    assert position.extreme_favourable == pytest.approx(125.0)


def test_the_session_flat_exit_fills_at_the_open_of_the_flat_bar():
    plan = _plan(entry=100.0, stop=90.0)
    outcome = _run(plan, [_bar(15, 15, 105.0, 121.0, 95.0, 106.0)])
    assert outcome.exit_reason is ExitReason.SESSION_FLAT
    assert outcome.exit_price == pytest.approx(105.0)
    assert outcome.r_multiple == pytest.approx(0.5)


def test_the_stop_still_outranks_the_session_flat_exit():
    plan = _plan(entry=100.0, stop=90.0)
    outcome = _run(plan, [_bar(15, 15, 105.0, 106.0, 89.0, 95.0)])
    assert outcome.exit_reason is ExitReason.STOP_LOSS
    assert outcome.exit_price == pytest.approx(90.0)


def test_a_structural_break_closes_the_position_at_that_close():
    """The reason for holding has gone, so the position goes -- at the close.

    The stop is nowhere near this bar. On a slow bleed back through the level the
    trade was taken on, the structural exit is the only thing that gets the
    position out at all, and it fills at ``bar.close`` because a close-based
    signal is not known until the bar is complete.
    """
    plan = _plan(entry=100.0, stop=90.0, reward_multiple=None)
    _, outcome = advance(
        open_position(plan),
        _bar(9, 35, 100.0, 101.0, 96.0, 97.0),
        structure_failed=True,
    )
    assert outcome.exit_reason is ExitReason.STRUCTURE
    assert outcome.exit_price == pytest.approx(97.0)
    assert outcome.r_multiple == pytest.approx(-0.3)


def test_a_short_is_broken_by_a_close_back_above_its_level():
    plan = _plan(Direction.BEARISH, entry=100.0, stop=110.0, reward_multiple=None)
    _, outcome = advance(
        open_position(plan),
        _bar(9, 35, 100.0, 104.0, 99.0, 103.0),
        structure_failed=True,
    )
    assert outcome.exit_reason is ExitReason.STRUCTURE
    assert outcome.exit_price == pytest.approx(103.0)
    assert outcome.r_multiple == pytest.approx(-0.3)


def test_anything_reached_inside_the_bar_outranks_a_structural_break():
    """Structure is known only at the close, so intra-bar touches happened first."""
    stopped = advance(
        open_position(_plan(entry=100.0, stop=90.0, reward_multiple=None)),
        _bar(9, 35, 100.0, 101.0, 89.0, 95.0),
        structure_failed=True,
    )[1]
    assert stopped.exit_reason is ExitReason.STOP_LOSS
    assert stopped.exit_price == pytest.approx(90.0)

    targeted = advance(
        open_position(_plan(entry=100.0, stop=90.0, reward_multiple=2.0)),
        _bar(9, 35, 100.0, 121.0, 99.0, 99.5),
        structure_failed=True,
    )[1]
    assert targeted.exit_reason is ExitReason.TARGET
    assert targeted.exit_price == pytest.approx(120.0)


def test_a_short_trails_down_and_exits_above_its_ratcheted_stop():
    plan = _plan(Direction.BEARISH, entry=100.0, stop=110.0, reward_multiple=4.0)
    outcome = _run(
        plan,
        [
            _bar(9, 35, 99.0, 99.0, 88.0, 89.0),
            _bar(9, 40, 89.0, 99.0, 89.0, 98.0),
        ],
    )
    assert outcome.exit_reason is ExitReason.TRAILING_STOP
    assert outcome.exit_price == pytest.approx(98.0)
    assert outcome.r_multiple == pytest.approx(0.2)
    assert outcome.mfe_r == pytest.approx(1.2)
    assert outcome.mae_points == pytest.approx(0.0)


def test_a_position_that_never_exits_reports_no_outcome():
    plan = _plan(entry=100.0, stop=90.0)
    position = open_position(plan)
    for bar in (_bar(9, 35, 100.0, 105.0, 99.0, 104.0), _bar(9, 40, 104.0, 106.0, 98.0, 99.0)):
        position, outcome = advance(position, bar)
        assert outcome is None
    assert position.bars_held == 2
    assert position.trailing_active is False
    assert position.stop_in_force == pytest.approx(90.0)


def test_the_2026_09_02_session_resolves_to_the_futures_vwap_crossing():
    """Regression built on measured NIFTY levels for 2026-09-02.

    Measured: the 09:20-09:25 red reference bar (high 23828.60, low 23786.80,
    midpoint 23807.70), the index low of the 09:25 candle that crossed the
    midpoint (23813.30), and the index low of the 09:30 slot whose *futures*
    candle crossed the futures VWAP (23818.75). The remaining opens and closes
    are constructed to reproduce those two crossings, and the entry price is a
    stand-in: only the trigger selection and the plan arithmetic are asserted.
    """
    index_bars = [
        _bar(9, 20, 23825.00, 23828.60, 23786.80, 23790.00),
        _bar(9, 25, 23814.00, 23824.00, 23813.30, 23820.00),
        _bar(9, 30, 23820.00, 23830.00, 23818.75, 23828.00),
    ]
    futures_bars = [
        _bar(9, 20, 23952.00, 23958.00, 23948.00, 23950.00),
        _bar(9, 25, 23950.00, 23959.00, 23948.00, 23955.00),
        _bar(9, 30, 23956.00, 23975.00, 23954.00, 23972.00),
    ]
    vwap = {_ts(9, 20): 23960.00, _ts(9, 25): 23960.00, _ts(9, 30): 23960.00}
    common = dict(
        direction=Direction.BULLISH,
        index_bars=index_bars,
        futures_bars=futures_bars,
        futures_vwap=vwap,
        reference_midpoint=23807.70,
        reference_timestamp=_ts(9, 20),
        entry_timestamp=_ts(9, 35),
    )

    latest = find_stop_trigger(**common)
    assert latest.trigger is StopTrigger.FUTURES_VWAP_CROSS
    assert latest.timestamp == _ts(9, 30)
    assert latest.stop_for(Direction.BULLISH) == pytest.approx(23818.75)

    widest = find_stop_trigger(**common, resolution=TriggerResolution.WIDEST)
    assert widest.trigger is StopTrigger.MIDPOINT_CROSS
    assert widest.stop_for(Direction.BULLISH) == pytest.approx(23813.30)

    common_plan = dict(
        direction=Direction.BULLISH,
        entry_timestamp=_ts(9, 35),
        entry_price=23840.00,
        trigger_candle=latest,
    )
    plan = build_risk_plan(**common_plan)
    assert plan.risk_points == pytest.approx(21.25)
    assert plan.trail_activation_price == pytest.approx(23861.25)
    # No target by default, so the trail owns everything above the activation.
    assert plan.target_price is None
    assert plan.reward_multiple is None

    # The measured arithmetic is still asserted, on a plan that asked for a 2R
    # target: 23840.00 + 2 x 21.25.
    targeted = build_risk_plan(**common_plan, reward_multiple=2.0)
    assert targeted.target_price == pytest.approx(23882.50)
