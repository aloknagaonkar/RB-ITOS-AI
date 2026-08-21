from red_bar_lab.services.option_chain_window import select_atm_option_chain_window


def _rows():
    return [
        {"strike": strike, "call_oi": strike * 2, "put_oi": strike * 3}
        for strike in range(24800, 25301, 50)
    ]


def test_selects_atm_and_four_strikes_each_side():
    result = select_atm_option_chain_window(
        _rows(),
        spot=25010,
        strikes_each_side=4,
    )

    assert result.status == "READY"
    assert result.atm_strike == 25000.0
    assert result.selected_strikes == (
        24800.0,
        24850.0,
        24900.0,
        24950.0,
        25000.0,
        25050.0,
        25100.0,
        25150.0,
        25200.0,
    )
    assert len(result.rows) == 9


def test_uses_explicit_atm_when_available():
    result = select_atm_option_chain_window(_rows(), atm_strike=25100)

    assert result.atm_strike == 25100.0
    assert 25100.0 in result.selected_strikes


def test_missing_rows_and_missing_atm_are_explicit():
    assert select_atm_option_chain_window([], spot=25000).reason_code == "OPTION_CHAIN_ROWS_MISSING"
    assert select_atm_option_chain_window(_rows()).reason_code == "ATM_REFERENCE_MISSING"
