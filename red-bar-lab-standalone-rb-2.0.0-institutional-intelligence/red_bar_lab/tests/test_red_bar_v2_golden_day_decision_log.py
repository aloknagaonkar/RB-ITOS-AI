"""Golden-day decision log tests.

The fixture is a deterministic synthetic session: the same shape the canonical
integration test uses (drop into a red bar, then a steady recovery), padded to a
full trading day. Everything up to and including the 09:31 entry is identical
across every tail, so one reference, one gate and one plan are shared and only
the path afterwards differs. That is what makes the exit reasons comparable --
each tail isolates exactly one way out of the same position.

The assertions are properties, not mirrors: the log must be reproducible, its
rows ordered, its R-multiples internally consistent, and its rejections
machine-readable.

The day now closes its own trade. The exit policy's verdict is fed back through
the replay's ``exit_timestamps`` seam, so a ``TRADE_CLOSED`` event appears in the
event stream and the position is not held to the close by default. That each tail
still produces exactly one entry is a fact about these four price paths, not a
cap: after the exit the fixture never offers another admissible condition.
"""

import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from red_bar_lab.domain.red_bar_v2 import (
    ExitReason,
    RiskPlanRejection,
    TriggerResolution,
)
from red_bar_lab.services.red_bar_v2_decision_log import (
    DECISION_LOG_SCHEMA,
    build_golden_day_decision_log,
    render_decision_log,
)

IST = timezone(timedelta(hours=5, minutes=30))
UNDERLYING = "NSE_INDEX|Nifty 50"
FUTURES = "NSE_FO|NIFTY-FUT"
SESSION_MINUTES = 375
# The red bar's own low-to-high band, and the midpoint of it. A long is
# structurally broken by a completed close below the midpoint, which is what the
# BREAK tail exercises; the band is what decides whether the working reference
# can be looked for at all.
BAND_LOW = 94.6
BAND_HIGH = 104.4
MIDPOINT = 99.5
# Where the BREAK tail settles once the collapse stalls: inside the band and
# below the midpoint, so neither a re-entry nor a deputy is available.
BREAK_PLATEAU = 97.0


def _candles(closes: list[float], volumes: list[float]) -> pd.DataFrame:
    timestamps = pd.date_range(
        datetime(2026, 8, 24, 9, 15, tzinfo=IST),
        periods=len(closes),
        freq="1min",
    )
    opens = [closes[0] - 0.2, *closes[:-1]]
    return pd.DataFrame(
        {
            "open": opens,
            "high": [max(o, c) + 0.4 for o, c in zip(opens, closes)],
            "low": [min(o, c) - 0.4 for o, c in zip(opens, closes)],
            "close": closes,
            "volume": volumes,
        },
        index=timestamps,
    )


def _market_frames(*, tail: str = "TREND") -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build one synthetic session, sharing everything up to the 09:31 entry.

    * TREND runs away and never looks back. With no target the trail activates
      and then never catches price, so the position survives to the session flat.
    * DRIFT creeps up too slowly to activate the trail, and also ends flat --
      but from a few points above the entry rather than thirty.
    * BREAK collapses back through the midpoint without ever reaching the stop,
      which is the only path that can produce a structural exit.
    * SPIKE dives *inside* the entry's own five-minute slot, at 09:32. The stop
      is read off that slot, so this is the tail that catches the log pricing it
      from price the strategy had not seen at 09:31.
    """
    index_closes = [100.0, 101.0, 102.0, 103.0, 104.0]
    index_closes += [103.0, 101.0, 99.0, 97.0, 95.0]
    # Drift just below the midpoint (99.5), then one wide candle crossing it:
    # that candle's low becomes the stop, ~10 points under the entry.
    index_closes += [95.0, 95.2, 95.4, 95.6, 95.8]
    index_closes += [106.0, 106.0]
    entered = len(index_closes)
    if tail == "BREAK":
        # The 09:30 five-minute bar is left exactly as TREND leaves it, so the
        # trigger candle and therefore the stop are unchanged and the plan still
        # matches. The collapse starts on the next five-minute slot and then
        # stalls just under the midpoint, never reaching the stop.
        index_closes += [106.9, 107.8, 108.7]
        index_closes += [97.0] * (SESSION_MINUTES - len(index_closes))
    elif tail == "SPIKE":
        # 09:32-09:34, still inside the slot the stop is read from. Taking the
        # finished slot would price the stop at this 89.6 low instead of the
        # 95.4 low that had printed by the 09:31 entry.
        index_closes += [90.0, 90.0, 90.0]
        index_closes += [97.0] * (SESSION_MINUTES - len(index_closes))
    elif tail == "TREND":
        index_closes += [106.0 + (step + 1) * 0.9 for step in range(23)]
        index_closes += [
            index_closes[-1] + 0.05 * (step + 1)
            for step in range(SESSION_MINUTES - len(index_closes))
        ]
    else:
        index_closes += [
            106.0 + 0.02 * (step + 1) for step in range(SESSION_MINUTES - entered)
        ]

    futures_closes = [200.0 + index * 0.6 for index in range(50)]
    futures_closes += [
        futures_closes[-1] + 0.10 * (step + 1) for step in range(SESSION_MINUTES - 50)
    ]

    index_volumes = [10.0 + index for index in range(SESSION_MINUTES)]
    futures_volumes = [1000.0 + index * 10.0 for index in range(SESSION_MINUTES)]
    return (
        _candles(index_closes, index_volumes),
        _candles(futures_closes, futures_volumes),
    )


def _build(*, tail: str = "TREND", **overrides) -> dict:
    index_candles, futures_candles = _market_frames(tail=tail)
    return build_golden_day_decision_log(
        index_candles,
        futures_candles,
        instrument_key=UNDERLYING,
        vwap_instrument_key=FUTURES,
        **overrides,
    )


def _only_trade(log: dict) -> dict:
    return next(trade for trade in log["trades"] if trade["plan"] is not None)


@pytest.fixture(scope="module")
def golden_log() -> dict:
    """The default policy: no target, so the trail is the only upside mechanism."""
    return _build()


@pytest.fixture(scope="module")
def target_log() -> dict:
    """The same day with a 2R target reinstated, which is now opt-in."""
    return _build(reward_multiple=2.0)


@pytest.fixture(scope="module")
def drift_log() -> dict:
    return _build(tail="DRIFT")


@pytest.fixture(scope="module")
def break_log() -> dict:
    return _build(tail="BREAK")


def test_the_log_declares_its_schema_and_day(golden_log):
    assert golden_log["schema"] == DECISION_LOG_SCHEMA
    assert golden_log["trading_date"] == "2026-08-24"
    assert golden_log["instrument_key"] == UNDERLYING


def test_rebuilding_the_same_day_reproduces_the_log_byte_for_byte():
    once, twice = _build(), _build()

    assert render_decision_log(once) == render_decision_log(twice)
    # The exit loop is part of the day now, so reproducibility has to cover how
    # it got there as well as what it produced. A stable log reached in a
    # different number of passes would mean the loop is resolving entries in an
    # order that happens to converge, which is not the same as being determinate.
    assert once["summary"]["resolution_passes"] == twice["summary"]["resolution_passes"]
    assert [row["timestamp"] for row in once["rows"] if row["kind"] == "EXIT"] == [
        row["timestamp"] for row in twice["rows"] if row["kind"] == "EXIT"
    ]


def test_the_whole_log_survives_a_json_round_trip(golden_log):
    """Every row is plain data, so the log can be committed as a fixture."""
    restored = json.loads(json.dumps(golden_log))
    assert render_decision_log(restored) == render_decision_log(golden_log)


def test_log_rows_are_in_chronological_order(golden_log):
    stamps = [row["timestamp"] for row in golden_log["rows"]]
    assert stamps == sorted(stamps)


def test_an_admitted_entry_produces_a_plan_and_an_outcome(golden_log):
    entries = [t for t in golden_log["trades"] if t["plan"] is not None]
    assert len(entries) == 1
    trade = entries[0]
    plan = trade["plan"]
    outcome = trade["outcome"]
    assert outcome is not None
    # The plan precedes the exit and is built at the entry moment.
    assert plan["timestamp"] == trade["entry_timestamp"]
    assert plan["timestamp"] <= outcome["exit_timestamp"]
    # R is internally consistent: points over the declared risk.
    assert outcome["r_multiple"] == pytest.approx(
        outcome["points"] / plan["risk_points"], abs=1e-3
    )


def test_no_target_is_planned_unless_one_is_asked_for(golden_log, target_log):
    """A 2R target with a 1R trail activation would silence the trail entirely.

    Between 1R and 2R the target always fires first, so the trail could never do
    the thing it exists for. The mechanism is intact -- an explicit
    ``reward_multiple`` reinstates it -- but it is off by default.
    """
    default_plan = _only_trade(golden_log)["plan"]
    assert default_plan["target_price"] is None
    assert default_plan["reward_multiple"] is None

    asked = _only_trade(target_log)["plan"]
    assert asked["reward_multiple"] == pytest.approx(2.0)
    assert asked["target_price"] == pytest.approx(
        asked["entry_price"] + asked["risk_points"] * asked["reward_multiple"]
    )
    # Only the target differs: the entry, the stop and the risk are the same day.
    assert asked["entry_price"] == default_plan["entry_price"]
    assert asked["stop_price"] == default_plan["stop_price"]
    assert asked["risk_points"] == default_plan["risk_points"]


def test_a_target_that_was_asked_for_pays_exactly_two_r(target_log):
    trade = _only_trade(target_log)
    outcome = trade["outcome"]
    assert ExitReason(outcome["exit_reason"]) is ExitReason.TARGET
    assert outcome["exit_price"] == pytest.approx(trade["plan"]["target_price"])
    assert outcome["r_multiple"] == pytest.approx(2.0)
    assert outcome["mfe_points"] >= 0.0
    assert outcome["mae_points"] >= 0.0


def test_an_untargeted_trend_rides_the_trail_to_the_session_flat(golden_log):
    """With no target the trail is what carries the trend, and it never catches it.

    This is the case a 2R target used to cut short: the same day pays a little
    over 3R when nothing takes the position off early.
    """
    trade = _only_trade(golden_log)
    plan = trade["plan"]
    outcome = trade["outcome"]
    assert ExitReason(outcome["exit_reason"]) is ExitReason.SESSION_FLAT
    assert outcome["exit_timestamp"].startswith("2026-08-24T15:15")
    # Price went well past the trail activation, so the trail was live for most
    # of the day -- and still did not stop the position out.
    assert outcome["exit_price"] > plan["trail_activation_price"]
    assert outcome["r_multiple"] > 1.0


def test_the_unstopped_day_ends_at_the_session_flat(drift_log):
    """Same entry and same plan; the price simply never resolves any level."""
    trade = _only_trade(drift_log)
    plan = trade["plan"]
    outcome = trade["outcome"]
    assert ExitReason(outcome["exit_reason"]) is ExitReason.SESSION_FLAT
    assert outcome["exit_timestamp"].startswith("2026-08-24T15:15")
    # Never far enough for the trail to arm, never back to the stop.
    assert plan["stop_price"] < outcome["exit_price"] < plan["trail_activation_price"]
    assert 0.0 < outcome["r_multiple"] < 1.0
    # MFE and MAE are never negative, whatever the path did.
    assert outcome["mfe_points"] >= 0.0
    assert outcome["mae_points"] >= 0.0


def test_a_close_back_through_the_midpoint_closes_the_position(break_log):
    """The structural exit: the reason for holding is gone, so the position is.

    The stop is never touched on this tail, so without the structural exit the
    position would sit through the whole collapse waiting for a level that is ten
    points further away. It fills at the close, because a close-based signal is
    not known until the bar is complete.
    """
    trade = _only_trade(break_log)
    plan = trade["plan"]
    outcome = trade["outcome"]
    assert ExitReason(outcome["exit_reason"]) is ExitReason.STRUCTURE
    assert outcome["exit_price"] < MIDPOINT
    # Out well before the session flat, and above the stop it never reached.
    assert outcome["exit_price"] > plan["stop_price"]
    assert outcome["exit_timestamp"] < "2026-08-24T10:00"
    assert -1.0 < outcome["r_multiple"] < 0.0


def test_the_policys_exit_reaches_the_replay_and_retires_the_trade_row(break_log):
    """The edge that was missing: the exit moment feeding back into the replay.

    The exit policy always ran, but after the replay had finished, so its verdict
    was written to a log row and thrown away -- the trade row stayed ACTIVE and the
    day was capped at one position. Now the resolved exit is fed back through the
    same ``exit_timestamps`` parameter live uses, so the state machine reaches it
    and emits ``TRADE_CLOSED``.

    The event lands one minute after the outcome. The policy closes on the bar
    stamped ``T``, which is not knowable until ``T`` completes, and the replay
    judges that bar at ``T + 1min`` -- so anything else would be the log claiming
    the strategy acted on a candle it had not seen.
    """
    exit_row = next(row for row in break_log["rows"] if row["kind"] == "EXIT")
    closed = [
        row
        for row in break_log["rows"]
        if row["kind"] == "EVENT" and row["event_type"] == "TRADE_CLOSED"
    ]

    assert len(closed) == 1
    assert closed[0]["trade_id"] == exit_row["trade_id"]
    assert pd.Timestamp(closed[0]["timestamp"]) == pd.Timestamp(
        exit_row["timestamp"]
    ) + timedelta(minutes=1)
    # One pass to resolve the entry, one to find nothing left. A third would mean
    # an entry was resolved twice.
    assert break_log["summary"]["resolution_passes"] == 2


def test_one_entry_a_tail_is_starvation_and_not_a_held_position(break_log, golden_log):
    """Why the count stays at one, now that an open row is no longer the reason.

    This is the honest version of the old ``len(entries) == 1``. That assertion
    used to hold because the first trade never came off and everything behind it
    was refused ``ACTIVE_TRADE_BLOCK``. It still holds -- but for a different
    reason, and the difference is the whole point of the change: no candidate on
    this fixture is ever refused for an open row. Every refusal is
    ``NO_ADMISSIBLE_CONDITION``, meaning the rules were consulted and found
    nothing.

    On BREAK the starvation is exact. Price settles at 97.0, which is inside the
    red bar's 94.6-104.4 band, so there is no space outside the zone for a working
    reference to be looked for; and it is below the 99.5 midpoint, so no close
    ever re-crosses it for a fresh initial entry. Both paths are correctly idle,
    for five and a half hours, on price that offers neither.
    """
    for log in (break_log, golden_log):
        codes = {
            row["admission_code"]
            for row in log["rows"]
            if row["kind"] == "EVENT" and row["admission_code"] is not None
        }
        assert "ACTIVE_TRADE_BLOCK" not in codes
        assert len([t for t in log["trades"] if t["plan"] is not None]) == 1

    index_candles, _futures = _market_frames(tail="BREAK")
    exit_row = next(row for row in break_log["rows"] if row["kind"] == "EXIT")
    after = index_candles.loc[index_candles.index > pd.Timestamp(exit_row["timestamp"])]

    assert not after.empty
    assert (after["close"] == BREAK_PLATEAU).all()
    assert BAND_LOW < BREAK_PLATEAU < MIDPOINT < BAND_HIGH
    assert after["close"].max() < MIDPOINT, "no close re-crosses the midpoint"
    assert after["high"].max() < BAND_HIGH, "price never leaves the zone either"


def test_every_tail_shares_the_same_gate_and_plan(golden_log, drift_log, break_log):
    """One entry, three paths. Any difference in the plan would confound them."""
    plans = [
        _only_trade(log)["plan"] for log in (golden_log, drift_log, break_log)
    ]
    assert plans[0] == plans[1] == plans[2]


def test_the_stop_cannot_be_priced_from_inside_the_entry_slot(golden_log):
    """Price after the 09:31 entry must not reach the stop, not even by one slot.

    The stop comes from the five-minute candle that crossed the midpoint, and the
    entry fires on a one-minute close inside that candle -- so the slot is still
    open when the plan is built. Resampling the whole day first handed over its
    finished 89.6 low here instead of the 95.4 low that had printed, which
    doubles ``risk_points`` and rescales every R-multiple on the trade.
    """
    spike = _only_trade(_build(tail="SPIKE"))
    assert spike["plan"] == _only_trade(golden_log)["plan"]
    assert spike["plan"]["stop_price"] == pytest.approx(95.4)
    # The dive is real, so the way out is free to differ -- only the plan is fixed.
    assert spike["outcome"]["exit_reason"] != _only_trade(golden_log)[
        "outcome"
    ]["exit_reason"]


def test_gate_rows_record_which_reference_was_in_force(golden_log):
    """A verdict without its geometry is unreadable.

    PASS against the red bar and PASS against the working reference are reached
    through different gates -- the first needs the futures against their VWAP,
    the second consults no VWAP at all -- so a gate row that does not name its
    reference cannot be audited.
    """
    events = [row for row in golden_log["rows"] if row["kind"] == "EVENT"]
    assert events
    # Same keys on every row, present or not, so two days stay diffable.
    for row in events:
        assert {
            "entry_type",
            "trend_strength",
            "governing_reference",
            "zone_position",
            "midpoint_distance_points",
            "working_body_ratio",
        } <= row.keys()

    admitted = [row for row in events if row["candidate_allowed"]]
    assert len(admitted) == 1
    assert admitted[0]["governing_reference"] == "RED_BAR"
    assert admitted[0]["entry_type"] == "INITIAL"
    assert admitted[0]["zone_position"] is not None
    assert "ref=RED_BAR" in render_decision_log(golden_log)


def test_a_plan_that_fails_the_risk_floor_is_rejected_with_a_code():
    log = _build(minimum_risk_points=10_000.0)
    assert log["summary"]["admitted_entries"] == 0
    assert log["summary"]["plans_rejected"] == 1
    rejection = next(t for t in log["trades"] if t["rejection"])
    assert rejection["rejection"] == RiskPlanRejection.RISK_BELOW_FLOOR.value
    assert any(row["kind"] == "REJECT" for row in log["rows"])


def test_widest_resolution_changes_the_stop_not_the_schema():
    latest = _build()
    widest = _build(trigger_resolution=TriggerResolution.WIDEST)
    latest_plan = latest["trades"][0]["plan"]
    widest_plan = widest["trades"][0]["plan"]
    assert latest_plan["trigger"] in {"MIDPOINT_CROSS", "FUTURES_VWAP_CROSS"}
    # Same entry, possibly different stop — the schema and day are unchanged.
    assert latest_plan["entry_price"] == widest_plan["entry_price"]
    assert widest["schema"] == latest["schema"]


def test_the_rendered_log_is_stable_text(golden_log, target_log):
    text = render_decision_log(golden_log)
    assert text.startswith(f"SCHEMA {DECISION_LOG_SCHEMA}")
    assert "GATE" in text
    assert "PLAN" in text
    assert "EXIT" in text
    assert "SUMMARY" in text
    # An absent target renders as a placeholder rather than vanishing, so the
    # PLAN line keeps the same columns whether or not one was asked for.
    assert "target=-" in text
    assert "target=-" not in render_decision_log(target_log)
