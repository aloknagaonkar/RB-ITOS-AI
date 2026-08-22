import pytest

from red_bar_lab.domain.red_bar_v2 import (
    DomainValidationError,
    FuturesVwapEvidence,
    MidpointEvidence,
    RsiEvidence,
)


def test_rejects_bullish_rsi_flag_below_bullish_threshold():
    with pytest.raises(DomainValidationError, match="RSI alignment flags"):
        RsiEvidence(
            value=20.0,
            bullish_threshold=60.0,
            bearish_threshold=40.0,
            bullish_aligned=True,
            bearish_aligned=False,
        )


def test_rejects_bearish_rsi_flag_above_bearish_threshold():
    with pytest.raises(DomainValidationError, match="RSI alignment flags"):
        RsiEvidence(
            value=80.0,
            bullish_threshold=60.0,
            bearish_threshold=40.0,
            bullish_aligned=False,
            bearish_aligned=True,
        )


@pytest.mark.parametrize("value", [40.0, 60.0])
def test_rejects_rsi_alignment_at_exact_threshold(value):
    with pytest.raises(DomainValidationError, match="RSI alignment flags"):
        RsiEvidence(
            value=value,
            bullish_threshold=60.0,
            bearish_threshold=40.0,
            bullish_aligned=value == 60.0,
            bearish_aligned=value == 40.0,
        )


def test_accepts_neutral_rsi_at_exact_threshold():
    assert RsiEvidence(
        value=60.0,
        bullish_threshold=60.0,
        bearish_threshold=40.0,
        bullish_aligned=False,
        bearish_aligned=False,
    ).bullish_aligned is False


def test_rejects_bullish_vwap_flag_when_price_is_below_vwap():
    with pytest.raises(DomainValidationError, match="futures VWAP alignment flags"):
        FuturesVwapEvidence(
            instrument_key="NSE_FO|NIFTY-FUT",
            comparison_price=90.0,
            vwap=100.0,
            volume=1000.0,
            bullish_aligned=True,
            bearish_aligned=False,
            fresh=True,
        )


def test_rejects_vwap_alignment_at_equality():
    with pytest.raises(DomainValidationError, match="futures VWAP alignment flags"):
        FuturesVwapEvidence(
            instrument_key="NSE_FO|NIFTY-FUT",
            comparison_price=100.0,
            vwap=100.0,
            volume=1000.0,
            bullish_aligned=True,
            bearish_aligned=False,
            fresh=True,
        )


def test_accepts_neutral_vwap_at_equality():
    value = FuturesVwapEvidence(
        instrument_key="NSE_FO|NIFTY-FUT",
        comparison_price=100.0,
        vwap=100.0,
        volume=1000.0,
        bullish_aligned=False,
        bearish_aligned=False,
        fresh=True,
    )
    assert value.bullish_aligned is False
    assert value.bearish_aligned is False


def test_rejects_bullish_midpoint_flag_when_close_is_below_midpoint():
    with pytest.raises(DomainValidationError, match="midpoint alignment flags"):
        MidpointEvidence(
            index_close=90.0,
            midpoint=100.0,
            bullish_aligned=True,
            bearish_aligned=False,
        )


def test_rejects_midpoint_alignment_at_equality():
    with pytest.raises(DomainValidationError, match="midpoint alignment flags"):
        MidpointEvidence(
            index_close=100.0,
            midpoint=100.0,
            bullish_aligned=True,
            bearish_aligned=False,
        )


def test_accepts_neutral_midpoint_at_equality():
    value = MidpointEvidence(
        index_close=100.0,
        midpoint=100.0,
        bullish_aligned=False,
        bearish_aligned=False,
    )
    assert value.bullish_aligned is False
    assert value.bearish_aligned is False
