"""The table that lets a live session remember the exits it resolved.

A cycle replays the whole day from scratch, so a resolved exit that is not written
down is a resolved exit that never happened. These tests are about the two
properties that makes it safe to write one down and hand it back next pass:

* **Written once.** The same exit arriving again is not an update. Monotonicity
  says a resolved exit cannot change -- an exit at 10:00 cannot alter any decision
  before 10:00, so the prefix it was priced from is fixed -- and a conflicting
  write is therefore a bug to surface, not a value to apply.
* **Settled only.** An exit with no ``fed_at`` is a position still open on the
  candles available. On a live session that reads "not closed yet", so recording
  it would freeze a verdict the next candle can still overturn.

The fixtures are hand-built domain objects rather than a replayed day, so the test
pins the attribute names the store reads and the columns it writes them to, with
no replay in the way.
"""

from datetime import datetime, time, timedelta, timezone

import pytest

from red_bar_lab.domain.red_bar_v2 import (
    Direction,
    ExitReason,
    RiskPlan,
    RiskPlanRejection,
    StopTrigger,
    TradeOutcome,
)
from red_bar_lab.services.red_bar_v2_derived_exit_store import (
    persist_red_bar_v2_derived_exit,
    read_red_bar_v2_derived_exits,
)
from red_bar_lab.services.red_bar_v2_derived_exits import DerivedExit, OPEN_AT_END

IST = timezone(timedelta(hours=5, minutes=30))
TRADING_DATE = "2026-09-03"
UNDERLYING = "NSE_INDEX|Nifty 50"
ENTRY = datetime(2026, 9, 3, 9, 25, tzinfo=IST)
EXIT = datetime(2026, 9, 3, 10, 21, tzinfo=IST)


def _plan(entry_timestamp: datetime = ENTRY) -> RiskPlan:
    return RiskPlan(
        direction=Direction.BEARISH,
        entry_timestamp=entry_timestamp,
        entry_price=23_965.0,
        stop_price=23_989.35,
        target_price=None,
        risk_points=24.35,
        reward_multiple=None,
        trigger=StopTrigger.MIDPOINT_CROSS,
        trigger_timestamp=entry_timestamp - timedelta(minutes=5),
        trail_activation_price=23_940.65,
        trail_distance_points=24.35,
        session_flat_time=time(15, 15),
        quantity_lots=1,
    )


def _outcome(
    plan: RiskPlan,
    *,
    exit_timestamp: datetime = EXIT,
    exit_price: float = 23_991.15,
    reason: ExitReason = ExitReason.STRUCTURE,
) -> TradeOutcome:
    points = plan.entry_price - exit_price
    return TradeOutcome(
        direction=plan.direction,
        trigger=plan.trigger,
        entry_timestamp=plan.entry_timestamp,
        entry_price=plan.entry_price,
        exit_timestamp=exit_timestamp,
        exit_price=exit_price,
        stop_price=plan.stop_price,
        target_price=None,
        risk_points=plan.risk_points,
        exit_reason=reason,
        points=points,
        r_multiple=round(points / plan.risk_points, 4),
        mfe_points=9.0,
        mae_points=26.15,
        mfe_r=0.3696,
        mae_r=1.0739,
        holding_minutes=56.0,
        bars_held=56,
        quantity_lots=plan.quantity_lots,
    )


def _settled(entry_timestamp: datetime = ENTRY, **overrides) -> DerivedExit:
    """One entry the policy took off, on the two clocks it lives on.

    ``exit_timestamp`` is the outcome's own stamp; ``fed_at`` is that value on the
    replay's known-at clock, one minute later. Both are stored, because a reader
    wants the first and the next cycle needs the second.
    """
    plan = _plan(entry_timestamp)
    outcome = _outcome(plan, **overrides)
    return DerivedExit(
        entry_timestamp=entry_timestamp,
        trade_id="RBV2-FVWAP-0001",
        direction=plan.direction.value,
        plan=plan,
        rejection=None,
        outcome=outcome,
        exit_timestamp=outcome.exit_timestamp,
        fed_at=outcome.exit_timestamp + timedelta(minutes=1),
    )


def _write(path, exit_: DerivedExit, **overrides) -> int:
    fields = {
        "trading_date": TRADING_DATE,
        "instrument_key": UNDERLYING,
        **overrides,
    }
    return persist_red_bar_v2_derived_exit(path, exit=exit_, **fields)


def _read(path, **overrides) -> list[dict]:
    fields = {"trading_date": TRADING_DATE, **overrides}
    return read_red_bar_v2_derived_exits(path, **fields)


def test_a_settled_exit_round_trips_with_its_reason_and_its_r(tmp_path):
    """What "why is it flat" needs: the reason, the level, and the R it paid."""
    path = tmp_path / "rb.db"
    settled = _settled()

    assert _write(path, settled) > 0
    (row,) = _read(path)

    assert row["entry_timestamp"] == ENTRY.isoformat()
    assert row["exit_timestamp"] == EXIT.isoformat()
    assert row["fed_at"] == (EXIT + timedelta(minutes=1)).isoformat()
    assert row["exit_reason"] == ExitReason.STRUCTURE.value
    assert row["direction"] == "BEARISH"
    assert row["trade_id"] == "RBV2-FVWAP-0001"
    assert row["entry_price"] == pytest.approx(23_965.0)
    assert row["exit_price"] == pytest.approx(23_991.15)
    assert row["stop_price"] == pytest.approx(23_989.35)
    assert row["risk_points"] == pytest.approx(24.35)
    assert row["holding_minutes"] == pytest.approx(56.0)
    # R is the stored points over the stored risk, so the row is self-checking.
    assert row["r_multiple"] == pytest.approx(row["points"] / row["risk_points"], abs=1e-3)
    assert row["rejection"] is None


def test_the_same_exit_arriving_again_is_not_a_second_row(tmp_path):
    """The property that makes a cycle safe to repeat.

    Cycles are not transactions -- one can persist and the next can be handed the
    same day again before anything downstream has moved. Re-writing has to be
    free, and it has to be detectable, so the second call reports that it wrote
    nothing rather than silently inserting a duplicate the replay would then
    consume twice.
    """
    path = tmp_path / "rb.db"
    settled = _settled()

    first = _write(path, settled)
    second = _write(path, settled)

    assert first > 0
    assert second == 0
    assert len(_read(path)) == 1


def test_a_conflicting_verdict_for_the_same_entry_is_ignored_not_applied(tmp_path):
    """A resolved exit cannot move, so a different one is a bug -- not an update.

    Monotonicity is what licenses caching at all: the exit was derived from a
    prefix of the day that later passes cannot disturb. Applying a second verdict
    would quietly rewrite history and rescale the trade's R; leaving the first in
    place keeps the row that every later cycle has already been acting on.
    """
    path = tmp_path / "rb.db"
    _write(path, _settled())
    _write(
        path,
        _settled(exit_price=23_900.0, reason=ExitReason.TRAILING_STOP),
    )

    (row,) = _read(path)
    assert row["exit_reason"] == ExitReason.STRUCTURE.value
    assert row["exit_price"] == pytest.approx(23_991.15)


def test_an_exit_that_is_not_settled_is_refused(tmp_path):
    """No ``fed_at`` means the position is still open on the data available.

    Research reads that as "held to the close" because the day is over. A live
    session cannot: its last candle is simply the last one so far. Writing it
    would freeze a verdict the next candle can still overturn, so the store
    refuses rather than trusting every call site to remember.
    """
    path = tmp_path / "rb.db"
    plan = _plan()
    open_at_end = DerivedExit(
        entry_timestamp=ENTRY,
        trade_id="RBV2-FVWAP-0001",
        direction=plan.direction.value,
        plan=plan,
        rejection=None,
        outcome=None,
        exit_timestamp=None,
        fed_at=None,
        status=OPEN_AT_END,
    )

    with pytest.raises(ValueError, match="fed_at"):
        _write(path, open_at_end)

    assert _read(path) == []
    assert not path.exists(), "a refused write must not leave a database behind"


def test_an_unplannable_entry_records_why_it_was_never_a_position(tmp_path):
    """It still opened a replay row, so it still has to be closed and explained.

    Risk outside the band means no plan and no outcome, but the row exists and the
    rest of the session is blocked until it comes off. The exit is its own entry
    bar and the rejection is what distinguishes it from a trade that made no money.
    """
    path = tmp_path / "rb.db"
    unplannable = DerivedExit(
        entry_timestamp=ENTRY,
        trade_id="RBV2-FVWAP-0001",
        direction="BULLISH",
        plan=None,
        rejection=RiskPlanRejection.RISK_BELOW_FLOOR.value,
        outcome=None,
        exit_timestamp=None,
        fed_at=ENTRY + timedelta(minutes=1),
        rejection_detail="risk 5.40 below floor 8.00",
    )

    assert _write(path, unplannable) > 0
    (row,) = _read(path)

    assert row["rejection"] == RiskPlanRejection.RISK_BELOW_FLOOR.value
    assert row["rejection_detail"] == "risk 5.40 below floor 8.00"
    assert row["exit_reason"] is None
    assert row["r_multiple"] is None
    assert row["entry_price"] is None
    # The row still carries a feedable moment, which is the point of writing it.
    assert row["fed_at"] == (ENTRY + timedelta(minutes=1)).isoformat()


def test_a_session_reads_back_its_own_exits_earliest_first(tmp_path):
    """Ordered by entry, because that is the order the replay consumes them in."""
    path = tmp_path / "rb.db"
    later = ENTRY + timedelta(hours=2)

    _write(path, _settled(later))
    _write(path, _settled())

    rows = _read(path)
    assert [row["entry_timestamp"] for row in rows] == [
        ENTRY.isoformat(),
        later.isoformat(),
    ]


def test_reads_are_scoped_to_one_day_and_one_instrument(tmp_path):
    """Two sessions in one file must not lend each other exits.

    An exit derived on another day, or against another instrument, would close a
    trade row this session never opened -- and the replay consumes whatever it is
    handed.
    """
    path = tmp_path / "rb.db"
    _write(path, _settled())
    _write(path, _settled(), trading_date="2026-09-04")
    _write(path, _settled(), instrument_key="NSE_INDEX|Bank Nifty")

    assert len(_read(path)) == 2
    assert len(_read(path, instrument_key=UNDERLYING)) == 1
    assert len(_read(path, trading_date="2026-09-04")) == 1
    assert _read(path, trading_date="2026-09-05") == []


def test_reading_before_anything_was_ever_written_creates_nothing(tmp_path):
    """The first cycle of a session asks this, and it must be free and silent."""
    missing = tmp_path / "absent.db"
    assert _read(missing) == []
    assert not missing.exists()

    empty = tmp_path / "empty.db"
    empty.write_bytes(b"")
    assert _read(empty) == []
