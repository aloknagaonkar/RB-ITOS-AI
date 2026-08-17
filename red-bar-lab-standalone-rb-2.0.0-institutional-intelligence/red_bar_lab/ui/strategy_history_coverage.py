from __future__ import annotations

from typing import Mapping, Sequence

import streamlit as st


COVERAGE_VERSION = "HISTORY-COVERAGE-V1"
COVERAGE_FIELDS = (
    "strategy_version",
    "setup_type",
    "mfe_points",
    "mae_points",
    "exit_policy_version",
)


def _present(value: object) -> bool:
    return value not in (None, "")


def build_history_coverage(
    records: Sequence[Mapping[str, object]] | None,
) -> dict[str, object]:
    """Describe historical metadata completeness without changing gate outcomes."""
    rows = [dict(row) for row in (records or [])]
    total = len(rows)
    fields = []
    for field in COVERAGE_FIELDS:
        present_count = sum(1 for row in rows if _present(row.get(field)))
        coverage_pct = (present_count / total * 100.0) if total else 0.0
        fields.append(
            {
                "field": field,
                "present_count": present_count,
                "missing_count": total - present_count,
                "coverage_pct": round(coverage_pct, 2),
            }
        )

    by_field = {row["field"]: row for row in fields}
    strategy_version_pct = float(by_field["strategy_version"]["coverage_pct"])
    exit_policy_pct = float(by_field["exit_policy_version"]["coverage_pct"])
    mfe_pct = float(by_field["mfe_points"]["coverage_pct"])
    mae_pct = float(by_field["mae_points"]["coverage_pct"])

    if total == 0:
        status = "EMPTY"
        matching_readiness = "NO_HISTORY"
    elif strategy_version_pct >= 80.0 and exit_policy_pct >= 80.0:
        status = "HIGH"
        matching_readiness = "VERSIONED_MATCHING_READY"
    elif strategy_version_pct > 0.0 or exit_policy_pct > 0.0:
        status = "PARTIAL"
        matching_readiness = "PARTIAL_VERSIONED_MATCHING"
    else:
        status = "LOW"
        matching_readiness = "STRATEGY_SIDE_BASELINE_ONLY"

    excursion_readiness = (
        "MFE_MAE_READY"
        if mfe_pct >= 80.0 and mae_pct >= 80.0
        else "PARTIAL_MFE_MAE"
        if mfe_pct > 0.0 or mae_pct > 0.0
        else "MFE_MAE_UNAVAILABLE"
    )

    return {
        "coverage_version": COVERAGE_VERSION,
        "record_count": total,
        "coverage_status": status,
        "matching_readiness": matching_readiness,
        "excursion_readiness": excursion_readiness,
        "fields": fields,
        "missing_fields": [row["field"] for row in fields if row["coverage_pct"] < 100.0],
        "source_read_only": True,
        "execution_allowed": False,
    }


def render_history_coverage(coverage: Mapping[str, object]) -> None:
    st.markdown("#### 7B.1 Historical Evidence Coverage")
    st.caption(
        "Read-only completeness diagnostics. Coverage does not approve, reject, "
        "persist, reserve, consume, or submit a trade."
    )
    cols = st.columns(4)
    cols[0].metric("Normalized trades", coverage.get("record_count", 0))
    cols[1].metric("Coverage", coverage.get("coverage_status", "EMPTY"))
    cols[2].metric("Version matching", coverage.get("matching_readiness", "NO_HISTORY"))
    cols[3].metric("MFE / MAE", coverage.get("excursion_readiness", "MFE_MAE_UNAVAILABLE"))
    fields = list(coverage.get("fields") or [])
    if fields:
        st.dataframe(fields, width="stretch", hide_index=True)
    else:
        st.info("No normalized completed trades are available for coverage analysis.")


__all__ = [
    "COVERAGE_FIELDS",
    "COVERAGE_VERSION",
    "build_history_coverage",
    "render_history_coverage",
]
