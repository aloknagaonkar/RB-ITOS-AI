"""Derived exits: a research day that closes its own trades and carries on.

The replay can only close a trade through injected ``exit_timestamps``, so a day
replayed with none of them opens one position and holds it to the close. These
tests are about the loop that fills that gap by deriving the exits from the
policy and feeding them back through the same parameter the live path uses.

The fixture is one purpose-built session, ``_day()``, arranged so that every step
of the sequence is forced rather than incidental:

* 09:15-09:19 rises, so it cannot be the reference.
* 09:20-09:24 falls, so it is: high 24008.4, low 23979.6, **midpoint 23994.0**.
* 09:27 closes at 23996.0, above the midpoint, with the futures above their
  VWAP, so a bullish entry is admitted at 09:28 -- and its stop comes from the
  crossing slot's low, 23979.6, which is 16.4 points of risk.
* 09:31 closes at 23992.0, back below the midpoint. The reason for holding is
  gone, so the policy closes the position there -- 4.4 points, well short of both
  the stop and the 1R trail activation, so *only* the structural test can be what
  took it off.
* 09:35-09:39 falls clear of the band and is the deputy: a red slot closing at
  23950.0 with a 0.98 body ratio, high 23986.4, low 23949.6, **midpoint
  23968.0**.
* 09:40-09:44 pulls back to 23976.0 -- above the deputy's midpoint but still
  under the band's low, so control stays with the deputy and nothing is admitted.
* 09:46 closes at 23964.0, back through the deputy's midpoint, so a bearish
  entry is admitted at 09:47 against a level the red bar knows nothing about.

None of that second half is reachable without the first trade being closed, which
is the whole point: the day is a chain, and the exit is the link.
"""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from red_bar_lab.domain.red_bar_v2 import ExitReason, RiskPlanRejection
from red_bar_lab.services import red_bar_v2_derived_exits as derived_exits_module
from red_bar_lab.services.red_bar_v2_derived_exit_store import (
    persist_red_bar_v2_derived_exit,
    read_red_bar_v2_derived_exits,
)
from red_bar_lab.services.red_bar_v2_derived_exits import (
    MISSING_EVIDENCE,
    OPEN_AT_END,
    DerivedExitsDidNotConverge,
    _assert_prefix_unchanged,
    resolve_next_derived_exit,
    resolve_red_bar_v2_derived_exits,
)
from red_bar_lab.services.red_bar_v2_futures_historical_replay import (
    replay_red_bar_v2_day_with_futures_vwap,
)

IST = timezone(timedelta(hours=5, minutes=30))
SESSION_START = datetime(2026, 8, 24, 9, 15, tzinfo=IST)
UNDERLYING = "NSE_INDEX|Nifty 50"
FUTURES = "NSE_FO|NIFTY-FUT"

RED_BAR_HIGH = 24008.4
RED_BAR_LOW = 23979.6
MIDPOINT = 23994.0
DEPUTY_MIDPOINT = 23968.0

OPENING = [24000.0, 24002.0, 24004.0, 24006.0, 24008.0]
RED_BAR = [24004.0, 23998.0, 23992.0, 23986.0, 23980.0]
CROSS = [23984.0, 23988.0, 23996.0, 23998.0, 24000.0]
COLLAPSE = [23996.0, 23992.0, 23990.0, 23988.0, 23986.0]
DEPUTY = [23980.0, 23972.0, 23964.0, 23956.0, 23950.0]
PULLBACK = [23958.0, 23966.0, 23972.0, 23974.0, 23976.0]
CONFIRM = [23970.0, 23964.0, 23958.0, 23952.0, 23946.0]
CLOSING = [23952.0, 23958.0, 23966.0, 23972.0, 23976.0, 23974.0]

SESSION = [*OPENING, *RED_BAR, *CROSS, *COLLAPSE, *DEPUTY, *PULLBACK, *CONFIRM, *CLOSING]

# The same day with the crossing brought forward against a slot that has barely
# any depth: 09:25-09:29 creeps up to 23993.0 without ever clearing the midpoint,
# so the crossing slot is 09:30-09:32, whose low is 23992.6. An entry at 23998.0
# against that is 5.4 points of risk -- under the 8.0-point floor, so it cannot
# be given a plan at all.
CREEP = [23988.0, 23990.0, 23992.0, 23993.0, 23993.0]
SHALLOW = [23993.0, 23998.0, 24000.0, 23998.0, 23990.0]
UNPLANNABLE = [
    *OPENING, *RED_BAR, *CREEP, *SHALLOW, *DEPUTY, *PULLBACK, *CONFIRM, *CLOSING
]


def _frame(closes: list[float], volumes: list[float]) -> pd.DataFrame:
    """Candles from closes alone, each one reaching 0.4 past its own body."""
    stamps = pd.date_range(SESSION_START, periods=len(closes), freq="1min")
    opens = [closes[0] - 0.2, *closes[:-1]]
    return pd.DataFrame(
        {
            "open": opens,
            "high": [max(o, c) + 0.4 for o, c in zip(opens, closes)],
            "low": [min(o, c) - 0.4 for o, c in zip(opens, closes)],
            "close": closes,
            "volume": volumes,
        },
        index=stamps,
    )


def _day(closes: list[float] = SESSION) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The session described in the module docstring, index and futures.

    The futures climb every minute, so their close sits above their own session
    VWAP from the second candle on. That gates the bullish half in without ever
    being the thing under test -- and the deputy half consults no VWAP at all,
    so the same rising series cannot be what admits the bearish entry either.
    """
    index = _frame(closes, [1_000.0] * len(closes))
    futures = _frame(
        [200.0 + 0.6 * i for i in range(len(closes))],
        [5_000.0] * len(closes),
    )
    return index, futures


def _replay(index_candles, futures_candles, **kwargs):
    replay, _health = replay_red_bar_v2_day_with_futures_vwap(
        index_candles,
        futures_candles,
        instrument_key=UNDERLYING,
        vwap_instrument_key=FUTURES,
        **kwargs,
    )
    return replay


def _resolve(index_candles, futures_candles, **kwargs):
    return resolve_red_bar_v2_derived_exits(
        index_candles,
        futures_candles,
        instrument_key=UNDERLYING,
        vwap_instrument_key=FUTURES,
        **kwargs,
    )


def _admitted(replay):
    return [
        event
        for event in replay.events
        if event.event_type == "CANDIDATE_ADMISSION" and event.candidate_allowed
    ]


@pytest.fixture(scope="module")
def frames():
    return _day()


@pytest.fixture(scope="module")
def resolution(frames):
    return _resolve(*frames)


@pytest.fixture(scope="module")
def derived(frames, resolution):
    return _replay(*frames, exit_timestamps=resolution.exit_timestamps)


def test_a_day_given_no_exits_holds_its_first_position_to_the_close(frames):
    """The gap being closed, stated as a fact rather than as a motivation.

    Nothing in the replay can retire a trade row on its own, so the day opens one
    position and stops there -- not because the rules refused anything later, but
    because the row never came off.
    """
    plain = _replay(*frames)

    assert len(_admitted(plain)) == 1
    assert plain.closed_trades == 0
    assert plain.final_trade_state == "ACTIVE"


def test_deriving_the_exits_turns_one_entry_into_the_days_whole_sequence(
    frames, resolution, derived
):
    """Entry, policy exit, deputy, second entry -- on the same candles."""
    assert len(_admitted(derived)) == 2
    assert derived.closed_trades == 2

    first, second = resolution.trades
    assert first.direction == "BULLISH"
    assert first.outcome.exit_reason is ExitReason.STRUCTURE
    assert second.direction == "BEARISH"
    assert second.outcome.exit_reason is ExitReason.STRUCTURE
    assert second.entry_timestamp > first.exit_timestamp


def test_the_first_trade_is_priced_off_the_slot_that_crossed_the_midpoint(resolution):
    """The stop is the crossing slot's low, taken from price visible at entry.

    09:25-09:28 is the slot that carried the close through 23994.0, and 23979.6
    is its low. Nothing later in the day can lower it, so a shift in this number
    means the entry was priced off a candle that had not happened yet.
    """
    first = resolution.trades[0]

    assert first.plan.stop_price == pytest.approx(RED_BAR_LOW)
    assert first.plan.risk_points == pytest.approx(16.4)
    assert first.outcome.r_multiple == pytest.approx(-0.24, abs=0.01)


def test_the_second_trade_exits_against_the_deputy_not_against_the_red_bar(resolution):
    """The rule row that had no way of being demonstrated before.

    The bearish position comes off on a close of 23972.0. That is above the
    deputy's midpoint of 23968.0, so the level it was held against has broken --
    but it is still 22 points below the red bar's midpoint and still below the
    band's low, so a position judged against the red bar would have stayed open.
    The two levels disagree here on purpose.
    """
    second = resolution.trades[1]

    assert second.plan.stop_price == pytest.approx(23976.4)
    assert second.exit_timestamp.strftime("%H:%M") == "09:53"
    assert second.outcome.exit_price == pytest.approx(23972.0)
    assert DEPUTY_MIDPOINT < second.outcome.exit_price < MIDPOINT
    assert second.outcome.exit_price < RED_BAR_LOW


def test_the_working_reference_is_reached_with_no_injected_exit(frames, derived):
    """The deputy search runs on a day whose caller passed no exits at all."""
    second = _admitted(derived)[1]

    assert second.details["entry_type"] == "WORKING"
    assert second.details["governing_reference"] == "WORKING"
    assert second.details["reference_midpoint"] == pytest.approx(DEPUTY_MIDPOINT)
    assert second.details["zone_position"] == "BELOW"
    assert derived.rule_state["working_reference"]["entries"] == 1


def test_the_first_entry_still_reads_as_the_days_opening_trade(derived):
    """Two rows now, so the fields that say which rule fired finally discriminate."""
    first = _admitted(derived)[0]

    assert first.details["entry_type"] == "INITIAL"
    assert first.details["governing_reference"] == "RED_BAR"
    assert first.details["reference_midpoint"] == pytest.approx(MIDPOINT)


def test_resolving_leaves_every_decision_before_the_first_exit_untouched(
    frames, resolution, derived
):
    """The correctness argument, asserted instead of argued.

    The replay reaches an exit only when the clock does, so feeding one cannot
    reach backwards. Every event stamped before the first fed exit must therefore
    be identical to the same event on a day that was fed nothing -- which is what
    makes it safe to resolve the day one exit at a time.
    """
    plain = _replay(*frames)
    cutoff = resolution.exit_timestamps[0]

    def prefix(replay):
        return [
            (event.timestamp, event.event_type, event.admission_code, event.direction)
            for event in replay.events
            if event.timestamp < cutoff
        ]

    assert prefix(derived) == prefix(plain)
    assert prefix(plain), "a prefix of nothing would make this vacuous"


def test_the_second_entry_is_reachable_only_because_the_first_one_closed(
    frames, resolution
):
    """Hand the replay the first exit alone: the rest of the day appears anyway.

    This separates the two halves of the claim. The resolver is not what admits
    the second entry -- the closed row is. All the resolver did was work out when.
    """
    first_only = _replay(*frames, exit_timestamps=resolution.exit_timestamps[:1])

    assert len(_admitted(first_only)) == 2
    assert [event.direction for event in _admitted(first_only)] == [
        "BULLISH",
        "BEARISH",
    ]


def _stopped_on_its_entry_bar() -> tuple[pd.DataFrame, pd.DataFrame]:
    """The canonical day with the 09:28 candle reaching down to the stop exactly.

    The stop is the crossing slot's low and 09:28 is inside that slot, so the only
    way for the entry bar to breach its own stop is to tie with it. That is enough:
    the policy closes on ``low <= stop``, so the position comes off on the first
    bar it was ever held, and the exit and the entry carry the same stamp.
    """
    index_candles, futures_candles = _day()
    index_candles = index_candles.copy()
    index_candles.loc[index_candles.index[13], "low"] = RED_BAR_LOW
    return index_candles, futures_candles


def test_an_exit_on_the_entry_bar_is_fed_a_minute_late_or_it_is_lost():
    """The two clocks, and why an outcome cannot be fed back at face value.

    The replay judges the candle stamped ``T`` at ``T + 1min`` and creates the
    trade row there, but it consumes exits at the *top* of that minute. An exit
    stamped ``T`` therefore arrives before the row exists, matches nothing, and is
    discarded -- and the loop, seeing an entry it has already resolved, would feed
    nothing else. The position would be held for the rest of the day on the
    strength of a stop that had already been hit.
    """
    frames = _stopped_on_its_entry_bar()
    resolution = _resolve(*frames)
    first = resolution.trades[0]

    assert first.outcome.exit_reason is ExitReason.STOP_LOSS
    assert first.outcome.r_multiple == pytest.approx(-1.0)
    assert first.outcome.exit_timestamp == first.entry_timestamp
    assert first.fed_at == first.entry_timestamp + timedelta(minutes=1)

    raw = _replay(*frames, exit_timestamps=(first.outcome.exit_timestamp,))
    lagged = _replay(*frames, exit_timestamps=(first.fed_at,))

    assert raw.closed_trades == 0
    assert lagged.closed_trades == 1


def test_a_stop_out_on_the_entry_bar_still_leaves_the_day_its_re_entry():
    """Instant loss, and the day gets on with it: three trades where there was one."""
    frames = _stopped_on_its_entry_bar()
    resolution = _resolve(*frames)
    derived = _replay(*frames, exit_timestamps=resolution.exit_timestamps)

    assert [trade.outcome.exit_reason for trade in resolution.trades] == [
        ExitReason.STOP_LOSS,
        ExitReason.STRUCTURE,
        ExitReason.STRUCTURE,
    ]
    assert len(_admitted(derived)) == 3
    assert derived.closed_trades == 3


def test_an_entry_that_cannot_be_planned_does_not_kill_the_day():
    """Risk under the floor: no plan, no outcome, and the session carries on.

    The crossing slot here is only 5.4 points deep, so the entry cannot be sized.
    Before, the row would have sat ACTIVE and refused everything behind it for the
    rest of the session. Now it is closed flat where it opened, marked with the
    reason it was never a position, and the day continues to a real trade.
    """
    frames = _day(UNPLANNABLE)
    resolution = _resolve(*frames)
    unplanned, planned = resolution.trades

    assert unplanned.rejection == RiskPlanRejection.RISK_BELOW_FLOOR.value
    assert unplanned.plan is None
    assert unplanned.outcome is None
    assert unplanned.planned is False
    assert unplanned.fed_at == unplanned.entry_timestamp + timedelta(minutes=1)

    assert planned.planned is True
    assert planned.entry_timestamp > unplanned.entry_timestamp
    assert planned.outcome.exit_reason is ExitReason.STRUCTURE

    derived = _replay(*frames, exit_timestamps=resolution.exit_timestamps)
    assert len(_admitted(derived)) == 2


def test_a_position_the_day_ends_holding_stops_the_loop_and_says_so():
    """No exit can be invented for a trade the session never closed.

    Truncated at 09:49, the day still admits the bearish entry -- the replay stamps
    it a minute after the last candle -- but there is no bar left to walk, so there
    is no outcome. The loop records that and stops rather than guessing a time.
    """
    frames = _day(SESSION[:35])
    resolution = _resolve(*frames)
    last = resolution.trades[-1]

    assert last.status == OPEN_AT_END
    assert last.outcome is None
    assert last.exit_timestamp is None
    assert last.fed_at is None
    assert last.plan is not None, "it was plannable; it simply never resolved"
    assert len(resolution.exit_timestamps) == len(resolution.trades) - 1


def test_the_loop_runs_one_replay_per_trade_and_one_to_confirm_it_is_done(
    resolution, frames
):
    """The number the termination argument predicts, not a tuning knob.

    Each pass resolves exactly one entry, in increasing time order, so the count
    of passes is pinned. If it ever exceeds the trade count by more than the one
    confirming pass, an entry was resolved twice and the prefix moved.
    """
    assert resolution.iterations == len(resolution.trades) + 1
    assert resolution.iterations <= len(_day()[0].index) + 1


def test_the_prefix_guard_raises_rather_than_letting_the_loop_spin():
    """The guard that makes the bound a fact rather than a hope."""
    stamp = SESSION_START
    later = stamp + timedelta(minutes=5)

    with pytest.raises(DerivedExitsDidNotConverge):
        _assert_prefix_unchanged([stamp], [])

    with pytest.raises(DerivedExitsDidNotConverge):
        _assert_prefix_unchanged([stamp], [(later, object())])

    _assert_prefix_unchanged([stamp], [(stamp, object()), (later, object())])


def test_the_resolution_is_reproducible(frames):
    """Same candles, same exits, same number of passes -- twice."""
    once, twice = _resolve(*frames), _resolve(*frames)

    assert once.exit_timestamps == twice.exit_timestamps
    assert once.iterations == twice.iterations
    assert [trade.entry_timestamp for trade in once.trades] == [
        trade.entry_timestamp for trade in twice.trades
    ]
    assert [trade.outcome.r_multiple for trade in once.trades] == [
        trade.outcome.r_multiple for trade in twice.trades
    ]


def test_an_exit_the_caller_supplies_is_used_verbatim(frames, resolution):
    """The live seam, unchanged: whoever passes exits still decides them.

    Live reads real fills off the paper order book and feeds them through this same
    parameter. Deriving exits had to be an extra source for it, not a replacement,
    so an injected exit at a time the policy would never have chosen must still be
    the one that closes the row.
    """
    early = SESSION_START + timedelta(minutes=15)
    assert early not in resolution.exit_timestamps
    assert early < resolution.exit_timestamps[0]

    injected = _replay(*frames, exit_timestamps=(early,))

    assert injected.closed_trades == 1
    assert injected.final_trade_state == "ACTIVE", (
        "one exit was supplied and one row came off; the loop was not consulted "
        "for the second, which is left open exactly as it would be today"
    )


def test_the_resolution_indexes_its_trades_by_entry(resolution):
    """Trade ids are a counter; the entry stamp is what the day is joined on."""
    by_entry = resolution.by_entry()

    assert list(by_entry) == [trade.entry_timestamp for trade in resolution.trades]
    assert all(stamp == trade.entry_timestamp for stamp, trade in by_entry.items())
    assert MISSING_EVIDENCE not in {trade.rejection for trade in resolution.trades}


# --- One step at a time: the shape a live session resolves exits in -----------
#
# The research loop settles a finished day in one call and pays a replay per
# entry. A live cycle is already replaying the whole session every pass, so the
# cycles *are* the iteration -- it needs the body of the loop, not the loop.


def _cycles(frames, *, limit: int = 12):
    """Drive ``resolve_next_derived_exit`` the way the live cycles drive it.

    One replay per cycle, at most one exit resolved per cycle, the result carried
    forward to the next. Nothing here re-runs a replay to consume what it just
    resolved -- that is what makes it a cycle rather than a loop.
    """
    fed: list = []
    resolved: list = []
    for count in range(1, limit + 1):
        replay = _replay(*frames, exit_timestamps=tuple(fed))
        settled = resolve_next_derived_exit(
            replay,
            *frames,
            resolved_entries=[trade.entry_timestamp for trade in resolved],
        )
        if settled is None:
            return tuple(fed), tuple(resolved), count
        resolved.append(settled)
        if settled.fed_at is None:
            return tuple(fed), tuple(resolved), count
        fed.append(settled.fed_at)
    raise AssertionError(f"{limit} cycles did not settle the day")


def test_settling_one_exit_a_cycle_reaches_the_same_day_as_the_loop(
    frames, resolution
):
    """The equivalence that lets live and research share one exit brain.

    If the cycle-at-a-time path could reach a different day, every R-multiple
    measured in research would be describing a session production never has. Same
    candles, same exits, same trades, and the same number of passes to get there.
    """
    fed, settled, cycles = _cycles(frames)

    assert fed == resolution.exit_timestamps
    assert cycles == resolution.iterations
    assert [trade.entry_timestamp for trade in settled] == [
        trade.entry_timestamp for trade in resolution.trades
    ]
    assert [trade.outcome.exit_reason for trade in settled] == [
        trade.outcome.exit_reason for trade in resolution.trades
    ]
    assert [trade.outcome.r_multiple for trade in settled] == [
        trade.outcome.r_multiple for trade in resolution.trades
    ]


def test_the_single_step_resolver_runs_no_replay_of_its_own(frames, monkeypatch):
    """Why the live path can afford this: it costs the cycle nothing extra.

    A cycle already replays the full session, so the one thing this must not do is
    replay it again -- at roughly four seconds a pass, every ~32 seconds, a second
    replay is not a detail. Patching the replay to raise proves it by construction
    rather than by reading the code, and the loop raising under the same patch
    proves the patch was in force.
    """
    def boom(*_args, **_kwargs):
        raise AssertionError("the single-step resolver must not replay the day")

    replay = _replay(*frames)
    monkeypatch.setattr(
        derived_exits_module, "replay_red_bar_v2_day_with_futures_vwap", boom
    )

    settled = resolve_next_derived_exit(replay, *frames)

    assert settled is not None
    assert settled.outcome.exit_reason is ExitReason.STRUCTURE
    with pytest.raises(AssertionError, match="must not replay"):
        _resolve(*frames)


def test_a_settled_day_asks_and_is_told_there_is_nothing_left(frames, resolution):
    """The steady state, which is where a live session spends its afternoon.

    Once every admitted entry has an exit there is nothing to resolve, and saying
    so has to be the cheap answer -- it is the answer on all but a handful of the
    day's cycles.
    """
    derived = _replay(*frames, exit_timestamps=resolution.exit_timestamps)

    assert (
        resolve_next_derived_exit(
            derived,
            *frames,
            resolved_entries=[t.entry_timestamp for t in resolution.trades],
        )
        is None
    )
    # Told about no exits at all, it resolves the first entry again rather than
    # reporting nothing: what is already settled is the caller's memory, not the
    # replay's.
    assert resolve_next_derived_exit(derived, *frames) is not None


def test_already_resolved_entries_are_recognised_from_their_stored_text(
    frames, resolution
):
    """The memory arrives back as strings, because it arrives back out of SQLite.

    A live cycle reads its resolved entries from a table, so they are ISO text by
    the time they are handed back. Text that failed to match the replay's own
    stamps would make every cycle re-resolve the first entry and never reach the
    second.
    """
    derived = _replay(*frames, exit_timestamps=resolution.exit_timestamps)
    stored = [trade.entry_timestamp.isoformat() for trade in resolution.trades[:1]]

    settled = resolve_next_derived_exit(derived, *frames, resolved_entries=stored)

    assert settled is not None
    assert settled.entry_timestamp == resolution.trades[1].entry_timestamp
    assert (
        resolve_next_derived_exit(
            derived,
            *frames,
            resolved_entries=[t.entry_timestamp.isoformat() for t in resolution.trades],
        )
        is None
    )


def test_a_resolved_exit_survives_the_store_and_still_closes_the_row(
    frames, resolution, tmp_path
):
    """End to end for the live carry: resolve, write, read, feed, closed.

    Persisting is what makes the cycles an iteration, and the round trip is not
    free of consequence -- a ``fed_at`` becomes text and comes back as text. If the
    replay could not consume the stored form, the row would reopen every pass and
    the direction would stay frozen exactly as it does today.
    """
    path = tmp_path / "derived.db"
    first = resolution.trades[0]
    persist_red_bar_v2_derived_exit(
        path,
        trading_date="2026-08-24",
        instrument_key=UNDERLYING,
        exit=first,
    )
    (row,) = read_red_bar_v2_derived_exits(
        path, trading_date="2026-08-24", instrument_key=UNDERLYING
    )

    assert row["fed_at"] == first.fed_at.isoformat()
    fed_from_store = _replay(*frames, exit_timestamps=(row["fed_at"],))

    assert fed_from_store.closed_trades == 1
    assert len(_admitted(fed_from_store)) == 2, (
        "the stored exit retired the first row, so the deputy half of the day is "
        "reachable from the table alone"
    )
