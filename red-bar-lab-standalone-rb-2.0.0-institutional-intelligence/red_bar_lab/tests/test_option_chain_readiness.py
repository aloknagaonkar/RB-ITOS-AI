import pytest

from red_bar_lab.execution.option_chain_readiness import (
    CHAIN_EMPTY,
    CHAIN_INVALID_CALL_OI,
    CHAIN_MISSING_CALL_LEG,
    CHAIN_MISSING_CALL_OI,
    CHAIN_MISSING_PUT_LEG,
    CHAIN_MISSING_PUT_OI,
    CHAIN_MISSING_STRIKE,
    CHAIN_READY,
    CHAIN_ZERO_CALL_OI,
    CHAIN_ZERO_PUT_OI,
    assess_option_chain_completeness,
)


def _row(call_oi=1000, put_oi=1250):
    return {
        "strike_price": 24200.0,
        "call_options": {"market_data": {"oi": call_oi}},
        "put_options": {"market_data": {"oi": put_oi}},
    }


def test_complete_selected_strike_is_ready_and_pcr_usable():
    result = assess_option_chain_completeness([_row()], 24200)

    assert result.status == CHAIN_READY
    assert result.ready is True
    assert result.pcr_usable is True
    assert result.call_oi == 1000.0
    assert result.put_oi == 1250.0


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        ([], CHAIN_EMPTY),
        ([_row()], CHAIN_MISSING_STRIKE),
        (
            [{"strike_price": 24200, "put_options": {"oi": 100}}],
            CHAIN_MISSING_CALL_LEG,
        ),
        (
            [{"strike_price": 24200, "call_options": {"oi": 100}}],
            CHAIN_MISSING_PUT_LEG,
        ),
        (
            [
                {
                    "strike_price": 24200,
                    "call_options": {"market_data": {}},
                    "put_options": {"oi": 100},
                }
            ],
            CHAIN_MISSING_CALL_OI,
        ),
        (
            [
                {
                    "strike_price": 24200,
                    "call_options": {"oi": 100},
                    "put_options": {"market_data": {}},
                }
            ],
            CHAIN_MISSING_PUT_OI,
        ),
    ],
)
def test_incomplete_chain_states_are_explicit(rows, expected):
    strike = 24300 if expected == CHAIN_MISSING_STRIKE else 24200
    result = assess_option_chain_completeness(rows, strike)

    assert result.status == expected
    assert result.ready is False
    assert result.pcr_usable is False


def test_negative_oi_is_invalid_not_missing():
    result = assess_option_chain_completeness([_row(call_oi=-1)], 24200)

    assert result.status == CHAIN_INVALID_CALL_OI
    assert result.call_oi is None
    assert result.pcr_usable is False


@pytest.mark.parametrize(
    ("call_oi", "put_oi", "expected"),
    [
        (0, 1250, CHAIN_ZERO_CALL_OI),
        (1000, 0, CHAIN_ZERO_PUT_OI),
    ],
)
def test_zero_oi_is_distinguished_from_missing_oi(
    call_oi, put_oi, expected
):
    result = assess_option_chain_completeness(
        [_row(call_oi=call_oi, put_oi=put_oi)],
        24200,
    )

    assert result.status == expected
    assert result.call_oi == float(call_oi)
    assert result.put_oi == float(put_oi)
    assert result.pcr_usable is False
