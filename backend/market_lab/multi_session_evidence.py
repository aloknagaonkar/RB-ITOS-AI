"""Read-only configuration discovery for future compatible evidence history."""

from dataclasses import dataclass

from .domain import (
    PCRChangeBucketConfig,
    PCRConfig,
    PatternEvidenceConfig,
    PatternEvidenceReport,
    SessionAnalysisObservation,
)
from .pattern_evidence import build_pattern_evidence
from .pattern_statistics import calculate_pattern_statistics
from .storage import Configuration, session_analysis_results


@dataclass(frozen=True)
class CompatibleConfigDiscovery:
    requested_config_id: int
    requested_config: PCRConfig
    evidence_compatibility_fingerprint: str
    compatible_configs: tuple[tuple[int, PCRConfig], ...]

    @property
    def compatible_config_ids(self) -> tuple[int, ...]:
        return tuple(config_id for config_id, _ in self.compatible_configs)

    @property
    def configuration_versions(self) -> tuple[int, ...]:
        return self.compatible_config_ids

    @property
    def expiries(self) -> tuple:
        return tuple(sorted({config.expiry for _, config in self.compatible_configs}))


@dataclass(frozen=True)
class CompatibleEvidenceHistoryInput:
    discovery: CompatibleConfigDiscovery
    calculation_fingerprints: tuple[str, ...]
    observations: tuple[SessionAnalysisObservation, ...]

    @property
    def requested_config_id(self) -> int:
        return self.discovery.requested_config_id

    @property
    def evidence_compatibility_fingerprint(self) -> str:
        return self.discovery.evidence_compatibility_fingerprint

    @property
    def compatible_config_ids(self) -> tuple[int, ...]:
        return self.discovery.compatible_config_ids

    @property
    def configuration_versions(self) -> tuple[int, ...]:
        return self.discovery.configuration_versions

    @property
    def expiries(self) -> tuple:
        return self.discovery.expiries


def discover_compatible_configs(session, requested_config_id: int) -> CompatibleConfigDiscovery:
    requested_row = session.get(Configuration, requested_config_id)
    if requested_row is None:
        raise ValueError("Configuration not found")
    requested = PCRConfig.model_validate(requested_row.payload)
    compatibility = requested.evidence_compatibility_fingerprint()
    candidates: list[tuple[int, PCRConfig]] = []
    for row in session.query(Configuration).order_by(Configuration.id):
        config = PCRConfig.model_validate(row.payload)
        if config.evidence_compatibility_fingerprint() == compatibility:
            candidates.append((row.id, config))
    return CompatibleConfigDiscovery(requested_config_id, requested, compatibility, tuple(candidates))


def collect_compatible_session_analysis(session, requested_config_id: int) -> CompatibleEvidenceHistoryInput:
    """Collect finalized per-config session analysis without cross-config forward matching."""
    discovery = discover_compatible_configs(session, requested_config_id)
    associated: list[tuple[int, SessionAnalysisObservation]] = []
    for config_id, _ in discovery.compatible_configs:
        associated.extend(
            (config_id, SessionAnalysisObservation.model_validate(value))
            for value in session_analysis_results(session, config_id)
        )
    associated.sort(
        key=lambda value: (
            value[1].received_at,
            value[1].configuration_version,
            value[0],
            value[1].observation_id,
        )
    )
    observations = tuple(observation for _, observation in associated)
    return CompatibleEvidenceHistoryInput(
        discovery=discovery,
        calculation_fingerprints=tuple(
            sorted({observation.calculation_fingerprint for observation in observations})
        ),
        observations=observations,
    )


def build_compatible_pattern_evidence(
    history: CompatibleEvidenceHistoryInput,
    statistics_config: PCRChangeBucketConfig = PCRChangeBucketConfig(),
    evidence_config: PatternEvidenceConfig = PatternEvidenceConfig(),
) -> PatternEvidenceReport:
    """Aggregate individual compatible observations once, then build existing statistics and evidence."""
    requested = history.discovery.requested_config
    canonical_calculation = requested.trend_fingerprint("full")
    if not history.observations:
        return PatternEvidenceReport(
            calculation_fingerprint=canonical_calculation,
            evidence_compatibility_fingerprint=history.evidence_compatibility_fingerprint,
            calculation_fingerprints=history.calculation_fingerprints,
            configuration_versions=history.configuration_versions,
            expiries=history.expiries,
            configuration_version=history.requested_config_id,
            underlying=requested.underlying,
            expiry=requested.expiry,
            observation_count=0,
            distinct_session_count=0,
            rows=[],
        )
    compatible_observations = tuple(
        observation.model_copy(
            update={"calculation_fingerprint": history.evidence_compatibility_fingerprint}
        )
        for observation in history.observations
    )
    statistics = calculate_pattern_statistics(compatible_observations, statistics_config)
    evidence = build_pattern_evidence(
        statistics[0], evidence_config, history.evidence_compatibility_fingerprint
    )
    return evidence.model_copy(
        update={
            "calculation_fingerprint": canonical_calculation,
            "calculation_fingerprints": history.calculation_fingerprints,
            "configuration_versions": history.configuration_versions,
            "expiries": history.expiries,
            "configuration_version": history.requested_config_id,
            "underlying": requested.underlying,
            "expiry": requested.expiry,
        }
    )
