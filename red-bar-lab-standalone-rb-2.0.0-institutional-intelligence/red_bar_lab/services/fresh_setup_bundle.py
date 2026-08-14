from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping


PRIORITY = {
    "BULLISH_STRUCTURE_BREAK": 10,
    "BEARISH_STRUCTURE_BREAK": 10,
    "BULLISH_RANGE_BREAKOUT": 20,
    "BEARISH_RANGE_BREAKDOWN": 20,
    "BULLISH_PULLBACK_CONTINUATION": 30,
    "BEARISH_PULLBACK_CONTINUATION": 30,
    "BULLISH_EMA_RECLAIM": 40,
    "BEARISH_EMA_LOSS": 40,
    "BULLISH_RED_BAR_CONFIRMATION": 50,
    "BEARISH_RED_BAR_CONFIRMATION": 50,
    "COUNTER_TREND_RED_BAR": 90,
}


@dataclass(frozen=True)
class FreshSetupBundle:
    bundle_id: str
    regime_snapshot_id: str
    transition_id: str
    detected_at: str
    direction: str
    primary_signal_id: str
    primary_setup_type: str
    supporting_signal_ids: tuple[str, ...]
    supporting_setup_types: tuple[str, ...]
    trigger_level: float | None
    invalidation_level: float | None
    fresh_until: str
    red_bar_alignment: str
    execution_allowed: bool = False

    def as_record(self) -> dict[str, object]:
        return {
            **self.__dict__,
            "supporting_signal_ids": list(self.supporting_signal_ids),
            "supporting_setup_types": list(self.supporting_setup_types),
            "execution_allowed": False,
        }


def _bundle_id(rows: list[Mapping[str, object]]) -> str:
    first = rows[0]
    return (
        f"BND-{first.get('transition_id')}-"
        f"{str(first.get('detected_at')).replace(':','').replace('-','')}"
    )


def build_setup_bundles(
    signals: Iterable[Mapping[str, object]],
) -> list[FreshSetupBundle]:
    grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
    for signal in signals:
        row = dict(signal)
        key = (
            str(row.get("transition_id") or ""),
            str(row.get("detected_at") or ""),
        )
        grouped.setdefault(key, []).append(row)

    bundles: list[FreshSetupBundle] = []
    for _, rows in sorted(grouped.items()):
        rows.sort(
            key=lambda row: (
                PRIORITY.get(str(row.get("setup_type") or ""), 999),
                str(row.get("signal_id") or ""),
            )
        )
        primary = rows[0]
        supporting = rows[1:]

        bundles.append(
            FreshSetupBundle(
                bundle_id=_bundle_id(rows),
                regime_snapshot_id=str(
                    primary.get("regime_snapshot_id") or ""
                ),
                transition_id=str(primary.get("transition_id") or ""),
                detected_at=str(primary.get("detected_at") or ""),
                direction=str(primary.get("direction") or ""),
                primary_signal_id=str(primary.get("signal_id") or ""),
                primary_setup_type=str(primary.get("setup_type") or ""),
                supporting_signal_ids=tuple(
                    str(row.get("signal_id") or "")
                    for row in supporting
                ),
                supporting_setup_types=tuple(
                    str(row.get("setup_type") or "")
                    for row in supporting
                ),
                trigger_level=primary.get("trigger_level"),
                invalidation_level=primary.get("invalidation_level"),
                fresh_until=str(primary.get("fresh_until") or ""),
                red_bar_alignment=str(
                    primary.get("red_bar_alignment") or "NOT_AVAILABLE"
                ),
                execution_allowed=False,
            )
        )

    return bundles
