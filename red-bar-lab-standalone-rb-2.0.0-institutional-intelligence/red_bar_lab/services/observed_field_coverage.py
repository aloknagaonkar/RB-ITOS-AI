from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any, Mapping

FIELD_COVERAGE_POLICY_VERSION = "observed-field-coverage-v1"

_STAGE_FIELDS = {
    "MARKET": {
        "mandatory": (
            "signal_id",
            "instrument_key",
            "trading_date",
            "entry_timestamp",
            "session_open",
            "minutes_from_open",
            "price_from_open_points",
            "session_high_so_far",
            "session_low_so_far",
            "session_range_so_far",
            "session_range_position",
            "trend_5m",
        ),
        "optional": (
            "previous_close",
            "previous_high",
            "previous_low",
            "gap_points",
            "gap_pct",
            "price_from_open_pct",
            "distance_to_previous_high",
            "distance_to_previous_low",
            "opening_range_15_high",
            "opening_range_15_low",
            "opening_range_15_position",
            "atr14_5m",
            "ema9_5m",
            "ema21_5m",
            "realized_volatility_30m_pct",
        ),
    },
    "VOLUME": {
        "mandatory": (
            "signal_id",
            "instrument_key",
            "trading_date",
            "entry_timestamp",
            "volume_current_1m",
            "volume_avg_20m",
            "volume_trend_5m",
            "price_volume_state",
            "structure_state",
        ),
        "optional": (
            "relative_volume_20m",
            "compression_ratio_20m",
            "breakout_strength",
            "range_width_20m",
            "higher_high_count_20m",
            "lower_low_count_20m",
            "bullish_structure_score",
            "bearish_structure_score",
        ),
    },
    "OPTIONS": {
        "mandatory": (
            "signal_id",
            "instrument_key",
            "trading_date",
            "entry_timestamp",
            "option_expiry",
            "option_snapshot_timestamp",
            "option_snapshot_delay_seconds",
            "entry_aligned",
            "option_spot_price",
            "atm_strike",
            "total_call_oi",
            "total_put_oi",
            "pcr_oi",
        ),
        "optional": (
            "total_call_oi_change",
            "total_put_oi_change",
            "pcr_oi_change",
            "call_wall_strike",
            "put_wall_strike",
            "max_pain_strike",
            "atm_call_iv",
            "atm_put_iv",
            "atm_call_delta",
            "atm_put_delta",
            "atm_call_gamma",
            "atm_put_gamma",
            "atm_call_theta",
            "atm_put_theta",
            "atm_call_vega",
            "atm_put_vega",
            "chain_artifact_path",
        ),
    },
}


@dataclass(frozen=True)
class FieldCoverageResult:
    stage: str
    status: str
    mandatory_present: int
    mandatory_expected: int
    optional_present: int
    optional_expected: int
    mandatory_coverage_pct: float
    optional_coverage_pct: float
    missing_mandatory_fields: tuple[str, ...]
    missing_optional_fields: tuple[str, ...]
    reason_code: str | None
    policy_version: str = FIELD_COVERAGE_POLICY_VERSION

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _present(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, float) and math.isnan(value):
        return False
    return True


def assess_observed_field_coverage(
    stage: str,
    row: Mapping[str, Any] | None,
) -> FieldCoverageResult:
    normalized_stage = str(stage or "").strip().upper()
    if normalized_stage not in _STAGE_FIELDS:
        raise ValueError(f"unsupported field coverage stage: {normalized_stage}")

    payload = dict(row or {})
    schema = _STAGE_FIELDS[normalized_stage]
    mandatory = tuple(schema["mandatory"])
    optional = tuple(schema["optional"])
    missing_mandatory = tuple(
        field for field in mandatory if not _present(payload.get(field))
    )
    missing_optional = tuple(
        field for field in optional if not _present(payload.get(field))
    )
    mandatory_present = len(mandatory) - len(missing_mandatory)
    optional_present = len(optional) - len(missing_optional)
    status = "READY" if not missing_mandatory else "MISSING"
    return FieldCoverageResult(
        stage=normalized_stage,
        status=status,
        mandatory_present=mandatory_present,
        mandatory_expected=len(mandatory),
        optional_present=optional_present,
        optional_expected=len(optional),
        mandatory_coverage_pct=(
            mandatory_present / len(mandatory) * 100.0 if mandatory else 100.0
        ),
        optional_coverage_pct=(
            optional_present / len(optional) * 100.0 if optional else 100.0
        ),
        missing_mandatory_fields=missing_mandatory,
        missing_optional_fields=missing_optional,
        reason_code=(
            None
            if not missing_mandatory
            else f"{normalized_stage}_MANDATORY_FIELDS_MISSING"
        ),
    )


__all__ = [
    "FIELD_COVERAGE_POLICY_VERSION",
    "FieldCoverageResult",
    "assess_observed_field_coverage",
]
