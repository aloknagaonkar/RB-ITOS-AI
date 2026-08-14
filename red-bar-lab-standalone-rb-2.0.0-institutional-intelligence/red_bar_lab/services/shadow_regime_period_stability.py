from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

import pandas as pd


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


def _ratio(mfe: float | None, mae: float | None) -> float | None:
    if mfe is None or mae in {None, 0}:
        return None
    return round(mfe / mae, 3)


def _period_summary(
    label: str,
    rows: Iterable[Mapping[str, object]],
) -> dict[str, object]:
    items = list(rows)
    mfe = _mean(items, "maximum_favorable_excursion")
    mae = _mean(items, "maximum_adverse_excursion")
    return {
        "period": label,
        "samples": len(items),
        "resolved_5m": sum(row.get("direction_correct_5m") is not None for row in items),
        "resolved_15m": sum(row.get("direction_correct_15m") is not None for row in items),
        "resolved_30m": sum(row.get("direction_correct_30m") is not None for row in items),
        "accuracy_5m": _accuracy(items, "direction_correct_5m"),
        "accuracy_15m": _accuracy(items, "direction_correct_15m"),
        "accuracy_30m": _accuracy(items, "direction_correct_30m"),
        "average_mfe": mfe,
        "average_mae": mae,
        "mfe_mae_ratio": _ratio(mfe, mae),
        "execution_allowed": False,
    }


def _group_summary(
    rows: Iterable[Mapping[str, object]],
    field: str,
) -> list[dict[str, object]]:
    grouped: dict[str, list[Mapping[str, object]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get(field) or "UNKNOWN"), []).append(row)

    output = []
    for value, group in sorted(grouped.items()):
        summary = _period_summary(value, group)
        output.append({field: value, **{k: v for k, v in summary.items() if k != "period"}})
    return output


def _week_key(row: Mapping[str, object]) -> str:
    raw = row.get("trading_date") or row.get("timestamp")
    value = pd.Timestamp(raw)
    iso = value.isocalendar()
    return f"{int(iso.year)}-W{int(iso.week):02d}"


def _volatility_bucket(row: Mapping[str, object]) -> str:
    value = float(row.get("range_atr") or 0.0)
    if value < 0.9:
        return "LOW_VOLATILITY"
    if value < 1.4:
        return "NORMAL_VOLATILITY"
    if value < 2.0:
        return "HIGH_VOLATILITY"
    return "EXTREME_VOLATILITY"


def _failure_clusters(rows: list[Mapping[str, object]]) -> list[dict[str, object]]:
    ordered = sorted(
        rows,
        key=lambda row: str(row.get("timestamp") or row.get("candle_timestamp") or ""),
    )
    clusters = []
    current = []
    for row in ordered:
        correct = row.get("direction_correct_30m")
        if correct is False:
            current.append(row)
        else:
            if len(current) >= 2:
                clusters.append(current)
            current = []
    if len(current) >= 2:
        clusters.append(current)

    output = []
    for index, cluster in enumerate(clusters, start=1):
        output.append(
            {
                "cluster_id": index,
                "failures": len(cluster),
                "start": cluster[0].get("timestamp") or cluster[0].get("candle_timestamp"),
                "end": cluster[-1].get("timestamp") or cluster[-1].get("candle_timestamp"),
                "direction": cluster[0].get("direction"),
                "regime": cluster[0].get("regime"),
                "time_bucket": cluster[0].get("time_bucket"),
                "execution_allowed": False,
            }
        )
    return output


def _duplicate_density(rows: list[Mapping[str, object]], cooldown_minutes: int = 30) -> dict[str, object]:
    ordered = sorted(
        rows,
        key=lambda row: pd.Timestamp(row.get("timestamp") or row.get("candle_timestamp")),
    )
    duplicates = 0
    for previous, current in zip(ordered, ordered[1:]):
        same_direction = previous.get("direction") == current.get("direction")
        delta = pd.Timestamp(
            current.get("timestamp") or current.get("candle_timestamp")
        ) - pd.Timestamp(
            previous.get("timestamp") or previous.get("candle_timestamp")
        )
        if same_direction and delta.total_seconds() / 60.0 <= cooldown_minutes:
            duplicates += 1

    return {
        "signals": len(ordered),
        "possible_duplicates": duplicates,
        "duplicate_share_pct": (
            round(duplicates / len(ordered) * 100.0, 2)
            if ordered else None
        ),
        "cooldown_minutes": cooldown_minutes,
        "execution_allowed": False,
    }


@dataclass(frozen=True)
class StabilityFinding:
    severity: str
    code: str
    message: str

    def as_record(self) -> dict[str, object]:
        return {
            **self.__dict__,
            "execution_allowed": False,
        }


def _build_findings(
    calibration_summary: Mapping[str, object],
    oos_summary: Mapping[str, object],
    duplicate_density: Mapping[str, object],
    failure_clusters: list[Mapping[str, object]],
) -> list[dict[str, object]]:
    findings: list[StabilityFinding] = []

    cal_acc = calibration_summary.get("accuracy_30m")
    oos_acc = oos_summary.get("accuracy_30m")
    if cal_acc is not None and oos_acc is not None:
        drop = float(cal_acc) - float(oos_acc)
        if drop >= 10.0:
            findings.append(
                StabilityFinding(
                    "HIGH",
                    "PERIOD_ACCURACY_DECAY",
                    f"30-minute accuracy fell by {drop:.2f} percentage points out of sample.",
                )
            )

    cal_ratio = calibration_summary.get("mfe_mae_ratio")
    oos_ratio = oos_summary.get("mfe_mae_ratio")
    if cal_ratio is not None and oos_ratio is not None and float(oos_ratio) < 1.0:
        findings.append(
            StabilityFinding(
                "HIGH",
                "OOS_ADVERSE_MOVE_DOMINATES",
                "Out-of-sample average MAE exceeds average MFE.",
            )
        )

    duplicate_share = duplicate_density.get("duplicate_share_pct")
    if duplicate_share is not None and float(duplicate_share) >= 25.0:
        findings.append(
            StabilityFinding(
                "MEDIUM",
                "HIGH_CONSECUTIVE_SIGNAL_DENSITY",
                f"{float(duplicate_share):.2f}% of signals occur within the cooldown window in the same direction.",
            )
        )

    if failure_clusters:
        largest = max(int(item.get("failures") or 0) for item in failure_clusters)
        if largest >= 3:
            findings.append(
                StabilityFinding(
                    "HIGH",
                    "CONSECUTIVE_FAILURE_CLUSTER",
                    f"Detected a cluster of {largest} consecutive 30-minute failures.",
                )
            )

    if not findings:
        findings.append(
            StabilityFinding(
                "INFO",
                "NO_MAJOR_STABILITY_BREAK",
                "No major stability break was detected by the configured checks.",
            )
        )

    return [item.as_record() for item in findings]


class ShadowRegimePeriodStabilityService:
    def analyze(
        self,
        calibration_rows: Iterable[Mapping[str, object]],
        out_of_sample_rows: Iterable[Mapping[str, object]],
        *,
        cooldown_minutes: int = 30,
    ) -> dict[str, object]:
        calibration = [dict(row) for row in calibration_rows]
        oos = [dict(row) for row in out_of_sample_rows]

        for row in calibration + oos:
            row["week"] = _week_key(row)
            row["volatility_bucket"] = _volatility_bucket(row)

        calibration_summary = _period_summary("CALIBRATION", calibration)
        oos_summary = _period_summary("OUT_OF_SAMPLE", oos)
        duplicate_density = _duplicate_density(oos, cooldown_minutes)
        failure_clusters = _failure_clusters(oos)

        return {
            "period_comparison": [calibration_summary, oos_summary],
            "calibration_by_week": _group_summary(calibration, "week"),
            "oos_by_week": _group_summary(oos, "week"),
            "calibration_by_regime": _group_summary(calibration, "regime"),
            "oos_by_regime": _group_summary(oos, "regime"),
            "calibration_by_direction": _group_summary(calibration, "direction"),
            "oos_by_direction": _group_summary(oos, "direction"),
            "calibration_by_time": _group_summary(calibration, "time_bucket"),
            "oos_by_time": _group_summary(oos, "time_bucket"),
            "calibration_by_volatility": _group_summary(calibration, "volatility_bucket"),
            "oos_by_volatility": _group_summary(oos, "volatility_bucket"),
            "failure_clusters": failure_clusters,
            "duplicate_density": duplicate_density,
            "findings": _build_findings(
                calibration_summary,
                oos_summary,
                duplicate_density,
                failure_clusters,
            ),
            "calibration_rows": calibration,
            "out_of_sample_rows": oos,
            "execution_allowed": False,
        }
