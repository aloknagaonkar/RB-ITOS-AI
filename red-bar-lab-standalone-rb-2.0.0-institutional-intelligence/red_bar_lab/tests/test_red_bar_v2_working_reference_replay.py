"""The deputy reached through the replay: the dead window after an exit.

Before this path existed, a closed trade left one way back in -- a later
1-minute candle had to touch the frozen midpoint. A move that ran away from the
red bar and reversed *without* returning to it was sat out in full, which is the
gap these two days describe.

Both days share their first twenty-five minutes:

* 09:15-09:19 rises, so it cannot be the reference.
* 09:20-09:24 falls, so it is: high 24004.4, low 23989.6, **midpoint 23997.0**.
  The band is 23989.6-24004.4 and never moves again.
* 09:24 closes at 23990.0, below the midpoint and with the futures below their
  VWAP, so a bearish entry is admitted.
* 09:25-09:34 sells off to 23870.0 and the trade is closed at **09:35**.
* 09:35-09:39 bottoms out. The exit moment excludes this bucket from the search,
  so the first candle that can be promoted is the 09:40 one.

They then differ in exactly one thing -- how high the 09:40 candle reaches:

* ``DEPUTY_UNDER_THE_BAND`` tops out at 23940.4, leaving 49 points of room
  between it and the band, so a later close can take out its high while still
  outside the red bar's reach. That close is the working entry.
* ``DEPUTY_INTO_THE_BAND`` wicks to 23992.4, above the band's low. Its high is
  now unreachable from outside the band, so the rally hands control back to the
  red bar before any working entry can trigger.

Neither day ever touches 23997.0 before the deputy is settled, so nothing here
is decided by the midpoint wait that used to be the only option.
"""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from red_bar_lab.services.red_bar_v2_futures_historical_replay import (
    replay_red_bar_v2_day_with_futures_vwap,
)

IST = timezone(timedelta(hours=5, minutes=30))
SESSION_START = datetime(2026, 8, 24, 9, 15, tzinfo=IST)
EXIT_AT = pd.Timestamp("2026-08-24 09:35", tz=IST)

RED_BAR_HIGH = 24004.4
RED_BAR_LOW = 23989.6
MIDPOINT = 23997.0

# Five buckets of five 1-minute closes, shared by both days.
OPENING = [24000.0, 24001.0, 24002.0, 24003.0, 24004.0]
RED_BAR = [24003.0, 24000.0, 23997.0, 23994.0, 23990.0]
SELL_OFF = [23980.0, 23960.0, 23940.0, 23920.0, 23900.0]
SELL_OFF_CONTINUES = [23890.0, 23880.0, 23875.0, 23872.0, 23870.0]
BASE = [23865.0, 23860.0, 23858.0, 23856.0, 23855.0]

# 09:40, the candle that can be promoted, in its two shapes.
DEPUTY_UNDER_THE_BAND = [23880.0, 23895.0, 23910.0, 23925.0, 23940.0]
DEPUTY_INTO_THE_BAND = [23890.0, 23930.0, 23992.0, 23960.0, 23985.0]

# 09:45, the rally that either takes out the deputy's high from outside the band
# or carries price back into it.
RALLY_UNDER_THE_BAND = [23950.0, 23960.0, 23970.0, 23980.0, 23985.0]
RALLY_INTO_THE_BAND = [23990.0, 23995.0, 24000.0, 24002.0, 24003.0]


def _frame(closes: list[float], volumes: list[float]) -> pd.DataFrame:
    """One-minute OHLCV from closes, each candle opening where the last closed.

    The 0.4 of padding on each extreme is what keeps a bucket's high strictly
    above its own close, so a candle can never confirm itself: taking out the
    deputy's high always needs a *later* candle.
    """
    opens = [closes[0] - 0.2, *closes[:-1]]
    return pd.DataFrame(
        {
            "open": opens,
            "high": [max(o, c) + 0.4 for o, c in zip(opens, closes)],
            "low": [min(o, c) - 0.4 for o, c in zip(opens, closes)],
            "close": closes,
            "volume": volumes,
        },
        index=pd.date_range(SESSION_START, periods=len(closes), freq="1min"),
    )


def _replay(deputy: list[float], rally: list[float], *, exits=(EXIT_AT,)):
    closes = [
        *OPENING,
        *RED_BAR,
        *SELL_OFF,
        *SELL_OFF_CONTINUES,
        *BASE,
        *deputy,
        *rally,
    ]
    index_frame = _frame(closes, [10.0 + step for step in range(len(closes))])
    # Futures decline all day, so their close sits under the session VWAP
    # throughout. That is what admits the opening bearish entry -- and the
    # working entry is admitted later against the same falling series, which is
    # the point: the deputy path reads no VWAP at all.
    futures_frame = _frame(
        [24000.0 - 2.0 * step for step in range(len(closes))],
        [1000.0 + 10.0 * step for step in range(len(closes))],
    )
    return replay_red_bar_v2_day_with_futures_vwap(
        index_frame,
        futures_frame,
        instrument_key="NSE_INDEX|Nifty 50",
        vwap_instrument_key="NSE_FO|NIFTY-FUT",
        exit_timestamps=exits,
    )[0]


def _admitted(replay, entry_type: str | None = None) -> list:
    return [
        event
        for event in replay.events
        if event.event_type == "CANDIDATE_ADMISSION"
        and event.candidate_allowed
        and (entry_type is None or event.details.get("entry_type") == entry_type)
    ]


def test_the_fixture_really_does_exit_a_bearish_trade_before_the_deputy_window():
    """The premise, asserted rather than assumed.

    Everything below is about what happens *after* a closed trade, so a day that
    never opened one would make each of those tests vacuously true.
    """
    replay = _replay(DEPUTY_UNDER_THE_BAND, RALLY_UNDER_THE_BAND)
    initial = _admitted(replay, "INITIAL")
    assert len(initial) == 1
    assert initial[0].direction == "BEARISH"
    assert pd.Timestamp(initial[0].timestamp) < EXIT_AT
    assert replay.closed_trades == 1
    assert replay.reference_midpoint == pytest.approx(MIDPOINT)


def test_a_trend_away_from_the_band_is_traded_without_returning_to_the_midpoint():
    """The gap this path closes: an entry with the midpoint never touched.

    23950.0 clears the deputy's high while sitting 39 points under the band, so
    the frozen midpoint plays no part in admitting it.
    """
    replay = _replay(DEPUTY_UNDER_THE_BAND, RALLY_UNDER_THE_BAND)
    working = _admitted(replay, "WORKING")
    assert len(working) == 1
    entry = working[0]
    assert entry.direction == "BULLISH"
    assert entry.option_side == "CE"
    assert entry.admission_code == "WORKING_REFERENCE_CONFIRMED_FLAT"
    assert entry.details["governing_reference"] == "WORKING"
    assert entry.details["zone_position"] == "BELOW"
    assert entry.details["index_close"] == pytest.approx(23950.0)
    assert RED_BAR_LOW > entry.details["index_close"]
    # No candle up to here has traded through the midpoint at all.
    assert replay.rule_state["reentry"]["last_touch_at"] is None
    assert replay.rule_state["working_reference"]["entries"] == 1


def test_the_working_entry_is_documented_against_the_deputy_not_the_red_bar():
    """Evidence has to name the level the close was compared against.

    Recording the red bar here would describe a comparison nobody made -- 23950.0
    is nowhere near 23997.0 -- and would leave the admitted row indistinguishable
    from an entry taken on the frozen midpoint.
    """
    entry = _admitted(_replay(DEPUTY_UNDER_THE_BAND, RALLY_UNDER_THE_BAND), "WORKING")[0]
    assert entry.details["reference_source"] == "WORKING_OPPOSITE_CANDLE"
    assert entry.details["reference_timestamp"].startswith("2026-08-24T09:40")
    assert entry.details["reference_high"] == pytest.approx(23940.4)
    assert entry.details["reference_low"] == pytest.approx(23854.6)
    assert entry.details["reference_midpoint"] == pytest.approx(23897.5)
    assert entry.details["evaluation_timeframe"] == "1m"
    # The deputy cleared the body filter by a wide margin, and the number is
    # carried so a reader can see which candle was promoted and why.
    assert entry.details["working_body_ratio"] > 0.5


def test_a_deputy_whose_high_is_inside_the_band_can_never_trigger_an_entry():
    """The red bar is senior, so a level only reachable from inside it is dead.

    The same rally, against a deputy wicking to 23992.4: taking out that high
    means closing inside the band, and inside the band the red bar governs. The
    deputy is evaluated -- it just never admits anything -- and is then discarded.
    """
    replay = _replay(DEPUTY_INTO_THE_BAND, RALLY_INTO_THE_BAND)
    assert _admitted(replay, "WORKING") == []
    evaluated = [
        event
        for event in replay.events
        if event.details.get("governing_reference") == "WORKING"
    ]
    assert evaluated, "the deputy was never reached, so this proves nothing"
    assert all(
        event.admission_code == "WORKING_REFERENCE_NOT_CONFIRMED"
        for event in evaluated
    )
    working = replay.rule_state["working_reference"]
    assert working["entries"] == 0


def test_a_close_back_inside_the_band_returns_control_to_the_red_bar():
    """Precedence by location, and the deputy is dropped rather than parked.

    23990.0 is inside the band by four tenths of a point, which is enough: the
    edges belong to the red bar. Discarding the deputy at that moment is what
    stops a later excursion from reviving a level the market has moved past --
    only a fresh exit may start a fresh search.
    """
    replay = _replay(DEPUTY_INTO_THE_BAND, RALLY_INTO_THE_BAND)
    working = replay.rule_state["working_reference"]
    assert working["established_at"] is not None
    assert working["active"] is False
    assert working["searching"] is False
    assert working["discards"] == 1
    assert working["last_discarded_at"].startswith("2026-08-24T09:46")


def test_no_exit_means_no_deputy_search_at_all():
    """The deputy exists to reopen a closed trade, so an open one must not get one.

    Same day, no injected exit. Without this the search could start from a
    default and hand the strategy a second position on top of the first.
    """
    replay = _replay(DEPUTY_UNDER_THE_BAND, RALLY_UNDER_THE_BAND, exits=())
    assert replay.closed_trades == 0
    assert _admitted(replay, "WORKING") == []
    working = replay.rule_state["working_reference"]
    assert working["established_at"] is None
    assert working["searching"] is False
    assert working["direction"] is None
