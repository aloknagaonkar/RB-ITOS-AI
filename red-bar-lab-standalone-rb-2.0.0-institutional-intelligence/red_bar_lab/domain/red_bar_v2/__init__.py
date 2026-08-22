"""Canonical, immutable and runtime-independent Red Bar V2 contracts."""

from .enums import (
    AdmissionOutcome,
    BundleLifecycleStatus,
    ContextStatus,
    Direction,
    EntryType,
    OptionSide,
    RedBarV2Section1Outcome,
    RedBarV2State,
    TrendStrength,
)
from .exceptions import (
    BundleIdentityError,
    DomainValidationError,
    RedBarV2DomainError,
    UnsupportedSchemaVersionError,
)
from .identity import (
    build_red_bar_v2_bundle_id,
    build_red_bar_v2_idempotency_key,
    build_red_bar_v2_signal_id,
)
from .models import (
    FuturesVwapEvidence,
    MarketTimestampEvidence,
    MidpointEvidence,
    RedBarV2Decision,
    RedBarV2InputReadiness,
    RedBarV2Reference,
    RedBarV2SignalBundle,
    RsiEvidence,
)
from .serialization import (
    SUPPORTED_SCHEMA_VERSIONS,
    red_bar_v2_bundle_from_dict,
    red_bar_v2_bundle_to_dict,
    red_bar_v2_resolution_to_dict,
)

__all__ = [
    "AdmissionOutcome",
    "BundleIdentityError",
    "BundleLifecycleStatus",
    "ContextStatus",
    "Direction",
    "DomainValidationError",
    "EntryType",
    "FuturesVwapEvidence",
    "MarketTimestampEvidence",
    "MidpointEvidence",
    "OptionSide",
    "RedBarV2Decision",
    "RedBarV2DomainError",
    "RedBarV2InputReadiness",
    "RedBarV2Reference",
    "RedBarV2Section1Outcome",
    "RedBarV2SignalBundle",
    "RedBarV2State",
    "RsiEvidence",
    "SUPPORTED_SCHEMA_VERSIONS",
    "TrendStrength",
    "UnsupportedSchemaVersionError",
    "build_red_bar_v2_bundle_id",
    "build_red_bar_v2_idempotency_key",
    "build_red_bar_v2_signal_id",
    "red_bar_v2_bundle_from_dict",
    "red_bar_v2_bundle_to_dict",
    "red_bar_v2_resolution_to_dict",
]
