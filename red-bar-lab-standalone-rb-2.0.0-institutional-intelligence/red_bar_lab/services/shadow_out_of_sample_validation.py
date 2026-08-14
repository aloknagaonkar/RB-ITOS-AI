from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

import pandas as pd


GROUP_BASELINE = "BASELINE"
GROUP_BULLISH_ONLY = "BULLISH_ONLY"
GROUP_BULLISH_BREAKOUT = "BULLISH_BREAKOUT"
GROUP_CALIBRATED = "CALIBRATED_BULLISH_BREAKOUT"


def _accuracy(rows: list[Mapping[str, object]], field: str) -> float | None:
    values = [bool(row[field]) for row in rows if row.get(field) is not None]
    if not values:
        return None
    return round(sum(values) / len(values) * 100.0, 2)


def _mean(rows: list[Mapping[str, object]], field: str) -> float | None:
    values = [
        float(row[field])
        for row in rows
        if row.get(field) is not None
    ]
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _contains_evidence(row: Mapping[str, object], *required: str) -> bool:
    evidence = row.get("evidence") or []
    if isinstance(evidence, str):
        evidence = [evidence]
    tags = {str(item) for item in evidence}
    return all(tag in tags for tag in required)


def classify_groups(
    rows: Iterable[Mapping[str, object]],
    *,
    adx_slope_threshold: float = 2.136,
    directional_displacement_threshold: float = 2.445,
) -> dict[str, list[dict[str, object]]]:
    items = [dict(row) for row in rows]

    baseline = list(items)
    bullish_only = [
        row for row in items
        if str(row.get("direction") or "") == "BULLISH"
    ]
    bullish_breakout = [
        row for row in bullish_only
        if bool(row.get("breakout"))
        or _contains_evidence(row, "SWING_HIGH_BREAKOUT")
    ]
    calibrated = [
        row for row in bullish_breakout
        if float(row.get("adx_slope") or 0.0) > adx_slope_threshold
        and float(row.get("directional_displacement_atr") or 0.0)
            > directional_displacement_threshold
        and _contains_evidence(
            row,
            "ADX_RISING",
            "SWING_HIGH_BREAKOUT",
            "POSITIVE_ATR_DISPLACEMENT",
        )
    ]

    return {
        GROUP_BASELINE: baseline,
        GROUP_BULLISH_ONLY: bullish_only,
        GROUP_BULLISH_BREAKOUT: bullish_breakout,
        GROUP_CALIBRATED: calibrated,
    }


def _group_by(
    rows: list[Mapping[str, object]],
    field: str,
) -> list[dict[str, object]]:
    grouped: dict[str, list[Mapping[str, object]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get(field) or "UNKNOWN"), []).append(row)

    output = []
    for value, group in sorted(grouped.items()):
        output.append(
            {
                field: value,
                "samples": len(group),
                "resolved_30m": sum(
                    row.get("direction_correct_30m") is not None
                    for row in group
                ),
                "accuracy_30m": _accuracy(list(group), "direction_correct_30m"),
                "average_mfe": _mean(list(group), "maximum_favorable_excursion"),
                "average_mae": _mean(list(group), "maximum_adverse_excursion"),
                "execution_allowed": False,
            }
        )
    return output


@dataclass(frozen=True)
class OutOfSampleGateResult:
    group: str
    eligible: bool
    samples: int
    resolved_30m: int
    accuracy_30m: float | None
    false_rate_30m: float | None
    average_mfe: float | None
    average_mae: float | None
    mfe_mae_ratio: float | None
    represented_regimes: int
    dominant_day_share_pct: float | None
    warnings: tuple[str, ...]

    def as_record(self) -> dict[str, object]:
        return {
            **self.__dict__,
            "warnings": list(self.warnings),
            "execution_allowed": False,
        }


def summarize_group(
    group: str,
    rows: Iterable[Mapping[str, object]],
    *,
    minimum_resolved: int = 20,
    minimum_accuracy: float = 60.0,
    maximum_false_rate: float = 40.0,
    minimum_mfe_mae_ratio: float = 1.30,
    minimum_regimes: int = 2,
    maximum_dominant_day_share_pct: float = 35.0,
) -> OutOfSampleGateResult:
    items = list(rows)
    resolved = [
        row for row in items
        if row.get("direction_correct_30m") is not None
    ]
    accuracy = _accuracy(resolved, "direction_correct_30m")
    false_rate = (
        round(100.0 - accuracy, 2)
        if accuracy is not None
        else None
    )
    mfe = _mean(resolved, "maximum_favorable_excursion")
    mae = _mean(resolved, "maximum_adverse_excursion")
    ratio = (
        round(mfe / mae, 3)
        if mfe is not None and mae not in {None, 0}
        else None
    )

    represented_regimes = len({
        str(row.get("regime") or "UNKNOWN")
        for row in resolved
    })

    by_day: dict[str, int] = {}
    for row in resolved:
        day = str(row.get("trading_date") or "UNKNOWN")
        by_day[day] = by_day.get(day, 0) + 1
    dominant_day_share = (
        round(max(by_day.values()) / len(resolved) * 100.0, 2)
        if resolved and by_day
        else None
    )

    warnings: list[str] = []
    if len(resolved) < minimum_resolved:
        warnings.append("INSUFFICIENT OUT-OF-SAMPLE SIGNALS")
    if accuracy is None or accuracy < minimum_accuracy:
        warnings.append("30M ACCURACY BELOW GATE")
    if false_rate is None or false_rate > maximum_false_rate:
        warnings.append("FALSE RATE ABOVE GATE")
    if ratio is None or ratio < minimum_mfe_mae_ratio:
        warnings.append("MFE/MAE BELOW GATE")
    if represented_regimes < minimum_regimes:
        warnings.append("INSUFFICIENT REGIME COVERAGE")
    if (
        dominant_day_share is not None
        and dominant_day_share > maximum_dominant_day_share_pct
    ):
        warnings.append("SUCCESS CONCENTRATED IN TOO FEW DAYS")

    return OutOfSampleGateResult(
        group=group,
        eligible=not warnings,
        samples=len(items),
        resolved_30m=len(resolved),
        accuracy_30m=accuracy,
        false_rate_30m=false_rate,
        average_mfe=mfe,
        average_mae=mae,
        mfe_mae_ratio=ratio,
        represented_regimes=represented_regimes,
        dominant_day_share_pct=dominant_day_share,
        warnings=tuple(warnings),
    )


class ShadowOutOfSampleValidationService:
    def evaluate(
        self,
        rows: Iterable[Mapping[str, object]],
        *,
        adx_slope_threshold: float = 2.136,
        directional_displacement_threshold: float = 2.445,
    ) -> dict[str, object]:
        groups = classify_groups(
            rows,
            adx_slope_threshold=adx_slope_threshold,
            directional_displacement_threshold=directional_displacement_threshold,
        )

        summaries = []
        details = {}
        for group, group_rows in groups.items():
            summary = summarize_group(group, group_rows).as_record()
            summaries.append(summary)
            details[group] = {
                "summary": summary,
                "by_regime": _group_by(group_rows, "regime"),
                "by_time_bucket": _group_by(group_rows, "time_bucket"),
                "by_trading_date": _group_by(group_rows, "trading_date"),
                "rows": group_rows,
                "execution_allowed": False,
            }

        return {
            "summaries": summaries,
            "details": details,
            "thresholds": {
                "adx_slope_threshold": adx_slope_threshold,
                "directional_displacement_threshold": directional_displacement_threshold,
            },
            "execution_allowed": False,
        }
