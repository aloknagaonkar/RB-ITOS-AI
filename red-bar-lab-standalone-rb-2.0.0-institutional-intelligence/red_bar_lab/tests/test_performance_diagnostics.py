from red_bar_lab.services.performance_diagnostics import build_performance_gate_trace


def test_soft_evidence_does_not_become_hard_block():
    row = {"eligible": 1, "decision": "BUY PE", "candidate_score": 80, "opportunity_score": 70, "selection_score": 69.28, "reason": "NO_HARD_PERFORMANCE_BLOCKERS | SOFT_EVIDENCE:OPPORTUNITY_EXTENSION=OPPORTUNITY_HEALTH=70.00<MIN=75.00; TSS=69.28<REFERENCE=70.00"}
    trace = build_performance_gate_trace(row)
    assert trace["blockers"] == []
    assert trace["duplicate"] is False


def test_duplicate_is_identified_as_operational_hard_block():
    row = {"eligible": 0, "decision": "SKIP", "reason": "NO_HARD_PERFORMANCE_BLOCKERS | SOFT_EVIDENCE:TSS=69.28<REFERENCE=70.00 | DUPLICATE_CANDIDATE"}
    trace = build_performance_gate_trace(row, {"duplicate": 1, "state": "ACTIVE"})
    assert trace["duplicate"] is True
    assert "Duplicate candidate" in trace["blockers"]


def test_spread_and_liquidity_are_real_performance_hard_blocks():
    row = {"eligible": 0, "decision": "SKIP", "reason": "HARD_BLOCK:SPREAD,LIQUIDITY | SOFT_EVIDENCE:ALL_REFERENCE_LEVELS_MET"}
    trace = build_performance_gate_trace(row)
    assert "Spread execution quality" in trace["blockers"]
    assert "Liquidity execution quality" in trace["blockers"]
