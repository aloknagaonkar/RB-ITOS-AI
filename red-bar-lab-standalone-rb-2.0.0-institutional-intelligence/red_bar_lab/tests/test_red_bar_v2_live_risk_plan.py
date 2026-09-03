"""Gate 5 as the live path runs it: can this admission be given a tradable stop?

The point of this module is that it is *not* a second implementation. Research
already prices a stop for every admitted entry, and if the live answer differs
from the research answer then every R-multiple in the validation report describes
a strategy that is not the one trading. So the central test here is an agreement
test between the two paths on the same day, and the rest pin the asymmetry the
live caller depends on: a strategy refusal blocks, a data outage does not.
"""

from dataclasses import replace

import pandas as pd
import pytest

from red_bar_lab.domain.red_bar_v2 import RiskPlanRejection, StopTrigger
from red_bar_lab.services.red_bar_v2_derived_exits import MISSING_EVIDENCE
from red_bar_lab.services.red_bar_v2_live_risk_plan import (
    RISK_PLAN_OK,
    RISK_PLAN_UNAVAILABLE,
    evaluate_live_red_bar_v2_risk_plan,
)
from red_bar_lab.tests.test_red_bar_v2_derived_exits import (
    UNPLANNABLE,
    _admitted,
    _day,
    _replay,
    _resolve,
)


def _first_admission(index_candles, futures_candles):
    """The day's first allowed admission, taken from the replay itself.

    Not hand-built: the entry price and reference level have to be the strategy's
    own, because an agreement test between two paths is worthless if the fixture
    is the thing both paths agree with.
    """
    return _admitted(_replay(index_candles, futures_candles))[0]


def _verdict(index_candles, futures_candles, **kwargs):
    return evaluate_live_red_bar_v2_risk_plan(
        event=_first_admission(index_candles, futures_candles),
        index_candles=index_candles,
        futures_candles=futures_candles,
        **kwargs,
    )


def test_the_live_verdict_matches_the_plan_research_builds_for_the_same_entry():
    """The whole reason this module reuses the research helpers, asserted.

    Same day, same admission, two code paths. If these ever part company the
    validation report stops describing the system that trades -- and it would part
    company silently, because each side looks right on its own.
    """
    index_candles, futures_candles = _day()
    plan = _resolve(index_candles, futures_candles).trades[0].plan
    verdict = _verdict(index_candles, futures_candles)

    assert verdict.tradable is True
    assert verdict.code == RISK_PLAN_OK
    assert verdict.stop_price == pytest.approx(round(plan.stop_price, 2))
    assert verdict.risk_points == pytest.approx(round(plan.risk_points, 2))
    assert verdict.stop_trigger == plan.trigger.value
    assert verdict.trigger_timestamp == plan.trigger_timestamp.isoformat()
    assert verdict.entry_price == pytest.approx(round(plan.entry_price, 2))
    assert verdict.direction == plan.direction.value


def test_risk_outside_the_band_is_refused_and_says_which_side():
    """The gate's reason for existing: 5.4 points of risk is not a trade.

    This is the day research already rejects with RISK_BELOW_FLOOR, so the live
    path agreeing on the code is what lets a day's refusals be reconciled across
    the two by code alone.
    """
    verdict = _verdict(*_day(UNPLANNABLE))

    assert verdict.tradable is False
    assert verdict.code == RiskPlanRejection.RISK_BELOW_FLOOR.value
    assert verdict.evidence_only is False


def test_a_band_the_entry_cannot_satisfy_refuses_it_rather_than_resizing():
    """Overriding the band is how the caller tunes the gate, not how it is bypassed."""
    index_candles, futures_candles = _day()
    verdict = _verdict(index_candles, futures_candles, minimum_risk_points=500.0)

    assert verdict.tradable is False
    assert verdict.code == RiskPlanRejection.RISK_BELOW_FLOOR.value
    # The band it was judged against travels with the verdict, so a refusal on the
    # panel can be read without knowing which policy was in force.
    assert verdict.minimum_risk_points == pytest.approx(500.0)


def test_the_fallback_prices_an_entry_no_five_minute_candle_crossed():
    """The entry that used to go unmeasured now carries a stop.

    With no completed 5-minute candle shown to have crossed anything,
    ``find_stop_trigger`` returns nothing and the candle that fired the entry has
    to answer for the stop. Before that fallback existed this was 5 of 8
    admissions on 2026-09-03, every one refused for want of a level the strategy
    had never needed.

    The stop must come from the minute *before* the entry stamp. The admission is
    stamped when its candle is judged, one minute after that candle closed, so the
    bar carrying the stamp is the first bar the position is held -- priced off that
    one, the stop is an extreme the same bar has already made and the entry is a
    -1R the moment it opens.
    """
    index_candles, futures_candles = _day()
    admission = _first_admission(index_candles, futures_candles)
    entry_stamp = pd.Timestamp(admission.timestamp)
    triggering = entry_stamp - pd.Timedelta(minutes=1)
    # A reference level the day never approaches, so no 5-minute slot can be shown
    # to have closed across it in either series. Nothing else about the admission
    # is touched -- this changes what the stop *search* can find, not what was
    # admitted or at what price.
    unreachable = replace(
        admission, details=admission.details | {"reference_midpoint": 1.0}
    )

    verdict = evaluate_live_red_bar_v2_risk_plan(
        event=unreachable,
        index_candles=index_candles,
        futures_candles=futures_candles,
        minimum_risk_points=0.5,
    )

    assert verdict.tradable is True
    assert verdict.stop_trigger == StopTrigger.ENTRY_CANDLE.value
    assert verdict.trigger_timestamp == triggering.isoformat()
    assert verdict.stop_price == pytest.approx(
        round(float(index_candles.loc[triggering, "low"]), 2)
    )
    assert verdict.stop_price != pytest.approx(
        round(float(index_candles.loc[entry_stamp, "low"]), 2)
    )


def test_an_absent_candle_series_is_an_outage_and_not_a_refusal():
    """A feed problem must never read as a verdict about this trade.

    Blocking here would turn every gap in the candle feed into a trading halt that
    is indistinguishable in the logs from the strategy declining an entry.
    """
    index_candles, futures_candles = _day()
    admission = _first_admission(index_candles, futures_candles)

    for absent in (
        {"index_candles": None, "futures_candles": futures_candles},
        {"index_candles": index_candles, "futures_candles": None},
        {"index_candles": index_candles.iloc[:0], "futures_candles": futures_candles},
        {"index_candles": index_candles, "futures_candles": futures_candles.iloc[:0]},
    ):
        verdict = evaluate_live_red_bar_v2_risk_plan(event=admission, **absent)
        assert verdict.code == RISK_PLAN_UNAVAILABLE
        assert verdict.tradable is True
        assert verdict.evidence_only is True
        assert verdict.risk_points is None


def test_an_admission_with_no_reference_level_cannot_be_priced_and_says_so():
    """Missing evidence is a refusal, because the entry itself is unexplainable."""
    index_candles, futures_candles = _day()
    admission = _first_admission(index_candles, futures_candles)
    stripped = replace(
        admission, details=admission.details | {"index_close": None}
    )

    verdict = evaluate_live_red_bar_v2_risk_plan(
        event=stripped,
        index_candles=index_candles,
        futures_candles=futures_candles,
    )

    assert verdict.tradable is False
    assert verdict.code == MISSING_EVIDENCE
    assert verdict.direction == admission.direction


def test_the_verdict_flattens_into_the_columns_the_signal_row_carries():
    """The dict is the contract between this module, the panel and the bridge."""
    verdict = _verdict(*_day())
    payload = verdict.as_dict()

    assert payload["risk_plan_tradable"] is True
    assert payload["risk_plan_code"] == RISK_PLAN_OK
    assert payload["risk_stop_price"] == pytest.approx(verdict.stop_price)
    assert payload["risk_points"] == pytest.approx(verdict.risk_points)
    assert payload["risk_stop_trigger"] in {trigger.value for trigger in StopTrigger}
    assert set(payload) >= {
        "risk_plan_tradable",
        "risk_plan_code",
        "risk_plan_detail",
        "risk_stop_price",
        "risk_points",
        "risk_stop_trigger",
    }


def test_the_stop_is_priced_from_what_had_printed_by_the_entry_minute():
    """The lookahead guard, restated where the live path can break it.

    Everything after the entry minute is deleted and the answer does not move. If
    it ever does, the live gate is reading candles that had not printed when the
    decision was made, and its risk numbers are unearned.
    """
    index_candles, futures_candles = _day()
    admission = _first_admission(index_candles, futures_candles)
    cutoff = pd.Timestamp(admission.timestamp)

    full = evaluate_live_red_bar_v2_risk_plan(
        event=admission,
        index_candles=index_candles,
        futures_candles=futures_candles,
    )
    truncated = evaluate_live_red_bar_v2_risk_plan(
        event=admission,
        index_candles=index_candles.loc[index_candles.index <= cutoff],
        futures_candles=futures_candles.loc[futures_candles.index <= cutoff],
    )

    assert truncated.stop_price == pytest.approx(full.stop_price)
    assert truncated.risk_points == pytest.approx(full.risk_points)
    assert truncated.stop_trigger == full.stop_trigger
    assert full.tradable is True, "a refused plan would make the comparison hollow"
