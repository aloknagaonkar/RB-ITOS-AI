"""Behaviour tests for the working reference -- the deputy level.

Each test states a property the deputy needs for it to stay subordinate to the red
bar. The red bar throughout is high 104.0, low 96.0, midpoint 100.0, so "outside
the band" means a close strictly above 104.0 or strictly below 96.0.

Every candidate has to close beyond the previous completed 5-minute candle's
extreme, so ``_candles`` puts a flat ``RUNWAY`` bar in front of the specs unless a
test asks for it to be left out. It sits inside the band with a narrow range, so
it can never be promoted itself and never stands in a candidate's way -- it is
there purely to give the first spec something to have cleared.
"""

import pandas as pd
import pytest

from red_bar_lab.strategy.red_bar_v2 import RedBarV2Reference
from red_bar_lab.strategy.red_bar_v2_working_reference import (
    MINIMUM_BODY_RATIO,
    ZonePosition,
    body_ratio,
    build_working_reference,
    select_governing_reference,
    structure_failed,
    zone_position,
)

IST = "Asia/Kolkata"
TRADING_DATE = "2026-09-02"
FIRST_BUCKET = pd.Timestamp("2026-09-02 09:15", tz=IST)
EVALUATED_AT = pd.Timestamp("2026-09-02 11:00", tz=IST)

# Five-minute shapes as (open, high, low, close).
RUNWAY = (100.0, 100.5, 99.5, 100.0)
STRONG_UP_ABOVE = (105.0, 108.0, 104.5, 107.5)
STRONG_UP_HIGHER = (108.0, 111.0, 107.5, 110.5)
DOJI_ABOVE = (106.0, 107.0, 105.0, 106.2)
STRONG_UP_INSIDE = (97.0, 102.5, 96.5, 102.0)
STRONG_DOWN_BELOW = (95.0, 95.5, 91.0, 91.5)
RED_INSIDE = (100.0, 101.0, 99.0, 99.5)
# Wrong-colour neighbours, used to pin down which candle the breakout is measured
# against. Both are skipped as candidates; only their extremes matter.
TALL_RED_ABOVE = (110.0, 111.0, 105.0, 105.5)
SHORT_RED_ABOVE = (107.0, 107.2, 105.0, 105.5)
TALL_GREEN_BELOW = (91.0, 95.0, 90.0, 94.5)
SHORT_GREEN_BELOW = (93.0, 95.0, 93.0, 94.5)


def _red_bar() -> RedBarV2Reference:
    return RedBarV2Reference(
        instrument_key="NIFTY",
        trading_date=TRADING_DATE,
        reference_timestamp=pd.Timestamp("2026-09-02 09:20", tz=IST).to_pydatetime(),
        reference_open=103.0,
        reference_high=104.0,
        reference_low=96.0,
        reference_close=97.0,
        midpoint=100.0,
    )


def _bucket(index: int) -> pd.Timestamp:
    return FIRST_BUCKET + pd.Timedelta(minutes=5 * index)


def _candles(
    *specs: tuple[float, float, float, float], runway: bool = True
) -> pd.DataFrame:
    """Expand five-minute (open, high, low, close) specs into 1-minute rows.

    The first minute of each bucket carries the extremes and the last carries the
    close, which is the smallest arrangement that survives the production
    aggregation. Going through it rather than fabricating 5-minute rows directly is
    the point: the deputy has to be reachable from the data the strategy really
    gets, including the rule that a partial bucket does not aggregate at all.

    ``runway`` prepends one flat bucket before the specs, so ``_bucket(0)`` still
    names the first spec and every existing timestamp assertion keeps its meaning.
    It sits before the default ``after``, so it is never itself a candidate.
    """
    ordered = ((RUNWAY, -1),) if runway else ()
    ordered = ordered + tuple((spec, offset) for offset, spec in enumerate(specs))
    rows = []
    for (open_price, high, low, close), bucket in ordered:
        inner_high = max(open_price, close)
        inner_low = min(open_price, close)
        for minute in range(5):
            rows.append(
                {
                    "timestamp": _bucket(bucket) + pd.Timedelta(minutes=minute),
                    "open": open_price,
                    "high": high if minute == 0 else inner_high,
                    "low": low if minute == 0 else inner_low,
                    "close": close if minute == 4 else open_price,
                    "volume": 1000.0,
                }
            )
    return pd.DataFrame(rows)


def _build(
    *specs, after=None, direction="BULLISH", evaluation_time=EVALUATED_AT, runway=True
):
    return build_working_reference(
        _candles(*specs, runway=runway),
        instrument_key="NIFTY",
        evaluation_time=evaluation_time,
        red_bar=_red_bar(),
        after=after if after is not None else FIRST_BUCKET - pd.Timedelta(minutes=1),
        required_direction=direction,
    )


def test_the_body_filter_is_a_ratio_so_it_needs_no_tuning():
    # 2 points of body in an 8-point range, whatever the instrument trades at.
    assert body_ratio(100.0, 104.0, 96.0, 102.0) == pytest.approx(0.25)
    assert body_ratio(1000.0, 1040.0, 960.0, 1020.0) == pytest.approx(0.25)
    # A candle with no range has no displacement to measure, so it can never pass.
    assert body_ratio(100.0, 100.0, 100.0, 100.0) == 0.0
    assert 0.0 < MINIMUM_BODY_RATIO < 1.0


@pytest.mark.parametrize(
    ("price", "expected"),
    [
        (104.5, ZonePosition.ABOVE),
        (104.0, ZonePosition.INSIDE),
        (100.0, ZonePosition.INSIDE),
        (96.0, ZonePosition.INSIDE),
        (95.5, ZonePosition.BELOW),
    ],
)
def test_the_band_edges_belong_to_the_red_bar(price, expected):
    """A close exactly on the high or low is INSIDE: the senior reference wins ties."""
    assert zone_position(_red_bar(), price) is expected


def test_a_weak_bodied_candle_is_skipped_and_waiting_continues():
    """The first bounce off a low is usually a wick, and a wick is not a level."""
    deputy = _build(DOJI_ABOVE, STRONG_UP_ABOVE)
    assert deputy is not None
    assert deputy.reference_timestamp == _bucket(1)
    assert deputy.body_ratio >= MINIMUM_BODY_RATIO


def test_no_qualifying_candle_means_no_deputy_and_no_entry():
    """Fail-closed: absence of a level is not licence to use the frozen one."""
    assert _build(DOJI_ABOVE, DOJI_ABOVE) is None


def test_a_candle_closing_inside_the_band_cannot_be_a_deputy():
    """Inside the band the red bar is already in charge, so a deputy governs nothing.

    The skipped candle here has a stronger body than the one that is accepted; it
    is rejected purely on location.
    """
    deputy = _build(STRONG_UP_INSIDE, STRONG_UP_ABOVE)
    assert deputy is not None
    assert deputy.reference_timestamp == _bucket(1)
    assert deputy.zone_side == ZonePosition.ABOVE.value


def test_the_deputy_prices_its_own_midpoint_and_records_its_side():
    """A bearish deputy below the band, with the level a structural exit will use."""
    deputy = _build(RED_INSIDE, STRONG_DOWN_BELOW, direction="BEARISH")
    assert deputy is not None
    assert deputy.direction == "BEARISH"
    assert deputy.zone_side == ZonePosition.BELOW.value
    assert deputy.reference_high == pytest.approx(95.5)
    assert deputy.reference_low == pytest.approx(91.0)
    assert deputy.midpoint == pytest.approx(93.25)
    assert deputy.trading_date == TRADING_DATE
    assert deputy.level_type == "WORKING_OPPOSITE_CANDLE"


def test_a_bullish_deputy_ignores_red_candles_and_vice_versa():
    """The colour is the whole signal that the move has turned."""
    assert _build(STRONG_DOWN_BELOW, direction="BULLISH") is None
    assert _build(STRONG_UP_ABOVE, direction="BEARISH") is None


def test_the_candle_a_trade_exited_on_cannot_become_its_own_re_entry_reference():
    """``after`` is compared strictly, so the exit bar is not a re-entry level."""
    both = (STRONG_UP_ABOVE, STRONG_UP_HIGHER)
    assert _build(*both, after=_bucket(0)).reference_timestamp == _bucket(1)
    # One minute earlier and the same first candle would have been taken, so the
    # exclusion is the comparison and not something else about the bar.
    earlier = _bucket(0) - pd.Timedelta(minutes=1)
    assert _build(*both, after=earlier).reference_timestamp == _bucket(0)


def test_a_candle_that_closes_inside_the_previous_range_has_not_displaced_anything():
    """Body quality is about the candle; this is about what the candle took out.

    Same candidate in both halves -- only the neighbour's high moves. A strong
    green body that closes back inside the range of the bar before it has not
    established anything for a counter-trend entry to lean on, and this is the one
    entry path with no futures VWAP gate behind it.
    """
    assert _build(TALL_RED_ABOVE, STRONG_UP_ABOVE) is None
    cleared = _build(SHORT_RED_ABOVE, STRONG_UP_ABOVE)
    assert cleared is not None
    assert cleared.reference_timestamp == _bucket(1)


def test_the_breakout_is_measured_against_the_bar_before_not_the_last_same_colour_bar():
    """The neighbour is taken from the unfiltered frame, colour included.

    ``TALL_RED_ABOVE`` is the wrong colour to be a bullish candidate, so a
    comparison drawn from the surviving candidates would skip straight past it to
    the flat runway and promote a candle that never cleared 111.0. Reaching it
    requires reading the frame the aggregation produced.
    """
    assert _build(TALL_RED_ABOVE, STRONG_UP_ABOVE) is None
    assert _build(TALL_GREEN_BELOW, STRONG_DOWN_BELOW, direction="BEARISH") is None


def test_a_bearish_deputy_has_to_close_below_the_previous_low():
    """The mirror image, with the same single moving part: the neighbour's low."""
    assert _build(TALL_GREEN_BELOW, STRONG_DOWN_BELOW, direction="BEARISH") is None
    cleared = _build(SHORT_GREEN_BELOW, STRONG_DOWN_BELOW, direction="BEARISH")
    assert cleared is not None
    assert cleared.reference_timestamp == _bucket(1)
    assert cleared.zone_side == ZonePosition.BELOW.value


def test_a_candle_with_nothing_in_front_of_it_cannot_qualify():
    """No predecessor means no range to have taken out, so it fails closed.

    The candle is identical in both halves and passes colour, location and body in
    both; the only difference is whether anything preceded it.
    """
    assert _build(STRONG_UP_ABOVE, runway=False) is None
    assert _build(STRONG_UP_ABOVE) is not None


def test_a_partial_five_minute_bucket_is_not_a_deputy_yet():
    """Only completed candles count, so the level cannot move under the strategy."""
    mid_bucket = _bucket(0) + pd.Timedelta(minutes=3)
    assert _build(STRONG_UP_ABOVE, evaluation_time=mid_bucket) is None


def test_required_direction_must_actually_be_a_direction():
    with pytest.raises(ValueError, match="BULLISH or BEARISH"):
        _build(STRONG_UP_ABOVE, direction="SIDEWAYS")


def test_the_red_bar_takes_control_back_the_moment_price_returns_to_its_band():
    """One reference in force at a time, decided by the current close alone."""
    red_bar = _red_bar()
    deputy = _build(STRONG_UP_ABOVE)
    assert deputy is not None

    governing, name = select_governing_reference(red_bar, deputy, 107.0)
    assert (governing, name) == (deputy, "WORKING")
    # Back inside the band, and exactly on its edge, which counts as inside.
    assert select_governing_reference(red_bar, deputy, 100.0) == (red_bar, "RED_BAR")
    assert select_governing_reference(red_bar, deputy, 104.0) == (red_bar, "RED_BAR")
    # Straight through to the far side: an ABOVE deputy does not govern down there.
    assert select_governing_reference(red_bar, deputy, 90.0) == (red_bar, "RED_BAR")


def test_with_no_deputy_the_red_bar_governs_everywhere():
    red_bar = _red_bar()
    for close in (90.0, 100.0, 110.0):
        assert select_governing_reference(red_bar, None, close) == (red_bar, "RED_BAR")


@pytest.mark.parametrize(
    ("direction", "close", "broken"),
    [
        ("BULLISH", 99.9, True),
        ("BULLISH", 100.0, False),
        ("BULLISH", 100.1, False),
        ("BEARISH", 100.1, True),
        ("BEARISH", 100.0, False),
        ("BEARISH", 99.9, False),
    ],
)
def test_structure_breaks_only_on_a_close_through_the_governing_level(
    direction, close, broken
):
    """A price that cannot open a position cannot close one either: ties hold."""
    assert structure_failed(100.0, direction=direction, close=close) is broken


def test_the_structural_test_reads_the_deputy_level_when_the_deputy_governs():
    """The exit follows whichever reference is in force, not always the red bar."""
    red_bar = _red_bar()
    deputy = _build(STRONG_UP_ABOVE)
    governing, name = select_governing_reference(red_bar, deputy, 107.0)
    assert name == "WORKING"
    # The deputy's own midpoint, well above the red bar's 100.0.
    assert governing.midpoint == pytest.approx(106.25)
    assert structure_failed(governing.midpoint, direction="BULLISH", close=105.0) is True
    assert structure_failed(red_bar.midpoint, direction="BULLISH", close=105.0) is False


def test_structure_direction_must_actually_be_a_direction():
    with pytest.raises(ValueError, match="BULLISH or BEARISH"):
        structure_failed(100.0, direction="FLAT", close=99.0)
