from red_bar_lab.services.option_participation_atm_window import (
    detect_atm_strike_window,
)


def test_detects_nearest_atm_and_returns_four_steps_each_side():
    strikes = [float(value) for value in range(24000, 24501, 50)]

    atm, interval, selected = detect_atm_strike_window(
        spot_price=24287.0,
        available_strikes=strikes,
        steps_each_side=4,
    )

    assert atm == 24300.0
    assert interval == 50.0
    assert selected == (
        24100.0,
        24150.0,
        24200.0,
        24250.0,
        24300.0,
        24350.0,
        24400.0,
        24450.0,
        24500.0,
    )


def test_atm_tie_uses_lower_available_strike_deterministically():
    atm, interval, selected = detect_atm_strike_window(
        spot_price=24275.0,
        available_strikes=[24200.0, 24250.0, 24300.0, 24350.0],
        steps_each_side=1,
    )

    assert atm == 24250.0
    assert interval == 50.0
    assert selected == (24200.0, 24250.0, 24300.0)


def test_window_is_bounded_by_available_chain_strikes():
    atm, interval, selected = detect_atm_strike_window(
        spot_price=24010.0,
        available_strikes=[24000.0, 24050.0, 24100.0, 24150.0],
        steps_each_side=4,
    )

    assert atm == 24000.0
    assert interval == 50.0
    assert selected == (24000.0, 24050.0, 24100.0, 24150.0)
