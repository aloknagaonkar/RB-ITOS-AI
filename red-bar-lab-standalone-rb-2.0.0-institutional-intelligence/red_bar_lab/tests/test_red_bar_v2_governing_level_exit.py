"""The governing-level exit: verdict, publication, ranking, and wiring.

Five layers, in the order a close travels through them: the replay publishes the
level, the snapshot carries it, ``evaluate_red_bar_v2_structural_exit`` judges one
position against it, ``PaperExitEngine`` decides whether that verdict wins, and
``monitor_and_exit`` closes the row.

The boundary rule that shares the module is tested separately in
``test_red_bar_v2_structural_exit.py``; nothing here should be able to pass by
accident because that one fired.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, time, timedelta, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

from red_bar_lab.execution import automation
from red_bar_lab.execution.automation import RedBarPaperAutomationService
from red_bar_lab.execution.execution_policy import (
    RED_BAR_V2_STRATEGY_SOURCE,
    RSI_EXIT_MODE,
)
from red_bar_lab.execution.exit_engine import PaperExitEngine
from red_bar_lab.operations.red_bar_v2_ui_snapshot import (
    RedBarV2UISnapshot,
    build_red_bar_v2_ui_snapshot_from_replay,
    persist_red_bar_v2_ui_snapshot,
    read_red_bar_v2_ui_snapshot,
)
from red_bar_lab.services.red_bar_v2_futures_historical_replay import (
    replay_red_bar_v2_day_with_futures_vwap,
)
from red_bar_lab.services.red_bar_v2_structural_exit import (
    BAR_SECONDS,
    MAX_CLOSE_AGE_SECONDS,
    STRUCTURAL_EXIT_REASON,
    evaluate_red_bar_v2_structural_exit,
    position_direction,
)
from red_bar_lab.tests.test_execution_foundation import (
    AutoFakeZerodha,
    _insert_confirmed_signal,
    _setup,
)

IST = timezone(timedelta(hours=5, minutes=30))

CLOSE_STAMP = datetime(2026, 9, 3, 10, 0, tzinfo=IST)
"""A completed 1m candle, stamped with the start of its minute."""

FRESH_NOW = CLOSE_STAMP + timedelta(seconds=BAR_SECONDS + 30.0)
"""One bar to complete it, then half a monitor cycle. Comfortably inside bound."""

MIDPOINT = 23_973.15


def _snapshot(**overrides: object) -> RedBarV2UISnapshot:
    """A snapshot whose governing block is published and holding."""
    payload: dict[str, object] = {
        "governing_reference": "RED_BAR",
        "governing_midpoint": MIDPOINT,
        "governing_close": MIDPOINT + 12.0,
        "governing_close_timestamp": CLOSE_STAMP.isoformat(),
        "governing_zone_position": "ABOVE",
        "governing_distance_points": 12.0,
    }
    payload.update(overrides)
    return RedBarV2UISnapshot(**payload)  # type: ignore[arg-type]


def _order(option_type: str | None = "CE", **overrides: object) -> dict[str, object]:
    """An open V2 row, entered on the surviving side of the midpoint.

    ``underlying_price_entry`` is deliberately part of the baseline: a row without
    it cannot be judged at all, which is asserted separately.
    """
    row: dict[str, object] = {
        "order_id": f"ORDER-{option_type}",
        "option_type": option_type,
        "execution_strategy_source": "RED_BAR_V2",
        "entry_timestamp": (CLOSE_STAMP - timedelta(minutes=5)).isoformat(),
        "underlying_price_entry": MIDPOINT + (12.0 if option_type == "CE" else -12.0),
    }
    row.update(overrides)
    return row


# A day with no exit injected and therefore no deputy: 09:15-09:19 rises so it
# cannot be the reference, 09:20-09:24 falls so it is (high 24004.4, low 23989.6,
# midpoint 23997.0), and 09:25-09:29 recovers to close back inside the band. The
# same geometry as the committed deputy fixture, minus the deputy.
PLAIN_SESSION_START = datetime(2026, 8, 24, 9, 15, tzinfo=IST)
PLAIN_OPENING = [24000.0, 24001.0, 24002.0, 24003.0, 24004.0]
PLAIN_RED_BAR = [24003.0, 24000.0, 23997.0, 23994.0, 23990.0]
PLAIN_RECOVERY = [23992.0, 23994.0, 23996.0, 23998.0, 24000.0]
PLAIN_MIDPOINT = 23997.0
PLAIN_FINAL_CLOSE = 24000.0


def _plain_frame(closes: list[float], volumes: list[float]) -> "pd.DataFrame":
    """One-minute OHLCV, each candle opening where the last one closed."""
    opens = [closes[0] - 0.2, *closes[:-1]]
    return pd.DataFrame(
        {
            "open": opens,
            "high": [max(o, c) + 0.4 for o, c in zip(opens, closes)],
            "low": [min(o, c) - 0.4 for o, c in zip(opens, closes)],
            "close": closes,
            "volume": volumes,
        },
        index=pd.date_range(PLAIN_SESSION_START, periods=len(closes), freq="1min"),
    )


def _plain_day():
    closes = [*PLAIN_OPENING, *PLAIN_RED_BAR, *PLAIN_RECOVERY]
    return replay_red_bar_v2_day_with_futures_vwap(
        _plain_frame(closes, [10.0 + step for step in range(len(closes))]),
        _plain_frame(
            [24000.0 - 2.0 * step for step in range(len(closes))],
            [1000.0 + 10.0 * step for step in range(len(closes))],
        ),
        instrument_key="NSE_INDEX|Nifty 50",
        vwap_instrument_key="NSE_FO|NIFTY-FUT",
    )[0]


# --- the verdict ---------------------------------------------------------


def test_a_bullish_row_exits_only_once_the_close_is_below_the_midpoint():
    """The rule itself, from both sides of the level, on one CE row."""
    holding = evaluate_red_bar_v2_structural_exit(
        position=_order("CE"),
        snapshot=_snapshot(governing_close=MIDPOINT + 0.05),
        now=FRESH_NOW,
    )
    breached = evaluate_red_bar_v2_structural_exit(
        position=_order("CE"),
        snapshot=_snapshot(governing_close=MIDPOINT - 0.05),
        now=FRESH_NOW,
    )

    assert (holding.breached, holding.status) == (False, "HOLDING")
    assert (breached.breached, breached.status) == (True, "BREACHED")
    assert breached.direction == "BULLISH"
    assert breached.distance_points == pytest.approx(-0.05)
    assert "BULLISH" in str(breached.detail)


def test_a_bearish_row_reads_the_same_close_the_other_way_round():
    """One close, two positions, opposite verdicts -- direction is per row."""
    close = MIDPOINT + 8.0
    long_row = evaluate_red_bar_v2_structural_exit(
        position=_order("CE"), snapshot=_snapshot(governing_close=close), now=FRESH_NOW
    )
    short_row = evaluate_red_bar_v2_structural_exit(
        position=_order("PE"), snapshot=_snapshot(governing_close=close), now=FRESH_NOW
    )

    assert long_row.breached is False
    assert short_row.breached is True
    assert short_row.direction == "BEARISH"


def test_a_close_exactly_on_the_midpoint_does_not_exit_either_side():
    """The level has to be closed *through*. Equality is not failure."""
    for option_type in ("CE", "PE"):
        verdict = evaluate_red_bar_v2_structural_exit(
            position=_order(option_type),
            snapshot=_snapshot(governing_close=MIDPOINT),
            now=FRESH_NOW,
        )
        assert verdict.breached is False, option_type
        assert verdict.status == "HOLDING"


def test_the_option_held_outranks_a_stale_recorded_direction():
    """The 2026-09-03 failure mode: a CE row while the snapshot still says BEARISH.

    ``direction`` on the snapshot is the last *admitted* direction and froze for
    56 minutes that day. A CE is long the index regardless, so the exit must be
    judged as BULLISH -- otherwise the stale field would close a winning row and
    hold a losing one.
    """
    verdict = evaluate_red_bar_v2_structural_exit(
        position=_order("CE", direction="BEARISH"),
        signal={"direction": "BEARISH"},
        snapshot=_snapshot(governing_close=MIDPOINT + 12.0, direction="BEARISH"),
        now=FRESH_NOW,
    )

    assert verdict.direction == "BULLISH"
    assert verdict.breached is False


def test_direction_falls_back_to_the_recorded_value_then_gives_up():
    assert position_direction({"option_type": "CE"}) == "BULLISH"
    assert position_direction({"option_type": "PE"}) == "BEARISH"
    assert position_direction({"option_type": "", "direction": "bullish"}) == "BULLISH"
    assert position_direction({}, {"direction": "BEARISH"}) == "BEARISH"
    assert position_direction({"option_type": "XX", "direction": "SIDEWAYS"}) is None


# --- the refusals --------------------------------------------------------


def test_every_refusal_names_itself_and_none_of_them_exit():
    """Each way the verdict can decline, and the status that says which.

    ``breached`` false is not enough: the exit audit has to distinguish "the
    level held" from "there was no level", so the statuses are asserted
    individually rather than collapsed into one truthiness check.
    """
    breaching_close = MIDPOINT - 20.0
    cases = {
        "NOT_RED_BAR_V2": dict(
            position=_order("CE", execution_strategy_source="DIRECTIONAL_REGIME"),
            snapshot=_snapshot(governing_close=breaching_close),
        ),
        "LEVEL_UNAVAILABLE": dict(
            position=_order("CE"),
            snapshot=_snapshot(governing_midpoint=None),
        ),
        "DIRECTION_UNAVAILABLE": dict(
            position=_order(None, direction=None),
            snapshot=_snapshot(governing_close=breaching_close),
        ),
        "CLOSE_TIMESTAMP_UNREADABLE": dict(
            position=_order("CE"),
            snapshot=_snapshot(
                governing_close=breaching_close,
                governing_close_timestamp="not-a-moment",
            ),
        ),
    }
    for expected, kwargs in cases.items():
        verdict = evaluate_red_bar_v2_structural_exit(now=FRESH_NOW, **kwargs)  # type: ignore[arg-type]
        assert verdict.status == expected, verdict
        assert verdict.breached is False, expected
        assert verdict.detail, expected


def test_a_level_that_was_never_published_is_not_read_as_a_breach():
    """A snapshot from before the governing block existed deserialises as None.

    The fail-closed direction matters here: ``governing_close`` of ``None`` must
    not compare as below any midpoint.
    """
    verdict = evaluate_red_bar_v2_structural_exit(
        position=_order("CE"), snapshot=RedBarV2UISnapshot(), now=FRESH_NOW
    )

    assert verdict.status == "LEVEL_UNAVAILABLE"
    assert verdict.governing_midpoint is None
    assert verdict.breached is False


def test_the_close_is_stale_exactly_one_bar_after_it_could_be_known():
    """The bound is measured from ``known_at``, not from the candle stamp.

    A candle stamped 10:00 is only knowable at 10:01, so a fresh close is already
    one bar old the instant it can be acted on. Getting this wrong by a bar would
    refuse every close on a slow cycle.
    """
    known_at = CLOSE_STAMP + timedelta(seconds=BAR_SECONDS)
    inside = evaluate_red_bar_v2_structural_exit(
        position=_order("CE"),
        snapshot=_snapshot(governing_close=MIDPOINT - 20.0),
        now=known_at + timedelta(seconds=MAX_CLOSE_AGE_SECONDS - 1.0),
    )
    outside = evaluate_red_bar_v2_structural_exit(
        position=_order("CE"),
        snapshot=_snapshot(governing_close=MIDPOINT - 20.0),
        now=known_at + timedelta(seconds=MAX_CLOSE_AGE_SECONDS + 1.0),
    )

    assert inside.breached is True
    assert outside.breached is False
    assert outside.status == "CLOSE_STALE"
    assert "past" in str(outside.detail)


def test_an_unmeasurable_freshness_claim_is_refused_rather_than_raised():
    """A naive ``now`` against an aware stamp must not abort the monitor loop.

    ``monitor_and_exit`` evaluates every open row in one pass; an exception here
    would leave the remaining rows unevaluated, so the mismatch is answered with
    a refusal instead.
    """
    verdict = evaluate_red_bar_v2_structural_exit(
        position=_order("CE"),
        snapshot=_snapshot(governing_close=MIDPOINT - 20.0),
        now=FRESH_NOW.replace(tzinfo=None),
    )

    assert verdict.status == "CLOSE_STALE"
    assert verdict.breached is False
    assert "unmeasurable" in str(verdict.detail)


def test_a_close_the_entry_already_knew_about_cannot_invalidate_the_entry():
    """Entry after the close became knowable -> refused; before -> acted on.

    The comparison is against ``known_at``, not the candle stamp. Comparing the
    raw stamp would skip the first legitimate break after entry: a 10:00 close is
    knowable at 10:01 and a 10:00:30 entry did not know it.
    """
    known_at = CLOSE_STAMP + timedelta(seconds=BAR_SECONDS)
    snapshot = _snapshot(governing_close=MIDPOINT - 20.0)

    already_knew = evaluate_red_bar_v2_structural_exit(
        position=_order("CE", entry_timestamp=(known_at + timedelta(seconds=1)).isoformat()),
        snapshot=snapshot,
        now=FRESH_NOW,
    )
    did_not_know = evaluate_red_bar_v2_structural_exit(
        position=_order("CE", entry_timestamp=(known_at - timedelta(seconds=1)).isoformat()),
        snapshot=snapshot,
        now=FRESH_NOW,
    )
    unmeasurable = evaluate_red_bar_v2_structural_exit(
        position=_order("CE", entry_timestamp=known_at.replace(tzinfo=None).isoformat()),
        snapshot=snapshot,
        now=FRESH_NOW,
    )

    assert already_knew.status == "CLOSE_PRECEDES_ENTRY"
    assert already_knew.breached is False
    assert did_not_know.breached is True
    assert unmeasurable.status == "CLOSE_PRECEDES_ENTRY"


def test_an_entry_time_that_cannot_be_read_does_not_block_the_exit():
    """A missing or unparseable entry stamp leaves the ordering check unapplied.

    Fail-closed on freshness, but not here: an order row with no readable entry
    time is still a live position, and refusing to protect it would be the more
    dangerous default.
    """
    for entry in (None, "", "unknown"):
        verdict = evaluate_red_bar_v2_structural_exit(
            position=_order("CE", entry_timestamp=entry),
            snapshot=_snapshot(governing_close=MIDPOINT - 20.0),
            now=FRESH_NOW,
        )
        assert verdict.breached is True, entry


# --- publication: the replay, then the snapshot --------------------------


def test_the_replay_publishes_the_red_bar_as_the_governing_level():
    """The branch the deputy search never reaches.

    ``select_governing_reference`` is consulted inside the replay only while a
    working-reference search is live, so a plain day -- no exit, no deputy -- used
    to leave the block unwritten and the exit permanently unable to act. The day
    below ends inside the band, which is also the state a deputy hands back from.
    """
    replay = _plain_day()
    governing = replay.rule_state["governing"]

    assert governing["reference"] == "RED_BAR"
    assert governing["midpoint"] == pytest.approx(PLAIN_MIDPOINT)
    assert governing["close"] == pytest.approx(PLAIN_FINAL_CLOSE)
    assert governing["zone_position"] == "INSIDE"
    assert governing["distance_points"] == pytest.approx(
        round(PLAIN_FINAL_CLOSE - PLAIN_MIDPOINT, 2)
    )
    # The published close is the last completed candle, not the last event.
    assert governing["close_timestamp"].startswith("2026-08-24T09:29")


def test_the_published_close_advances_after_the_last_event():
    """Why the level is read from ``rule_state`` and not from an event.

    Events fire on candidates, admissions, upgrades and closures; on 2026-09-03
    the newest event was 56 minutes old. The governing close has to be newer than
    that or the exit would judge today's position against a frozen price.
    """
    replay = _plain_day()
    last_event = max(event.timestamp for event in replay.events)
    published = datetime.fromisoformat(replay.rule_state["governing"]["close_timestamp"])

    assert published > last_event


def test_the_replay_publishes_the_deputy_only_while_it_is_still_alive():
    """A live deputy governs; an admitted one no longer exists to govern.

    The replay retires a deputy the moment it produces an entry -- so that the
    next exit starts a fresh search rather than re-entering off a level the market
    has traded through -- which means the level published for a *deputy-born*
    position is the red bar, not the deputy. Both halves are asserted here because
    the second is the one that makes the entry guard load-bearing.
    """
    from red_bar_lab.tests.test_red_bar_v2_working_reference_replay import (
        DEPUTY_UNDER_THE_BAND,
        RALLY_UNDER_THE_BAND,
        _replay,
    )

    # A tail that never reaches the deputy's 23940.4 high, so nothing is admitted
    # off it and the deputy is still standing at the close.
    alive = _replay(DEPUTY_UNDER_THE_BAND, [23900.0, 23905.0, 23910.0, 23915.0, 23920.0])
    retired = _replay(DEPUTY_UNDER_THE_BAND, RALLY_UNDER_THE_BAND)

    assert alive.rule_state["governing"]["reference"] == "WORKING"
    assert alive.rule_state["governing"]["midpoint"] == pytest.approx(23897.5)
    assert alive.rule_state["governing"]["zone_position"] == "BELOW"
    assert alive.rule_state["working_reference"]["entries"] == 0

    assert retired.rule_state["working_reference"]["entries"] == 1
    assert retired.rule_state["governing"]["reference"] == "RED_BAR"


def test_a_deputy_born_position_is_not_closed_by_the_level_it_opened_beneath():
    """The instant-exit bug the entry guard exists to prevent.

    A WORKING CE is taken at 23950.0, below the red bar band, and the level
    published from the next cycle onward is the red bar midpoint 23997.0. Reading
    that as an invalidation would close the position on its first completed close,
    every time, before the trade could go anywhere.
    """
    from red_bar_lab.tests.test_red_bar_v2_working_reference_replay import (
        MIDPOINT as RED_BAR_MIDPOINT,
    )

    verdict = evaluate_red_bar_v2_structural_exit(
        position=_order("CE", underlying_price_entry=23950.0),
        snapshot=_snapshot(
            governing_reference="RED_BAR",
            governing_midpoint=RED_BAR_MIDPOINT,
            governing_close=23960.0,
        ),
        now=FRESH_NOW,
    )

    assert verdict.status == "ENTRY_ON_FAILING_SIDE"
    assert verdict.breached is False
    assert "23,950.00" in str(verdict.detail)
    # The level is still reported, so the row can be read without guessing.
    assert verdict.governing_midpoint == pytest.approx(RED_BAR_MIDPOINT)


def test_a_row_with_no_recorded_entry_level_declines_rather_than_guesses():
    """Refusing costs a structural exit; acting risks closing a sound position."""
    verdict = evaluate_red_bar_v2_structural_exit(
        position=_order("CE", underlying_price_entry=None),
        snapshot=_snapshot(governing_close=MIDPOINT - 20.0),
        now=FRESH_NOW,
    )

    assert verdict.status == "ENTRY_LEVEL_UNAVAILABLE"
    assert verdict.breached is False


def test_the_snapshot_carries_the_level_and_survives_a_round_trip(tmp_path):
    """Six fields from ``rule_state`` to disk and back, unchanged."""
    replay = _plain_day()
    built = build_red_bar_v2_ui_snapshot_from_replay(
        SimpleNamespace(replay=replay, health=SimpleNamespace(status="READY")),
        futures_instrument_key="NSE_FO|NIFTY-FUT",
    )

    assert built.governing_reference == "RED_BAR"
    assert built.governing_midpoint == pytest.approx(PLAIN_MIDPOINT)
    assert built.governing_close == pytest.approx(PLAIN_FINAL_CLOSE)
    assert built.governing_zone_position == "INSIDE"

    persist_red_bar_v2_ui_snapshot(built, artifacts_root=tmp_path)
    reloaded = read_red_bar_v2_ui_snapshot(tmp_path)

    assert reloaded is not None
    for field in (
        "governing_reference",
        "governing_midpoint",
        "governing_close",
        "governing_close_timestamp",
        "governing_zone_position",
        "governing_distance_points",
    ):
        assert getattr(reloaded, field) == getattr(built, field), field


def test_a_replay_result_predating_the_block_yields_a_snapshot_that_cannot_act():
    """Older recorded results have no ``governing`` key at all.

    The snapshot must build with ``None`` rather than raise, and the verdict must
    then decline -- the fail-closed direction end to end.
    """
    stale = SimpleNamespace(
        rule_state={},
        events=(),
        reference_timestamp=None,
        reference_midpoint=None,
        final_trade_state="FLAT",
    )
    built = build_red_bar_v2_ui_snapshot_from_replay(
        SimpleNamespace(replay=stale, health=SimpleNamespace(status="DEGRADED")),
        futures_instrument_key="NSE_FO|NIFTY-FUT",
    )

    assert built.governing_reference is None
    assert built.governing_midpoint is None

    verdict = evaluate_red_bar_v2_structural_exit(
        position=_order("CE"), snapshot=built, now=FRESH_NOW
    )
    assert verdict.status == "LEVEL_UNAVAILABLE"
    assert verdict.breached is False


# --- ranking: what the engine does with the verdict ----------------------


def _v2_position(**overrides: object) -> dict[str, object]:
    """A V2 premium row with no protection earned yet.

    This is the state the rule exists for: ``red_bar_v2_external_initial_exit``
    drops the configured premium stop for a V2 row until a favourable move arms
    breakeven or trailing, so ``effective_stop`` is None and nothing below the
    structural rule is a price stop on the level the trade was taken on.
    """
    position: dict[str, object] = {
        "entry_price": 100.0,
        "current_price": 96.0,
        "stop_price": 93.0,
        "initial_stop_price": 93.0,
        "target1_price": 125.0,
        "execution_strategy_source": "RED_BAR_V2",
        "option_type": "CE",
        "underlying_price_entry": MIDPOINT + 12.0,
    }
    position.update(overrides)
    return position


def _breach() -> object:
    return evaluate_red_bar_v2_structural_exit(
        position=_order("CE"),
        snapshot=_snapshot(governing_close=MIDPOINT - 15.0),
        now=FRESH_NOW,
    )


def _holding() -> object:
    return evaluate_red_bar_v2_structural_exit(
        position=_order("CE"), snapshot=_snapshot(), now=FRESH_NOW
    )


def test_the_engine_exits_a_v2_row_on_a_breach_with_no_premium_protection_earned():
    engine = PaperExitEngine()
    verdict = _breach()

    result = engine.evaluate(position=_v2_position(), structural_exit=verdict)

    assert result.hard_exit_reason == STRUCTURAL_EXIT_REASON
    assert result.action == "EXIT"
    assert result.structural_exit == "BREACHED"
    assert result.governing_reference == "RED_BAR"
    assert result.governing_midpoint == pytest.approx(MIDPOINT)


def test_premium_protection_only_does_not_shadow_the_structural_exit():
    """Every other non-stop reason is suppressed in that mode; this one is not.

    The mode exists to stop premium *proxies* firing on a row whose thesis is
    owned elsewhere. The structural rule is that thesis, so suppressing it would
    leave the row with no price-based authority at all.
    """
    result = PaperExitEngine().evaluate(
        position=_v2_position(),
        exit_mode=RSI_EXIT_MODE,
        structural_exit=_breach(),
    )

    assert result.hard_exit_reason == STRUCTURAL_EXIT_REASON


def test_an_earned_premium_stop_and_the_day_end_both_outrank_a_breach():
    """Precedence: realised stop, then EOD, then structure.

    A realised stop has already happened to the premium; the structural close is a
    statement about the index. Reporting the index reason for a row the market
    already stopped out would misattribute the exit.
    """
    engine = PaperExitEngine()
    stopped = engine.evaluate(
        position=_v2_position(
            current_price=99.0, breakeven_armed=True, protected_stop_price=100.0
        ),
        structural_exit=_breach(),
    )
    at_the_bell = engine.evaluate(
        position=_v2_position(), eod_due=True, structural_exit=_breach()
    )

    assert stopped.hard_exit_reason == "PROTECTED_STOP"
    assert at_the_bell.hard_exit_reason == "EOD_EXIT"
    # The verdict is still recorded on both, so the row says the level had failed.
    assert stopped.structural_exit == "BREACHED"
    assert at_the_bell.structural_exit == "BREACHED"


def test_a_breach_outranks_the_option_premium_proxies():
    """EMA10 and the rest are correlated stand-ins; this is the thesis itself."""
    result = PaperExitEngine().evaluate(
        position=_v2_position(),
        signal={
            "direction": "BULLISH",
            "confirmation_high": 24_600.0,
            "confirmation_low": 24_500.0,
            "_ema10_5m_ready": True,
            "_ema10_5m_close": 90.0,
            "_ema10_5m_value": 95.0,
        },
        structural_exit=_breach(),
    )

    assert result.hard_exit_reason == STRUCTURAL_EXIT_REASON


def test_the_verdict_is_recorded_on_every_pass_even_when_it_does_not_fire():
    """"Why is this still open" has to be answerable from the stored row.

    ``exit_detail`` is built from ``reasons``, so a status line on a holding pass
    is the difference between a level that held and a level that was never
    published.
    """
    engine = PaperExitEngine()
    holding = engine.evaluate(position=_v2_position(), structural_exit=_holding())
    unpublished = engine.evaluate(
        position=_v2_position(),
        structural_exit=evaluate_red_bar_v2_structural_exit(
            position=_order("CE"), snapshot=RedBarV2UISnapshot(), now=FRESH_NOW
        ),
    )
    unasked = engine.evaluate(position=_v2_position())

    assert holding.hard_exit_reason is None
    assert holding.structural_exit == "HOLDING"
    assert any("STRUCTURE[HOLDING]" in reason for reason in holding.reasons)
    assert "midpoint" in str(holding.next_trigger)

    assert unpublished.structural_exit == "LEVEL_UNAVAILABLE"
    assert any("STRUCTURE[LEVEL_UNAVAILABLE]" in r for r in unpublished.reasons)

    assert unasked.structural_exit == "NOT_EVALUATED"
    assert not any("STRUCTURE[" in reason for reason in unasked.reasons)
    assert unasked.governing_midpoint is None


def test_a_breach_costs_health_so_the_read_only_panels_agree_with_the_exit():
    engine = PaperExitEngine()
    held = engine.evaluate(position=_v2_position(), structural_exit=_holding())
    broke = engine.evaluate(position=_v2_position(), structural_exit=_breach())

    assert broke.health_score == pytest.approx(held.health_score - 40.0)


def test_the_live_cycle_reads_the_level_once_and_closes_the_rows_it_breaks(
    tmp_path, monkeypatch
):
    """End to end through the real monitor: two open rows, one snapshot read.

    The read count is the point of the assertion, not decoration. The governing
    level is a property of the session, so reading it per row would reread the
    same file once per position and could hand two rows in the same cycle two
    different levels if the publisher wrote between them.
    """
    settings, db = _setup(tmp_path)
    _insert_confirmed_signal(db)
    service = RedBarPaperAutomationService(
        zerodha=AutoFakeZerodha(),
        database=db,
        settings=settings,
        underlying_name="NIFTY 50",
        minimum_candidate_score=65.0,
        eod_exit_time=time(23, 59),
        allow_outside_market_hours=True,
        allow_stale_signals=True,
        maximum_portfolio_risk_pct=5.0,
    )
    service.run_cycle(trading_date="2026-08-10", lots=1)

    opened = db.read_open_paper_execution_orders("PAPER-STD")
    assert len(opened) == 2
    assert {row["option_type"] for row in opened} == {"CE"}

    # The fixture opens ordinary rows; only a V2 row has its configured premium
    # stop excluded, so only a V2 row needs this exit. The entry is aged so the
    # close it is judged on is one it could not have known about, and the entry
    # index level is above the midpoint, as an admitted BULLISH entry's is.
    now = datetime.now(IST)
    with sqlite3.connect(db.path) as conn:
        conn.execute(
            """
            UPDATE paper_execution_orders
            SET execution_strategy_source=?, underlying_price_entry=?,
                entry_timestamp=?
            """,
            (
                RED_BAR_V2_STRATEGY_SOURCE,
                25_020.0,
                (now - timedelta(minutes=10)).isoformat(),
            ),
        )
        conn.commit()

    persist_red_bar_v2_ui_snapshot(
        _snapshot(
            governing_midpoint=25_000.0,
            governing_close=24_990.0,
            governing_close_timestamp=(now - timedelta(seconds=90)).isoformat(),
            governing_zone_position="BELOW",
            governing_distance_points=-10.0,
        ),
        artifacts_root=settings.artifacts_root,
    )

    reads: list[object] = []
    unpatched = read_red_bar_v2_ui_snapshot

    def counted(artifacts_root):
        snapshot = unpatched(artifacts_root)
        reads.append(snapshot)
        return snapshot

    monkeypatch.setattr(automation, "read_red_bar_v2_ui_snapshot", counted)

    closed, errors = service.monitor_and_exit()

    assert errors == []
    assert closed == 2
    assert len(reads) == 1

    rows = db.read_paper_execution_orders("PAPER-STD")
    assert len(rows) == 2
    assert {row["status"] for row in rows} == {"CLOSED"}
    assert {row["exit_reason"] for row in rows} == {f"AUTO_{STRUCTURAL_EXIT_REASON}"}

    # The audit line has to carry the level and the close, or a closed row cannot
    # be explained after the snapshot has moved on.
    triggered = [
        row
        for row in db.read_execution_state_events(signal_id="SIG-AUTO-1")
        if row["state"] == "EXIT_TRIGGERED"
    ]
    assert len(triggered) == 2
    assert all(
        "structure=BREACHED@RED_BAR 25000.00 close=24990.0" in str(row["detail"])
        for row in triggered
    )


def test_the_live_cycle_leaves_a_row_open_when_the_level_still_holds(
    tmp_path, monkeypatch
):
    """The same wiring, one field different: the close is above the midpoint.

    Without this the test above would pass just as well if ``monitor_and_exit``
    closed every V2 row it saw.
    """
    settings, db = _setup(tmp_path)
    _insert_confirmed_signal(db)
    service = RedBarPaperAutomationService(
        zerodha=AutoFakeZerodha(),
        database=db,
        settings=settings,
        underlying_name="NIFTY 50",
        minimum_candidate_score=65.0,
        eod_exit_time=time(23, 59),
        allow_outside_market_hours=True,
        allow_stale_signals=True,
        maximum_portfolio_risk_pct=5.0,
    )
    service.run_cycle(trading_date="2026-08-10", lots=1)

    now = datetime.now(IST)
    with sqlite3.connect(db.path) as conn:
        conn.execute(
            """
            UPDATE paper_execution_orders
            SET execution_strategy_source=?, underlying_price_entry=?,
                entry_timestamp=?
            """,
            (
                RED_BAR_V2_STRATEGY_SOURCE,
                25_020.0,
                (now - timedelta(minutes=10)).isoformat(),
            ),
        )
        conn.commit()

    persist_red_bar_v2_ui_snapshot(
        _snapshot(
            governing_midpoint=25_000.0,
            governing_close=25_010.0,
            governing_close_timestamp=(now - timedelta(seconds=90)).isoformat(),
            governing_distance_points=10.0,
        ),
        artifacts_root=settings.artifacts_root,
    )

    closed, errors = service.monitor_and_exit()

    assert errors == []
    assert closed == 0
    rows = db.read_paper_execution_orders("PAPER-STD")
    assert {row["status"] for row in rows} == {"OPEN"}
    monitored = [
        row
        for row in db.read_execution_state_events(signal_id="SIG-AUTO-1")
        if row["state"] == "EXIT_MONITOR"
    ]
    assert monitored
    assert all(
        "structure=HOLDING@RED_BAR 25000.00" in str(row["detail"])
        for row in monitored
    )

