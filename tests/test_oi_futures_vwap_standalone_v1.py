from market_lab.oi_futures_vwap_standalone_v1 import (
    confluence_direction,
    raw_oi_direction,
)


def test_bullish_oi_and_vwap():
    assert raw_oi_direction("LONG_BUILDUP", "SHORT_BUILDUP") == "BULLISH"
    assert (
        confluence_direction(
            "LONG_BUILDUP", "SHORT_BUILDUP", 24010.0, 24000.0
        )
        == "BULLISH"
    )
    assert (
        confluence_direction(
            "LONG_BUILDUP", "SHORT_BUILDUP", 23990.0, 24000.0
        )
        is None
    )


def test_bearish_oi_and_vwap():
    assert raw_oi_direction("SHORT_BUILDUP", "LONG_BUILDUP") == "BEARISH"
    assert (
        confluence_direction(
            "SHORT_BUILDUP", "LONG_BUILDUP", 23990.0, 24000.0
        )
        == "BEARISH"
    )
    assert (
        confluence_direction(
            "SHORT_BUILDUP", "LONG_BUILDUP", 24010.0, 24000.0
        )
        is None
    )


def test_other_oi_combinations_do_not_signal():
    assert raw_oi_direction("SHORT_COVERING", "SHORT_BUILDUP") is None
    assert raw_oi_direction("LONG_BUILDUP", "LONG_BUILDUP") is None
