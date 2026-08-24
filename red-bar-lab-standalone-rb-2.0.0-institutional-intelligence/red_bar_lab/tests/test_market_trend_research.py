from datetime import date, datetime, timezone

import pytest

from red_bar_lab.services.market_trend_research.calculator import DualPcrCalculator
from red_bar_lab.services.market_trend_research.models import OptionOiCell, PcrBias
from red_bar_lab.services.market_trend_research.policy import (
    MarketTrendResearchPolicy,
    StaticExchangeSessionCalendar,
)

NOW = datetime(2026, 8, 24, 4, 0, tzinfo=timezone.utc)
EXPIRY = date(2026, 8, 25)


def cells(*, steps=5, ce_oi=100.0, pe_oi=125.0):
    rows = []
    for offset in range(-steps, steps + 1):
        strike = 24250.0 + offset * 50.0
        rows.append(OptionOiCell(f"CE-{strike}", "CE", strike, EXPIRY, ce_oi, 90.0, NOW))
        rows.append(OptionOiCell(f"PE-{strike}", "PE", strike, EXPIRY, pe_oi, 100.0, NOW))
    return tuple(rows)


@pytest.mark.parametrize(
    ("trading_date", "expected"),
    [
        (date(2026, 8, 19), 5),
        (date(2026, 8, 20), 4),
        (date(2026, 8, 21), 3),
        (date(2026, 8, 24), 2),
        (date(2026, 8, 25), 1),
    ],
)
def test_expiry_window_uses_sessions_remaining(trading_date, expected):
    policy = MarketTrendResearchPolicy()
    assert policy.window_steps(trading_date, EXPIRY, StaticExchangeSessionCalendar()) == expected
    assert policy.expected_contract_count(expected) == ((2 * expected) + 1) * 2


def test_holiday_adjusts_session_window():
    policy = MarketTrendResearchPolicy()
    calendar = StaticExchangeSessionCalendar(frozenset({date(2026, 8, 20)}))
    assert policy.window_steps(date(2026, 8, 19), EXPIRY, calendar) == 4


def test_missing_session_position_fails_explicitly():
    policy = MarketTrendResearchPolicy()
    with pytest.raises(ValueError, match="SESSION_POSITION_UNAVAILABLE"):
        policy.window_steps(date(2026, 8, 26), EXPIRY, StaticExchangeSessionCalendar())


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.69, PcrBias.BEARISH),
        (0.70, PcrBias.NEUTRAL),
        (1.24, PcrBias.NEUTRAL),
        (1.25, PcrBias.BULLISH),
        (1.50, PcrBias.BULLISH),
        (1.51, PcrBias.STRONGLY_BULLISH),
    ],
)
def test_pcr_classification_boundaries(value, expected):
    assert MarketTrendResearchPolicy().classify(value) is expected


def test_current_pcr_and_totals_are_calculated_from_aggregate_oi():
    calculator = DualPcrCalculator(MarketTrendResearchPolicy())
    chain = cells(steps=2)
    window = calculator.define_window(chain, spot=24272.5, window_steps=2)
    panel = calculator.panel(
        name="Current / Overall PCR",
        cells=chain,
        window=window,
        spot=24272.5,
        sessions_to_expiry=1,
        source_timestamp=NOW,
        evaluated_at=NOW,
    )
    assert window.atm == 24250.0
    assert panel.expected_contract_count == 10
    assert panel.aggregate.total_ce_oi == 500.0
    assert panel.aggregate.total_pe_oi == 625.0
    assert panel.aggregate.pcr == 1.25
    assert panel.rows[-1]["strike"] == "OVERALL TOTAL"


def test_zero_ce_denominator_is_not_coerced():
    calculator = DualPcrCalculator(MarketTrendResearchPolicy())
    chain = cells(steps=1, ce_oi=0.0)
    window = calculator.define_window(chain, spot=24250.0, window_steps=1)
    panel = calculator.panel(name="Current", cells=chain, window=window, spot=24250.0, sessions_to_expiry=0, source_timestamp=NOW, evaluated_at=NOW)
    assert panel.aggregate.pcr is None
    assert panel.state.value == "PCR_UNAVAILABLE_ZERO_DENOMINATOR"


def test_duplicate_strike_side_and_partial_window_fail_closed():
    calculator = DualPcrCalculator(MarketTrendResearchPolicy())
    chain = cells(steps=1)
    with pytest.raises(ValueError, match="DUPLICATE_STRIKE_SIDE"):
        calculator.index(chain + (chain[0],))
    with pytest.raises(ValueError, match="PARTIAL_CONTRACT_WINDOW"):
        calculator.define_window(chain[:-1], spot=24250.0, window_steps=1)


def test_halfway_atm_rounds_to_lower_strike_deterministically():
    calculator = DualPcrCalculator(MarketTrendResearchPolicy())
    window = calculator.define_window(cells(steps=1), spot=24275.0, window_steps=1)
    assert window.atm == 24250.0
