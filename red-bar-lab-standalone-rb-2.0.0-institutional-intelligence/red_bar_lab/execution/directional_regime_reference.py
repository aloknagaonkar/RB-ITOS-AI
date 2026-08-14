from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Mapping

import pandas as pd


VALID_DIRECTIONS = {"BULLISH", "BEARISH"}
NON_DIRECTIONAL_REGIMES = {"SIDEWAYS", "TRANSITION", "CONFLICT"}


@dataclass(frozen=True)
class DirectionalRegimeReference:
    signal_direction: str
    regime: str
    bundle_direction: str | None
    bundle_id: str | None
    primary_setup_type: str | None
    detected_at: str | None
    fresh_until: str | None
    status: str
    alignment_score: float
    reason: str
    execution_allowed: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "signal_direction": self.signal_direction,
            "regime": self.regime,
            "bundle_direction": self.bundle_direction,
            "bundle_id": self.bundle_id,
            "primary_setup_type": self.primary_setup_type,
            "detected_at": self.detected_at,
            "fresh_until": self.fresh_until,
            "status": self.status,
            "alignment_score": self.alignment_score,
            "reason": self.reason,
            "execution_allowed": False,
        }


class DirectionalRegimeReferenceService:
    """Read-only Paper Trading reference to Directional Regime Intelligence.

    This service does not create signals, candidates, queue items, paper orders,
    or live orders. It only compares an existing Paper Trading direction with
    the latest fresh v4.3 directional setup bundle.
    """

    def __init__(
        self,
        *,
        runs_root: str | Path,
        maximum_age_minutes: int = 30,
    ):
        self.runs_root = Path(runs_root)
        self.maximum_age_minutes = int(maximum_age_minutes)

    @staticmethod
    def _parse_market_time(value: object) -> pd.Timestamp | None:
        if value in (None, ""):
            return None
        try:
            ts = pd.Timestamp(value)
        except Exception:
            return None

        # v4.3 bundle artifacts preserve India market wall-clock values even
        # when +00:00 metadata is present. Remove timezone without shifting.
        try:
            if ts.tzinfo is not None:
                ts = ts.tz_localize(None)
        except Exception:
            return None
        return ts

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        if not path.exists():
            return rows
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
        return rows

    def _bundle_rows(self) -> list[dict[str, object]]:
        folder = self.runs_root / "fresh_setup_bundles_v43"
        rows: list[dict[str, object]] = []
        if not folder.exists():
            return rows
        for path in sorted(folder.glob("*.jsonl")):
            rows.extend(self._read_jsonl(path))
        return rows


    def _signal_rows(self) -> list[dict[str, object]]:
        folder = self.runs_root / "fresh_setup_signals_v43"
        rows: list[dict[str, object]] = []
        if not folder.exists():
            return rows
        for path in sorted(folder.glob("*.jsonl")):
            rows.extend(self._read_jsonl(path))
        return rows

    def _enriched_bundle_rows(self) -> list[dict[str, object]]:
        signal_index = {
            str(row.get("signal_id") or ""): row
            for row in self._signal_rows()
            if str(row.get("signal_id") or "")
        }
        enriched_rows: list[dict[str, object]] = []
        for original in self._bundle_rows():
            row = dict(original)
            primary_id = str(row.get("primary_signal_id") or "")
            primary = signal_index.get(primary_id)
            if primary is not None:
                field_map = {
                    "fresh_until": "fresh_until",
                    "trigger_level": "trigger_level",
                    "invalidation_level": "invalidation_level",
                    "primary_setup_type": "setup_type",
                    "red_bar_alignment": "red_bar_alignment",
                    "detected_at": "detected_at",
                    "direction": "direction",
                }
                for bundle_field, signal_field in field_map.items():
                    if row.get(bundle_field) in (None, ""):
                        value = primary.get(signal_field)
                        if value not in (None, ""):
                            row[bundle_field] = value
            enriched_rows.append(row)
        return enriched_rows

    def _regime_rows(self) -> list[dict[str, object]]:
        folder = self.runs_root / "stateful_regime_v43"
        rows: list[dict[str, object]] = []
        if not folder.exists():
            return rows
        for path in sorted(folder.glob("*.jsonl")):
            rows.extend(self._read_jsonl(path))
        return rows

    def _latest_regime(
        self,
        *,
        instrument_key: str,
        at_time: pd.Timestamp,
    ) -> str:
        candidates = []
        for row in self._regime_rows():
            row_instrument = str(row.get("instrument_key") or "")
            if row_instrument and row_instrument != instrument_key:
                continue
            ts = self._parse_market_time(
                row.get("evaluated_at")
                or row.get("timestamp")
                or row.get("created_at")
            )
            if ts is None or ts > at_time:
                continue
            candidates.append((ts, row))

        if not candidates:
            return "UNAVAILABLE"

        candidates.sort(key=lambda item: item[0], reverse=True)
        row = candidates[0][1]
        return str(
            row.get("regime")
            or row.get("directional_regime")
            or row.get("state")
            or "UNAVAILABLE"
        ).upper()

    def evaluate(
        self,
        *,
        signal_direction: str,
        instrument_key: str,
        at_time: datetime | pd.Timestamp | str,
    ) -> DirectionalRegimeReference:
        direction = str(signal_direction or "").upper()
        if direction not in VALID_DIRECTIONS:
            return DirectionalRegimeReference(
                signal_direction=direction,
                regime="UNAVAILABLE",
                bundle_direction=None,
                bundle_id=None,
                primary_setup_type=None,
                detected_at=None,
                fresh_until=None,
                status="UNAVAILABLE",
                alignment_score=0.0,
                reason="PAPER_SIGNAL_DIRECTION_UNSUPPORTED",
            )

        reference_time = self._parse_market_time(at_time)
        if reference_time is None:
            return DirectionalRegimeReference(
                signal_direction=direction,
                regime="UNAVAILABLE",
                bundle_direction=None,
                bundle_id=None,
                primary_setup_type=None,
                detected_at=None,
                fresh_until=None,
                status="UNAVAILABLE",
                alignment_score=0.0,
                reason="PAPER_SIGNAL_TIME_UNAVAILABLE",
            )

        regime = self._latest_regime(
            instrument_key=instrument_key,
            at_time=reference_time,
        )

        candidates = []
        for row in self._enriched_bundle_rows():
            row_instrument = str(row.get("instrument_key") or "")
            if row_instrument and row_instrument != instrument_key:
                continue

            detected = self._parse_market_time(row.get("detected_at"))
            if detected is None or detected > reference_time:
                continue

            fresh_until = self._parse_market_time(row.get("fresh_until"))
            if fresh_until is not None and reference_time > fresh_until:
                continue

            age_minutes = (
                reference_time - detected
            ).total_seconds() / 60.0
            if age_minutes > self.maximum_age_minutes:
                continue

            candidates.append((detected, row))

        if not candidates:
            status = (
                "NEUTRAL"
                if regime in NON_DIRECTIONAL_REGIMES
                else "UNAVAILABLE"
            )
            score = 50.0 if status == "NEUTRAL" else 0.0
            return DirectionalRegimeReference(
                signal_direction=direction,
                regime=regime,
                bundle_direction=None,
                bundle_id=None,
                primary_setup_type=None,
                detected_at=None,
                fresh_until=None,
                status=status,
                alignment_score=score,
                reason=(
                    f"NO_FRESH_DIRECTIONAL_BUNDLE; REGIME={regime}"
                ),
            )

        candidates.sort(key=lambda item: item[0], reverse=True)
        bundle = candidates[0][1]
        bundle_direction = str(
            bundle.get("direction") or ""
        ).upper()

        if (
            bundle_direction == direction
            and regime in {direction, "UNAVAILABLE"}
        ):
            status = "ALIGNED"
            score = 100.0
            reason = (
                "PAPER_SIGNAL_AND_FRESH_DIRECTIONAL_BUNDLE_AGREE"
            )
        elif bundle_direction == direction:
            status = "PARTIAL_ALIGNMENT"
            score = 75.0
            reason = (
                f"BUNDLE_AGREES_BUT_REGIME={regime}"
            )
        elif bundle_direction in VALID_DIRECTIONS:
            status = "CONFLICT"
            score = 0.0
            reason = (
                "PAPER_SIGNAL_OPPOSES_FRESH_DIRECTIONAL_BUNDLE"
            )
        else:
            status = "NEUTRAL"
            score = 50.0
            reason = "DIRECTIONAL_BUNDLE_HAS_NO_USABLE_DIRECTION"

        return DirectionalRegimeReference(
            signal_direction=direction,
            regime=regime,
            bundle_direction=bundle_direction or None,
            bundle_id=str(bundle.get("bundle_id") or "") or None,
            primary_setup_type=(
                str(bundle.get("primary_setup_type") or "") or None
            ),
            detected_at=(
                str(bundle.get("detected_at") or "") or None
            ),
            fresh_until=(
                str(bundle.get("fresh_until") or "") or None
            ),
            status=status,
            alignment_score=score,
            reason=reason,
        )
