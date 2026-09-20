from market_lab.canonical_90_four_leg_option_coverage_v1 import leg_spec


def test_bullish_four_leg_mapping():
    assert leg_spec("BULLISH") == [
        ("ATM", 0, "CE"),
        ("OTM1", 1, "CE"),
        ("OTM2", 2, "CE"),
        ("OTM3", 3, "CE"),
    ]


def test_bearish_four_leg_mapping():
    assert leg_spec("BEARISH") == [
        ("ATM", 0, "PE"),
        ("OTM1", -1, "PE"),
        ("OTM2", -2, "PE"),
        ("OTM3", -3, "PE"),
    ]


def test_four_legs_are_exact_and_unique():
    for direction in ("BULLISH", "BEARISH"):
        legs = leg_spec(direction)
        assert len(legs) == 4
        assert len({x[0] for x in legs}) == 4
        assert len({x[1] for x in legs}) == 4
        assert len({x[2] for x in legs}) == 1
