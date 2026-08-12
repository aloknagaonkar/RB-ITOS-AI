from red_bar_lab.services.committee_diagnostics import build_committee_gate_trace


def base_row(**overrides):
    row = {
        "candidate_rank": 1,
        "candidate_symbol": "NIFTY 24250 PE",
        "decision": "BUY PE",
        "eligible": 1,
        "primary_confidence_pct": 88.9,
        "execution_probability_pct": 88.9,
        "expectancy_pct": 19.32,
        "expected_value_pct": 0.0,
        "expected_win_pct": 25.0,
        "expected_loss_pct": 15.0,
        "expectancy_confidence_pct": 28.0,
        "historical_score": 50.0,
        "kelly_fraction_pct": 25.0,
        "shadow_decision": "BUY PE",
        "reason": (
            "EXECUTION_COMMITTEE_APPROVED | NO_HARD_PERFORMANCE_BLOCKERS | "
            "PAYOFF_METRICS_INFORMATIONAL_ONLY"
        ),
    }
    row.update(overrides)
    return row


def test_approved_candidate_has_no_authoritative_blockers():
    trace = build_committee_gate_trace(base_row())
    assert trace["calculated_eligible"] is True
    assert trace["parity"] is True
    assert trace["authoritative_blockers"] == []


def test_probability_below_70_is_authoritative_blocker():
    trace = build_committee_gate_trace(base_row(
        eligible=0,
        decision="WAIT",
        execution_probability_pct=69.5,
        reason="EXECUTION_PROBABILITY=69.50<MIN=70.00 | PERFORMANCE_DETAIL[OK]",
    ))
    assert trace["calculated_eligible"] is False
    assert "Execution probability" in trace["authoritative_blockers"]
    assert trace["parity"] is True


def test_non_positive_expectancy_is_informational_only():
    trace = build_committee_gate_trace(base_row(
        eligible=1,
        decision="BUY PE",
        expectancy_pct=-0.1,
        expected_value_pct=0.0,
    ))
    assert trace["calculated_eligible"] is True
    assert trace["authoritative_blockers"] == []
    statuses = {row["gate"]: row["status"] for row in trace["gates"]}
    assert statuses["Expected Value / Expectancy / Expected Win / Expected Loss"] == "INFO"


def test_shadow_and_low_expectancy_confidence_do_not_block():
    trace = build_committee_gate_trace(base_row(
        shadow_decision="BUY CE",
        expectancy_confidence_pct=5.0,
        historical_score=0.0,
        kelly_fraction_pct=0.0,
    ))
    assert trace["calculated_eligible"] is True
    statuses = {row["gate"]: row["status"] for row in trace["gates"]}
    assert statuses["Shadow Intelligence"] == "INFO"
    assert statuses["Expectancy confidence / Historical / Half-Kelly"] == "INFO"


def test_ema_terminal_and_performance_blocks_are_detected_from_persisted_reason():
    trace = build_committee_gate_trace(base_row(
        eligible=0,
        decision="WAIT",
        reason=(
            "PERFORMANCE_HARD_BLOCK[INSUFFICIENT_QUALITY] | "
            "OPPORTUNITY_TERMINAL[BEARISH_EMA10_LOST] | "
            "PERFORMANCE_DETAIL[INSUFFICIENT_QUALITY]"
        ),
    ))
    assert "Performance hard blocker" in trace["authoritative_blockers"]
    assert "Opportunity terminal validity" in trace["authoritative_blockers"]
