from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Callable, Mapping

import pandas as pd


COMPARISON_VERSION = "INDEPENDENT-STRATEGY-COMPARISON-V2"
STRATEGIES = ("red_bar",)
DRI_STAGE_WINDOW_SECONDS = 15 * 60


def _text(value: object) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _number(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first(record: Mapping[str, object], *names: str) -> object:
    for name in names:
        value = record.get(name)
        if value not in (None, ""):
            return value
    return None


def _timestamp_delta_seconds(left: object, right: object) -> float | None:
    if left in (None, "") or right in (None, ""):
        return None
    try:
        return (pd.Timestamp(right) - pd.Timestamp(left)).total_seconds()
    except (TypeError, ValueError):
        return None


def _different(left: object, right: object) -> bool:
    if left is None and right is None:
        return False
    if isinstance(left, float) or isinstance(right, float):
        if left is None or right is None:
            return True
        return abs(float(left) - float(right)) > 1e-6
    return left != right


def _is_early_stage(setup_type: object) -> bool:
    return "EARLY_1M" in str(setup_type or "").upper()


def canonical_strategy_record(
    strategy: str,
    record: Mapping[str, object] | None,
) -> dict[str, object]:
    """Normalize legacy and shadow records without changing strategy policy."""
    row = dict(record or {})
    if strategy == "red_bar":
        latest = dict(row.get("latest_attempt") or row)
        return {
            "available": bool(row) and row.get("status") != "INPUT_UNAVAILABLE",
            "status": _text(_first(row, "status", "state")),
            "signal_id": _text(_first(latest, "signal_id", "id")),
            "direction": _text(_first(latest, "direction")),
            "setup_type": _text(_first(latest, "level_type", "setup_type")),
            "timestamp": _text(
                _first(
                    latest,
                    "confirmation_timestamp",
                    "cross_timestamp",
                    "timestamp",
                )
            ),
            "trigger_level": _number(
                _first(latest, "trigger_level", "level_value", "underlying_entry")
            ),
            "invalidation_level": _number(_first(latest, "invalidation_level")),
            "fresh_until": _text(_first(latest, "fresh_until")),
        }
    if strategy == "directional_regime":
        bundle = dict(row.get("early_bundle_preview") or row)
        direction = _first(bundle, "direction") or row.get("early_direction")
        return {
            "available": bool(bundle),
            "status": _text(_first(row, "detection_status", "status")),
            "signal_id": _text(_first(bundle, "primary_signal_id", "signal_id")),
            "direction": _text(direction),
            "setup_type": _text(
                _first(bundle, "primary_setup_type", "setup_type")
            ),
            "timestamp": _text(_first(bundle, "detected_at", "timestamp")),
            "trigger_level": _number(_first(bundle, "trigger_level")),
            "invalidation_level": _number(
                _first(bundle, "invalidation_level")
            ),
            "fresh_until": _text(_first(bundle, "fresh_until")),
        }
    latest = dict(
        row.get("latest_historical_signal")
        or row.get("latest_signal")
        or row
    )
    return {
        "available": bool(latest),
        "status": _text(_first(row, "status", "state")),
        "signal_id": _text(_first(latest, "signal_id", "id")),
        "direction": _text(_first(latest, "direction")),
        "setup_type": _text(_first(latest, "level_name", "setup_type")),
        "timestamp": _text(
            _first(
                latest,
                "confirmation_timestamp",
                "detected_at",
                "timestamp",
            )
        ),
        "trigger_level": _number(
            _first(latest, "trigger_level", "level_value")
        ),
        "invalidation_level": _number(
            _first(latest, "invalidation_level")
        ),
        "fresh_until": _text(_first(latest, "fresh_until")),
    }


def _readiness_result(
    *,
    strategy: str,
    status: str,
    left: dict[str, object],
    right: dict[str, object],
) -> dict[str, object]:
    return {
        "strategy": strategy,
        "comparison_status": status,
        "comparison_class": "NOT_COMPARABLE",
        "match": None,
        "mismatch_fields": [],
        "identity_difference_fields": [],
        "timestamp_delta_seconds": None,
        "legacy": left,
        "shadow": right,
    }


def _compare_directional_regime(
    left: dict[str, object],
    right: dict[str, object],
) -> dict[str, object]:
    hard_fields = ("direction", "trigger_level", "invalidation_level")
    identity_fields = ("signal_id", "setup_type", "timestamp", "fresh_until")
    hard_mismatches = [
        field for field in hard_fields if _different(left.get(field), right.get(field))
    ]
    identity_differences = [
        field
        for field in identity_fields
        if _different(left.get(field), right.get(field))
    ]
    delta = _timestamp_delta_seconds(left.get("timestamp"), right.get("timestamp"))

    if hard_mismatches:
        return {
            "comparison_status": "TRUE_MISMATCH",
            "comparison_class": "GEOMETRY_OR_DIRECTION_MISMATCH",
            "match": False,
            "mismatch_fields": hard_mismatches,
            "identity_difference_fields": identity_differences,
            "timestamp_delta_seconds": delta,
        }

    if not identity_differences:
        return {
            "comparison_status": "EXACT_MATCH",
            "comparison_class": "EXACT_IDENTITY",
            "match": True,
            "mismatch_fields": [],
            "identity_difference_fields": [],
            "timestamp_delta_seconds": delta,
        }

    stage_difference = _is_early_stage(left.get("setup_type")) != _is_early_stage(
        right.get("setup_type")
    )
    within_stage_window = delta is not None and abs(delta) <= DRI_STAGE_WINDOW_SECONDS
    if stage_difference and within_stage_window:
        status = "EXPECTED_STAGE_DIFFERENCE"
        comparison_class = "LIFECYCLE_EQUIVALENT"
    else:
        status = "DIRECTIONAL_EQUIVALENT"
        comparison_class = "GEOMETRY_EQUIVALENT"
    return {
        "comparison_status": status,
        "comparison_class": comparison_class,
        "match": True,
        "mismatch_fields": [],
        "identity_difference_fields": identity_differences,
        "timestamp_delta_seconds": delta,
    }


def compare_strategy_records(
    strategy: str,
    legacy: Mapping[str, object] | None,
    shadow: Mapping[str, object] | None,
) -> dict[str, object]:
    left = canonical_strategy_record(strategy, legacy)
    right = canonical_strategy_record(strategy, shadow)
    if not left["available"]:
        return _readiness_result(
            strategy=strategy,
            status="LEGACY_NOT_READY",
            left=left,
            right=right,
        )
    if not right["available"]:
        return _readiness_result(
            strategy=strategy,
            status="SHADOW_NOT_READY",
            left=left,
            right=right,
        )

    if strategy == "directional_regime":
        result = _compare_directional_regime(left, right)
        return {
            "strategy": strategy,
            **result,
            "legacy": left,
            "shadow": right,
        }

    fields = (
        "signal_id",
        "direction",
        "setup_type",
        "timestamp",
        "trigger_level",
        "invalidation_level",
        "fresh_until",
    )
    mismatches = [
        field for field in fields if _different(left.get(field), right.get(field))
    ]
    return {
        "strategy": strategy,
        "comparison_status": "MATCH" if not mismatches else "MISMATCH",
        "comparison_class": "EXACT_IDENTITY" if not mismatches else "TRUE_MISMATCH",
        "match": not mismatches,
        "mismatch_fields": mismatches,
        "identity_difference_fields": [],
        "timestamp_delta_seconds": _timestamp_delta_seconds(
            left.get("timestamp"), right.get("timestamp")
        ),
        "legacy": left,
        "shadow": right,
    }


@dataclass
class StrategyShadowComparisonService:
    runs_root: Path
    instrument_key: str
    legacy_snapshot_loader: Callable[[], Mapping[str, object]]

    def __post_init__(self) -> None:
        safe = "".join(
            character if character.isalnum() or character in {"-", "_"} else "_"
            for character in self.instrument_key
        ).strip("_") or "UNKNOWN"
        root = Path(self.runs_root) / "independent_strategy_comparison_v1"
        self.journal_path = root / f"{safe}.jsonl"
        self.status_path = root / f"{safe}.status.json"

    def compare_and_record(
        self,
        shadow_record: Mapping[str, object],
    ) -> dict[str, object]:
        legacy = dict(self.legacy_snapshot_loader() or {})
        comparisons = [
            compare_strategy_records(
                strategy,
                legacy.get(strategy)
                if isinstance(legacy.get(strategy), Mapping)
                else None,
                shadow_record.get(strategy)
                if isinstance(shadow_record.get(strategy), Mapping)
                else None,
            )
            for strategy in STRATEGIES
        ]
        comparable = [item for item in comparisons if item["match"] is not None]
        mismatches = [item for item in comparable if item["match"] is False]
        exact = [
            item
            for item in comparable
            if item["comparison_status"] in {"MATCH", "EXACT_MATCH"}
        ]
        equivalent = [
            item
            for item in comparable
            if item["comparison_status"]
            in {"EXPECTED_STAGE_DIFFERENCE", "DIRECTIONAL_EQUIVALENT"}
        ]
        payload = {
            "comparison_version": COMPARISON_VERSION,
            "scan_identity": shadow_record.get("scan_identity"),
            "instrument_key": self.instrument_key,
            "evaluated_at": shadow_record.get("evaluated_at"),
            "comparison_status": (
                "MISMATCH"
                if mismatches
                else "MATCH"
                if comparable
                else "WAITING_FOR_LEGACY"
            ),
            "comparable_strategy_count": len(comparable),
            "matching_strategy_count": len(comparable) - len(mismatches),
            "exact_match_strategy_count": len(exact),
            "equivalent_strategy_count": len(equivalent),
            "mismatch_strategy_count": len(mismatches),
            "comparisons": comparisons,
            "diagnostic_only": True,
            "production_persistence": False,
            "execution_allowed": False,
        }
        self.status_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.status_path.with_suffix(self.status_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, default=str),
            encoding="utf-8",
        )
        temporary.replace(self.status_path)
        with self.journal_path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(payload, separators=(",", ":"), default=str) + "\n"
            )
        return payload


__all__ = [
    "COMPARISON_VERSION",
    "DRI_STAGE_WINDOW_SECONDS",
    "canonical_strategy_record",
    "compare_strategy_records",
    "StrategyShadowComparisonService",
]
