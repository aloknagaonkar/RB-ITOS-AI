from red_bar_lab.execution.underlying_volume_authority import (
    VOLUME_APPLICABLE,
    VOLUME_INVALID,
    VOLUME_MISSING,
    VOLUME_NOT_APPLICABLE,
    assess_underlying_volume_authority,
    is_cash_index_instrument,
)


def test_nifty_cash_index_volume_is_not_applicable_even_when_zero():
    result = assess_underlying_volume_authority(
        instrument_key="NSE_INDEX|Nifty 50",
        volume=0,
    )

    assert result.status == VOLUME_NOT_APPLICABLE
    assert result.volume is None
    assert result.source == "INDEX_PRICE_ONLY"
    assert result.usable is False
    assert "active futures contract" in result.reason


def test_bank_nifty_cash_index_volume_is_not_applicable_when_missing():
    result = assess_underlying_volume_authority(
        instrument_key="NSE_INDEX|Nifty Bank",
        volume=None,
    )

    assert result.status == VOLUME_NOT_APPLICABLE
    assert result.volume is None


def test_index_detection_is_case_insensitive():
    assert is_cash_index_instrument("nse_index|Nifty 50") is True
    assert is_cash_index_instrument("BSE_INDEX|SENSEX") is True
    assert is_cash_index_instrument("NSE_FO|58072") is False


def test_futures_zero_volume_remains_applicable_not_weakly_reclassified():
    result = assess_underlying_volume_authority(
        instrument_key="NSE_FO|58072",
        volume=0,
    )

    assert result.status == VOLUME_APPLICABLE
    assert result.volume == 0.0
    assert result.source == "TRADED_INSTRUMENT"
    assert result.usable is True


def test_traded_instrument_positive_volume_is_applicable():
    result = assess_underlying_volume_authority(
        instrument_key="NSE_FO|58072",
        volume="125000",
    )

    assert result.status == VOLUME_APPLICABLE
    assert result.volume == 125000.0


def test_traded_instrument_missing_volume_is_explicit():
    result = assess_underlying_volume_authority(
        instrument_key="NSE_FO|58072",
        volume=None,
    )

    assert result.status == VOLUME_MISSING
    assert result.volume is None
    assert result.usable is False


def test_traded_instrument_negative_volume_is_invalid():
    result = assess_underlying_volume_authority(
        instrument_key="NSE_FO|58072",
        volume=-1,
    )

    assert result.status == VOLUME_INVALID
    assert result.volume is None
    assert result.usable is False
