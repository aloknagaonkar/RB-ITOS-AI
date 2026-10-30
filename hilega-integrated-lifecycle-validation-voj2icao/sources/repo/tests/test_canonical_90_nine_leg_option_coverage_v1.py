from market_lab.canonical_90_nine_leg_option_coverage_v1 import leg_spec


def test_bullish_nine_leg_mapping():
    assert leg_spec("BULLISH") == [
        ("ITM4",-4,"CE"),
        ("ITM3",-3,"CE"),
        ("ITM2",-2,"CE"),
        ("ITM1",-1,"CE"),
        ("ATM",0,"CE"),
        ("OTM1",1,"CE"),
        ("OTM2",2,"CE"),
        ("OTM3",3,"CE"),
        ("OTM4",4,"CE"),
    ]


def test_bearish_nine_leg_mapping():
    assert leg_spec("BEARISH") == [
        ("ITM4",4,"PE"),
        ("ITM3",3,"PE"),
        ("ITM2",2,"PE"),
        ("ITM1",1,"PE"),
        ("ATM",0,"PE"),
        ("OTM1",-1,"PE"),
        ("OTM2",-2,"PE"),
        ("OTM3",-3,"PE"),
        ("OTM4",-4,"PE"),
    ]


def test_nine_legs_exact_and_unique():
    for direction in ("BULLISH","BEARISH"):
        legs = leg_spec(direction)
        assert len(legs) == 9
        assert len({x[0] for x in legs}) == 9
        assert len({x[1] for x in legs}) == 9
        assert sorted(x[1] for x in legs) == list(range(-4,5))
        assert len({x[2] for x in legs}) == 1
