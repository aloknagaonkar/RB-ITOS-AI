"""Repository for evaluation and execution lifecycle domains."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from red_bar_lab.storage.database import RedBarDatabase


class EvaluationRepository:
    """Domain-specific repository for evaluation, execution lifecycle, and diagnostic operations."""

    def __init__(self, database: RedBarDatabase) -> None:
        self._db = database

    # ---- Trade Selection Evaluations ----

    def insert_trade_selection_evaluation(self, row: dict[str, object]) -> None:
        self._db.initialize()
        with self._db._connect() as conn:
            conn.execute(
                """
                INSERT INTO trade_selection_evaluations(
                    scan_id,signal_id,trading_date,direction,candidate_rank,
                    candidate_symbol,instrument_token,candidate_score,
                    opportunity_score,reward_remaining_pct,reward_risk_ratio,
                    execution_quality_score,history_sample_size,
                    history_win_rate_pct,history_profit_factor,
                    history_expectancy_pct,history_avg_mfe_pct,
                    history_avg_mae_pct,historical_score,selection_score,
                    evidence_ready,eligible,decision,reason,evaluated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    row.get("scan_id"), row.get("signal_id"), row.get("trading_date"),
                    row.get("direction"), row.get("candidate_rank"),
                    row.get("candidate_symbol"), row.get("instrument_token"),
                    row.get("candidate_score"), row.get("opportunity_score"),
                    row.get("reward_remaining_pct"), row.get("reward_risk_ratio"),
                    row.get("execution_quality_score"), row.get("history_sample_size"),
                    row.get("history_win_rate_pct"), row.get("history_profit_factor"),
                    row.get("history_expectancy_pct"), row.get("history_avg_mfe_pct"),
                    row.get("history_avg_mae_pct"), row.get("historical_score"),
                    row.get("selection_score"), int(bool(row.get("evidence_ready"))),
                    int(bool(row.get("eligible"))), row.get("decision"),
                    row.get("reason"), row.get("evaluated_at"),
                ),
            )
            conn.commit()

    def read_trade_selection_evaluations(
        self, *, signal_id: str | None = None, trading_date: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, object]]:
        self._db.initialize()
        with self._db._connect() as conn:
            conn.row_factory = sqlite3.Row
            if signal_id:
                rows = conn.execute(
                    """SELECT * FROM trade_selection_evaluations
                    WHERE signal_id=? ORDER BY evaluated_at DESC,candidate_rank LIMIT ?""",
                    (signal_id, int(limit)),
                ).fetchall()
            elif trading_date:
                rows = conn.execute(
                    """SELECT * FROM trade_selection_evaluations
                    WHERE trading_date=? ORDER BY evaluated_at DESC,candidate_rank LIMIT ?""",
                    (trading_date, int(limit)),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM trade_selection_evaluations
                    ORDER BY evaluated_at DESC,candidate_rank LIMIT ?""",
                    (int(limit),),
                ).fetchall()
        return [dict(row) for row in rows]

    # ---- Institutional Execution Evaluations ----

    def insert_institutional_execution_evaluation(
        self, row: dict[str, object]
    ) -> None:
        self._db.initialize()
        with self._db._connect() as conn:
            conn.execute(
                """
                INSERT INTO institutional_execution_evaluations(
                    scan_id,signal_id,trading_date,direction,candidate_rank,
                    candidate_symbol,instrument_token,option_type,
                    execution_probability_pct,expected_value_pct,
                    expectancy_pct,expected_win_pct,expected_loss_pct,
                    expectancy_source,expectancy_confidence_pct,kelly_fraction_pct,
                    expected_reward_pct,expected_risk_pct,intelligence_score,
                    adaptive_history_weight_pct,rule_quality_score,
                    opportunity_score,historical_score,selection_score,
                    primary_decision,primary_confidence_pct,shadow_decision,
                    shadow_confidence_pct,agreement,shadow_adjustment_pct,
                    evidence_sample_size,evidence_ready,modules_json,expert_votes_json,eligible,
                    decision,reason,evaluated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    row.get("scan_id"), row.get("signal_id"),
                    row.get("trading_date"), row.get("direction"),
                    row.get("candidate_rank"), row.get("candidate_symbol"),
                    row.get("instrument_token"), row.get("option_type"),
                    row.get("execution_probability_pct"),
                    row.get("expected_value_pct"),
                    row.get("expectancy_pct"), row.get("expected_win_pct"),
                    row.get("expected_loss_pct"), row.get("expectancy_source"),
                    row.get("expectancy_confidence_pct"), row.get("kelly_fraction_pct"),
                    row.get("expected_reward_pct"), row.get("expected_risk_pct"),
                    row.get("intelligence_score"),
                    row.get("adaptive_history_weight_pct"),
                    row.get("rule_quality_score"), row.get("opportunity_score"),
                    row.get("historical_score"), row.get("selection_score"),
                    row.get("primary_decision"), row.get("primary_confidence_pct"),
                    row.get("shadow_decision"), row.get("shadow_confidence_pct"),
                    row.get("agreement"), row.get("shadow_adjustment_pct"),
                    row.get("evidence_sample_size"),
                    int(bool(row.get("evidence_ready"))),
                    json.dumps(row.get("modules") or [], sort_keys=True, default=str),
                    json.dumps(row.get("expert_votes") or [], sort_keys=True, default=str),
                    int(bool(row.get("eligible"))), row.get("decision"),
                    row.get("reason"), row.get("evaluated_at"),
                ),
            )
            conn.commit()

    def read_institutional_execution_evaluations(
        self, *, signal_id: str | None = None, trading_date: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, object]]:
        self._db.initialize()
        clauses = []
        values: list[object] = []
        if signal_id:
            clauses.append("signal_id=?")
            values.append(signal_id)
        if trading_date:
            clauses.append("trading_date=?")
            values.append(trading_date)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        values.append(int(limit))
        with self._db._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""SELECT * FROM institutional_execution_evaluations
                {where} ORDER BY evaluated_at DESC,candidate_rank LIMIT ?""",
                tuple(values),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            try:
                item["modules"] = json.loads(str(item.get("modules_json") or "[]"))
            except Exception:
                item["modules"] = []
            try:
                item["expert_votes"] = json.loads(str(item.get("expert_votes_json") or "[]"))
            except Exception:
                item["expert_votes"] = []
            result.append(item)
        return result

    # ---- Opportunity Evaluations ----

    def insert_opportunity_evaluation(
        self,
        row: dict[str, object],
    ) -> None:
        self._db.initialize()
        with self._db._connect() as conn:
            conn.execute(
                """
                INSERT INTO opportunity_evaluations(
                    scan_id,signal_id,trading_date,direction,
                    signal_age_seconds,entry_mode,candidate_symbol,
                    candidate_score,opportunity_score,
                    structure_score,momentum_score,reward_score,
                    option_health_score,market_context_score,time_score,
                    reward_remaining_pct,move_consumed_pct,
                    structure_valid,opposite_red_bar,eligible,
                    decision,reason,evaluated_at
                )
                VALUES(
                    ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
                )
                """,
                (
                    row.get("scan_id"),
                    row.get("signal_id"),
                    row.get("trading_date"),
                    row.get("direction"),
                    row.get("signal_age_seconds"),
                    row.get("entry_mode"),
                    row.get("candidate_symbol"),
                    row.get("candidate_score"),
                    row.get("opportunity_score"),
                    row.get("structure_score"),
                    row.get("momentum_score"),
                    row.get("reward_score"),
                    row.get("option_health_score"),
                    row.get("market_context_score"),
                    row.get("time_score"),
                    row.get("reward_remaining_pct"),
                    row.get("move_consumed_pct"),
                    int(bool(row.get("structure_valid"))),
                    int(bool(row.get("opposite_red_bar"))),
                    int(bool(row.get("eligible"))),
                    row.get("decision"),
                    row.get("reason"),
                    row.get("evaluated_at"),
                ),
            )
            conn.commit()

    def read_opportunity_evaluations(
        self,
        *,
        limit: int = 100,
        signal_id: str | None = None,
        entry_mode: str | None = None,
    ) -> list[dict[str, object]]:
        self._db.initialize()
        clauses = []
        values: list[object] = []
        if signal_id:
            clauses.append("signal_id=?")
            values.append(signal_id)
        if entry_mode:
            clauses.append("entry_mode=?")
            values.append(entry_mode)
        where = (
            "WHERE " + " AND ".join(clauses)
            if clauses else ""
        )
        values.append(int(limit))
        with self._db._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT *
                FROM opportunity_evaluations
                {where}
                ORDER BY evaluated_at DESC
                LIMIT ?
                """,
                tuple(values),
            ).fetchall()
        return [dict(row) for row in rows]

    # ---- Shadow Intelligence Evaluations ----

    def insert_shadow_intelligence_evaluation(
        self,
        row: dict[str, object],
    ) -> None:
        self._db.initialize()
        with self._db._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO shadow_intelligence_evaluations(
                    signal_id,trading_date,current_decision,shadow_decision,
                    shadow_confidence,agreement,portfolio_conflict,
                    portfolio_action,execution_impact,modules_json,evaluated_at
                )
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    row.get("signal_id"),
                    row.get("trading_date"),
                    row.get("current_decision") or "WAIT",
                    row.get("shadow_decision") or "WAIT",
                    float(row.get("shadow_confidence") or 0.0),
                    row.get("agreement") or "UNKNOWN",
                    int(bool(row.get("portfolio_conflict"))),
                    row.get("portfolio_action"),
                    "NONE",
                    json.dumps(
                        row.get("modules") or [],
                        sort_keys=True,
                        default=str,
                    ),
                    row.get("evaluated_at")
                    or datetime.now().astimezone().isoformat(),
                ),
            )
            conn.commit()

    def read_shadow_intelligence_evaluations(
        self,
        *,
        signal_id: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, object]]:
        self._db.initialize()
        with self._db._connect() as conn:
            conn.row_factory = sqlite3.Row
            if signal_id:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM shadow_intelligence_evaluations
                    WHERE signal_id=?
                    ORDER BY evaluated_at DESC
                    LIMIT ?
                    """,
                    (signal_id, int(limit)),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM shadow_intelligence_evaluations
                    ORDER BY evaluated_at DESC
                    LIMIT ?
                    """,
                    (int(limit),),
                ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            try:
                item["modules"] = json.loads(
                    str(item.get("modules_json") or "[]")
                )
            except Exception:
                item["modules"] = []
            result.append(item)
        return result

    # ---- Execution State Events ----

    def insert_execution_state_event(
        self,
        row: dict[str, object],
    ) -> None:
        self._db.initialize()
        with self._db._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO execution_state_events(
                    event_id,signal_id,order_id,state,detail,
                    candidate_score,timestamp
                )
                VALUES(?,?,?,?,?,?,?)
                """,
                (
                    row.get("event_id"),
                    row.get("signal_id"),
                    row.get("order_id"),
                    row.get("state"),
                    row.get("detail"),
                    row.get("candidate_score"),
                    row.get("timestamp"),
                ),
            )
            conn.commit()

    def read_execution_state_events(
        self,
        *,
        signal_id: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, object]]:
        self._db.initialize()
        with self._db._connect() as conn:
            conn.row_factory = sqlite3.Row
            if signal_id:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM execution_state_events
                    WHERE signal_id=?
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (signal_id, int(limit)),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM execution_state_events
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (int(limit),),
                ).fetchall()
        return [dict(row) for row in rows]

    def read_execution_state_events_for_signals(
        self,
        signal_ids: Iterable[str],
        *,
        per_signal_limit: int = 50,
    ) -> dict[str, list[dict[str, object]]]:
        """Batch-load newest lifecycle events for multiple signals."""
        self._db.initialize()
        ids = tuple(dict.fromkeys(str(item) for item in signal_ids if str(item)))
        if not ids:
            return {}
        limit = max(1, int(per_signal_limit))
        result: dict[str, list[dict[str, object]]] = {key: [] for key in ids}
        with self._db._connect() as conn:
            conn.row_factory = sqlite3.Row
            for start in range(0, len(ids), 400):
                chunk = ids[start:start + 400]
                placeholders = ",".join("?" for _ in chunk)
                query = f"""
                    SELECT event_id,signal_id,order_id,state,detail,candidate_score,timestamp
                    FROM (
                        SELECT *,
                               ROW_NUMBER() OVER (
                                   PARTITION BY signal_id
                                   ORDER BY timestamp DESC
                               ) AS rn
                        FROM execution_state_events
                        WHERE signal_id IN ({placeholders})
                    ) ranked
                    WHERE rn <= ?
                    ORDER BY signal_id, timestamp DESC
                """
                rows = conn.execute(query, chunk + (limit,)).fetchall()
                for row in rows:
                    key = str(row["signal_id"] or "")
                    if key:
                        result.setdefault(key, []).append(dict(row))
        return result

    # ---- Execution Queue ----

    def upsert_execution_queue_item(self, row: dict[str, object]) -> None:
        self._db.initialize()
        now = datetime.now().astimezone().isoformat()
        with self._db._connect() as conn:
            conn.execute(
                """
                INSERT INTO execution_queue(
                    queue_id,signal_id,trading_date,direction,candidate_rank,
                    candidate_symbol,instrument_token,exchange,option_type,strike,
                    expiry,lot_size,quantity,candidate_score,selection_score,
                    execution_probability_pct,expected_value_pct,opportunity_score,
                    entry_mode,signal_age_seconds,status,reason,order_id,created_at,
                    updated_at,executed_at,execution_strategy_source,
                    strategy_stop_loss_pct,strategy_target_pct,exit_mode,
                    evaluation_horizon_minutes,signal_sources_json,merge_status,
                    rsi_signal_id,rsi_confirmation_timestamp
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(signal_id,instrument_token) DO UPDATE SET
                    trading_date=excluded.trading_date,
                    direction=excluded.direction,
                    candidate_rank=excluded.candidate_rank,
                    candidate_symbol=excluded.candidate_symbol,
                    exchange=excluded.exchange,
                    option_type=excluded.option_type,
                    strike=excluded.strike,
                    expiry=excluded.expiry,
                    lot_size=excluded.lot_size,
                    quantity=excluded.quantity,
                    candidate_score=excluded.candidate_score,
                    selection_score=excluded.selection_score,
                    execution_probability_pct=excluded.execution_probability_pct,
                    expected_value_pct=excluded.expected_value_pct,
                    opportunity_score=excluded.opportunity_score,
                    entry_mode=excluded.entry_mode,
                    signal_age_seconds=excluded.signal_age_seconds,
                    execution_strategy_source=excluded.execution_strategy_source,
                    strategy_stop_loss_pct=excluded.strategy_stop_loss_pct,
                    strategy_target_pct=excluded.strategy_target_pct,
                    exit_mode=excluded.exit_mode,
                    evaluation_horizon_minutes=excluded.evaluation_horizon_minutes,
                    signal_sources_json=excluded.signal_sources_json,
                    merge_status=excluded.merge_status,
                    rsi_signal_id=excluded.rsi_signal_id,
                    rsi_confirmation_timestamp=excluded.rsi_confirmation_timestamp,
                    status=CASE
                        WHEN execution_queue.status IN ('EXECUTED','ACTIVE','CLOSED')
                            THEN execution_queue.status
                        ELSE excluded.status
                    END,
                    reason=CASE
                        WHEN execution_queue.status IN ('EXECUTED','ACTIVE','CLOSED')
                            THEN execution_queue.reason
                        ELSE excluded.reason
                    END,
                    updated_at=excluded.updated_at
                """,
                (
                    row.get('queue_id'), row.get('signal_id'), row.get('trading_date'),
                    row.get('direction'), row.get('candidate_rank'),
                    row.get('candidate_symbol'), row.get('instrument_token'),
                    row.get('exchange') or 'NFO', row.get('option_type'), row.get('strike'),
                    row.get('expiry'), int(row.get('lot_size') or 1),
                    int(row.get('quantity') or 0), row.get('candidate_score'),
                    row.get('selection_score'), row.get('execution_probability_pct'),
                    row.get('expected_value_pct'), row.get('opportunity_score'),
                    row.get('entry_mode'), row.get('signal_age_seconds'),
                    row.get('status'), row.get('reason'), row.get('order_id'),
                    row.get('created_at') or now, row.get('updated_at') or now,
                    row.get('executed_at'),
                    row.get('execution_strategy_source'),
                    row.get('strategy_stop_loss_pct'),
                    row.get('strategy_target_pct'),
                    row.get('exit_mode'),
                    row.get('evaluation_horizon_minutes'),
                    json.dumps(row.get('signal_sources') or [], sort_keys=True, default=str),
                    row.get('merge_status'),
                    row.get('rsi_signal_id'),
                    row.get('rsi_confirmation_timestamp'),
                ),
            )
            conn.commit()

    def read_execution_queue(
        self, *, status: str | None = None, signal_id: str | None = None,
        trading_date: str | None = None, limit: int = 200,
    ) -> list[dict[str, object]]:
        self._db.initialize()
        clauses = []
        values: list[object] = []
        if status:
            clauses.append('status=?')
            values.append(status)
        if signal_id:
            clauses.append('signal_id=?')
            values.append(signal_id)
        if trading_date:
            clauses.append('trading_date=?')
            values.append(trading_date)
        where = ('WHERE ' + ' AND '.join(clauses)) if clauses else ''
        values.append(int(limit))
        with self._db._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""SELECT * FROM execution_queue {where}
                ORDER BY CASE status
                    WHEN 'EXECUTING' THEN 0 WHEN 'APPROVED' THEN 1
                    WHEN 'WAITING' THEN 2 WHEN 'REJECTED' THEN 3 ELSE 4 END,
                    expected_value_pct DESC, execution_probability_pct DESC,
                    candidate_rank ASC LIMIT ?""",
                tuple(values),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_execution_queue_status(
        self, *, queue_id: str, status: str, reason: str | None = None,
        order_id: str | None = None, executed_at: str | None = None,
    ) -> None:
        self._db.initialize()
        now = datetime.now().astimezone().isoformat()
        with self._db._connect() as conn:
            conn.execute(
                """UPDATE execution_queue SET status=?, reason=COALESCE(?,reason),
                order_id=COALESCE(?,order_id), updated_at=?,
                executed_at=COALESCE(?,executed_at) WHERE queue_id=?""",
                (status, reason, order_id, now, executed_at, queue_id),
            )
            conn.commit()

    def update_execution_queue_for_order(
        self, *, order_id: str, status: str, reason: str | None = None,
    ) -> None:
        self._db.initialize()
        now = datetime.now().astimezone().isoformat()
        with self._db._connect() as conn:
            conn.execute(
                """UPDATE execution_queue SET status=?, reason=COALESCE(?,reason),
                updated_at=? WHERE order_id=?""",
                (status, reason, now, order_id),
            )
            conn.commit()

    def expire_execution_queue_for_signal(self, *, signal_id: str, reason: str) -> None:
        with self._db._connect() as conn:
            conn.execute(
                """UPDATE execution_queue
                   SET status='EXPIRED', reason=?, updated_at=?
                   WHERE signal_id=? AND status IN ('APPROVED','WAITING','REJECTED')""",
                (reason, datetime.now().isoformat(), signal_id),
            )

    # ---- Candidate Lifecycle ----

    def upsert_candidate_lifecycle(self, row: dict[str, object]) -> None:
        now = str(row.get("updated_at") or datetime.now().isoformat())
        created = str(row.get("created_at") or now)
        with self._db._connect() as conn:
            conn.execute(
                """
                INSERT INTO candidate_lifecycle(
                    candidate_id, signal_id, trading_date, candidate_symbol,
                    instrument_token, state, health_score, age_seconds,
                    created_session, current_session, market_drift, duplicate,
                    reason, action, replacement_required, replacement_signal_id,
                    created_at, updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(candidate_id) DO UPDATE SET
                    state=excluded.state, health_score=excluded.health_score,
                    age_seconds=excluded.age_seconds,
                    created_session=excluded.created_session,
                    current_session=excluded.current_session,
                    market_drift=excluded.market_drift, duplicate=excluded.duplicate,
                    reason=excluded.reason, action=excluded.action,
                    replacement_required=excluded.replacement_required,
                    replacement_signal_id=excluded.replacement_signal_id,
                    updated_at=excluded.updated_at
                """,
                (
                    row.get("candidate_id"), row.get("signal_id"),
                    row.get("trading_date"), row.get("candidate_symbol"),
                    row.get("instrument_token"), row.get("state"),
                    row.get("health_score"), row.get("age_seconds"),
                    row.get("created_session"), row.get("current_session"),
                    row.get("market_drift"), int(bool(row.get("duplicate"))),
                    row.get("reason"), row.get("action"),
                    int(bool(row.get("replacement_required"))),
                    row.get("replacement_signal_id"), created, now,
                ),
            )

    def read_candidate_lifecycle(
        self, *, signal_id: str | None = None, state: str | None = None, limit: int = 100
    ) -> list[dict[str, object]]:
        clauses = []
        params: list[object] = []
        if signal_id:
            clauses.append("signal_id=?")
            params.append(signal_id)
        if state:
            clauses.append("state=?")
            params.append(state)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(int(limit))
        with self._db._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"SELECT * FROM candidate_lifecycle {where} ORDER BY updated_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    # ---- Paper Candidate Decisions ----

    def upsert_paper_candidate_decision(
        self,
        row: dict[str, object],
    ) -> None:
        self._db.initialize()
        now = datetime.now().astimezone().isoformat()
        with self._db._connect() as conn:
            conn.execute(
                """
                INSERT INTO paper_candidate_decisions(
                    signal_id,trading_date,direction,tradingsymbol,
                    instrument_token,option_type,strike,expiry,
                    candidate_score,score_detail,decision,
                    created_at,updated_at
                )
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(signal_id) DO UPDATE SET
                    direction=excluded.direction,
                    tradingsymbol=excluded.tradingsymbol,
                    instrument_token=excluded.instrument_token,
                    option_type=excluded.option_type,
                    strike=excluded.strike,
                    expiry=excluded.expiry,
                    candidate_score=excluded.candidate_score,
                    score_detail=excluded.score_detail,
                    decision=excluded.decision,
                    updated_at=excluded.updated_at
                """,
                (
                    row.get("signal_id"),
                    row.get("trading_date"),
                    row.get("direction"),
                    row.get("tradingsymbol"),
                    row.get("instrument_token"),
                    row.get("option_type"),
                    row.get("strike"),
                    row.get("expiry"),
                    row.get("candidate_score"),
                    row.get("score_detail"),
                    row.get("decision"),
                    now,
                    now,
                ),
            )
            conn.commit()

    def read_paper_candidate_decision(
        self,
        signal_id: str,
    ) -> dict[str, object] | None:
        self._db.initialize()
        with self._db._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT *
                FROM paper_candidate_decisions
                WHERE signal_id=?
                """,
                (signal_id,),
            ).fetchone()
        return dict(row) if row else None

    def read_paper_candidate_decisions(
        self,
        trading_date: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, object]]:
        self._db.initialize()
        with self._db._connect() as conn:
            conn.row_factory = sqlite3.Row
            if trading_date:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM paper_candidate_decisions
                    WHERE trading_date=?
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (trading_date, int(limit)),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM paper_candidate_decisions
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (int(limit),),
                ).fetchall()
        return [dict(row) for row in rows]

    # ---- Paper Monitor Status ----

    def upsert_paper_monitor_status(
        self,
        row: dict[str, object],
    ) -> None:
        self._db.initialize()
        now = datetime.now().astimezone().isoformat()
        monitor_id = str(row.get("monitor_id") or "PAPER-MONITOR")
        with self._db._connect() as conn:
            conn.execute(
                """
                INSERT INTO paper_monitor_status(
                    monitor_id,status,heartbeat_at,last_scan_at,started_at,
                    underlying_name,signals_seen,signals_qualified,
                    candidates_scored,orders_opened,orders_closed,
                    signals_skipped,current_state,last_signal_id,
                    last_decision,last_reason,last_error,
                    last_success_at,last_success_decision,
                    last_success_signal_id,last_success_total_ms,
                    last_success_stages_json,updated_at
                )
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(monitor_id) DO UPDATE SET
                    status=excluded.status,
                    heartbeat_at=excluded.heartbeat_at,
                    last_scan_at=excluded.last_scan_at,
                    started_at=COALESCE(
                        paper_monitor_status.started_at,
                        excluded.started_at
                    ),
                    underlying_name=excluded.underlying_name,
                    signals_seen=excluded.signals_seen,
                    signals_qualified=excluded.signals_qualified,
                    candidates_scored=excluded.candidates_scored,
                    orders_opened=excluded.orders_opened,
                    orders_closed=excluded.orders_closed,
                    signals_skipped=excluded.signals_skipped,
                    current_state=excluded.current_state,
                    last_signal_id=excluded.last_signal_id,
                    last_decision=excluded.last_decision,
                    last_reason=excluded.last_reason,
                    last_error=excluded.last_error,
                    updated_at=excluded.updated_at
                """,
                (
                    monitor_id,
                    row.get("status") or "UNKNOWN",
                    row.get("heartbeat_at"),
                    row.get("last_scan_at"),
                    row.get("started_at"),
                    row.get("underlying_name"),
                    int(row.get("signals_seen") or 0),
                    int(row.get("signals_qualified") or 0),
                    int(row.get("candidates_scored") or 0),
                    int(row.get("orders_opened") or 0),
                    int(row.get("orders_closed") or 0),
                    int(row.get("signals_skipped") or 0),
                    row.get("current_state"),
                    row.get("last_signal_id"),
                    row.get("last_decision"),
                    row.get("last_reason"),
                    row.get("last_error"),
                    None,  # last_success_at — written by specialized helper
                    None,  # last_success_decision
                    None,  # last_success_signal_id
                    None,  # last_success_total_ms
                    None,  # last_success_stages_json
                    now,
                ),
            )
            conn.commit()

    def record_paper_monitor_success(
        self,
        monitor_id: str,
        *,
        success_at: str,
        decision: str | None,
        signal_id: str | None,
        total_ms: float | None,
        stages: dict[str, float] | None,
        underlying_status: str | None = None,
        readiness_ms: float | None = None,
        futures_status: str | None = None,
        candle_timestamp: str | None = None,
        candle_age_seconds: float | None = None,
        bridge_alignment: str | None = None,
        readiness_reason: str | None = None,
    ) -> None:
        """Update only the last-success fields on an existing status row.

        Called by the paper monitor after a cycle that is not a circuit
        breaker trip and not an exception, so the UI can show "last
        successful cycle" details that survive subsequent SUSPENDED/
        FAILED cycles.
        """
        import json as _json

        self._db.initialize()
        stages_json = _json.dumps(stages) if stages else None
        with self._db._connect() as conn:
            conn.execute(
                """
                UPDATE paper_monitor_status SET
                    last_success_at=?,
                    last_success_decision=?,
                    last_success_signal_id=?,
                    last_success_total_ms=?,
                    last_success_stages_json=?,
                    last_success_underlying_status=?,
                    last_success_readiness_ms=?,
                    last_success_futures_status=?,
                    last_success_candle_timestamp=?,
                    last_success_candle_age_seconds=?,
                    last_success_bridge_alignment=?,
                    last_success_readiness_reason=?
                WHERE monitor_id=?
                """,
                (
                    success_at,
                    decision,
                    signal_id,
                    float(total_ms) if total_ms is not None else None,
                    stages_json,
                    underlying_status,
                    float(readiness_ms) if readiness_ms is not None else None,
                    futures_status,
                    candle_timestamp,
                    float(candle_age_seconds)
                    if candle_age_seconds is not None
                    else None,
                    bridge_alignment,
                    readiness_reason,
                    monitor_id,
                ),
            )
            conn.commit()

    def read_paper_monitor_status(
        self,
        monitor_id: str = "PAPER-MONITOR",
    ) -> dict[str, object] | None:
        self._db.initialize()
        with self._db._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT *
                FROM paper_monitor_status
                WHERE monitor_id=?
                """,
                (monitor_id,),
            ).fetchone()
        return dict(row) if row else None

    # ---- Process Evidence ----

    def write_step_evidence(
        self,
        *,
        process_name: str,
        run_id: str,
        step_name: str,
        parent_step: str | None,
        started_at: str,
        status: str,
        artifacts: dict[str, object] | None = None,
    ) -> int:
        """Insert a new step evidence row. Returns the inserted row id."""
        import json as _json

        self._db.initialize()
        artifacts_json = _json.dumps(artifacts) if artifacts else None
        with self._db._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO process_evidence(
                    process_name, run_id, step_name, parent_step,
                    started_at, status, artifacts_json
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    process_name,
                    run_id,
                    step_name,
                    parent_step,
                    started_at,
                    status,
                    artifacts_json,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def update_step_evidence(
        self,
        *,
        step_id: int,
        completed_at: str,
        status: str,
        duration_ms: float,
        error_message: str | None = None,
    ) -> None:
        """Mark a step as completed (or errored) with its final duration."""
        self._db.initialize()
        with self._db._connect() as conn:
            conn.execute(
                """
                UPDATE process_evidence SET
                    completed_at=?,
                    status=?,
                    duration_ms=?,
                    error_message=?
                WHERE id=?
                """,
                (
                    completed_at,
                    status,
                    float(duration_ms) if duration_ms is not None else None,
                    error_message,
                    step_id,
                ),
            )
            conn.commit()

    def read_step_timelines(
        self,
        *,
        process_name: str | None = None,
        limit_per_step: int = 5,
    ) -> dict[str, list[dict[str, object]]]:
        """Return the most recent N evidence rows per (process_name, step_name).

        Returns: {step_name: [row, row, ...]} where each row has all columns
        from process_evidence plus parsed artifacts as a dict.
        """
        import json as _json

        self._db.initialize()
        where = ""
        params: tuple = ()
        if process_name is not None:
            where = "WHERE process_name=?"
            params = (process_name,)
        with self._db._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT *
                FROM process_evidence
                {where}
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (*params, limit_per_step * 50),
            ).fetchall()
        # Group by (process_name, step_name), keep the most recent N.
        grouped: dict[str, list[dict[str, object]]] = {}
        for row in rows:
            row_dict = dict(row)
            artifacts_raw = row_dict.pop("artifacts_json", None)
            if artifacts_raw:
                try:
                    row_dict["artifacts"] = _json.loads(artifacts_raw)
                except (TypeError, ValueError):
                    row_dict["artifacts"] = None
            else:
                row_dict["artifacts"] = None
            key = f"{row_dict['process_name']}::{row_dict['step_name']}"
            if key not in grouped:
                grouped[key] = []
            if len(grouped[key]) < limit_per_step:
                grouped[key].append(row_dict)
        return grouped

    def read_latest_step_evidence(
        self,
        *,
        process_name: str,
        step_name: str,
    ) -> dict[str, object] | None:
        """Return the most recent evidence row for a single (process, step)."""
        import json as _json

        self._db.initialize()
        with self._db._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT *
                FROM process_evidence
                WHERE process_name=? AND step_name=?
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (process_name, step_name),
            ).fetchone()
        if row is None:
            return None
        d = dict(row)
        raw = d.pop("artifacts_json", None)
        if raw:
            try:
                d["artifacts"] = _json.loads(raw)
            except (TypeError, ValueError):
                d["artifacts"] = None
        else:
            d["artifacts"] = None
        return d

    def read_running_steps(
        self,
        *,
        older_than_seconds: float = 60.0,
    ) -> list[dict[str, object]]:
        """Return evidence rows that started but never completed (stuck)."""
        self._db.initialize()
        import time as _time

        now = _time.time()
        with self._db._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM process_evidence
                WHERE status='RUNNING'
                """
            ).fetchall()
        result: list[dict[str, object]] = []
        for row in rows:
            d = dict(row)
            try:
                from datetime import datetime

                parsed = datetime.fromisoformat(
                    d["started_at"].replace("Z", "+00:00")
                )
                age = now - parsed.timestamp()
            except (TypeError, ValueError):
                age = 0.0
            if age >= older_than_seconds:
                d["stuck_for_seconds"] = age
                result.append(d)
        return result

    # ---- Process Run Correlation ----

    def write_process_run_correlation(
        self,
        *,
        process_name: str,
        run_id: str,
        started_at: str,
        artifacts: dict[str, object] | None = None,
    ) -> None:
        """Record the most recent run_id for a process. Other processes
        can read this to correlate their cycles with the upstream."""
        import json as _json

        self._db.initialize()
        artifacts_json = _json.dumps(artifacts) if artifacts else None
        with self._db._connect() as conn:
            conn.execute(
                """
                INSERT INTO process_run_correlation(
                    process_name, run_id, started_at, artifacts_json
                ) VALUES(?,?,?,?)
                ON CONFLICT(process_name) DO UPDATE SET
                    run_id=excluded.run_id,
                    started_at=excluded.started_at,
                    artifacts_json=excluded.artifacts_json
                """,
                (process_name, run_id, started_at, artifacts_json),
            )
            conn.commit()

    def read_process_run_correlation(
        self, *, process_name: str
    ) -> dict[str, object] | None:
        self._db.initialize()
        with self._db._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT *
                FROM process_run_correlation
                WHERE process_name=?
                """,
                (process_name,),
            ).fetchone()
        if row is None:
            return None
        d = dict(row)
        raw = d.pop("artifacts_json", None)
        if raw:
            try:
                d["artifacts"] = json.loads(raw) if not isinstance(raw, dict) else raw
            except (TypeError, ValueError):
                d["artifacts"] = None
        else:
            d["artifacts"] = None
        return d

    def read_all_process_run_correlations(self) -> list[dict[str, object]]:
        """Return all process run correlations, sorted by started_at desc."""
        self._db.initialize()
        with self._db._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM process_run_correlation
                ORDER BY started_at DESC
                """
            ).fetchall()
        out: list[dict[str, object]] = []
        for row in rows:
            d = dict(row)
            raw = d.pop("artifacts_json", None)
            if raw:
                try:
                    d["artifacts"] = (
                        json.loads(raw) if not isinstance(raw, dict) else raw
                    )
                except (TypeError, ValueError):
                    d["artifacts"] = None
            else:
                d["artifacts"] = None
            out.append(d)
        return out

    def read_run_evidence(self, *, run_id: str) -> list[dict[str, object]]:
        """Return all evidence rows for a single run_id, ordered by time."""
        import json as _json

        self._db.initialize()
        with self._db._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM process_evidence
                WHERE run_id=?
                ORDER BY started_at ASC
                """,
                (run_id,),
            ).fetchall()
        out: list[dict[str, object]] = []
        for row in rows:
            d = dict(row)
            raw = d.pop("artifacts_json", None)
            if raw:
                try:
                    d["artifacts"] = _json.loads(raw)
                except (TypeError, ValueError):
                    d["artifacts"] = None
            else:
                d["artifacts"] = None
            out.append(d)
        return out

    def read_evidence_run_ids(
        self,
        *,
        process_name: str,
        step_name: str,
        date_prefix: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, object]]:
        """Return the newest run_ids that recorded a given step, one row each.

        ``date_prefix`` matches the leading characters of ``started_at``, which is
        an ISO timestamp -- so a ``YYYY-MM-DD`` prefix scopes the read to one day.
        Needed because the ladder page must find the cycles for a chosen date, and
        every other evidence reader here is keyed by run_id or is global.

        Note that ``record_strategy_subcheck`` stamps ``started_at`` in UTC. For a
        session that trades 09:15-15:30 IST the UTC date is the same date, so a
        trading-date prefix is exact; a row written before 05:30 IST would file
        under the previous day, which no strategy cycle does.
        """
        self._db.initialize()
        clauses = ["process_name=?", "step_name=?"]
        params: list[object] = [process_name, step_name]
        if date_prefix:
            clauses.append("started_at LIKE ?")
            params.append(f"{date_prefix}%")
        params.append(max(1, int(limit)))
        with self._db._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT run_id, MAX(started_at) AS started_at, COUNT(*) AS rows_seen
                FROM process_evidence
                WHERE {" AND ".join(clauses)}
                GROUP BY run_id
                ORDER BY started_at DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [dict(row) for row in rows]

    def read_latest_error_per_process(self) -> list[dict[str, object]]:
        """Return the most recent ERROR row per process, with the
        duration since that error started (computed from
        ``process_run_correlation``'s last-started-at, or from the
        evidence row's own started_at if no later run exists).

        Used by the cadence panel to surface "this process has been
        failing for 47 minutes" banners.
        """
        import time as _time

        self._db.initialize()
        now = _time.time()
        with self._db._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT process_name, step_name, started_at, completed_at,
                       error_message, run_id, duration_ms
                FROM process_evidence
                WHERE status='ERROR'
                GROUP BY process_name
                HAVING started_at = MAX(started_at)
                ORDER BY started_at DESC
                """
            ).fetchall()
        out: list[dict[str, object]] = []
        for row in rows:
            d = dict(row)
            try:
                from datetime import datetime

                parsed = datetime.fromisoformat(
                    d["started_at"].replace("Z", "+00:00")
                )
                age = max(0.0, now - parsed.timestamp())
            except (TypeError, ValueError):
                age = 0.0
            d["error_age_seconds"] = age
            out.append(d)
        return out

    def cleanup_process_evidence(
        self, *, retention_days: int = 7
    ) -> int:
        """Delete ``process_evidence`` rows older than ``retention_days``.

        Also deletes ``process_run_correlation`` rows older than the
        cutoff, since they're useless without their evidence rows.

        Returns the number of rows deleted.
        """
        from datetime import datetime, timezone, timedelta

        self._db.initialize()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        deleted = 0
        with self._db._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM process_evidence WHERE started_at < ?", (cutoff,)
            )
            deleted += cursor.rowcount or 0
            conn.execute(
                "DELETE FROM process_run_correlation WHERE started_at < ?",
                (cutoff,),
            )
            conn.commit()
        return int(deleted)

    def read_last_cleanup_at(self) -> str | None:
        """Return the ISO timestamp of the last successful cleanup, or
        None if cleanup has never run."""
        self._db.initialize()
        with self._db._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT started_at FROM process_run_correlation "
                "WHERE process_name='_evidence_cleanup' "
                "ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return str(row["started_at"])

    def write_last_cleanup_at(self, started_at: str) -> None:
        """Record that a cleanup just ran. Uses the correlation table
        itself as a tiny key-value store keyed by ``_evidence_cleanup``."""
        self._db.initialize()
        with self._db._connect() as conn:
            conn.execute(
                """
                INSERT INTO process_run_correlation(
                    process_name, run_id, started_at, artifacts_json
                ) VALUES(?,?,?,?)
                ON CONFLICT(process_name) DO UPDATE SET
                    run_id=excluded.run_id,
                    started_at=excluded.started_at,
                    artifacts_json=excluded.artifacts_json
                """,
                ("_evidence_cleanup", "cleanup", started_at, None),
            )
            conn.commit()

    # ---- Paper Signal Diagnostics ----

    def insert_paper_signal_diagnostic(
        self,
        row: dict[str, object],
    ) -> None:
        self._db.initialize()
        with self._db._connect() as conn:
            conn.execute(
                """
                INSERT INTO paper_signal_diagnostics(
                    scan_id,signal_id,signal_state,direction,
                    confirmation_timestamp,signal_age_seconds,
                    market_hours_ok,freshness_ok,duplicate_free,
                    candidate_available,best_candidate,best_score,
                    minimum_score,score_ok,final_decision,reason,timestamp
                )
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    row.get("scan_id"),
                    row.get("signal_id"),
                    row.get("signal_state"),
                    row.get("direction"),
                    row.get("confirmation_timestamp"),
                    row.get("signal_age_seconds"),
                    int(bool(row.get("market_hours_ok"))),
                    int(bool(row.get("freshness_ok"))),
                    int(bool(row.get("duplicate_free"))),
                    int(bool(row.get("candidate_available"))),
                    row.get("best_candidate"),
                    row.get("best_score"),
                    row.get("minimum_score"),
                    int(bool(row.get("score_ok"))),
                    row.get("final_decision"),
                    row.get("reason"),
                    row.get("timestamp"),
                ),
            )
            conn.commit()

    def read_paper_signal_diagnostics(
        self,
        *,
        limit: int = 100,
        signal_id: str | None = None,
    ) -> list[dict[str, object]]:
        self._db.initialize()
        with self._db._connect() as conn:
            conn.row_factory = sqlite3.Row
            if signal_id:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM paper_signal_diagnostics
                    WHERE signal_id=?
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (signal_id, int(limit)),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM paper_signal_diagnostics
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (int(limit),),
                ).fetchall()
        return [dict(row) for row in rows]

    def read_latest_option_chain_snapshot(
        self,
        instrument_key: str,
        trading_date: str,
    ) -> dict[str, object] | None:
        """Return the most recent option chain snapshot for readiness checks."""
        self._db.initialize()
        with self._db._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT snapshot_timestamp, option_expiry, atm_strike
                FROM option_chain_snapshot_history
                WHERE instrument_key=? AND trading_date=?
                ORDER BY snapshot_timestamp DESC
                LIMIT 1
                """,
                (instrument_key, trading_date),
            ).fetchone()
        return dict(row) if row else None

    # ---- Paper Entry Intelligence Update ----

    def update_paper_entry_intelligence(
        self,
        *,
        order_id: str,
        entry_mode: str,
        signal_age_at_entry: float | None,
        opportunity_score: float | None,
        reward_remaining_pct: float | None,
        candidate_rank: int | None = None,
        candidate_score: float | None = None,
        selection_score: float | None = None,
        historical_win_rate_pct: float | None = None,
        historical_profit_factor: float | None = None,
        historical_expectancy_pct: float | None = None,
        historical_sample_size: int | None = None,
        execution_probability_pct: float | None = None,
        expected_value_pct: float | None = None,
        intelligence_score: float | None = None,
    ) -> None:
        self._db.initialize()
        with self._db._connect() as conn:
            conn.execute(
                """
                UPDATE paper_execution_orders
                SET entry_mode=?,
                    signal_age_at_entry=?,
                    opportunity_score=?,
                    reward_remaining_pct=?,
                    candidate_rank=?,
                    candidate_score=?,
                    selection_score=?,
                    historical_win_rate_pct=?,
                    historical_profit_factor=?,
                    historical_expectancy_pct=?,
                    historical_sample_size=?,
                    execution_probability_pct=?,
                    expected_value_pct=?,
                    intelligence_score=?,
                    updated_at=?
                WHERE order_id=?
                """,
                (
                    entry_mode,
                    signal_age_at_entry,
                    opportunity_score,
                    reward_remaining_pct,
                    candidate_rank,
                    candidate_score,
                    selection_score,
                    historical_win_rate_pct,
                    historical_profit_factor,
                    historical_expectancy_pct,
                    historical_sample_size,
                    execution_probability_pct,
                    expected_value_pct,
                    intelligence_score,
                    datetime.now().astimezone().isoformat(),
                    order_id,
                ),
            )
            conn.commit()

    # ---- Trading-View Aggregations ----

    def read_latest_signal_for_trading(
        self, *, instrument_key: str, trading_date: str
    ) -> dict[str, object] | None:
        """Return the most recent confirmed signal for the given date,
        along with its Section 1 / 2 / 3 verdict from the canonical V2
        shadow. Used by the trading view of the cadence panel.

        Returns None if no signal exists for that date.
        """
        self._db.initialize()
        # 1. The latest confirmed signal.
        with self._db._connect() as conn:
            conn.row_factory = sqlite3.Row
            sig_row = conn.execute(
                """
                SELECT *
                FROM signal_attempts
                WHERE instrument_key=? AND trading_date=? AND state='CONFIRMED'
                ORDER BY confirmation_timestamp DESC, created_at DESC
                LIMIT 1
                """,
                (instrument_key, trading_date),
            ).fetchone()
        if sig_row is None:
            return None
        signal = dict(sig_row)
        signal_id = signal.get("signal_id")
        if not isinstance(signal_id, str):
            return None
        # 2. The latest signal_pipeline_status row for it.
        with self._db._connect() as conn:
            conn.row_factory = sqlite3.Row
            status_row = conn.execute(
                """
                SELECT core_eligible, hybrid_eligible, market_context_ready,
                       volume_structure_ready, options_context_ready,
                       admission_outcome, admission_code
                FROM signal_pipeline_status
                WHERE signal_id=?
                """,
                (signal_id,),
            ).fetchone()
        signal["pipeline_status"] = dict(status_row) if status_row else None
        # 3. The latest canonical_shadow_evaluations row, if any.
        with self._db._connect() as conn:
            conn.row_factory = sqlite3.Row
            shadow_row = conn.execute(
                """
                SELECT resolution_id, bundle_id, message, status,
                       section_1_outcome, section_2_outcome
                FROM canonical_shadow_evaluations
                WHERE signal_id=?
                ORDER BY written_at DESC
                LIMIT 1
                """,
                (signal_id,),
            ).fetchone()
        signal["shadow_observation"] = dict(shadow_row) if shadow_row else None
        return signal

    def read_today_paper_activity(
        self, *, account_id: str, trading_date: str
    ) -> dict[str, object]:
        """Return today's paper-trading activity: counts of entries
        opened, entries closed, open positions, and most-recent
        entry/close. Used by the trading view of the cadence panel.

        Best-effort: returns an empty dict with zero counts if the
        paper_execution_orders table doesn't exist or is empty.
        """
        self._db.initialize()
        with self._db._connect() as conn:
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(
                    """
                    SELECT order_id, direction, option_type, strike_price,
                           entry_price, exit_price, entry_timestamp,
                           exit_timestamp, status, exit_reason
                    FROM paper_execution_orders
                    WHERE account_id=? AND date(entry_timestamp)=?
                    ORDER BY entry_timestamp DESC
                    """,
                    (account_id, trading_date),
                ).fetchall()
            except Exception:  # noqa: BLE001
                return {
                    "entered": 0,
                    "closed": 0,
                    "open": 0,
                    "last_entry": None,
                    "last_close": None,
                    "realized_pnl": 0.0,
                }
        entered = len(rows)
        closed = sum(1 for r in rows if r["exit_timestamp"] is not None)
        open_count = entered - closed
        last_entry = None
        last_close = None
        for r in rows:
            d = dict(r)
            if last_entry is None:
                last_entry = d
            if d["exit_timestamp"] is not None and last_close is None:
                last_close = d
        # Realized P&L: simple sum of (exit_price - entry_price) for
        # closed positions, direction-adjusted. Best-effort; the
        # signal_explorer page has the full mark-to-market calculation.
        realized = 0.0
        for r in rows:
            if r["exit_price"] is None or r["entry_price"] is None:
                continue
            diff = float(r["exit_price"]) - float(r["entry_price"])
            if str(r["direction"]).upper() == "SHORT":
                diff = -diff
            realized += diff
        return {
            "entered": entered,
            "closed": closed,
            "open": open_count,
            "last_entry": last_entry,
            "last_close": last_close,
            "realized_pnl": realized,
        }

    def read_today_signal_counts(
        self, *, instrument_key: str, trading_date: str
    ) -> dict[str, int]:
        """Return counts of confirmed / pending / expired signals for
        the trading date. Used by the trading view of the cadence
        panel."""
        self._db.initialize()
        with self._db._connect() as conn:
            rows = conn.execute(
                """
                SELECT state, COUNT(*) AS cnt
                FROM signal_attempts
                WHERE instrument_key=? AND trading_date=?
                GROUP BY state
                """,
                (instrument_key, trading_date),
            ).fetchall()
        return {r["state"]: r["cnt"] for r in rows}
