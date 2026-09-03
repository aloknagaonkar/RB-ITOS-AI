"""The cut entry gates, at every later layer that could re-promote them.

Gates 7-14 were demoted to recorded evidence rather than deleted, so the codes
themselves still travel in the reason string. Three layers read that string
afterwards, and each is somewhere a demoted gate can come back as a blocker
without anyone editing the policy:

* the base opportunity engine writes its demotions into one
  ``SHADOW_ENTRY_WARNINGS=`` token;
* ``EMA10OpportunityIntelligenceEngine`` re-splits that reason to build its own
  blocker list, so it must recognise the shadow line as evidence;
* ``InstitutionalExecutionCommittee`` matches the reason against a list of
  terminal codes, and a substring test there reads a disclaimer
  (``BEARISH_EMA10_LOST_INFORMATIONAL_ONLY``) as the very blocker it disclaims.

Every test asserts on ``eligible`` and on the reason a real row would carry,
because the reason string *is* the interface between these layers -- there is no
structured channel for a demotion to travel down.

The last two cover the other half of the same change: structure judged on a
completed close instead of a live tick.
"""

from types import SimpleNamespace

from red_bar_lab.execution.institutional_execution import (
    InstitutionalExecutionCommittee,
)
from red_bar_lab.execution.opportunity_engine import (
    SHADOW_ENTRY_WARNINGS_PREFIX,
    OpportunityIntelligenceEngine,
)
from red_bar_lab.execution.paper_engine import PaperContract
from red_bar_lab.execution.performance_selection import (
    HistoricalPerformance,
    TradeSelectionEvaluation,
)
from red_bar_lab.execution.trend_automation import (
    EMA10OpportunityIntelligenceEngine,
)


def _candidate(option_type="PE"):
    """A contract healthy enough that SPREAD/LIQUIDITY never decide a test.

    Those two stay authoritative for every source, so leaving them near zero
    would make an eligibility assertion agree with anything.
    """
    return SimpleNamespace(
        contract=PaperContract(
            instrument_token=101,
            tradingsymbol=f"NIFTYTEST{option_type}",
            exchange="NFO",
            option_type=option_type,
            strike=24000.0,
            expiry="2026-09-08",
            lot_size=75,
        ),
        total_score=90.0,
        spread_score=15.0,
        liquidity_score=20.0,
        volume_score=15.0,
        oi_score=10.0,
        vwap_score=10.0,
        ema_score=10.0,
        momentum_score=10.0,
    )


# The red bar of the day, at the geometry the research fixtures use.
RED_BAR_HIGH = 24008.4
RED_BAR_LOW = 23979.6
QUALIFYING_CLOSE = 23996.0


def _signal(
    *,
    direction="BULLISH",
    signal_id="RBV2-DEMOTED",
    ema10_ready=True,
    ema10_close=None,
    ema10_value=None,
):
    """One V2 signal row as the live path assembles it.

    ``signal_id`` carries the source: ``execution_strategy_source`` resolves V2
    off the ``RBV2-`` prefix, so a row is a V2 row here for the same reason it is
    one in production.
    """
    return {
        "signal_id": signal_id,
        "level_type": "RED_BAR_V2",
        "direction": direction,
        "confirmation_high": RED_BAR_HIGH,
        "confirmation_low": RED_BAR_LOW,
        "confirmation_close": QUALIFYING_CLOSE,
        "underlying_entry": QUALIFYING_CLOSE,
        "_ema10_5m_ready": ema10_ready,
        "_ema10_5m_close": ema10_close,
        "_ema10_5m_value": ema10_value,
    }


def _shadow_codes(reason):
    """The demoted gates, read back off the reason exactly as a later layer does."""
    for token in str(reason or "").split("|"):
        token = token.strip()
        if token.startswith(SHADOW_ENTRY_WARNINGS_PREFIX):
            return [
                code
                for code in token[len(SHADOW_ENTRY_WARNINGS_PREFIX):].split(",")
                if code
            ]
    return []


def _selection():
    """A passing selection, so the committee's own verdict is the only variable."""
    history = HistoricalPerformance(
        sample_size=0,
        wins=0,
        losses=0,
        win_rate_pct=None,
        average_return_pct=None,
        average_winner_pct=None,
        average_loser_pct=None,
        profit_factor=None,
        expectancy_pct=None,
        average_mfe_pct=None,
        average_mae_pct=None,
        evidence_ready=False,
    )
    return TradeSelectionEvaluation(
        candidate_rank=1,
        candidate_symbol="NIFTYTESTPE",
        candidate_score=90.0,
        opportunity_score=90.0,
        reward_remaining_pct=80.0,
        reward_risk_ratio=1.667,
        execution_quality_score=100.0,
        historical_score=50.0,
        selection_score=88.0,
        historical=history,
        eligible=True,
        decision="BUY PE",
        reason="ALL_SELECTION_GATES_PASS",
    )


def _committee_verdict(opportunity_reason, *, strategy_source=""):
    """The committee's verdict on one upstream reason string, nothing else moving.

    ``minimum_execution_probability_pct=0`` because the probability gate has its
    own tests; leaving it armed would let a probability refusal masquerade as the
    token match under test.
    """
    committee = InstitutionalExecutionCommittee(
        minimum_execution_probability_pct=0
    )
    return committee.evaluate(
        candidate=_candidate(),
        selection=_selection(),
        opportunity=SimpleNamespace(
            opportunity_score=90.0, reason=opportunity_reason
        ),
        historical_orders=[],
        current_shadow=None,
        historical_shadow=[],
        stop_loss_pct=15.0,
        target_pct=25.0,
        strategy_source=strategy_source,
    )


def test_a_disclaimed_gate_is_not_read_as_the_gate_it_disclaims():
    """The 2026-09-03 inversion, as a test.

    The upstream engine says "this no longer vetoes an entry" by *appending* a
    suffix and setting eligible=True. Under a substring test the disclaimer
    contains the code it disclaims, so the committee blocked 23 already-eligible
    PE entries that day on the strength of the sentence saying they were fine.
    """
    verdict = _committee_verdict(
        "OPPORTUNITY_HEALTH_PASS "
        "| BEARISH_EMA10_LOST_INFORMATIONAL_ONLY "
        "| REWARD_METRICS_INFORMATIONAL_ONLY"
    )

    assert verdict.eligible is True
    assert "OPPORTUNITY_TERMINAL" not in verdict.reason


def test_a_shadow_line_is_evidence_and_never_matches_a_terminal_code():
    """One token holding many codes must match none of them.

    ``SHADOW_ENTRY_WARNINGS=STRUCTURE_INVALID,OPPOSITE_RED_BAR`` is how the base
    engine records a demotion. If the committee split on commas as well as pipes
    it would re-promote every gate the layer below had just cut -- silently, and
    only for the rows that had something demoted.
    """
    verdict = _committee_verdict(
        "OPPORTUNITY_HEALTH_PASS | REWARD_METRICS_INFORMATIONAL_ONLY "
        "| SHADOW_ENTRY_WARNINGS=STRUCTURE_INVALID,OPPOSITE_RED_BAR"
    )

    assert verdict.eligible is True
    assert "OPPORTUNITY_TERMINAL" not in verdict.reason


def test_a_bare_terminal_code_still_blocks_a_non_v2_row():
    """The positive case. Exact-token matching is a narrowing, not a disabling.

    Without this the two tests above would be satisfied by a committee that had
    stopped looking at the reason at all.
    """
    verdict = _committee_verdict(
        "STRUCTURE_INVALID | OPPOSITE_RED_BAR", strategy_source="RED_BAR"
    )

    assert verdict.eligible is False
    assert "OPPORTUNITY_TERMINAL[OPPOSITE_RED_BAR,STRUCTURE_INVALID]" in verdict.reason


def test_the_same_bare_code_is_demoted_to_shadow_for_a_v2_row():
    """Gates 7 and 8 are not on V2's rule table, so for V2 they only get recorded.

    Same input as the test above, one field different. The pair is the whole
    policy: the code is terminal where it is the strategy's own test, and
    evidence where the strategy has a contradictory test of its own.
    """
    verdict = _committee_verdict(
        "STRUCTURE_INVALID | OPPOSITE_RED_BAR", strategy_source="RED_BAR_V2"
    )

    assert verdict.eligible is True
    assert (
        SHADOW_ENTRY_WARNINGS_PREFIX
        + "OPPORTUNITY_TERMINAL[OPPOSITE_RED_BAR,STRUCTURE_INVALID]"
    ) in verdict.reason


def test_the_ema10_layer_carries_a_demotion_through_instead_of_re_promoting_it():
    """The layer that rebuilds the blocker list is the one that can undo a cut.

    ``EMA10OpportunityIntelligenceEngine`` re-splits the base engine's reason on
    ``|`` and treats every unrecognised token as a blocker. The shadow line is an
    unrecognised token, so without the explicit exemption a V2 row demoted by the
    base engine would be blocked one layer later -- by the record of its own
    demotion.

    Both gates are demoted at once here: the structure test fails (a close below
    the red bar's low on a bullish row) and EMA10 continuation fails too. Two
    codes from two different layers have to survive as evidence in the same
    string.

    The tick and the completed close are on the same side of the level, so the
    structure verdict here does not depend on which of the two is read. Which one
    it *should* read is the subject of the last two tests.
    """
    engine = EMA10OpportunityIntelligenceEngine(minimum_opportunity_score=0)

    result = engine.evaluate(
        signal=_signal(ema10_close=23960.0, ema10_value=24000.0),
        candidate=_candidate(option_type="CE"),
        spot_price=23959.6,
        signal_age_seconds=120,
        opposite_red_bar_confirmed=True,
    )

    assert result.eligible is True
    assert result.decision == "BUY CE"
    assert _shadow_codes(result.reason) == [
        "STRUCTURE_INVALID",
        "OPPOSITE_RED_BAR",
        "BULLISH_EMA10_LOST",
    ]


def test_a_non_v2_row_keeps_every_one_of_those_gates_terminal():
    """The demotion is scoped to V2, and this is what proves the scoping.

    Identical prices and an identical candidate; only the source differs. If this
    row were eligible the cut would have leaked into every other strategy.
    """
    engine = EMA10OpportunityIntelligenceEngine(minimum_opportunity_score=0)

    result = engine.evaluate(
        signal=_signal(signal_id="SIG-LEGACY", ema10_close=23960.0, ema10_value=24000.0)
        | {"level_type": "RED_BAR"},
        candidate=_candidate(option_type="CE"),
        spot_price=23959.6,
        signal_age_seconds=120,
        opposite_red_bar_confirmed=True,
    )

    assert result.eligible is False
    assert result.decision == "SKIP"
    assert "STRUCTURE_INVALID" in result.reason
    assert "OPPOSITE_RED_BAR" in result.reason
    assert _shadow_codes(result.reason) == []


def _legacy_bullish_row(**kwargs):
    """A non-V2 bullish row, so a structure refusal is terminal and therefore visible.

    On a V2 row STRUCTURE_INVALID is only recorded, which would make an
    eligibility assertion below say nothing about which price was judged.
    """
    return _signal(signal_id="SIG-LEGACY", **kwargs) | {"level_type": "RED_BAR"}


def test_structure_is_judged_on_a_completed_close_when_one_is_available():
    """Live spot is a tick mid-candle; it has not closed anywhere.

    Judged on the tick, a finished bullish setup fails the moment price dips
    through the red bar's low and passes again when it ticks back -- the same
    signal flipping valid and invalid between cycles, which is what 0 of 50
    bullish evaluations passing on 2026-09-03 looked like from inside.

    Here the tick is 20 points below the low and the completed close is inside the
    band. The completed close is the one that decides.
    """
    engine = OpportunityIntelligenceEngine(minimum_opportunity_score=0)

    result = engine.evaluate(
        signal=_legacy_bullish_row(),
        candidate=_candidate(option_type="CE"),
        spot_price=RED_BAR_LOW - 20.0,
        signal_age_seconds=120,
        opposite_red_bar_confirmed=False,
        structure_close=QUALIFYING_CLOSE,
    )

    assert result.structure_valid is True
    assert result.eligible is True
    assert "STRUCTURE_INVALID" not in result.reason


def test_without_a_completed_close_structure_still_falls_back_to_live_spot():
    """Every existing caller keeps its behaviour, which is why the argument is optional.

    Same call as above with the completed close removed: the tick decides again
    and refuses, exactly as it did before this parameter existed. That the two
    tests disagree is the point -- it is what shows the first one is reading the
    close and not merely passing for some unrelated reason.
    """
    engine = OpportunityIntelligenceEngine(minimum_opportunity_score=0)

    result = engine.evaluate(
        signal=_legacy_bullish_row(),
        candidate=_candidate(option_type="CE"),
        spot_price=RED_BAR_LOW - 20.0,
        signal_age_seconds=120,
        opposite_red_bar_confirmed=False,
    )

    assert result.structure_valid is False
    assert result.eligible is False
    assert "STRUCTURE_INVALID" in result.reason


def test_the_ema10_layer_hands_down_the_completed_close_it_already_holds():
    """Nobody has to plumb a second candle feed: the trend layer already has one.

    ``EMA10OpportunityIntelligenceEngine`` fetches completed 5-minute underlying
    candles for its own continuation test, so it is the layer that can give the
    base engine a close to judge structure on. This asserts the hand-down happens
    without the caller passing anything: the tick is below the red bar's low and
    the row survives anyway, because the 5-minute close is inside the band.
    """
    engine = EMA10OpportunityIntelligenceEngine(minimum_opportunity_score=0)

    result = engine.evaluate(
        signal=_legacy_bullish_row(
            ema10_close=QUALIFYING_CLOSE, ema10_value=RED_BAR_LOW
        ),
        candidate=_candidate(option_type="CE"),
        spot_price=RED_BAR_LOW - 20.0,
        signal_age_seconds=120,
        opposite_red_bar_confirmed=False,
    )

    assert result.structure_valid is True
    assert result.eligible is True
    assert result.decision == "BUY CE"
    assert "EMA10_TREND_VALID" in result.reason


def test_an_explicit_completed_close_is_not_overwritten_by_the_trend_layer():
    """The hand-down fills a gap; it does not seize the decision.

    A caller that has priced structure itself -- the V2 admission path judges the
    close against the governing midpoint -- must keep its answer, or the layer
    below would silently substitute a different level's candle.
    """
    engine = EMA10OpportunityIntelligenceEngine(minimum_opportunity_score=0)

    result = engine.evaluate(
        signal=_legacy_bullish_row(
            ema10_close=QUALIFYING_CLOSE, ema10_value=RED_BAR_LOW
        ),
        candidate=_candidate(option_type="CE"),
        spot_price=QUALIFYING_CLOSE,
        signal_age_seconds=120,
        opposite_red_bar_confirmed=False,
        structure_close=RED_BAR_LOW - 20.0,
    )

    assert result.structure_valid is False
    assert result.eligible is False
    assert "STRUCTURE_INVALID" in result.reason
