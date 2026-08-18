from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Callable, Mapping


COMPARISON_VERSION = "INDEPENDENT-STRATEGY-COMPARISON-V1"
STRATEGIES = ("red_bar", "directional_regime", "rsi_reversal")


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
            "timestamp": _text(_first(latest, "confirmation_timestamp", "cross_timestamp", "timestamp")),
            "trigger_level": _number(_first(latest, "trigger_level", "level_value", "underlying_entry")),
            "invalidation_level": _number(_first(latest, "invalidation_level")),
            "fresh_until": _text(_first(latest, "fresh_until")),
        }
    if strategy == "directional_regime":
        bundle = dict(row.get("early_bundle_preview") or row)
        return {
            "available": bool(bundle),
            "status": _text(_first(row, "detection_status", "status")),
            "signal_id": _text(_first(bundle, "primary_signal_id", "signal_id")),
            "direction": _text(_first(bundle, "direction", row.get("early_direction"))),
            "setup_type": _text(_first(bundle, "primary_setup_type", "setup_type")),
            "timestamp": _text(_first(bundle, "detected_at", "timestamp")),
            "trigger_level": _number(_first(bundle, "trigger_level")),
            "invalidation_level": _number(_first(bundle, "invalidation_level")),
            "fresh_until": _text(_first(bundle, "fresh_until")),
        }
    latest = dict(row.get("latest_historical_signal") or row.get("latest_signal") or row)
    return {
        "available": bool(latest),
        "status": _text(_first(row, "status", "state")),
        "signal_id": _text(_first(latest, "signal_id", "id")),
        "direction": _text(_first(latest, "direction")),
        "setup_type": _text(_first(latest, "level_name", "setup_type")),
        "timestamp": _text(_first(latest, "confirmation_timestamp", "detected_at", "timestamp")),
        "trigger_level": _number(_first(latest, "trigger_level", "level_value")),
        "invalidation_level": _number(_first(latest, "invalidation_level")),
        "fresh_until": _text(_first(latest, "fresh_until")),
    }


def compare_strategy_records(
    strategy: str,
    legacy: Mapping[str, object] | None,
    shadow: Mapping[str, object] | None,
) -> dict[str, object]:
    left = canonical_strategy_record(strategy, legacy)
    right = canonical_strategy_record(strategy, shadow)
    if not left["available"]:
        return {
            "strategy": strategy,
            "comparison_status": "LEGACY_NOT_READY",
            "match": None,
            "mismatch_fields": [],
            "legacy": left,
            "shadow": right,
        }
    if not right["available"]:
        return {
            "strategy": strategy,
            "comparison_status": "SHADOW_NOT_READY",
            "match": None,
            "mismatch_fields": [],
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
    mismatches: list[str] = []
    for field in fields:
        legacy_value = left.get(field)
        shadow_value = right.get(field)
        if legacy_value is None and shadow_value is None:
            continue
        if isinstance(legacy_value, float) or isinstance(shadow_value, float):
            if legacy_value is None or shadow_value is None or abs(float(legacy_value) - float(shadow_value)) > 1e-6:
                mismatches.append(field)
        elif legacy_value != shadow_value:
            mismatches.append(field)
    return {
        "strategy": strategy,
        "comparison_status": "MATCH" if not mismatches else "MISMATCH",
        "match": not mismatches,
        "mismatch_fields": mismatches,
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

    def compare_and_record(self, shadow_record: Mapping[str, object]) -> dict[str, object]:
        legacy = dict(self.legacy_snapshot_loader() or {})
        comparisons = [
            compare_strategy_records(
                strategy,
                legacy.get(strategy) if isinstance(legacy.get(strategy), Mapping) else None,
                shadow_record.get(strategy) if isinstance(shadow_record.get(strategy), Mapping) else None,
            )
            for strategy in STRATEGIES
        ]
        comparable = [item for item in comparisons if item["match"] is not None]
        mismatches = [item for item in comparable if item["match"] is False]
        payload = {
            "comparison_version": COMPARISON_VERSION,
            "scan_identity": shadow_record.get("scan_identity"),
            "instrument_key": self.instrument_key,
            "evaluated_at": shadow_record.get("evaluated_at"),
            "comparison_status": (
                "MISMATCH" if mismatches else "MATCH" if comparable else "WAITING_FOR_LEGACY"
            ),
            "comparable_strategy_count": len(comparable),
            "matching_strategy_count": len(comparable) - len(mismatches),
            "mismatch_strategy_count": len(mismatches),
            "comparisons": comparisons,
            "diagnostic_only": True,
            "production_persistence": False,
            "execution_allowed": False,
        }
        self.status_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.status_path.with_suffix(self.status_path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        temporary.replace(self.status_path)
        with self.journal_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, separators=(",", ":"), default=str) + "\n")
        return payload


__all__ = [
    "COMPARISON_VERSION",
    "canonical_strategy_record",
    "compare_strategy_records",
    "StrategyShadowComparisonService",
]
