from __future__ import annotations

from dataclasses import dataclass, replace
import re
import sqlite3
from typing import Any

from red_bar_lab.operations.red_bar_v2_ui_snapshot import RedBarV2UISnapshot


_TERMINAL_RE = re.compile(r"OPPORTUNITY_TERMINAL\[([^\]]+)\]")
REFERENCE_LEVEL_TYPE = "NEXT_RED_CANDLE"


@dataclass(frozen=True)
class RedBarV2RuntimeDiagnostics:
    signal_id: str | None = None
    trading_date: str | None = None
    confirmation_timestamp: str | None = None
    signal_age_seconds: float | None = None
    pipeline_updated_at: str | None = None
    monitor_heartbeat: str | None = None
    monitor_state: str | None = None
    market_context_ready: bool | None = None
    volume_structure_ready: bool | None = None
    options_context_ready: bool | None = None
    reference_level_type: str = REFERENCE_LEVEL_TYPE
    reference_found: bool | None = None
    reference_data_quality: str | None = None
    alignment_status: str | None = None
    alignment_blocking_reasons: tuple[str, ...] = ()
    core_eligible: bool | None = None
    hybrid_eligible: bool | None = None
    committee_decision: str | None = None
    committee_reason: str | None = None
    terminal_condition: str | None = None
    candidate_symbol: str | None = None
    candidate_score: float | None = None
    source_status: str = "UNAVAILABLE"

    def to_dict(self) -> dict[str, object]:
        return dict(self.__dict__)


def _database_path(database: Any) -> str | None:
    value = getattr(database, "path", None)
    return str(value) if value else None


def _row(
    conn: sqlite3.Connection,
    query: str,
    params: tuple[object, ...],
) -> dict[str, object]:
    result = conn.execute(query, params).fetchone()
    return dict(result) if result is not None else {}


def _diagnostic_date_expression(
    conn: sqlite3.Connection,
    alias: str = "",
) -> str:
    columns = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(paper_signal_diagnostics)")
    }
    prefix = f"{alias}." if alias else ""
    if "trading_date" in columns:
        return f"{prefix}trading_date"
    return f"substr({prefix}timestamp, 1, 10)"


def _flag(value: object) -> bool | None:
    if value is None:
        return None
    return bool(int(value))


def _option_side(direction: object) -> str | None:
    value = str(direction or "").upper()
    if value == "BULLISH":
        return "CE"
    if value == "BEARISH":
        return "PE"
    return None


def _terminal(detail: object) -> str | None:
    match = _TERMINAL_RE.search(str(detail or ""))
    return match.group(1) if match else None


def _alignment_reasons(
    *,
    pipeline: dict[str, object],
    reference: dict[str, object],
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not pipeline:
        reasons.append("PIPELINE_STATUS_MISSING")
    else:
        for field, code in (
            ("market_context_ready", "MARKET_CONTEXT_NOT_READY"),
            ("volume_structure_ready", "VOLUME_STRUCTURE_NOT_READY"),
            ("options_context_ready", "OPTIONS_CONTEXT_NOT_READY"),
        ):
            if _flag(pipeline.get(field)) is not True:
                reasons.append(code)

    if not reference:
        reasons.append(f"{REFERENCE_LEVEL_TYPE}_REFERENCE_NOT_FOUND")
    elif str(reference.get("data_quality") or "").upper() != "VALID":
        quality = str(reference.get("data_quality") or "UNKNOWN").upper()
        reasons.append(f"REFERENCE_DATA_QUALITY_{quality}")
    return tuple(reasons)


def resolve_red_bar_v2_live_state(
    database: Any,
    snapshot: RedBarV2UISnapshot | None,
    *,
    instrument_key: str,
    trading_date: str,
) -> tuple[RedBarV2UISnapshot | None, RedBarV2RuntimeDiagnostics]:
    """Overlay the file snapshot with current-day persisted runtime facts.

    This reader is UI-only. It does not recalculate RSI/VWAP, create signals,
    alter committee decisions, or write to the database. Red Bar V2 reference
    geometry is resolved from the strategy-owned NEXT_RED_CANDLE level.
    """
    path = _database_path(database)
    if not path:
        return snapshot, RedBarV2RuntimeDiagnostics(
            trading_date=trading_date,
            source_status="DATABASE_UNAVAILABLE",
        )

    try:
        with sqlite3.connect(path) as conn:
            conn.row_factory = sqlite3.Row
            diagnostic_date = _diagnostic_date_expression(conn, "d")
            diagnostic = _row(
                conn,
                f"""
                SELECT d.*
                FROM paper_signal_diagnostics AS d
                WHERE {diagnostic_date}=?
                  AND d.signal_id LIKE 'RBV2-%'
                  AND EXISTS (
                      SELECT 1 FROM signal_pipeline_status AS p
                      WHERE p.signal_id=d.signal_id
                        AND p.trading_date=?
                  )
                ORDER BY d.timestamp DESC, d.id DESC LIMIT 1
                """,
                (trading_date, trading_date),
            )
            if not diagnostic:
                diagnostic_date = _diagnostic_date_expression(conn)
                diagnostic = _row(
                    conn,
                    f"""
                    SELECT * FROM paper_signal_diagnostics
                    WHERE {diagnostic_date}=?
                      AND signal_id LIKE 'RBV2-%'
                    ORDER BY timestamp DESC, id DESC LIMIT 1
                    """,
                    (trading_date,),
                )
            if not diagnostic:
                return snapshot, RedBarV2RuntimeDiagnostics(
                    trading_date=trading_date,
                    source_status="NO_CURRENT_DAY_SIGNAL",
                )

            signal_id = str(diagnostic.get("signal_id") or "")
            pipeline = _row(
                conn,
                """
                SELECT * FROM signal_pipeline_status
                WHERE signal_id=? AND trading_date=?
                ORDER BY updated_at DESC LIMIT 1
                """,
                (signal_id, trading_date),
            )
            reference = _row(
                conn,
                """
                SELECT * FROM reference_levels
                WHERE instrument_key=?
                  AND trading_date=?
                  AND level_type=?
                ORDER BY source_timestamp DESC, id DESC LIMIT 1
                """,
                (instrument_key, trading_date, REFERENCE_LEVEL_TYPE),
            )
            monitor = _row(
                conn,
                """
                SELECT * FROM paper_monitor_status
                ORDER BY updated_at DESC LIMIT 1
                """,
                (),
            )
            committee = _row(
                conn,
                """
                SELECT * FROM execution_state_events
                WHERE signal_id=?
                  AND state IN ('EXECUTION_COMMITTEE', 'DECISION_RECORDED')
                ORDER BY timestamp DESC LIMIT 1
                """,
                (signal_id,),
            )
    except (sqlite3.Error, OSError):
        return snapshot, RedBarV2RuntimeDiagnostics(
            trading_date=trading_date,
            source_status="READ_ERROR",
        )

    direction = str(diagnostic.get("direction") or "").upper() or None
    decision = str(
        diagnostic.get("final_decision")
        or monitor.get("last_decision")
        or ""
    ).upper() or None
    reason = str(
        diagnostic.get("reason")
        or monitor.get("last_reason")
        or ""
    ) or None
    detail = committee.get("detail")

    blocking_reasons = _alignment_reasons(
        pipeline=pipeline,
        reference=reference,
    )
    pipeline_ready = bool(pipeline) and all(
        _flag(pipeline.get(name)) is True
        for name in (
            "market_context_ready",
            "volume_structure_ready",
            "options_context_ready",
        )
    )
    reference_quality = str(
        reference.get("data_quality") or ""
    ).upper() or None
    reference_ready = bool(reference) and reference_quality == "VALID"
    alignment_status = (
        "ALIGNED" if pipeline_ready and reference_ready else "BLOCKED"
    )

    diagnostics = RedBarV2RuntimeDiagnostics(
        signal_id=signal_id or None,
        trading_date=trading_date,
        confirmation_timestamp=(
            str(diagnostic.get("confirmation_timestamp") or "") or None
        ),
        signal_age_seconds=(
            float(diagnostic["signal_age_seconds"])
            if diagnostic.get("signal_age_seconds") is not None
            else None
        ),
        pipeline_updated_at=(
            str(pipeline.get("updated_at") or "") or None
        ),
        monitor_heartbeat=(
            str(monitor.get("heartbeat_at") or "") or None
        ),
        monitor_state=(
            str(monitor.get("current_state") or "") or None
        ),
        market_context_ready=_flag(pipeline.get("market_context_ready")),
        volume_structure_ready=_flag(
            pipeline.get("volume_structure_ready")
        ),
        options_context_ready=_flag(pipeline.get("options_context_ready")),
        reference_found=bool(reference),
        reference_data_quality=reference_quality,
        alignment_status=alignment_status,
        alignment_blocking_reasons=blocking_reasons,
        core_eligible=_flag(pipeline.get("core_eligible")),
        hybrid_eligible=_flag(pipeline.get("hybrid_eligible")),
        committee_decision=decision,
        committee_reason=reason,
        terminal_condition=_terminal(detail),
        candidate_symbol=(
            str(diagnostic.get("best_candidate") or "") or None
        ),
        candidate_score=(
            float(diagnostic["best_score"])
            if diagnostic.get("best_score") is not None
            else None
        ),
        source_status="CURRENT_DAY_RUNTIME",
    )

    base = snapshot or RedBarV2UISnapshot(
        mode="PAPER",
        execution_scope="PAPER_TRADING_ONLY",
    )
    admission_allowed: bool | None
    if decision in {"APPROVE", "APPROVED", "OPEN", "EXECUTE"}:
        admission_allowed = True
    elif decision in {"REJECT", "REJECTED", "SKIP"}:
        admission_allowed = False
    else:
        admission_allowed = None

    resolved = replace(
        base,
        mode="PAPER",
        execution_scope="PAPER_TRADING_ONLY",
        reference_status=(
            "REFERENCE_READY" if reference_ready else "REFERENCE_NOT_READY"
        ),
        reference_timestamp=(
            str(reference.get("source_timestamp") or "") or None
        ),
        reference_high=reference.get("source_high"),
        reference_low=reference.get("source_low"),
        reference_midpoint=(
            reference.get("midpoint")
            if reference.get("midpoint") is not None
            else reference.get("level_value")
        ),
        alignment_status=alignment_status,
        directional_state=(
            "ACTIVE_SIGNAL" if signal_id else base.directional_state
        ),
        direction=direction,
        option_side=_option_side(direction),
        admission_allowed=admission_allowed,
        admission_code=decision,
        admission_reason=reason,
        last_evaluation_timestamp=(
            str(
                diagnostic.get("timestamp")
                or pipeline.get("updated_at")
                or ""
            )
            or None
        ),
        session_completeness=(
            "CURRENT_DAY_ALIGNED"
            if alignment_status == "ALIGNED"
            else "PARTIAL"
        ),
    )
    return resolved, diagnostics


__all__ = [
    "REFERENCE_LEVEL_TYPE",
    "RedBarV2RuntimeDiagnostics",
    "resolve_red_bar_v2_live_state",
]
