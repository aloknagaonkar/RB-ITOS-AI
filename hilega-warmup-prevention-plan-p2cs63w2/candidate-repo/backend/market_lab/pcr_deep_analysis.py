"""Deep descriptive PCR regime and multi-horizon analysis.

This module deliberately stays inside the PCR research layer.  It measures
absolute PCR regimes, 5m/15m/30m alignment and early-horizon flip candidates
against already-recorded future NIFTY changes.  It does not emit BUY/SELL
signals and it does not claim that an early flip is a confirmed market reversal.
"""

from __future__ import annotations

import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Callable, Iterable

from pydantic import BaseModel, ConfigDict, Field

PANELS = ("fixed", "moving", "full")
HORIZONS = (5, 15, 30)
FORWARD_FIELDS = (
    "forward_change_5m",
    "forward_change_10m",
    "forward_change_15m",
    "forward_change_30m",
)

# Non-overlapping descriptive bands.  These are fixed domain thresholds, not
# thresholds learned from OOS data.
LEVEL_BANDS = (
    ("LT_0_50", None, 0.50),
    ("0_50_TO_0_70", 0.50, 0.70),
    ("0_70_TO_1_00", 0.70, 1.00),
    ("1_00_TO_1_25", 1.00, 1.25),
    ("1_25_TO_1_50", 1.25, 1.50),
    ("GT_1_50", 1.50, None),
)

# Cumulative questions the user explicitly wants answered.  Overlap is
# intentional: PCR < 0.50 is also part of PCR < 0.70 and PCR < 1.00.
LEVEL_THRESHOLDS = (
    ("PCR_LT_0_50", lambda value: value < 0.50),
    ("PCR_LT_0_70", lambda value: value < 0.70),
    ("PCR_LT_1_00", lambda value: value < 1.00),
    ("PCR_GT_1_25", lambda value: value > 1.25),
    ("PCR_GT_1_50", lambda value: value > 1.50),
)


class PCRDeepModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ForwardStats(PCRDeepModel):
    count: int
    session_count: int
    mean: float | None = None
    median: float | None = None
    stdev: float | None = None
    bullish_pct: float | None = None
    bearish_pct: float | None = None
    flat_pct: float | None = None
    positive_session_pct: float | None = None
    negative_session_pct: float | None = None


class ConditionStats(PCRDeepModel):
    condition: str
    row_count: int
    session_count: int
    forwards: dict[str, ForwardStats]


class PanelDeepAnalysis(PCRDeepModel):
    panel: str
    level_bands: list[ConditionStats]
    level_thresholds: list[ConditionStats]
    horizon_alignment: list[ConditionStats]
    early_flip_candidates: list[ConditionStats]
    level_plus_turn: list[ConditionStats]


class CrossPanelAnalysis(PCRDeepModel):
    conditions: list[ConditionStats]


class PCRDeepAnalysisReport(PCRDeepModel):
    status: str
    source: str
    row_count: int
    session_count: int
    first_session_date: str | None = None
    last_session_date: str | None = None
    methodology: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    panels: list[PanelDeepAnalysis]
    cross_panel: CrossPanelAnalysis


def _float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def load_pcr_deep_evidence_csv(path: str | Path) -> list[dict[str, object]]:
    numeric_fields = {"spot", *FORWARD_FIELDS}
    for panel in PANELS:
        numeric_fields.add(f"{panel}_pcr")
        for horizon in HORIZONS:
            numeric_fields.add(f"{panel}_pcr_change_{horizon}m")

    required = {"session_date", "timestamp", *FORWARD_FIELDS}
    required.update(f"{panel}_pcr" for panel in PANELS)
    required.update(
        f"{panel}_pcr_change_{horizon}m"
        for panel in PANELS
        for horizon in HORIZONS
    )

    rows: list[dict[str, object]] = []
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(
                "historical evidence CSV missing columns: " + ", ".join(sorted(missing))
            )
        for raw in reader:
            row: dict[str, object] = dict(raw)
            for field in numeric_fields:
                row[field] = _float(raw.get(field))
            rows.append(row)
    return rows


def _pct(part: int, whole: int) -> float | None:
    return part * 100.0 / whole if whole else None


def _forward_stats(rows: Iterable[dict[str, object]], field: str) -> ForwardStats:
    values: list[tuple[str, float]] = []
    for row in rows:
        value = row.get(field)
        session = row.get("session_date")
        if isinstance(value, (int, float)) and not isinstance(value, bool) and isinstance(session, str):
            values.append((session, float(value)))
    if not values:
        return ForwardStats(count=0, session_count=0)

    numeric = [value for _, value in values]
    by_session: dict[str, list[float]] = defaultdict(list)
    for session, value in values:
        by_session[session].append(value)
    session_means = [statistics.fmean(items) for items in by_session.values()]
    return ForwardStats(
        count=len(numeric),
        session_count=len(by_session),
        mean=statistics.fmean(numeric),
        median=statistics.median(numeric),
        stdev=statistics.stdev(numeric) if len(numeric) > 1 else 0.0,
        bullish_pct=_pct(sum(value > 0 for value in numeric), len(numeric)),
        bearish_pct=_pct(sum(value < 0 for value in numeric), len(numeric)),
        flat_pct=_pct(sum(value == 0 for value in numeric), len(numeric)),
        positive_session_pct=_pct(sum(value > 0 for value in session_means), len(session_means)),
        negative_session_pct=_pct(sum(value < 0 for value in session_means), len(session_means)),
    )


def _condition(name: str, rows: list[dict[str, object]]) -> ConditionStats:
    return ConditionStats(
        condition=name,
        row_count=len(rows),
        session_count=len({str(row["session_date"]) for row in rows if row.get("session_date")}),
        forwards={field: _forward_stats(rows, field) for field in FORWARD_FIELDS},
    )


def _select(rows: list[dict[str, object]], predicate: Callable[[dict[str, object]], bool]) -> list[dict[str, object]]:
    return [row for row in rows if predicate(row)]


def _number(row: dict[str, object], key: str) -> float | None:
    value = row.get(key)
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _sign(value: float | None) -> int | None:
    if value is None:
        return None
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _in_band(value: float | None, lower: float | None, upper: float | None) -> bool:
    if value is None:
        return False
    if lower is not None and value < lower:
        return False
    if upper is not None and value >= upper:
        return False
    return True


def _panel_analysis(rows: list[dict[str, object]], panel: str) -> PanelDeepAnalysis:
    level_key = f"{panel}_pcr"
    change = {h: f"{panel}_pcr_change_{h}m" for h in HORIZONS}

    level_bands = [
        _condition(
            label,
            _select(rows, lambda row, lo=lower, hi=upper: _in_band(_number(row, level_key), lo, hi)),
        )
        for label, lower, upper in LEVEL_BANDS
    ]

    level_thresholds = [
        _condition(
            label,
            _select(rows, lambda row, pred=predicate: (
                (value := _number(row, level_key)) is not None and pred(value)
            )),
        )
        for label, predicate in LEVEL_THRESHOLDS
    ]

    def signs(row: dict[str, object]) -> tuple[int | None, int | None, int | None]:
        return tuple(_sign(_number(row, change[h])) for h in HORIZONS)  # type: ignore[return-value]

    horizon_alignment = [
        _condition("ALL_5M_15M_30M_RISING", _select(rows, lambda row: signs(row) == (1, 1, 1))),
        _condition("ALL_5M_15M_30M_FALLING", _select(rows, lambda row: signs(row) == (-1, -1, -1))),
        _condition("ALL_5M_15M_30M_NONNEGATIVE", _select(rows, lambda row: all(s is not None and s >= 0 for s in signs(row)))),
        _condition("ALL_5M_15M_30M_NONPOSITIVE", _select(rows, lambda row: all(s is not None and s <= 0 for s in signs(row)))),
    ]

    # These are deliberately labelled CANDIDATE rather than REVERSAL.  A short
    # horizon disagreement can be an early warning, a pullback, or noise.  v2
    # will compare these timestamps with explicit price-reversal labels.
    early_flip_candidates = [
        _condition(
            "BULLISH_5M_FLIP_WHILE_15M_30M_FALLING",
            _select(rows, lambda row: signs(row) == (1, -1, -1)),
        ),
        _condition(
            "BEARISH_5M_FLIP_WHILE_15M_30M_RISING",
            _select(rows, lambda row: signs(row) == (-1, 1, 1)),
        ),
        _condition(
            "BULLISH_5M_15M_FLIP_WHILE_30M_FALLING",
            _select(rows, lambda row: signs(row) == (1, 1, -1)),
        ),
        _condition(
            "BEARISH_5M_15M_FLIP_WHILE_30M_RISING",
            _select(rows, lambda row: signs(row) == (-1, -1, 1)),
        ),
    ]

    level_plus_turn = [
        _condition(
            "PCR_LT_0_50_AND_5M_RISING",
            _select(rows, lambda row: (_number(row, level_key) is not None and _number(row, level_key) < 0.50 and _sign(_number(row, change[5])) == 1)),
        ),
        _condition(
            "PCR_LT_0_70_AND_5M_RISING",
            _select(rows, lambda row: (_number(row, level_key) is not None and _number(row, level_key) < 0.70 and _sign(_number(row, change[5])) == 1)),
        ),
        _condition(
            "PCR_LT_1_00_AND_5M_RISING",
            _select(rows, lambda row: (_number(row, level_key) is not None and _number(row, level_key) < 1.00 and _sign(_number(row, change[5])) == 1)),
        ),
        _condition(
            "PCR_GT_1_25_AND_5M_FALLING",
            _select(rows, lambda row: (_number(row, level_key) is not None and _number(row, level_key) > 1.25 and _sign(_number(row, change[5])) == -1)),
        ),
        _condition(
            "PCR_GT_1_50_AND_5M_FALLING",
            _select(rows, lambda row: (_number(row, level_key) is not None and _number(row, level_key) > 1.50 and _sign(_number(row, change[5])) == -1)),
        ),
    ]

    return PanelDeepAnalysis(
        panel=panel,
        level_bands=level_bands,
        level_thresholds=level_thresholds,
        horizon_alignment=horizon_alignment,
        early_flip_candidates=early_flip_candidates,
        level_plus_turn=level_plus_turn,
    )


def _cross_panel_analysis(rows: list[dict[str, object]]) -> CrossPanelAnalysis:
    def horizon_panel_signs(row: dict[str, object], horizon: int) -> tuple[int | None, int | None, int | None]:
        return tuple(
            _sign(_number(row, f"{panel}_pcr_change_{horizon}m")) for panel in PANELS
        )  # type: ignore[return-value]

    def every_panel_every_horizon(row: dict[str, object], expected: int) -> bool:
        values = [
            _sign(_number(row, f"{panel}_pcr_change_{horizon}m"))
            for panel in PANELS
            for horizon in HORIZONS
        ]
        return all(value == expected for value in values)

    conditions: list[ConditionStats] = []
    for horizon in HORIZONS:
        conditions.append(_condition(
            f"FIXED_MOVING_FULL_{horizon}M_RISING",
            _select(rows, lambda row, h=horizon: horizon_panel_signs(row, h) == (1, 1, 1)),
        ))
        conditions.append(_condition(
            f"FIXED_MOVING_FULL_{horizon}M_FALLING",
            _select(rows, lambda row, h=horizon: horizon_panel_signs(row, h) == (-1, -1, -1)),
        ))
    conditions.extend([
        _condition(
            "ALL_PANELS_ALL_5M_15M_30M_RISING",
            _select(rows, lambda row: every_panel_every_horizon(row, 1)),
        ),
        _condition(
            "ALL_PANELS_ALL_5M_15M_30M_FALLING",
            _select(rows, lambda row: every_panel_every_horizon(row, -1)),
        ),
    ])
    return CrossPanelAnalysis(conditions=conditions)


def build_pcr_deep_analysis_report(rows: list[dict[str, object]], source: str) -> PCRDeepAnalysisReport:
    sessions = sorted({str(row["session_date"]) for row in rows if row.get("session_date")})
    return PCRDeepAnalysisReport(
        status="AVAILABLE" if rows else "UNAVAILABLE",
        source=source,
        row_count=len(rows),
        session_count=len(sessions),
        first_session_date=sessions[0] if sessions else None,
        last_session_date=sessions[-1] if sessions else None,
        methodology=[
            "Descriptive PCR research only; no BUY/SELL signal is emitted.",
            "Absolute PCR thresholds are fixed domain thresholds and are not learned from the input dataset.",
            "5m/15m/30m rising and falling use the sign of exact historical PCR change fields already present in evidence rows.",
            "Forward NIFTY outcomes use only exact +5m/+10m/+15m/+30m values already present in the evidence dataset.",
            "Early-flip conditions are candidate warnings only; they are not labelled as confirmed reversals in v1.",
            "The same analyzer can be run unchanged on training, OOS-A and OOS-B for comparable descriptive validation.",
        ],
        limitations=[
            "The current evidence CSV does not contain underlying volume, so PCR lead time versus volume expansion cannot yet be measured.",
            "The current evidence CSV does not contain an explicit objective price-reversal label, so true reversal vs short reversal vs pullback is deferred to the lead/lag v2 evidence extension.",
            "Minute rows are serially dependent; session_count and session-level percentages should be considered alongside raw row counts.",
        ],
        panels=[_panel_analysis(rows, panel) for panel in PANELS],
        cross_panel=_cross_panel_analysis(rows),
    )


def analyze_pcr_deep_csv(path: str | Path) -> PCRDeepAnalysisReport:
    return build_pcr_deep_analysis_report(load_pcr_deep_evidence_csv(path), str(path))


def write_pcr_deep_analysis_json(report: PCRDeepAnalysisReport, path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
