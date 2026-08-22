from red_bar_lab.services.market_evidence_engine import corrected_option_summary


def _row(**overrides):
    row = {
        "option_type": "CE",
        "strike": 25000,
        "atm_strike": 25000,
        "strike_offset_steps": 0,
        "current_price": 100,
        "bid": 99,
        "ask": 101,
        "spread": 2,
        "iv": 18,
        "volume": 1000,
        "oi": 5000,
        "participation_state": "FRESH_BUYING",
        "vwap": 95,
        "oi_change_pct": 5,
        "option_rsi": 60,
        "delta": 0.5,
    }
    row.update(overrides)
    return row


def test_missing_iv_is_rejected_consistently_with_ui_contract():
    summary = corrected_option_summary([_row(iv=None)])

    assert summary["eligible_ce"] == 0
    assert summary["rejected"] == 1
    assert summary["rows"][0]["contract_eligibility"] == "IV_UNAVAILABLE"


def test_iv_outlier_remains_distinct_from_missing_iv():
    summary = corrected_option_summary([_row(iv=0.5)])

    assert summary["rows"][0]["contract_eligibility"] == "IV_OUTLIER"


def test_persisted_strike_offset_has_priority_over_detected_interval():
    rows = [
        _row(strike=24900, strike_offset_steps=-2),
        _row(strike=25000, strike_offset_steps=0),
        _row(strike=25050, strike_offset_steps=1),
    ]

    summary = corrected_option_summary(rows)
    distances = [row["strike_distance_steps"] for row in summary["rows"]]

    assert distances == [2, 0, 1]


def test_median_interval_resists_one_anomalous_adjacent_strike():
    rows = [
        _row(strike=24900, strike_offset_steps=None),
        _row(strike=24950, strike_offset_steps=None),
        _row(strike=24975, strike_offset_steps=None),
        _row(strike=25000, strike_offset_steps=None),
        _row(strike=25050, strike_offset_steps=None),
        _row(strike=25100, strike_offset_steps=None),
    ]

    summary = corrected_option_summary(rows)
    by_strike = {
        row["strike"]: row["strike_distance_steps"]
        for row in summary["rows"]
    }

    # Adjacent differences are 50, 25, 25, 50, 50; median is 50.
    assert by_strike[24900] == 2
    assert by_strike[24950] == 1
    assert by_strike[25000] == 0
    assert by_strike[25100] == 2
