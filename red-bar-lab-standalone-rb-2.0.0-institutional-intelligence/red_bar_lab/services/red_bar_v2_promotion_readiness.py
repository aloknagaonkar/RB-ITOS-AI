from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Mapping


class PromotionStage(str, Enum):
    NOT_READY = "NOT_READY"
    SHADOW_READY = "SHADOW_READY"
    PAPER_READY = "PAPER_READY"


@dataclass(frozen=True)
class PromotionThresholds:
    minimum_unit_tests: int = 76
    minimum_replay_sessions: int = 5
    minimum_replay_candidates: int = 10
    minimum_shadow_sessions: int = 3
    minimum_shadow_decisions: int = 20
    minimum_parity_comparisons: int = 10
    maximum_parity_mismatches: int = 0
    maximum_duplicate_entries: int = 0
    maximum_unresolved_lifecycle_conflicts: int = 0


@dataclass(frozen=True)
class PromotionEvidence:
    unit_tests_passed: int = 0
    unit_tests_failed: int = 0
    replay_sessions: int = 0
    replay_candidates: int = 0
    replay_errors: int = 0
    shadow_sessions: int = 0
    shadow_decisions: int = 0
    shadow_errors: int = 0
    parity_comparisons: int = 0
    parity_mismatches: int = 0
    duplicate_entries: int = 0
    unresolved_lifecycle_conflicts: int = 0
    storage_audit_available: bool = False
    rollback_plan_available: bool = False
    feature_flag_default_off: bool = True
    legacy_exit_path_unchanged: bool = True
    operator_approval: bool = False
    operator_name: str | None = None
    evidence_reference: str | None = None


@dataclass(frozen=True)
class PromotionGate:
    code: str
    passed: bool
    required_for: PromotionStage
    observed: Any
    required: Any
    reason: str


@dataclass(frozen=True)
class PromotionReadinessReport:
    stage: PromotionStage
    strategy_version: str
    gates: tuple[PromotionGate, ...]
    blocking_codes: tuple[str, ...]
    shadow_ready: bool
    paper_ready: bool
    execution_enablement_allowed: bool
    evidence_reference: str | None

    def to_record(self) -> dict[str, Any]:
        row = asdict(self)
        row["stage"] = self.stage.value
        for gate in row["gates"]:
            gate["required_for"] = gate["required_for"].value
        return row


def _gate(
    code: str,
    passed: bool,
    required_for: PromotionStage,
    observed: Any,
    required: Any,
    reason: str,
) -> PromotionGate:
    return PromotionGate(
        code=code,
        passed=bool(passed),
        required_for=required_for,
        observed=observed,
        required=required,
        reason=reason,
    )


def evaluate_promotion_readiness(
    evidence: PromotionEvidence | Mapping[str, Any],
    *,
    thresholds: PromotionThresholds | None = None,
    strategy_version: str = "RED_BAR_V2",
) -> PromotionReadinessReport:
    """Evaluate fail-closed Red Bar V2 rollout readiness.

    This function only evaluates evidence. It never changes feature flags,
    starts execution, writes orders, or promotes a strategy automatically.
    PAPER_READY means that an operator may separately approve a controlled
    paper rollout; it is not live-trading authorization.
    """
    if not isinstance(evidence, PromotionEvidence):
        evidence = PromotionEvidence(**dict(evidence))
    limits = thresholds or PromotionThresholds()

    gates = (
        _gate(
            "UNIT_TEST_BASELINE",
            evidence.unit_tests_failed == 0
            and evidence.unit_tests_passed >= limits.minimum_unit_tests,
            PromotionStage.SHADOW_READY,
            {
                "passed": evidence.unit_tests_passed,
                "failed": evidence.unit_tests_failed,
            },
            {
                "minimum_passed": limits.minimum_unit_tests,
                "maximum_failed": 0,
            },
            "The validated unit and integration baseline must pass without failures.",
        ),
        _gate(
            "REPLAY_COVERAGE",
            evidence.replay_sessions >= limits.minimum_replay_sessions
            and evidence.replay_candidates >= limits.minimum_replay_candidates
            and evidence.replay_errors == 0,
            PromotionStage.SHADOW_READY,
            {
                "sessions": evidence.replay_sessions,
                "candidates": evidence.replay_candidates,
                "errors": evidence.replay_errors,
            },
            {
                "minimum_sessions": limits.minimum_replay_sessions,
                "minimum_candidates": limits.minimum_replay_candidates,
                "maximum_errors": 0,
            },
            "Historical replay must provide sufficient error-free strategy evidence.",
        ),
        _gate(
            "PARITY_BASELINE",
            evidence.parity_comparisons >= limits.minimum_parity_comparisons
            and evidence.parity_mismatches <= limits.maximum_parity_mismatches,
            PromotionStage.SHADOW_READY,
            {
                "comparisons": evidence.parity_comparisons,
                "mismatches": evidence.parity_mismatches,
            },
            {
                "minimum_comparisons": limits.minimum_parity_comparisons,
                "maximum_mismatches": limits.maximum_parity_mismatches,
            },
            "Legacy and independent architecture outputs must remain semantically identical.",
        ),
        _gate(
            "DUPLICATE_ENTRY_SAFETY",
            evidence.duplicate_entries <= limits.maximum_duplicate_entries,
            PromotionStage.SHADOW_READY,
            evidence.duplicate_entries,
            limits.maximum_duplicate_entries,
            "No duplicate candidate may produce more than one entry.",
        ),
        _gate(
            "LIFECYCLE_CONFLICT_SAFETY",
            evidence.unresolved_lifecycle_conflicts
            <= limits.maximum_unresolved_lifecycle_conflicts,
            PromotionStage.SHADOW_READY,
            evidence.unresolved_lifecycle_conflicts,
            limits.maximum_unresolved_lifecycle_conflicts,
            "All active, pending, and closed lifecycle conflicts must be resolved.",
        ),
        _gate(
            "FEATURE_FLAG_FAIL_CLOSED",
            evidence.feature_flag_default_off,
            PromotionStage.SHADOW_READY,
            evidence.feature_flag_default_off,
            True,
            "Red Bar V2 must remain disabled by default.",
        ),
        _gate(
            "LEGACY_EXIT_PRESERVED",
            evidence.legacy_exit_path_unchanged,
            PromotionStage.SHADOW_READY,
            evidence.legacy_exit_path_unchanged,
            True,
            "The stable legacy exit engine must remain the sole exit authority.",
        ),
        _gate(
            "SHADOW_OBSERVATION",
            evidence.shadow_sessions >= limits.minimum_shadow_sessions
            and evidence.shadow_decisions >= limits.minimum_shadow_decisions
            and evidence.shadow_errors == 0,
            PromotionStage.PAPER_READY,
            {
                "sessions": evidence.shadow_sessions,
                "decisions": evidence.shadow_decisions,
                "errors": evidence.shadow_errors,
            },
            {
                "minimum_sessions": limits.minimum_shadow_sessions,
                "minimum_decisions": limits.minimum_shadow_decisions,
                "maximum_errors": 0,
            },
            "A controlled shadow observation window must complete without runtime errors.",
        ),
        _gate(
            "STORAGE_AUDIT_AVAILABLE",
            evidence.storage_audit_available,
            PromotionStage.PAPER_READY,
            evidence.storage_audit_available,
            True,
            "Candidate, context, state, and parity evidence must remain auditable.",
        ),
        _gate(
            "ROLLBACK_PLAN_AVAILABLE",
            evidence.rollback_plan_available,
            PromotionStage.PAPER_READY,
            evidence.rollback_plan_available,
            True,
            "A tested feature-flag rollback path must exist before paper promotion.",
        ),
        _gate(
            "OPERATOR_APPROVAL",
            evidence.operator_approval and bool((evidence.operator_name or "").strip()),
            PromotionStage.PAPER_READY,
            {
                "approved": evidence.operator_approval,
                "operator_name": evidence.operator_name,
            },
            {
                "approved": True,
                "operator_name": "required",
            },
            "Paper promotion requires explicit named operator approval.",
        ),
    )

    shadow_gates = tuple(
        gate for gate in gates if gate.required_for == PromotionStage.SHADOW_READY
    )
    paper_gates = tuple(
        gate for gate in gates if gate.required_for == PromotionStage.PAPER_READY
    )
    shadow_ready = all(gate.passed for gate in shadow_gates)
    paper_ready = shadow_ready and all(gate.passed for gate in paper_gates)

    if paper_ready:
        stage = PromotionStage.PAPER_READY
    elif shadow_ready:
        stage = PromotionStage.SHADOW_READY
    else:
        stage = PromotionStage.NOT_READY

    blocking_codes = tuple(gate.code for gate in gates if not gate.passed)
    return PromotionReadinessReport(
        stage=stage,
        strategy_version=strategy_version,
        gates=gates,
        blocking_codes=blocking_codes,
        shadow_ready=shadow_ready,
        paper_ready=paper_ready,
        execution_enablement_allowed=paper_ready,
        evidence_reference=evidence.evidence_reference,
    )
