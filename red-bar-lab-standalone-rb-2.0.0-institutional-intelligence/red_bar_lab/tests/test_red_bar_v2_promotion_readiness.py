from red_bar_lab.services.red_bar_v2_promotion_readiness import (
    PromotionEvidence,
    PromotionStage,
    PromotionThresholds,
    evaluate_promotion_readiness,
)


def _shadow_ready_evidence(**overrides):
    values = {
        "unit_tests_passed": 76,
        "unit_tests_failed": 0,
        "replay_sessions": 5,
        "replay_candidates": 10,
        "replay_errors": 0,
        "parity_comparisons": 10,
        "parity_mismatches": 0,
        "duplicate_entries": 0,
        "unresolved_lifecycle_conflicts": 0,
        "feature_flag_default_off": True,
        "legacy_exit_path_unchanged": True,
    }
    values.update(overrides)
    return PromotionEvidence(**values)


def _paper_ready_evidence(**overrides):
    values = {
        **_shadow_ready_evidence().__dict__,
        "shadow_sessions": 3,
        "shadow_decisions": 20,
        "shadow_errors": 0,
        "storage_audit_available": True,
        "rollback_plan_available": True,
        "operator_approval": True,
        "operator_name": "Test Operator",
        "evidence_reference": "phase-11-test",
    }
    values.update(overrides)
    return PromotionEvidence(**values)


def test_empty_evidence_fails_closed():
    report = evaluate_promotion_readiness(PromotionEvidence())
    assert report.stage == PromotionStage.NOT_READY
    assert report.shadow_ready is False
    assert report.paper_ready is False
    assert report.execution_enablement_allowed is False
    assert "UNIT_TEST_BASELINE" in report.blocking_codes
    assert "REPLAY_COVERAGE" in report.blocking_codes


def test_validated_baseline_can_reach_shadow_ready_only():
    report = evaluate_promotion_readiness(_shadow_ready_evidence())
    assert report.stage == PromotionStage.SHADOW_READY
    assert report.shadow_ready is True
    assert report.paper_ready is False
    assert report.execution_enablement_allowed is False
    assert "SHADOW_OBSERVATION" in report.blocking_codes
    assert "OPERATOR_APPROVAL" in report.blocking_codes


def test_named_operator_and_all_paper_gates_are_required():
    report = evaluate_promotion_readiness(
        _paper_ready_evidence(operator_name=None)
    )
    assert report.stage == PromotionStage.SHADOW_READY
    assert report.paper_ready is False
    assert "OPERATOR_APPROVAL" in report.blocking_codes


def test_all_gates_can_reach_controlled_paper_ready():
    report = evaluate_promotion_readiness(_paper_ready_evidence())
    assert report.stage == PromotionStage.PAPER_READY
    assert report.shadow_ready is True
    assert report.paper_ready is True
    assert report.execution_enablement_allowed is True
    assert report.blocking_codes == ()
    record = report.to_record()
    assert record["stage"] == "PAPER_READY"
    assert record["evidence_reference"] == "phase-11-test"
    assert all(isinstance(item["required_for"], str) for item in record["gates"])


def test_any_parity_mismatch_blocks_even_shadow_promotion():
    report = evaluate_promotion_readiness(
        _paper_ready_evidence(parity_mismatches=1)
    )
    assert report.stage == PromotionStage.NOT_READY
    assert report.shadow_ready is False
    assert report.execution_enablement_allowed is False
    assert "PARITY_BASELINE" in report.blocking_codes


def test_duplicate_entry_or_lifecycle_conflict_blocks_promotion():
    duplicate = evaluate_promotion_readiness(
        _paper_ready_evidence(duplicate_entries=1)
    )
    conflict = evaluate_promotion_readiness(
        _paper_ready_evidence(unresolved_lifecycle_conflicts=1)
    )
    assert duplicate.stage == PromotionStage.NOT_READY
    assert "DUPLICATE_ENTRY_SAFETY" in duplicate.blocking_codes
    assert conflict.stage == PromotionStage.NOT_READY
    assert "LIFECYCLE_CONFLICT_SAFETY" in conflict.blocking_codes


def test_feature_flag_and_legacy_exit_guards_are_mandatory():
    flag = evaluate_promotion_readiness(
        _paper_ready_evidence(feature_flag_default_off=False)
    )
    exit_path = evaluate_promotion_readiness(
        _paper_ready_evidence(legacy_exit_path_unchanged=False)
    )
    assert "FEATURE_FLAG_FAIL_CLOSED" in flag.blocking_codes
    assert "LEGACY_EXIT_PRESERVED" in exit_path.blocking_codes
    assert flag.execution_enablement_allowed is False
    assert exit_path.execution_enablement_allowed is False


def test_thresholds_are_configurable_without_weakening_fail_closed_logic():
    thresholds = PromotionThresholds(
        minimum_unit_tests=100,
        minimum_replay_sessions=10,
        minimum_replay_candidates=50,
        minimum_shadow_sessions=5,
        minimum_shadow_decisions=100,
        minimum_parity_comparisons=25,
    )
    report = evaluate_promotion_readiness(
        _paper_ready_evidence(),
        thresholds=thresholds,
    )
    assert report.stage == PromotionStage.NOT_READY
    assert "UNIT_TEST_BASELINE" in report.blocking_codes
    assert "REPLAY_COVERAGE" in report.blocking_codes
    assert "PARITY_BASELINE" in report.blocking_codes
