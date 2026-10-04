from scripts.analyze_hilega_wma_gap_loss_attribution import (
    absolute_gap_bucket,
    enrich,
    expansion_bucket,
    grouped_metrics,
    latency_bucket,
    wma_bucket,
)


def test_fixed_buckets_are_boundary_stable():
    assert latency_bucket(2) == "00_0_TO_2_MIN"
    assert latency_bucket(5) == "01_3_TO_5_MIN"
    assert latency_bucket(10) == "02_6_TO_10_MIN"
    assert latency_bucket(11) == "03_OVER_10_MIN"
    assert wma_bucket(0.75) == "00_0_75_TO_0_99"
    assert wma_bucket(1.0) == "01_GE_1_00"
    assert expansion_bucket(0.25) == "00_WEAK_LE_0_25"
    assert expansion_bucket(0.75) == "01_MEDIUM_0_25_TO_0_75"
    assert expansion_bucket(0.751) == "02_STRONG_GT_0_75"
    assert absolute_gap_bucket(2.99) == "00_NARROW_LT_3"
    assert absolute_gap_bucket(3) == "01_MODERATE_3_TO_6"
    assert absolute_gap_bucket(6) == "02_WIDE_GE_6"


def sample_trade(decision="ENTRY", candidate="8"):
    return {
        "session_date": "2026-10-01",
        "evidence_block": "OBSERVED_FORWARD",
        "trade_id": "T1",
        "direction": "BULLISH",
        "route": "TEST",
        "entry_timestamp": "2026-10-01T10:00:00+05:30",
        "candidate_decision": decision,
        "candidate_entry_timestamp": (
            "2026-10-01T10:04:00+05:30" if decision == "ENTRY" else ""
        ),
        "canonical_points": "10",
        "candidate_points": candidate if decision == "ENTRY" else "",
        "mfe_points": "80",
        "mae_points": "-5",
    }


def sample_attempt():
    return {
        "trade_id": "T1",
        "confirmation_timestamp": "2026-10-01T10:04:00+05:30",
        "passed": "True",
        "confirmation_wma_strength": "1.2",
        "confirmation_directional_gap": "4.0",
        "directional_gap_delta": "0.5",
    }


def test_enrich_attributes_accepted_trade_without_future_information():
    accepted, denied = enrich(
        [sample_trade()], [sample_attempt()], {"BULLISH": 70, "BEARISH": 70}
    )
    assert not denied
    assert len(accepted) == 1
    row = accepted[0]
    assert row["confirmation_latency_minutes"] == 4
    assert row["latency_bucket"] == "01_3_TO_5_MIN"
    assert row["wma_tier"] == "01_GE_1_00"
    assert row["gap_expansion_tier"] == "01_MEDIUM_0_25_TO_0_75"
    assert row["absolute_gap_tier"] == "01_MODERATE_3_TO_6"
    assert row["adverse_entry_delay_cost_points"] == 2
    assert row["plus20_retained"] is True
    assert row["top_decile_retained"] is True


def test_denied_trade_records_saved_loss_and_destroyed_move():
    trade = sample_trade("NO_ENTRY", "")
    trade["canonical_points"] = "-12"
    accepted, denied = enrich(
        [trade], [sample_attempt()], {"BULLISH": 70, "BEARISH": 70}
    )
    assert not accepted
    assert denied[0]["saved_loss_points"] == 12
    assert denied[0]["plus20_destroyed"] is True
    assert denied[0]["top_decile_destroyed"] is True


def test_grouped_metrics_keeps_directions_separate():
    accepted, _ = enrich(
        [sample_trade()], [sample_attempt()], {"BULLISH": 70, "BEARISH": 70}
    )
    result = grouped_metrics(accepted, ("direction", "latency_bucket"))
    assert result[0]["direction"] == "BULLISH"
    assert result[0]["entries"] == 1
    assert result[0]["candidate_points"] == 8
    assert result[0]["profit_factor"] is None
