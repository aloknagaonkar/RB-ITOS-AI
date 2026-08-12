from red_bar_lab.intelligence.candidate_inspection import inspect_candidate


def _row(rank, score, spread=15, liquidity=20, volume=15, oi=10,
         vwap=10, ema=10, momentum=10):
    return {
        "Rank": rank,
        "Option": f"NIFTY-TEST-{rank}",
        "Score": score,
        "Spread Score": spread,
        "Liquidity": liquidity,
        "Volume Score": volume,
        "OI Score": oi,
        "VWAP Score": vwap,
        "EMA Score": ema,
        "Momentum": momentum,
        "Delta": -0.5,
        "Gamma": 0.002,
        "IV": 15.0,
    }


def test_rank_one_is_execution_candidate():
    best = _row(1, 95.0)
    result = inspect_candidate(best, best)
    assert result.execution_candidate is True
    assert result.rank == 1
    assert result.health_score >= 85
    assert result.health_band == "EXCELLENT"
    assert any(
        "only automatic paper execution candidate" in line
        for line in result.comparison_to_best
    )


def test_lower_rank_is_inspection_only_and_compared_to_best():
    best = _row(1, 90.0, liquidity=20, volume=15)
    second = _row(2, 83.0, liquidity=15, volume=10)
    result = inspect_candidate(second, best)
    assert result.execution_candidate is False
    assert any(
        "trails Rank #1" in line
        for line in result.comparison_to_best
    )
    assert any(
        "Lower Liquidity" in line
        for line in result.comparison_to_best
    )
    assert any(
        "does not alter execution" in line
        for line in result.comparison_to_best
    )


def test_score_breakdown_contains_current_execution_components():
    best = _row(1, 88.0)
    result = inspect_candidate(best, best)
    labels = {
        row["Evidence"] for row in result.score_breakdown
    }
    assert labels == {
        "Spread",
        "Liquidity",
        "Volume",
        "Open Interest",
        "VWAP",
        "EMA9 / EMA21",
        "Momentum",
    }
