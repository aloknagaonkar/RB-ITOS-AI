from red_bar_lab.services.option_research_features import (
    aggregate_option_chain_without_double_counting,
    assess_option_liquidity,
    normalize_option_features,
    rank_liquid_option_candidates,
)


def _rows():
    return [
        {
            "instrument_key": "OPT-A",
            "strike": 25000,
            "option_type": "CE",
            "bid": 99,
            "ask": 101,
            "open_interest": 5000,
            "volume": 1000,
            "oi_change": 500,
        },
        {
            "instrument_key": "OPT-B",
            "strike": 25100,
            "option_type": "CE",
            "bid": 90,
            "ask": 110,
            "open_interest": 8000,
            "volume": 1500,
            "oi_change": 800,
        },
        {
            "instrument_key": "OPT-C",
            "strike": 24900,
            "option_type": "CE",
            "bid": 79,
            "ask": 81,
            "open_interest": 3000,
            "volume": 600,
            "oi_change": 200,
        },
    ]


def test_liquidity_is_applied_before_ranking():
    ranked = rank_liquid_option_candidates(_rows(), max_spread_pct=5.0)

    assert [row["instrument_key"] for row in ranked] == ["OPT-A", "OPT-C"]
    assert all(row["liquidity_eligible"] is True for row in ranked)
    assert all(row["authority"] == "OBSERVATIONAL_ONLY" for row in ranked)


def test_wide_spread_is_ineligible_even_with_high_oi_and_volume():
    result = assess_option_liquidity(_rows()[1], max_spread_pct=5.0)

    assert result.eligible is False
    assert "SPREAD_TOO_WIDE" in result.reason_codes


def test_normalization_is_bounded_and_deterministic():
    rows = normalize_option_features(_rows())

    for row in rows:
        assert 0.0 <= row["open_interest_normalized"] <= 1.0
        assert 0.0 <= row["volume_normalized"] <= 1.0
        assert 0.0 <= row["oi_change_normalized"] <= 1.0


def test_chain_aggregation_deduplicates_contracts():
    rows = _rows()
    rows.append({**rows[0], "volume": 1200})

    aggregate = aggregate_option_chain_without_double_counting(rows)

    assert aggregate["contract_count"] == 3.0
    assert aggregate["total_volume"] == 1200 + 1500 + 600
    assert aggregate["total_open_interest"] == 5000 + 8000 + 3000
