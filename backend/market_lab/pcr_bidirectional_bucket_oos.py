"""Fresh-OOS validation for frozen bidirectional Stage-2 severity buckets.

Consumes the existing 100-session discriminator JSON only as a frozen specification
(cut points + expected monotonic direction) and applies it unchanged to a fresh
evidence CSV. Research only; no CE/PE signal is emitted.
"""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .pcr_bidirectional_discriminator import _events, _load, _bucket_index


class ResearchModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class BucketResult(ResearchModel):
    bucket: str
    lower_exclusive: float | None = None
    upper_inclusive: float | None = None
    event_count: int
    true_reversal_count: int
    false_warning_count: int
    other_count: int
    true_vs_false_rate_pct: float | None = None
    true_reversal_rate_all_pct: float | None = None


class FeatureValidation(ResearchModel):
    feature: str
    train_cut_points: list[float]
    expected_monotonic: str
    fresh_oos_rates: list[float | None]
    monotonic_increasing: bool
    monotonic_decreasing: bool
    expected_direction_confirmed: bool
    buckets: list[BucketResult]


class DirectionValidation(ResearchModel):
    direction: str
    stage_2_definition: str
    event_count: int
    true_reversals: int
    false_warnings: int
    features: list[FeatureValidation]
    confirmed_feature_count: int
    tested_feature_count: int


class FreshOOSReport(ResearchModel):
    status: str
    source: str
    spec_source: str
    row_count: int
    session_count: int
    bearish: DirectionValidation
    bullish: DirectionValidation
    methodology: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


def _pct(n: int, d: int) -> float | None:
    return n * 100.0 / d if d else None


def _is_monotonic(values: list[float | None], increasing: bool) -> bool:
    if len(values) != 4 or any(v is None for v in values):
        return False
    vals = [float(v) for v in values if v is not None]
    if increasing:
        return all(a <= b for a, b in zip(vals, vals[1:]))
    return all(a >= b for a, b in zip(vals, vals[1:]))


def _direction(spec: dict, rows: list[dict[str, object]], direction: str) -> DirectionValidation:
    ds = spec[direction.lower()]
    true_label = f"TRUE_{direction}_REVERSAL"
    false_label = f"FALSE_{direction}_WARNING"
    events = _events(rows, direction)
    features: list[FeatureValidation] = []

    for item in ds.get("frozen_train_buckets", []):
        inc = bool(item.get("monotonic_increasing"))
        dec = bool(item.get("monotonic_decreasing"))
        # Only validate relationships that were monotonic in the frozen 100-session study.
        if inc == dec:
            continue
        feature = str(item["feature"])
        cuts = [float(x) for x in item.get("train_cut_points", [])]
        if len(cuts) != 3:
            continue
        bucket_events = [[] for _ in range(4)]
        for event in events:
            value = event.get(feature)
            if isinstance(value, (int, float)):
                bucket_events[_bucket_index(float(value), cuts)].append(event)

        buckets: list[BucketResult] = []
        rates: list[float | None] = []
        for idx, selected in enumerate(bucket_events):
            t = sum(e["label"] == true_label for e in selected)
            f = sum(e["label"] == false_label for e in selected)
            rate = _pct(t, t + f)
            rates.append(rate)
            buckets.append(BucketResult(
                bucket=f"Q{idx + 1}",
                lower_exclusive=None if idx == 0 else cuts[idx - 1],
                upper_inclusive=None if idx == 3 else cuts[idx],
                event_count=len(selected),
                true_reversal_count=t,
                false_warning_count=f,
                other_count=len(selected) - t - f,
                true_vs_false_rate_pct=rate,
                true_reversal_rate_all_pct=_pct(t, len(selected)),
            ))
        mi = _is_monotonic(rates, True)
        md = _is_monotonic(rates, False)
        expected = "INCREASING" if inc else "DECREASING"
        features.append(FeatureValidation(
            feature=feature,
            train_cut_points=cuts,
            expected_monotonic=expected,
            fresh_oos_rates=rates,
            monotonic_increasing=mi,
            monotonic_decreasing=md,
            expected_direction_confirmed=mi if inc else md,
            buckets=buckets,
        ))

    return DirectionValidation(
        direction=direction,
        stage_2_definition=str(ds.get("stage_2_definition", "")),
        event_count=len(events),
        true_reversals=sum(e["label"] == true_label for e in events),
        false_warnings=sum(e["label"] == false_label for e in events),
        features=features,
        confirmed_feature_count=sum(x.expected_direction_confirmed for x in features),
        tested_feature_count=len(features),
    )


def validate_fresh_oos(spec_path: str | Path, evidence_path: str | Path) -> FreshOOSReport:
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    if spec.get("status") != "AVAILABLE":
        raise ValueError("frozen discriminator spec is not AVAILABLE")
    rows = _load(evidence_path)
    if not rows:
        raise ValueError("fresh OOS evidence has no rows")
    sessions = len({str(row["session_date"]) for row in rows})
    return FreshOOSReport(
        status="AVAILABLE",
        source=str(evidence_path),
        spec_source=str(spec_path),
        row_count=len(rows),
        session_count=sessions,
        bearish=_direction(spec, rows, "BEARISH"),
        bullish=_direction(spec, rows, "BULLISH"),
        methodology=[
            "The 100-session discriminator JSON is treated as a frozen specification; no cut point is recalculated from fresh OOS data.",
            "Only features that were monotonic in the frozen study are tested in this report.",
            "Stage-2 definitions and TRUE/FALSE outcome labels are unchanged from the bidirectional research engine.",
            "Fresh OOS confirmation requires the same monotonic direction across all four frozen quartile buckets.",
            "This report is descriptive research and emits no CE/PE BUY signal.",
        ],
        limitations=[
            "One 20-session fresh block is a useful confirmation gate but not final proof of regime robustness.",
            "Per-strike option premium plus OI positioning and underlying-volume timing are still not included.",
        ],
    )


def write_fresh_oos_json(report: FreshOOSReport, path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
