from __future__ import annotations

from datetime import datetime
import hashlib
import json
import sqlite3
import threading
from pathlib import Path
from typing import Iterable

from red_bar_lab.strategy.identity import canonical_signal_id
from red_bar_lab.storage.signal_repository import SignalRepository
from red_bar_lab.storage.paper_trade_outcome_repository import PaperTradeOutcomeRepository
from red_bar_lab.storage.evaluation_repository import EvaluationRepository
from red_bar_lab.strategy.models import Direction, ReferenceLevel, SignalAttempt, SignalState
import pandas as pd


SCHEMA = """
CREATE TABLE IF NOT EXISTS strategy_runs (
    run_id TEXT PRIMARY KEY,
    mode TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL,
    parameters_json TEXT NOT NULL DEFAULT '{}',
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS reference_levels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instrument_key TEXT NOT NULL,
    trading_date TEXT NOT NULL,
    level_type TEXT NOT NULL,
    source_timestamp TEXT NOT NULL,
    source_open REAL,
    source_high REAL NOT NULL,
    source_low REAL NOT NULL,
    source_close REAL,
    midpoint REAL NOT NULL,
    interval_minutes INTEGER NOT NULL,
    data_quality TEXT NOT NULL DEFAULT 'VALID',
    UNIQUE(instrument_key, trading_date, level_type, source_timestamp)
);

CREATE TABLE IF NOT EXISTS signal_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id TEXT,
    run_id TEXT NOT NULL,
    instrument_key TEXT NOT NULL,
    trading_date TEXT NOT NULL,
    level_type TEXT NOT NULL,
    level_value REAL NOT NULL,
    direction TEXT,
    state TEXT NOT NULL,
    cross_timestamp TEXT,
    confirmation_timestamp TEXT,
    underlying_entry REAL,
    cross_open REAL,
    cross_high REAL,
    cross_low REAL,
    cross_close REAL,
    confirmation_open REAL,
    confirmation_high REAL,
    confirmation_low REAL,
    confirmation_close REAL,
    confirmation_delay_minutes INTEGER,
    entry_type TEXT,
    governing_reference TEXT,
    governing_midpoint REAL,
    risk_plan_tradable INTEGER,
    risk_plan_code TEXT,
    risk_plan_detail TEXT,
    risk_stop_price REAL,
    risk_points REAL,
    risk_stop_trigger TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_attempt_id INTEGER NOT NULL,
    option_instrument_key TEXT,
    option_symbol TEXT,
    option_type TEXT,
    strike REAL,
    entry_timestamp TEXT,
    entry_price REAL,
    exit_timestamp TEXT,
    exit_price REAL,
    exit_reason TEXT,
    status TEXT NOT NULL,
    FOREIGN KEY(signal_attempt_id) REFERENCES signal_attempts(id)
);


CREATE TABLE IF NOT EXISTS paper_trade_outcomes (
    trade_id TEXT PRIMARY KEY,
    signal_id TEXT NOT NULL,
    instrument_key TEXT NOT NULL,
    trading_date TEXT NOT NULL,
    level_type TEXT NOT NULL,
    direction TEXT NOT NULL,
    entry_timestamp TEXT NOT NULL,
    entry_price REAL NOT NULL,
    stop_price REAL NOT NULL,
    risk_points REAL,
    exit_model TEXT,
    model_parameter TEXT,
    target_points REAL,
    target_price REAL,
    exit_timestamp TEXT,
    exit_price REAL,
    exit_reason TEXT NOT NULL,
    status TEXT NOT NULL,
    points REAL,
    r_multiple REAL,
    mfe REAL,
    mae REAL,
    holding_minutes INTEGER,
    session_mfe_points REAL,
    session_mae_points REAL,
    session_extreme_price REAL,
    session_extreme_timestamp TEXT,
    move_after_target_points REAL,
    minutes_from_target_to_extreme INTEGER,
    giveback_from_extreme_points REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Historical backtest exit models may legitimately share the same
-- numeric target_points for the same signal (for example FIXED_TARGET
-- 20pt and RISK_REWARD 1R when risk is 20 points). trade_id already
-- uniquely identifies signal + exit model + model parameter.
DROP INDEX IF EXISTS uq_paper_trade_signal_target;

CREATE INDEX IF NOT EXISTS idx_paper_trade_signal_target
ON paper_trade_outcomes(signal_id, target_points);


CREATE TABLE IF NOT EXISTS market_context_snapshots (
    signal_id TEXT PRIMARY KEY,
    instrument_key TEXT NOT NULL,
    trading_date TEXT NOT NULL,
    entry_timestamp TEXT NOT NULL,
    session_open REAL,
    previous_close REAL,
    previous_high REAL,
    previous_low REAL,
    gap_points REAL,
    gap_pct REAL,
    minutes_from_open REAL,
    price_from_open_points REAL,
    price_from_open_pct REAL,
    session_high_so_far REAL,
    session_low_so_far REAL,
    session_range_so_far REAL,
    session_range_position REAL,
    distance_to_previous_high REAL,
    distance_to_previous_low REAL,
    opening_range_15_high REAL,
    opening_range_15_low REAL,
    opening_range_15_position TEXT,
    atr14_5m REAL,
    ema9_5m REAL,
    ema21_5m REAL,
    trend_5m TEXT,
    realized_volatility_30m_pct REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);


CREATE TABLE IF NOT EXISTS volume_structure_snapshots (
    signal_id TEXT PRIMARY KEY,
    instrument_key TEXT NOT NULL,
    trading_date TEXT NOT NULL,
    entry_timestamp TEXT NOT NULL,
    volume_current_1m REAL,
    volume_avg_20m REAL,
    relative_volume_20m REAL,
    volume_trend_5m TEXT,
    price_volume_state TEXT,
    compression_ratio_20m REAL,
    structure_state TEXT,
    breakout_strength REAL,
    range_width_20m REAL,
    higher_high_count_20m INTEGER,
    lower_low_count_20m INTEGER,
    bullish_structure_score REAL,
    bearish_structure_score REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);


CREATE TABLE IF NOT EXISTS option_context_snapshots (
    signal_id TEXT PRIMARY KEY,
    instrument_key TEXT NOT NULL,
    trading_date TEXT NOT NULL,
    entry_timestamp TEXT NOT NULL,
    option_expiry TEXT,
    option_snapshot_timestamp TEXT NOT NULL,
    option_snapshot_delay_seconds REAL,
    entry_aligned INTEGER NOT NULL DEFAULT 0,
    option_spot_price REAL,
    atm_strike REAL,
    total_call_oi REAL,
    total_put_oi REAL,
    pcr_oi REAL,
    total_call_oi_change REAL,
    total_put_oi_change REAL,
    pcr_oi_change REAL,
    call_wall_strike REAL,
    put_wall_strike REAL,
    max_pain_strike REAL,
    atm_call_iv REAL,
    atm_put_iv REAL,
    atm_call_delta REAL,
    atm_put_delta REAL,
    atm_call_gamma REAL,
    atm_put_gamma REAL,
    atm_call_theta REAL,
    atm_put_theta REAL,
    atm_call_vega REAL,
    atm_put_vega REAL,
    chain_artifact_path TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);


CREATE TABLE IF NOT EXISTS option_chain_snapshot_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_key TEXT NOT NULL UNIQUE,
    instrument_key TEXT NOT NULL,
    trading_date TEXT NOT NULL,
    option_expiry TEXT,
    snapshot_timestamp TEXT NOT NULL,
    collector_mode TEXT NOT NULL,
    option_spot_price REAL,
    atm_strike REAL,
    total_call_oi REAL,
    total_put_oi REAL,
    pcr_oi REAL,
    total_call_oi_change REAL,
    total_put_oi_change REAL,
    pcr_oi_change REAL,
    call_wall_strike REAL,
    put_wall_strike REAL,
    max_pain_strike REAL,
    atm_call_iv REAL,
    atm_put_iv REAL,
    atm_call_delta REAL,
    atm_put_delta REAL,
    atm_call_gamma REAL,
    atm_put_gamma REAL,
    atm_call_theta REAL,
    atm_put_theta REAL,
    atm_call_vega REAL,
    atm_put_vega REAL,
    chain_artifact_path TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_option_chain_history_lookup
ON option_chain_snapshot_history(
    instrument_key,
    snapshot_timestamp
);

CREATE TABLE IF NOT EXISTS signal_option_snapshot_links (
    signal_id TEXT PRIMARY KEY,
    snapshot_id INTEGER NOT NULL,
    relation TEXT NOT NULL,
    delta_seconds REAL,
    authoritative INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(snapshot_id) REFERENCES option_chain_snapshot_history(id)
);

CREATE TABLE IF NOT EXISTS market_collector_status (
    collector_name TEXT PRIMARY KEY,
    collector_mode TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT,
    last_snapshot_id INTEGER,
    updated_at TEXT NOT NULL
);


CREATE TABLE IF NOT EXISTS signal_pipeline_status (
    signal_id TEXT PRIMARY KEY,
    instrument_key TEXT NOT NULL,
    trading_date TEXT NOT NULL,
    market_context_ready INTEGER NOT NULL DEFAULT 0,
    volume_structure_ready INTEGER NOT NULL DEFAULT 0,
    options_context_ready INTEGER NOT NULL DEFAULT 0,
    core_eligible INTEGER NOT NULL DEFAULT 0,
    hybrid_eligible INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS intelligence_pipeline_run_status (
    instrument_key TEXT NOT NULL,
    trading_date TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT,
    confirmed_count INTEGER,
    core_eligible_count INTEGER,
    hybrid_eligible_count INTEGER,
    run_duration_ms REAL,
    started_at TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(instrument_key, trading_date)
);

CREATE TABLE IF NOT EXISTS process_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    process_name TEXT NOT NULL,
    run_id TEXT NOT NULL,
    step_name TEXT NOT NULL,
    parent_step TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL,
    duration_ms REAL,
    error_message TEXT,
    artifacts_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_evidence_process_step_time
    ON process_evidence(process_name, step_name, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_evidence_run
    ON process_evidence(run_id);

-- One row per process: the most recent run_id that process produced.
-- Used by the cadence panel to correlate cross-process cycles.
CREATE TABLE IF NOT EXISTS process_run_correlation (
    process_name TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    artifacts_json TEXT
);

CREATE TABLE IF NOT EXISTS eod_pipeline_validation (
    instrument_key TEXT NOT NULL,
    trading_date TEXT NOT NULL,
    confirmed_signals INTEGER NOT NULL,
    core_eligible INTEGER NOT NULL,
    hybrid_eligible INTEGER NOT NULL,
    core_completeness_pct REAL NOT NULL,
    hybrid_completeness_pct REAL NOT NULL,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(instrument_key, trading_date)
);


CREATE TABLE IF NOT EXISTS historical_option_backfill (
    instrument_key TEXT NOT NULL,
    trading_date TEXT NOT NULL,
    option_expiry TEXT NOT NULL,
    spot_closing_price REAL,
    total_call_oi REAL,
    total_put_oi REAL,
    pcr_oi REAL,
    total_call_oi_change REAL,
    total_put_oi_change REAL,
    pcr_oi_change REAL,
    call_wall_strike REAL,
    put_wall_strike REAL,
    max_pain_strike REAL,
    strike_count INTEGER,
    source_type TEXT NOT NULL,
    entry_aligned INTEGER NOT NULL DEFAULT 0,
    oi_artifact_path TEXT,
    change_artifact_path TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(instrument_key, trading_date)
);


CREATE TABLE IF NOT EXISTS paper_execution_accounts (
    account_id TEXT PRIMARY KEY,
    account_name TEXT NOT NULL,
    initial_capital REAL NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_execution_orders (
    order_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    signal_id TEXT,
    market_data_provider TEXT NOT NULL,
    execution_provider TEXT NOT NULL,
    execution_mode TEXT NOT NULL,
    underlying_name TEXT,
    underlying_price_entry REAL,
    instrument_token INTEGER NOT NULL,
    exchange TEXT NOT NULL,
    tradingsymbol TEXT NOT NULL,
    option_type TEXT NOT NULL,
    strike REAL NOT NULL,
    expiry TEXT NOT NULL,
    lot_size INTEGER NOT NULL,
    side TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    entry_timestamp TEXT NOT NULL,
    entry_price REAL NOT NULL,
    current_price REAL,
    stop_price REAL,
    target1_price REAL,
    target2_price REAL,
    status TEXT NOT NULL,
    entry_reason TEXT,
    exit_timestamp TEXT,
    exit_price REAL,
    exit_reason TEXT,
    unrealized_pnl REAL,
    realized_pnl REAL,
    mfe_points REAL,
    mae_points REAL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(account_id) REFERENCES paper_execution_accounts(account_id)
);

CREATE INDEX IF NOT EXISTS idx_paper_execution_orders_account_status
ON paper_execution_orders(account_id, status);

CREATE TABLE IF NOT EXISTS paper_execution_marks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    price REAL NOT NULL,
    underlying_price REAL,
    unrealized_pnl REAL,
    mfe_points REAL,
    mae_points REAL,
    event_type TEXT NOT NULL,
    FOREIGN KEY(order_id) REFERENCES paper_execution_orders(order_id)
);

CREATE INDEX IF NOT EXISTS idx_paper_execution_marks_order
ON paper_execution_marks(order_id, timestamp);

CREATE TABLE IF NOT EXISTS paper_trade_checkpoints (
    checkpoint_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    signal_id TEXT,
    execution_strategy_source TEXT,
    horizon_minutes INTEGER NOT NULL,
    due_timestamp TEXT NOT NULL,
    observed_timestamp TEXT NOT NULL,
    entry_price REAL NOT NULL,
    checkpoint_price REAL NOT NULL,
    return_pct REAL NOT NULL,
    mfe_points REAL,
    mae_points REAL,
    peak_price REAL,
    protected_stop_price REAL,
    position_status_at_checkpoint TEXT NOT NULL,
    captured_order_status TEXT NOT NULL,
    observation_quality TEXT NOT NULL DEFAULT 'UNKNOWN',
    observation_lag_seconds REAL,
    observation_note TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(order_id, horizon_minutes),
    FOREIGN KEY(order_id) REFERENCES paper_execution_orders(order_id)
);

CREATE INDEX IF NOT EXISTS idx_paper_trade_checkpoints_order
ON paper_trade_checkpoints(order_id, horizon_minutes);
CREATE INDEX IF NOT EXISTS idx_paper_trade_checkpoints_signal
ON paper_trade_checkpoints(signal_id, observed_timestamp);

CREATE TABLE IF NOT EXISTS option_execution_telemetry (
    telemetry_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    signal_id TEXT,
    execution_strategy_source TEXT,
    observed_timestamp TEXT NOT NULL,
    exchange TEXT,
    tradingsymbol TEXT,
    instrument_token INTEGER,
    option_type TEXT,
    strike REAL,
    expiry TEXT,
    entry_price REAL,
    current_price REAL,
    premium_return_pct REAL,
    volume REAL,
    volume_change REAL,
    relative_volume REAL,
    oi REAL,
    oi_change REAL,
    oi_change_pct REAL,
    best_bid REAL,
    best_ask REAL,
    spread_points REAL,
    spread_pct REAL,
    buy_quantity REAL,
    sell_quantity REAL,
    iv REAL,
    delta REAL,
    gamma REAL,
    theta REAL,
    vega REAL,
    pcr_oi REAL,
    pcr_source TEXT,
    support_classification TEXT NOT NULL,
    support_reason TEXT,
    authority TEXT NOT NULL DEFAULT 'OBSERVATIONAL_ONLY',
    created_at TEXT NOT NULL,
    UNIQUE(order_id, observed_timestamp),
    FOREIGN KEY(order_id) REFERENCES paper_execution_orders(order_id)
);

CREATE INDEX IF NOT EXISTS idx_option_execution_telemetry_order
ON option_execution_telemetry(order_id, observed_timestamp);
CREATE INDEX IF NOT EXISTS idx_option_execution_telemetry_signal
ON option_execution_telemetry(signal_id, observed_timestamp);


CREATE TABLE IF NOT EXISTS shadow_intelligence_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id TEXT,
    trading_date TEXT,
    current_decision TEXT NOT NULL,
    shadow_decision TEXT NOT NULL,
    shadow_confidence REAL NOT NULL,
    agreement TEXT NOT NULL,
    portfolio_conflict INTEGER NOT NULL DEFAULT 0,
    portfolio_action TEXT,
    execution_impact TEXT NOT NULL DEFAULT 'NONE',
    modules_json TEXT NOT NULL,
    evaluated_at TEXT NOT NULL,
    UNIQUE(signal_id, evaluated_at)
);

CREATE INDEX IF NOT EXISTS idx_shadow_intelligence_signal
ON shadow_intelligence_evaluations(signal_id, evaluated_at);

CREATE TABLE IF NOT EXISTS paper_monitor_status (
    monitor_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    heartbeat_at TEXT,
    last_scan_at TEXT,
    started_at TEXT,
    underlying_name TEXT,
    signals_seen INTEGER NOT NULL DEFAULT 0,
    signals_qualified INTEGER NOT NULL DEFAULT 0,
    candidates_scored INTEGER NOT NULL DEFAULT 0,
    orders_opened INTEGER NOT NULL DEFAULT 0,
    orders_closed INTEGER NOT NULL DEFAULT 0,
    signals_skipped INTEGER NOT NULL DEFAULT 0,
    current_state TEXT,
    last_signal_id TEXT,
    last_decision TEXT,
    last_reason TEXT,
    last_error TEXT,
    last_success_at TEXT,
    last_success_decision TEXT,
    last_success_signal_id TEXT,
    last_success_total_ms REAL,
    last_success_stages_json TEXT,
    last_success_underlying_status TEXT,
    last_success_readiness_ms REAL,
    last_success_futures_status TEXT,
    last_success_candle_timestamp TEXT,
    last_success_candle_age_seconds REAL,
    last_success_bridge_alignment TEXT,
    last_success_readiness_reason TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_signal_diagnostics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id TEXT NOT NULL,
    signal_id TEXT,
    signal_state TEXT,
    direction TEXT,
    confirmation_timestamp TEXT,
    signal_age_seconds REAL,
    market_hours_ok INTEGER,
    freshness_ok INTEGER,
    duplicate_free INTEGER,
    candidate_available INTEGER,
    best_candidate TEXT,
    best_score REAL,
    minimum_score REAL,
    score_ok INTEGER,
    final_decision TEXT NOT NULL,
    reason TEXT,
    timestamp TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_paper_signal_diagnostics_signal
ON paper_signal_diagnostics(signal_id, timestamp);

CREATE TABLE IF NOT EXISTS execution_state_events (
    event_id TEXT PRIMARY KEY,
    signal_id TEXT,
    order_id TEXT,
    state TEXT NOT NULL,
    detail TEXT,
    candidate_score REAL,
    timestamp TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_execution_state_events_signal
ON execution_state_events(signal_id, timestamp);

CREATE TABLE IF NOT EXISTS paper_candidate_decisions (
    signal_id TEXT PRIMARY KEY,
    trading_date TEXT NOT NULL,
    direction TEXT NOT NULL,
    tradingsymbol TEXT,
    instrument_token INTEGER,
    option_type TEXT,
    strike REAL,
    expiry TEXT,
    candidate_score REAL,
    score_detail TEXT,
    decision TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_paper_execution_signal_account_instrument
ON paper_execution_orders(signal_id, account_id, instrument_token)
WHERE signal_id IS NOT NULL;



CREATE TABLE IF NOT EXISTS trade_selection_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id TEXT NOT NULL,
    signal_id TEXT NOT NULL,
    trading_date TEXT NOT NULL,
    direction TEXT,
    candidate_rank INTEGER NOT NULL,
    candidate_symbol TEXT NOT NULL,
    instrument_token INTEGER NOT NULL,
    candidate_score REAL NOT NULL,
    opportunity_score REAL,
    reward_remaining_pct REAL,
    reward_risk_ratio REAL,
    execution_quality_score REAL,
    history_sample_size INTEGER NOT NULL DEFAULT 0,
    history_win_rate_pct REAL,
    history_profit_factor REAL,
    history_expectancy_pct REAL,
    history_avg_mfe_pct REAL,
    history_avg_mae_pct REAL,
    historical_score REAL,
    selection_score REAL NOT NULL,
    evidence_ready INTEGER NOT NULL DEFAULT 0,
    eligible INTEGER NOT NULL DEFAULT 0,
    decision TEXT NOT NULL,
    reason TEXT,
    evaluated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trade_selection_signal
ON trade_selection_evaluations(signal_id, evaluated_at);
CREATE INDEX IF NOT EXISTS idx_trade_selection_date
ON trade_selection_evaluations(trading_date, evaluated_at);

CREATE TABLE IF NOT EXISTS institutional_execution_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id TEXT NOT NULL,
    signal_id TEXT NOT NULL,
    trading_date TEXT NOT NULL,
    direction TEXT,
    candidate_rank INTEGER NOT NULL,
    candidate_symbol TEXT NOT NULL,
    instrument_token INTEGER NOT NULL,
    option_type TEXT,
    execution_probability_pct REAL NOT NULL,
    expected_value_pct REAL NOT NULL,
    expectancy_pct REAL,
    expected_win_pct REAL,
    expected_loss_pct REAL,
    expectancy_source TEXT,
    expectancy_confidence_pct REAL,
    kelly_fraction_pct REAL,
    expected_reward_pct REAL,
    expected_risk_pct REAL,
    intelligence_score REAL,
    adaptive_history_weight_pct REAL,
    rule_quality_score REAL,
    opportunity_score REAL,
    historical_score REAL,
    selection_score REAL,
    primary_decision TEXT,
    primary_confidence_pct REAL,
    shadow_decision TEXT,
    shadow_confidence_pct REAL,
    agreement TEXT,
    shadow_adjustment_pct REAL,
    evidence_sample_size INTEGER NOT NULL DEFAULT 0,
    evidence_ready INTEGER NOT NULL DEFAULT 0,
    modules_json TEXT NOT NULL DEFAULT '[]',
    expert_votes_json TEXT NOT NULL DEFAULT '[]',
    eligible INTEGER NOT NULL DEFAULT 0,
    decision TEXT NOT NULL,
    reason TEXT,
    evaluated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_institutional_execution_signal
ON institutional_execution_evaluations(signal_id, evaluated_at);
CREATE INDEX IF NOT EXISTS idx_institutional_execution_date
ON institutional_execution_evaluations(trading_date, evaluated_at);

CREATE TABLE IF NOT EXISTS execution_queue (
    queue_id TEXT PRIMARY KEY,
    signal_id TEXT NOT NULL,
    trading_date TEXT NOT NULL,
    direction TEXT,
    candidate_rank INTEGER NOT NULL,
    candidate_symbol TEXT NOT NULL,
    instrument_token INTEGER NOT NULL,
    exchange TEXT NOT NULL DEFAULT 'NFO',
    option_type TEXT,
    strike REAL,
    expiry TEXT,
    lot_size INTEGER NOT NULL DEFAULT 1,
    quantity INTEGER NOT NULL DEFAULT 0,
    candidate_score REAL,
    selection_score REAL,
    execution_probability_pct REAL,
    expected_value_pct REAL,
    opportunity_score REAL,
    entry_mode TEXT,
    signal_age_seconds REAL,
    status TEXT NOT NULL,
    reason TEXT,
    order_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    executed_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_execution_queue_signal_instrument
ON execution_queue(signal_id, instrument_token);
CREATE INDEX IF NOT EXISTS idx_execution_queue_status
ON execution_queue(status, updated_at);
CREATE INDEX IF NOT EXISTS idx_execution_queue_signal
ON execution_queue(signal_id, candidate_rank);

CREATE TABLE IF NOT EXISTS candidate_lifecycle (
    candidate_id TEXT PRIMARY KEY,
    signal_id TEXT NOT NULL,
    trading_date TEXT NOT NULL,
    candidate_symbol TEXT,
    instrument_token INTEGER,
    state TEXT NOT NULL,
    health_score REAL,
    age_seconds REAL,
    created_session TEXT,
    current_session TEXT,
    market_drift TEXT,
    duplicate INTEGER NOT NULL DEFAULT 0,
    reason TEXT,
    action TEXT,
    replacement_required INTEGER NOT NULL DEFAULT 0,
    replacement_signal_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_candidate_lifecycle_signal
ON candidate_lifecycle(signal_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_candidate_lifecycle_state
ON candidate_lifecycle(state, updated_at);

CREATE TABLE IF NOT EXISTS opportunity_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id TEXT NOT NULL,
    signal_id TEXT NOT NULL,
    trading_date TEXT NOT NULL,
    direction TEXT,
    signal_age_seconds REAL,
    entry_mode TEXT NOT NULL,
    candidate_symbol TEXT,
    candidate_score REAL,
    opportunity_score REAL NOT NULL,
    structure_score REAL,
    momentum_score REAL,
    reward_score REAL,
    option_health_score REAL,
    market_context_score REAL,
    time_score REAL,
    reward_remaining_pct REAL,
    move_consumed_pct REAL,
    structure_valid INTEGER NOT NULL DEFAULT 0,
    opposite_red_bar INTEGER NOT NULL DEFAULT 0,
    eligible INTEGER NOT NULL DEFAULT 0,
    decision TEXT NOT NULL,
    reason TEXT,
    evaluated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_opportunity_evaluations_signal
ON opportunity_evaluations(signal_id, evaluated_at);

CREATE INDEX IF NOT EXISTS idx_opportunity_evaluations_mode
ON opportunity_evaluations(entry_mode, evaluated_at);


CREATE TABLE IF NOT EXISTS trade_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_trade_id INTEGER NOT NULL,
    target_model TEXT NOT NULL,
    stop_model TEXT NOT NULL,
    mfe REAL,
    mae REAL,
    points REAL,
    result TEXT,
    holding_minutes INTEGER,
    FOREIGN KEY(paper_trade_id) REFERENCES paper_trades(id)
);

CREATE INDEX IF NOT EXISTS idx_signal_attempts_trading_date
ON signal_attempts(trading_date);

CREATE INDEX IF NOT EXISTS idx_paper_execution_orders_signal
ON paper_execution_orders(signal_id)
WHERE signal_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_option_chain_history_trading_date
ON option_chain_snapshot_history(instrument_key, snapshot_timestamp);

CREATE INDEX IF NOT EXISTS idx_paper_trade_outcomes_signal
ON paper_trade_outcomes(signal_id);
"""

_EXECUTION_QUEUE_POLICY_COLUMNS = {
    "execution_strategy_source": "TEXT",
    "strategy_stop_loss_pct": "REAL",
    "strategy_target_pct": "REAL",
    "exit_mode": "TEXT",
    "evaluation_horizon_minutes": "INTEGER",
    "signal_sources_json": "TEXT NOT NULL DEFAULT '[]'",
    "merge_status": "TEXT",
    "rsi_signal_id": "TEXT",
    "rsi_confirmation_timestamp": "TEXT",
}

_PAPER_EXECUTION_EXIT_COLUMNS = {
    "execution_strategy_source": "TEXT",
    "strategy_stop_loss_pct": "REAL",
    "strategy_target_pct": "REAL",
    "exit_mode": "TEXT",
    "evaluation_horizon_minutes": "INTEGER",
    "signal_sources_json": "TEXT NOT NULL DEFAULT '[]'",
    "merge_status": "TEXT",
    "rsi_signal_id": "TEXT",
    "rsi_confirmation_timestamp": "TEXT",
    "initial_stop_price": "REAL",
    "breakeven_armed": "INTEGER NOT NULL DEFAULT 0",
    "trailing_active": "INTEGER NOT NULL DEFAULT 0",
    "trailing_stop_price": "REAL",
    "exit_health_score": "REAL",
    "exit_action": "TEXT",
    "exit_detail": "TEXT",
    "entry_mode": "TEXT",
    "signal_age_at_entry": "REAL",
    "opportunity_score": "REAL",
    "reward_remaining_pct": "REAL",
    "candidate_rank": "INTEGER",
    "candidate_score": "REAL",
    "selection_score": "REAL",
    "historical_win_rate_pct": "REAL",
    "historical_profit_factor": "REAL",
    "historical_expectancy_pct": "REAL",
    "historical_sample_size": "INTEGER",
    "execution_probability_pct": "REAL",
    "expected_value_pct": "REAL",
    "intelligence_score": "REAL",
}


_PAPER_MONITOR_SUCCESS_COLUMNS = {
    "last_success_at": "TEXT",
    "last_success_decision": "TEXT",
    "last_success_signal_id": "TEXT",
    "last_success_total_ms": "REAL",
    "last_success_stages_json": "TEXT",
    "last_success_underlying_status": "TEXT",
    "last_success_readiness_ms": "REAL",
    "last_success_futures_status": "TEXT",
    "last_success_candle_timestamp": "TEXT",
    "last_success_candle_age_seconds": "REAL",
    "last_success_bridge_alignment": "TEXT",
    "last_success_readiness_reason": "TEXT",
}


_INTELLIGENCE_PIPELINE_RUN_COLUMNS = {
    "confirmed_count": "INTEGER",
    "core_eligible_count": "INTEGER",
    "hybrid_eligible_count": "INTEGER",
    "run_duration_ms": "REAL",
    "started_at": "TEXT",
}


_INSTITUTIONAL_EXECUTION_COLUMNS = {
    "expert_votes_json": "TEXT NOT NULL DEFAULT '[]'",
    "expectancy_pct": "REAL",
    "expected_win_pct": "REAL",
    "expected_loss_pct": "REAL",
    "expectancy_source": "TEXT",
    "expectancy_confidence_pct": "REAL",
    "kelly_fraction_pct": "REAL",
    "primary_decision": "TEXT",
    "primary_confidence_pct": "REAL",
    "shadow_decision": "TEXT",
    "shadow_confidence_pct": "REAL",
    "agreement": "TEXT",
    "shadow_adjustment_pct": "REAL",
}

_SIGNAL_COLUMNS = {
    "signal_id": "TEXT",
    "cross_open": "REAL",
    "cross_high": "REAL",
    "cross_low": "REAL",
    "cross_close": "REAL",
    "confirmation_open": "REAL",
    "confirmation_high": "REAL",
    "confirmation_low": "REAL",
    "confirmation_close": "REAL",
    "confirmation_delay_minutes": "INTEGER",
    # Frozen at admission, for the exit to judge a position against the level it
    # was actually taken on. ``signal_attempts.level_value`` is always the red
    # bar's midpoint, so a deputy-born (WORKING) entry -- taken outside the red
    # bar band, against a level the red bar cannot describe -- is otherwise
    # indistinguishable from an INITIAL one once the deputy has been retired.
    "entry_type": "TEXT",
    "governing_reference": "TEXT",
    "governing_midpoint": "REAL",
    # Also frozen at admission, and for a stricter reason: the stop is priced
    # from 5-minute bars truncated at the qualifying minute, so it can only be
    # computed *then*. By the time the order path looks at this signal those
    # bars have finished and the same arithmetic would read price that printed
    # after the decision. ``risk_plan_tradable`` is the live entry gate;
    # ``risk_points`` is the denominator of the trade's R-multiple.
    "risk_plan_tradable": "INTEGER",
    "risk_plan_code": "TEXT",
    "risk_plan_detail": "TEXT",
    "risk_stop_price": "REAL",
    "risk_points": "REAL",
    "risk_stop_trigger": "TEXT",
}


def deterministic_signal_id(
    instrument_key: str,
    trading_date: str,
    level_type: str,
    direction: str | None,
    cross_timestamp: str | None,
    confirmation_timestamp: str | None,
) -> str:
    return canonical_signal_id(
        instrument_key,
        trading_date,
        level_type,
        direction,
        cross_timestamp,
        confirmation_timestamp,
    )


class RedBarDatabase:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        # RB-1.3.2 performance: schema/migration work is process-instance scoped.
        # The file-existence check in initialize() still runs on every call so a
        # deleted database self-heals exactly as before.
        self._initialized = False
        self._initialize_lock = threading.Lock()
        self._signal_repo: SignalRepository | None = None
        self._paper_trade_outcome_repo: PaperTradeOutcomeRepository | None = None
        self._evaluation_repo: EvaluationRepository | None = None

    @property
    def signal(self) -> SignalRepository:
        if self._signal_repo is None:
            self._signal_repo = SignalRepository(self)
        return self._signal_repo

    @property
    def paper_trade_outcome(self) -> PaperTradeOutcomeRepository:
        if self._paper_trade_outcome_repo is None:
            self._paper_trade_outcome_repo = PaperTradeOutcomeRepository(self)
        return self._paper_trade_outcome_repo

    @property
    def evaluation(self) -> EvaluationRepository:
        if self._evaluation_repo is None:
            self._evaluation_repo = EvaluationRepository(self)
        return self._evaluation_repo

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA cache_size=-64000")
        conn.execute("PRAGMA journal_size_limit=67108864")
        return conn

    def _snapshot_to(self, destination: Path) -> None:
        """Write a consistent, self-contained copy of the database.

        ``_connect`` puts the database in WAL mode, which is a persistent
        property of the file, so committed transactions can still live in the
        ``-wal`` sidecar when this runs. A plain file copy of ``self.path``
        alone would silently omit them -- on a freshly created database that
        means the copy is missing the schema itself. SQLite's own backup API
        reads through the WAL and produces one complete file.

        The copy is staged under a temporary name and moved into place so an
        interrupted snapshot cannot leave a truncated file behind: callers
        create the backup only when it does not already exist, so a torn file
        would otherwise be permanent.
        """
        staged = destination.with_name(f"{destination.name}.partial")
        staged.unlink(missing_ok=True)
        try:
            source = sqlite3.connect(self.path, timeout=10.0)
            try:
                target = sqlite3.connect(staged, timeout=10.0)
                try:
                    source.backup(target)
                finally:
                    target.close()
            finally:
                source.close()
            staged.replace(destination)
        finally:
            staged.unlink(missing_ok=True)

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        # RB-0.6.6 safety: preserve the database exactly as it existed before
        # the first startup of this patch. initialize() is called frequently,
        # so the backup is intentionally created only once.
        path_exists = self.path.exists()
        if path_exists:
            backup = self.path.with_name(
                f"{self.path.stem}.pre_RB_0_6_6{self.path.suffix}"
            )
            if not backup.exists():
                self._snapshot_to(backup)

        # Normal hot-path calls return here after the first successful migration.
        # If the DB file was deleted, path_exists is False and initialization is
        # intentionally re-run to preserve RB-0.6.6 self-healing semantics.
        if self._initialized and path_exists:
            return

        with self._initialize_lock:
            # A second caller may have completed initialization while waiting.
            if self._initialized and self.path.exists():
                return

            with self._connect() as conn:
                conn.executescript(SCHEMA)
                columns = {
                    row[1] for row in conn.execute("PRAGMA table_info(signal_attempts)")
                }
                for name, definition in _SIGNAL_COLUMNS.items():
                    if name not in columns:
                        conn.execute(
                            f"ALTER TABLE signal_attempts ADD COLUMN {name} {definition}"
                        )

                queue_columns = {
                    row[1]
                    for row in conn.execute("PRAGMA table_info(execution_queue)")
                }
                for name, definition in _EXECUTION_QUEUE_POLICY_COLUMNS.items():
                    if name not in queue_columns:
                        conn.execute(
                            f"ALTER TABLE execution_queue ADD COLUMN {name} {definition}"
                        )

                paper_columns = {
                    row[1]
                    for row in conn.execute(
                        "PRAGMA table_info(paper_execution_orders)"
                    )
                }
                for name, definition in _PAPER_EXECUTION_EXIT_COLUMNS.items():
                    if name not in paper_columns:
                        conn.execute(
                            f"ALTER TABLE paper_execution_orders "
                            f"ADD COLUMN {name} {definition}"
                        )

                committee_columns = {
                    row[1] for row in conn.execute(
                        "PRAGMA table_info(institutional_execution_evaluations)"
                    )
                }
                for name, definition in _INSTITUTIONAL_EXECUTION_COLUMNS.items():
                    if name not in committee_columns:
                        conn.execute(
                            f"ALTER TABLE institutional_execution_evaluations "
                            f"ADD COLUMN {name} {definition}"
                        )

                paper_monitor_columns = {
                    row[1]
                    for row in conn.execute(
                        "PRAGMA table_info(paper_monitor_status)"
                    )
                }
                for name, definition in _PAPER_MONITOR_SUCCESS_COLUMNS.items():
                    if name not in paper_monitor_columns:
                        conn.execute(
                            f"ALTER TABLE paper_monitor_status "
                            f"ADD COLUMN {name} {definition}"
                        )

                pipeline_run_columns = {
                    row[1]
                    for row in conn.execute(
                        "PRAGMA table_info(intelligence_pipeline_run_status)"
                    )
                }
                for name, definition in _INTELLIGENCE_PIPELINE_RUN_COLUMNS.items():
                    if name not in pipeline_run_columns:
                        conn.execute(
                            f"ALTER TABLE intelligence_pipeline_run_status "
                            f"ADD COLUMN {name} {definition}"
                        )

                # RB-0.9.1: one signal may execute multiple independently-qualified
                # option candidates. Preserve duplicate protection at candidate level.
                conn.execute("DROP INDEX IF EXISTS uq_paper_execution_signal_account")
                conn.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS
                    uq_paper_execution_signal_account_instrument
                    ON paper_execution_orders(signal_id, account_id, instrument_token)
                    WHERE signal_id IS NOT NULL
                    """
                )

                conn.execute(
                    """
                    UPDATE paper_execution_orders
                    SET initial_stop_price=stop_price
                    WHERE initial_stop_price IS NULL
                      AND stop_price IS NOT NULL
                    """
                )

                # Backfill deterministic IDs into RB-0.3 databases and remove any
                # duplicates that were created by running the same replay repeatedly.
                conn.row_factory = sqlite3.Row
                legacy = conn.execute(
                    """SELECT id,instrument_key,trading_date,level_type,direction,
                              cross_timestamp,confirmation_timestamp
                       FROM signal_attempts
                       WHERE signal_id IS NULL OR signal_id=''"""
                ).fetchall()
                for row in legacy:
                    signal_id = deterministic_signal_id(
                        str(row["instrument_key"]),
                        str(row["trading_date"]),
                        str(row["level_type"]),
                        row["direction"],
                        row["cross_timestamp"],
                        row["confirmation_timestamp"],
                    )
                    conn.execute(
                        "UPDATE signal_attempts SET signal_id=? WHERE id=?",
                        (signal_id, row["id"]),
                    )
                conn.execute(
                    """DELETE FROM signal_attempts
                       WHERE id NOT IN (
                           SELECT MIN(id) FROM signal_attempts GROUP BY signal_id
                       )"""
                )
                conn.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ux_signal_attempts_signal_id "
                    "ON signal_attempts(signal_id)"
                )
                conn.commit()
            self._initialized = True

    def replace_reference_levels(
        self, instrument_key: str, trading_date: str, levels: Iterable[ReferenceLevel]
    ) -> int:
        self.initialize()
        rows = list(levels)
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM reference_levels WHERE instrument_key=? AND trading_date=?",
                (instrument_key, trading_date),
            )
            conn.executemany(
                """INSERT INTO reference_levels(
                    instrument_key,trading_date,level_type,source_timestamp,
                    source_high,source_low,midpoint,interval_minutes,data_quality
                ) VALUES(?,?,?,?,?,?,?,?,?)""",
                [
                    (
                        instrument_key,
                        trading_date,
                        level.level_type,
                        level.source_timestamp.isoformat(),
                        level.source_high,
                        level.source_low,
                        level.value,
                        level.interval_minutes,
                        "VALID",
                    )
                    for level in rows
                ],
            )
            conn.commit()
        return len(rows)

    def read_reference_levels(
        self, instrument_key: str, trading_date: str
    ) -> list[dict[str, object]]:
        self.initialize()
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT level_type,source_timestamp,source_high,source_low,
                          midpoint,interval_minutes,data_quality
                   FROM reference_levels
                   WHERE instrument_key=? AND trading_date=?
                   ORDER BY
                     CASE
                       WHEN level_type LIKE 'PD%_315' THEN
                         CAST(REPLACE(REPLACE(level_type,'PD',''),'_315','') AS INTEGER)
                       ELSE 100
                     END,
                     level_type""",
                (instrument_key, trading_date),
            ).fetchall()
        return [dict(row) for row in rows]

    def load_reference_levels(
        self, instrument_key: str, trading_date: str
    ) -> tuple[ReferenceLevel, ...]:
        rows = self.read_reference_levels(instrument_key, trading_date)
        return tuple(
            ReferenceLevel(
                level_type=str(row["level_type"]),
                value=float(row["midpoint"]),
                source_timestamp=datetime.fromisoformat(str(row["source_timestamp"])),
                source_high=float(row["source_high"]),
                source_low=float(row["source_low"]),
                interval_minutes=int(row["interval_minutes"]),
            )
            for row in rows
        )

    def replace_signal_attempts(
        self,
        run_id: str,
        instrument_key: str,
        trading_date: str,
        attempts: Iterable[SignalAttempt],
    ) -> int:
        """Replace the complete historical replay result for one date."""
        return self.signal.replace_signal_attempts(
            run_id, instrument_key, trading_date, attempts
        )

    def read_signal_attempts(
        self, instrument_key: str, trading_date: str, run_id: str | None = None
    ) -> list[dict[str, object]]:
        return self.signal.read_signal_attempts(instrument_key, trading_date, run_id)

    def read_signal_attempt_by_id(
        self,
        signal_id: str,
    ) -> dict[str, object] | None:
        return self.signal.read_signal_attempt_by_id(signal_id)

    def read_signal_attempts_by_ids(
        self,
        signal_ids: Iterable[str],
    ) -> dict[str, dict[str, object]]:
        """Batch-load signal metadata keyed by signal_id."""
        return self.signal.read_signal_attempts_by_ids(signal_ids)

    def signal_summary(
        self, instrument_key: str, trading_date: str, run_id: str | None = None
    ) -> dict[str, int]:
        return self.signal.signal_summary(instrument_key, trading_date, run_id)

    def health(self) -> dict[str, object]:
        self.initialize()
        with self._connect() as conn:
            result = conn.execute("SELECT 1").fetchone()
        return {"ok": result == (1,), "path": str(self.path)}


    def replace_paper_trade_outcomes(
        self,
        instrument_key: str,
        trading_date: str,
        outcomes,
    ) -> int:
        return self.paper_trade_outcome.replace_paper_trade_outcomes(
            instrument_key, trading_date, outcomes
        )

    def read_paper_trade_outcomes(
        self,
        instrument_key: str,
        trading_date: str,
    ) -> list[dict[str, object]]:
        return self.paper_trade_outcome.read_paper_trade_outcomes(
            instrument_key, trading_date
        )

    def paper_trade_summary(
        self,
        instrument_key: str,
        trading_date: str,
    ) -> dict[str, object]:
        return self.paper_trade_outcome.paper_trade_summary(
            instrument_key, trading_date
        )

    def paper_trade_range_rows(
        self,
        instrument_key: str,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, object]]:
        return self.paper_trade_outcome.paper_trade_range_rows(
            instrument_key, start_date, end_date
        )

    def paper_trade_range_summary(
        self,
        instrument_key: str,
        start_date: str,
        end_date: str,
    ) -> dict[str, object]:
        return self.paper_trade_outcome.paper_trade_range_summary(
            instrument_key, start_date, end_date
        )


    def read_signal_attempts_range(
        self,
        instrument_key: str,
        date_from: str,
        date_to: str,
    ) -> list[dict[str, object]]:
        return self.signal.read_signal_attempts_range(instrument_key, date_from, date_to)

    def read_paper_trade_outcomes_range(
        self,
        instrument_key: str,
        date_from: str,
        date_to: str,
    ) -> list[dict[str, object]]:
        return self.paper_trade_outcome.read_paper_trade_outcomes_range(
            instrument_key, date_from, date_to
        )



    def upsert_market_context_snapshots(
        self,
        rows: Iterable[dict[str, object]],
    ) -> int:
        self.initialize()
        payload = list(rows)
        if not payload:
            return 0

        now = datetime.now().astimezone().isoformat()
        with self._connect() as conn:
            for row in payload:
                conn.execute(
                    """
                    INSERT INTO market_context_snapshots(
                        signal_id,instrument_key,trading_date,entry_timestamp,
                        session_open,previous_close,previous_high,previous_low,
                        gap_points,gap_pct,minutes_from_open,
                        price_from_open_points,price_from_open_pct,
                        session_high_so_far,session_low_so_far,
                        session_range_so_far,session_range_position,
                        distance_to_previous_high,distance_to_previous_low,
                        opening_range_15_high,opening_range_15_low,
                        opening_range_15_position,atr14_5m,ema9_5m,ema21_5m,
                        trend_5m,realized_volatility_30m_pct,
                        created_at,updated_at
                    )
                    VALUES(
                        ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
                    )
                    ON CONFLICT(signal_id) DO UPDATE SET
                        instrument_key=excluded.instrument_key,
                        trading_date=excluded.trading_date,
                        entry_timestamp=excluded.entry_timestamp,
                        session_open=excluded.session_open,
                        previous_close=excluded.previous_close,
                        previous_high=excluded.previous_high,
                        previous_low=excluded.previous_low,
                        gap_points=excluded.gap_points,
                        gap_pct=excluded.gap_pct,
                        minutes_from_open=excluded.minutes_from_open,
                        price_from_open_points=excluded.price_from_open_points,
                        price_from_open_pct=excluded.price_from_open_pct,
                        session_high_so_far=excluded.session_high_so_far,
                        session_low_so_far=excluded.session_low_so_far,
                        session_range_so_far=excluded.session_range_so_far,
                        session_range_position=excluded.session_range_position,
                        distance_to_previous_high=excluded.distance_to_previous_high,
                        distance_to_previous_low=excluded.distance_to_previous_low,
                        opening_range_15_high=excluded.opening_range_15_high,
                        opening_range_15_low=excluded.opening_range_15_low,
                        opening_range_15_position=excluded.opening_range_15_position,
                        atr14_5m=excluded.atr14_5m,
                        ema9_5m=excluded.ema9_5m,
                        ema21_5m=excluded.ema21_5m,
                        trend_5m=excluded.trend_5m,
                        realized_volatility_30m_pct=excluded.realized_volatility_30m_pct,
                        updated_at=excluded.updated_at
                    """,
                    (
                        row.get("signal_id"),
                        row.get("instrument_key"),
                        row.get("trading_date"),
                        row.get("entry_timestamp"),
                        row.get("session_open"),
                        row.get("previous_close"),
                        row.get("previous_high"),
                        row.get("previous_low"),
                        row.get("gap_points"),
                        row.get("gap_pct"),
                        row.get("minutes_from_open"),
                        row.get("price_from_open_points"),
                        row.get("price_from_open_pct"),
                        row.get("session_high_so_far"),
                        row.get("session_low_so_far"),
                        row.get("session_range_so_far"),
                        row.get("session_range_position"),
                        row.get("distance_to_previous_high"),
                        row.get("distance_to_previous_low"),
                        row.get("opening_range_15_high"),
                        row.get("opening_range_15_low"),
                        row.get("opening_range_15_position"),
                        row.get("atr14_5m"),
                        row.get("ema9_5m"),
                        row.get("ema21_5m"),
                        row.get("trend_5m"),
                        row.get("realized_volatility_30m_pct"),
                        now,
                        now,
                    ),
                )
            conn.commit()
        return len(payload)

    def read_market_context_snapshots(
        self,
        instrument_key: str,
        date_from: str,
        date_to: str,
    ) -> list[dict[str, object]]:
        self.initialize()
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM market_context_snapshots
                WHERE instrument_key=?
                  AND trading_date>=?
                  AND trading_date<=?
                ORDER BY trading_date, entry_timestamp, signal_id
                """,
                (instrument_key, date_from, date_to),
            ).fetchall()
        return [dict(row) for row in rows]



    def upsert_volume_structure_snapshots(
        self,
        rows: Iterable[dict[str, object]],
    ) -> int:
        self.initialize()
        payload = list(rows)
        if not payload:
            return 0

        now = datetime.now().astimezone().isoformat()
        with self._connect() as conn:
            for row in payload:
                conn.execute(
                    """
                    INSERT INTO volume_structure_snapshots(
                        signal_id,instrument_key,trading_date,entry_timestamp,
                        volume_current_1m,volume_avg_20m,relative_volume_20m,
                        volume_trend_5m,price_volume_state,
                        compression_ratio_20m,structure_state,
                        breakout_strength,range_width_20m,
                        higher_high_count_20m,lower_low_count_20m,
                        bullish_structure_score,bearish_structure_score,
                        created_at,updated_at
                    )
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(signal_id) DO UPDATE SET
                        instrument_key=excluded.instrument_key,
                        trading_date=excluded.trading_date,
                        entry_timestamp=excluded.entry_timestamp,
                        volume_current_1m=excluded.volume_current_1m,
                        volume_avg_20m=excluded.volume_avg_20m,
                        relative_volume_20m=excluded.relative_volume_20m,
                        volume_trend_5m=excluded.volume_trend_5m,
                        price_volume_state=excluded.price_volume_state,
                        compression_ratio_20m=excluded.compression_ratio_20m,
                        structure_state=excluded.structure_state,
                        breakout_strength=excluded.breakout_strength,
                        range_width_20m=excluded.range_width_20m,
                        higher_high_count_20m=excluded.higher_high_count_20m,
                        lower_low_count_20m=excluded.lower_low_count_20m,
                        bullish_structure_score=excluded.bullish_structure_score,
                        bearish_structure_score=excluded.bearish_structure_score,
                        updated_at=excluded.updated_at
                    """,
                    (
                        row.get("signal_id"),
                        row.get("instrument_key"),
                        row.get("trading_date"),
                        row.get("entry_timestamp"),
                        row.get("volume_current_1m"),
                        row.get("volume_avg_20m"),
                        row.get("relative_volume_20m"),
                        row.get("volume_trend_5m"),
                        row.get("price_volume_state"),
                        row.get("compression_ratio_20m"),
                        row.get("structure_state"),
                        row.get("breakout_strength"),
                        row.get("range_width_20m"),
                        row.get("higher_high_count_20m"),
                        row.get("lower_low_count_20m"),
                        row.get("bullish_structure_score"),
                        row.get("bearish_structure_score"),
                        now,
                        now,
                    ),
                )
            conn.commit()
        return len(payload)

    def read_volume_structure_snapshots(
        self,
        instrument_key: str,
        date_from: str,
        date_to: str,
    ) -> list[dict[str, object]]:
        self.initialize()
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM volume_structure_snapshots
                WHERE instrument_key=?
                  AND trading_date>=?
                  AND trading_date<=?
                ORDER BY trading_date, entry_timestamp, signal_id
                """,
                (instrument_key, date_from, date_to),
            ).fetchall()
        return [dict(row) for row in rows]



    def upsert_option_context_snapshots(
        self,
        rows: Iterable[dict[str, object]],
    ) -> int:
        self.initialize()
        payload = list(rows)
        if not payload:
            return 0

        now = datetime.now().astimezone().isoformat()
        with self._connect() as conn:
            for row in payload:
                conn.execute(
                    """
                    INSERT INTO option_context_snapshots(
                        signal_id,instrument_key,trading_date,entry_timestamp,
                        option_expiry,option_snapshot_timestamp,
                        option_snapshot_delay_seconds,entry_aligned,
                        option_spot_price,atm_strike,total_call_oi,total_put_oi,
                        pcr_oi,total_call_oi_change,total_put_oi_change,
                        pcr_oi_change,call_wall_strike,put_wall_strike,
                        max_pain_strike,atm_call_iv,atm_put_iv,
                        atm_call_delta,atm_put_delta,atm_call_gamma,
                        atm_put_gamma,atm_call_theta,atm_put_theta,
                        atm_call_vega,atm_put_vega,chain_artifact_path,
                        created_at,updated_at
                    )
                    VALUES(
                        ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
                    )
                    ON CONFLICT(signal_id) DO UPDATE SET
                        instrument_key=excluded.instrument_key,
                        trading_date=excluded.trading_date,
                        entry_timestamp=excluded.entry_timestamp,
                        option_expiry=excluded.option_expiry,
                        option_snapshot_timestamp=excluded.option_snapshot_timestamp,
                        option_snapshot_delay_seconds=excluded.option_snapshot_delay_seconds,
                        entry_aligned=excluded.entry_aligned,
                        option_spot_price=excluded.option_spot_price,
                        atm_strike=excluded.atm_strike,
                        total_call_oi=excluded.total_call_oi,
                        total_put_oi=excluded.total_put_oi,
                        pcr_oi=excluded.pcr_oi,
                        total_call_oi_change=excluded.total_call_oi_change,
                        total_put_oi_change=excluded.total_put_oi_change,
                        pcr_oi_change=excluded.pcr_oi_change,
                        call_wall_strike=excluded.call_wall_strike,
                        put_wall_strike=excluded.put_wall_strike,
                        max_pain_strike=excluded.max_pain_strike,
                        atm_call_iv=excluded.atm_call_iv,
                        atm_put_iv=excluded.atm_put_iv,
                        atm_call_delta=excluded.atm_call_delta,
                        atm_put_delta=excluded.atm_put_delta,
                        atm_call_gamma=excluded.atm_call_gamma,
                        atm_put_gamma=excluded.atm_put_gamma,
                        atm_call_theta=excluded.atm_call_theta,
                        atm_put_theta=excluded.atm_put_theta,
                        atm_call_vega=excluded.atm_call_vega,
                        atm_put_vega=excluded.atm_put_vega,
                        chain_artifact_path=excluded.chain_artifact_path,
                        updated_at=excluded.updated_at
                    """,
                    (
                        row.get("signal_id"),
                        row.get("instrument_key"),
                        row.get("trading_date"),
                        row.get("entry_timestamp"),
                        row.get("option_expiry"),
                        row.get("option_snapshot_timestamp"),
                        row.get("option_snapshot_delay_seconds"),
                        int(bool(row.get("entry_aligned"))),
                        row.get("option_spot_price"),
                        row.get("atm_strike"),
                        row.get("total_call_oi"),
                        row.get("total_put_oi"),
                        row.get("pcr_oi"),
                        row.get("total_call_oi_change"),
                        row.get("total_put_oi_change"),
                        row.get("pcr_oi_change"),
                        row.get("call_wall_strike"),
                        row.get("put_wall_strike"),
                        row.get("max_pain_strike"),
                        row.get("atm_call_iv"),
                        row.get("atm_put_iv"),
                        row.get("atm_call_delta"),
                        row.get("atm_put_delta"),
                        row.get("atm_call_gamma"),
                        row.get("atm_put_gamma"),
                        row.get("atm_call_theta"),
                        row.get("atm_put_theta"),
                        row.get("atm_call_vega"),
                        row.get("atm_put_vega"),
                        row.get("chain_artifact_path"),
                        now,
                        now,
                    ),
                )
            conn.commit()
        return len(payload)

    def read_option_context_snapshots(
        self,
        instrument_key: str,
        date_from: str,
        date_to: str,
    ) -> list[dict[str, object]]:
        self.initialize()
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM option_context_snapshots
                WHERE instrument_key=?
                  AND trading_date>=?
                  AND trading_date<=?
                ORDER BY trading_date, entry_timestamp, signal_id
                """,
                (instrument_key, date_from, date_to),
            ).fetchall()
        return [dict(row) for row in rows]

    def read_market_context_by_signal(
        self,
        signal_id: str,
    ) -> dict[str, object] | None:
        self.initialize()
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT *
                FROM market_context_snapshots
                WHERE signal_id=?
                """,
                (signal_id,),
            ).fetchone()
        return dict(row) if row else None

    def read_volume_structure_by_signal(
        self,
        signal_id: str,
    ) -> dict[str, object] | None:
        self.initialize()
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT *
                FROM volume_structure_snapshots
                WHERE signal_id=?
                """,
                (signal_id,),
            ).fetchone()
        return dict(row) if row else None

    def read_option_context_by_signal(
        self,
        signal_id: str,
    ) -> dict[str, object] | None:
        self.initialize()
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT *
                FROM option_context_snapshots
                WHERE signal_id=?
                """,
                (signal_id,),
            ).fetchone()
        return dict(row) if row else None



    def upsert_option_chain_history(
        self,
        row: dict[str, object],
    ) -> int:
        self.initialize()
        now = datetime.now().astimezone().isoformat()

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO option_chain_snapshot_history(
                    snapshot_key,instrument_key,trading_date,option_expiry,
                    snapshot_timestamp,collector_mode,option_spot_price,
                    atm_strike,total_call_oi,total_put_oi,pcr_oi,
                    total_call_oi_change,total_put_oi_change,pcr_oi_change,
                    call_wall_strike,put_wall_strike,max_pain_strike,
                    atm_call_iv,atm_put_iv,atm_call_delta,atm_put_delta,
                    atm_call_gamma,atm_put_gamma,atm_call_theta,
                    atm_put_theta,atm_call_vega,atm_put_vega,
                    chain_artifact_path,created_at,updated_at
                )
                VALUES(
                    ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
                )
                ON CONFLICT(snapshot_key) DO UPDATE SET
                    option_spot_price=excluded.option_spot_price,
                    atm_strike=excluded.atm_strike,
                    total_call_oi=excluded.total_call_oi,
                    total_put_oi=excluded.total_put_oi,
                    pcr_oi=excluded.pcr_oi,
                    total_call_oi_change=excluded.total_call_oi_change,
                    total_put_oi_change=excluded.total_put_oi_change,
                    pcr_oi_change=excluded.pcr_oi_change,
                    call_wall_strike=excluded.call_wall_strike,
                    put_wall_strike=excluded.put_wall_strike,
                    max_pain_strike=excluded.max_pain_strike,
                    atm_call_iv=excluded.atm_call_iv,
                    atm_put_iv=excluded.atm_put_iv,
                    atm_call_delta=excluded.atm_call_delta,
                    atm_put_delta=excluded.atm_put_delta,
                    atm_call_gamma=excluded.atm_call_gamma,
                    atm_put_gamma=excluded.atm_put_gamma,
                    atm_call_theta=excluded.atm_call_theta,
                    atm_put_theta=excluded.atm_put_theta,
                    atm_call_vega=excluded.atm_call_vega,
                    atm_put_vega=excluded.atm_put_vega,
                    chain_artifact_path=excluded.chain_artifact_path,
                    updated_at=excluded.updated_at
                """,
                (
                    row.get("snapshot_key"),
                    row.get("instrument_key"),
                    row.get("trading_date"),
                    row.get("option_expiry"),
                    row.get("snapshot_timestamp"),
                    row.get("collector_mode"),
                    row.get("option_spot_price"),
                    row.get("atm_strike"),
                    row.get("total_call_oi"),
                    row.get("total_put_oi"),
                    row.get("pcr_oi"),
                    row.get("total_call_oi_change"),
                    row.get("total_put_oi_change"),
                    row.get("pcr_oi_change"),
                    row.get("call_wall_strike"),
                    row.get("put_wall_strike"),
                    row.get("max_pain_strike"),
                    row.get("atm_call_iv"),
                    row.get("atm_put_iv"),
                    row.get("atm_call_delta"),
                    row.get("atm_put_delta"),
                    row.get("atm_call_gamma"),
                    row.get("atm_put_gamma"),
                    row.get("atm_call_theta"),
                    row.get("atm_put_theta"),
                    row.get("atm_call_vega"),
                    row.get("atm_put_vega"),
                    row.get("chain_artifact_path"),
                    now,
                    now,
                ),
            )
            snapshot_id = conn.execute(
                """
                SELECT id
                FROM option_chain_snapshot_history
                WHERE snapshot_key=?
                """,
                (row.get("snapshot_key"),),
            ).fetchone()[0]
            conn.commit()
        return int(snapshot_id)

    def read_option_chain_history(
        self,
        instrument_key: str,
        date_from: str,
        date_to: str,
        limit: int = 500,
    ) -> list[dict[str, object]]:
        self.initialize()
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM option_chain_snapshot_history
                WHERE instrument_key=?
                  AND trading_date>=?
                  AND trading_date<=?
                ORDER BY snapshot_timestamp DESC
                LIMIT ?
                """,
                (instrument_key, date_from, date_to, int(limit)),
            ).fetchall()
        return [dict(row) for row in rows]

    def find_nearest_pre_entry_option_snapshot(
        self,
        *,
        instrument_key: str,
        entry_timestamp: str,
        max_age_seconds: int,
    ) -> dict[str, object] | None:
        self.initialize()
        entry = pd.Timestamp(entry_timestamp)
        if entry.tzinfo is None:
            entry = entry.tz_localize("Asia/Kolkata")
        else:
            entry = entry.tz_convert("Asia/Kolkata")
        minimum = (
            entry - pd.Timedelta(seconds=int(max_age_seconds))
        ).isoformat()

        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT *
                FROM option_chain_snapshot_history
                WHERE instrument_key=?
                  AND snapshot_timestamp<=?
                  AND snapshot_timestamp>=?
                  AND collector_mode='ONLINE'
                ORDER BY snapshot_timestamp DESC
                LIMIT 1
                """,
                (
                    instrument_key,
                    entry.isoformat(),
                    minimum,
                ),
            ).fetchone()
        return dict(row) if row else None

    def upsert_signal_option_snapshot_link(
        self,
        *,
        signal_id: str,
        snapshot_id: int,
        relation: str,
        delta_seconds: float | None,
        authoritative: int,
    ) -> None:
        self.initialize()
        now = datetime.now().astimezone().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO signal_option_snapshot_links(
                    signal_id,snapshot_id,relation,delta_seconds,
                    authoritative,created_at,updated_at
                )
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(signal_id) DO UPDATE SET
                    snapshot_id=excluded.snapshot_id,
                    relation=excluded.relation,
                    delta_seconds=excluded.delta_seconds,
                    authoritative=excluded.authoritative,
                    updated_at=excluded.updated_at
                """,
                (
                    signal_id,
                    int(snapshot_id),
                    relation,
                    delta_seconds,
                    int(authoritative),
                    now,
                    now,
                ),
            )
            conn.commit()

    def read_signal_option_snapshot_link(
        self,
        signal_id: str,
    ) -> dict[str, object] | None:
        self.initialize()
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT l.*, h.snapshot_timestamp, h.option_expiry,
                       h.chain_artifact_path
                FROM signal_option_snapshot_links l
                JOIN option_chain_snapshot_history h
                  ON h.id=l.snapshot_id
                WHERE l.signal_id=?
                """,
                (signal_id,),
            ).fetchone()
        return dict(row) if row else None

    def update_collector_status(
        self,
        collector_name: str,
        collector_mode: str,
        status: str,
        message: str | None,
        last_snapshot_id: int | None,
    ) -> None:
        self.initialize()
        now = datetime.now().astimezone().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO market_collector_status(
                    collector_name,collector_mode,status,message,
                    last_snapshot_id,updated_at
                )
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(collector_name) DO UPDATE SET
                    collector_mode=excluded.collector_mode,
                    status=excluded.status,
                    message=excluded.message,
                    last_snapshot_id=excluded.last_snapshot_id,
                    updated_at=excluded.updated_at
                """,
                (
                    collector_name,
                    collector_mode,
                    status,
                    message,
                    last_snapshot_id,
                    now,
                ),
            )
            conn.commit()

    def read_collector_status(
        self,
        collector_name: str = "DUAL_OPTIONS",
    ) -> dict[str, object] | None:
        self.initialize()
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT *
                FROM market_collector_status
                WHERE collector_name=?
                """,
                (collector_name,),
            ).fetchone()
        return dict(row) if row else None



    def read_paper_execution_marks(
        self,
        order_id: str,
    ) -> list[dict[str, object]]:
        self.initialize()
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM paper_execution_marks
                WHERE order_id=?
                ORDER BY timestamp ASC, id ASC
                """,
                (order_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_paper_trade_checkpoint(
        self,
        row: dict[str, object],
    ) -> None:
        """Persist one immutable observational checkpoint per order/horizon."""
        self.initialize()
        now = datetime.now().astimezone().isoformat()
        with self._connect() as conn:
            existing_columns = {
                str(item[1])
                for item in conn.execute(
                    'PRAGMA table_info(paper_trade_checkpoints)'
                ).fetchall()
            }
            for column_name, column_type in {
                'observation_quality': (
                    "TEXT NOT NULL DEFAULT 'UNKNOWN'"
                ),
                'observation_lag_seconds': 'REAL',
                'observation_note': 'TEXT',
            }.items():
                if column_name not in existing_columns:
                    conn.execute(
                        f'ALTER TABLE paper_trade_checkpoints '
                        f'ADD COLUMN {column_name} {column_type}'
                    )

            conn.execute(
                """
                INSERT INTO paper_trade_checkpoints(
                    checkpoint_id,order_id,signal_id,
                    execution_strategy_source,horizon_minutes,
                    due_timestamp,observed_timestamp,
                    entry_price,checkpoint_price,return_pct,
                    mfe_points,mae_points,peak_price,
                    protected_stop_price,position_status_at_checkpoint,
                    captured_order_status,observation_quality,
                    observation_lag_seconds,observation_note,created_at
                )
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(order_id,horizon_minutes) DO NOTHING
                """,
                (
                    row.get("checkpoint_id"),
                    row.get("order_id"),
                    row.get("signal_id"),
                    row.get("execution_strategy_source"),
                    int(row.get("horizon_minutes") or 0),
                    row.get("due_timestamp"),
                    row.get("observed_timestamp"),
                    row.get("entry_price"),
                    row.get("checkpoint_price"),
                    row.get("return_pct"),
                    row.get("mfe_points"),
                    row.get("mae_points"),
                    row.get("peak_price"),
                    row.get("protected_stop_price"),
                    row.get("position_status_at_checkpoint"),
                    row.get("captured_order_status"),
                    row.get("observation_quality") or "UNKNOWN",
                    row.get("observation_lag_seconds"),
                    row.get("observation_note"),
                    row.get("created_at") or now,
                ),
            )
            conn.commit()

    def read_paper_trade_checkpoint(
        self,
        *,
        order_id: str,
        horizon_minutes: int,
    ) -> dict[str, object] | None:
        self.initialize()
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT *
                FROM paper_trade_checkpoints
                WHERE order_id=? AND horizon_minutes=?
                """,
                (order_id, int(horizon_minutes)),
            ).fetchone()
        return dict(row) if row else None

    def read_paper_trade_checkpoints(
        self,
        *,
        signal_id: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, object]]:
        self.initialize()
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            if signal_id:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM paper_trade_checkpoints
                    WHERE signal_id=?
                    ORDER BY observed_timestamp DESC
                    LIMIT ?
                    """,
                    (signal_id, int(limit)),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM paper_trade_checkpoints
                    ORDER BY observed_timestamp DESC
                    LIMIT ?
                    """,
                    (int(limit),),
                ).fetchall()
        return [dict(row) for row in rows]

    def insert_option_execution_telemetry(
        self,
        row: dict[str, object],
    ) -> None:
        self.initialize()
        now = datetime.now().astimezone().isoformat()
        with self._connect() as conn:
            conn.execute(
                '''
                INSERT OR IGNORE INTO option_execution_telemetry(
                    telemetry_id,order_id,signal_id,
                    execution_strategy_source,observed_timestamp,
                    exchange,tradingsymbol,instrument_token,
                    option_type,strike,expiry,entry_price,current_price,
                    premium_return_pct,volume,volume_change,relative_volume,
                    oi,oi_change,oi_change_pct,best_bid,best_ask,
                    spread_points,spread_pct,buy_quantity,sell_quantity,
                    iv,delta,gamma,theta,vega,pcr_oi,pcr_source,
                    support_classification,support_reason,authority,created_at
                )
                VALUES(
                    ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,
                    ?,?,?,?,?,?,?,?,?,?,?
                )
                ''',
                (
                    row.get('telemetry_id'), row.get('order_id'),
                    row.get('signal_id'), row.get('execution_strategy_source'),
                    row.get('observed_timestamp'), row.get('exchange'),
                    row.get('tradingsymbol'), row.get('instrument_token'),
                    row.get('option_type'), row.get('strike'), row.get('expiry'),
                    row.get('entry_price'), row.get('current_price'),
                    row.get('premium_return_pct'), row.get('volume'),
                    row.get('volume_change'), row.get('relative_volume'),
                    row.get('oi'), row.get('oi_change'), row.get('oi_change_pct'),
                    row.get('best_bid'), row.get('best_ask'),
                    row.get('spread_points'), row.get('spread_pct'),
                    row.get('buy_quantity'), row.get('sell_quantity'),
                    row.get('iv'), row.get('delta'), row.get('gamma'),
                    row.get('theta'), row.get('vega'), row.get('pcr_oi'),
                    row.get('pcr_source'), row.get('support_classification'),
                    row.get('support_reason'),
                    row.get('authority') or 'OBSERVATIONAL_ONLY',
                    row.get('created_at') or now,
                ),
            )
            conn.commit()

    def read_latest_option_execution_telemetry(
        self,
        order_id: str,
    ) -> dict[str, object] | None:
        self.initialize()
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                '''SELECT * FROM option_execution_telemetry
                   WHERE order_id=?
                   ORDER BY observed_timestamp DESC LIMIT 1''',
                (order_id,),
            ).fetchone()
        return dict(row) if row else None

    def read_option_execution_telemetry(
        self,
        *,
        order_id: str | None = None,
        signal_id: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, object]]:
        self.initialize()
        clauses = []
        values: list[object] = []
        if order_id:
            clauses.append('order_id=?')
            values.append(order_id)
        if signal_id:
            clauses.append('signal_id=?')
            values.append(signal_id)
        where = ('WHERE ' + ' AND '.join(clauses)) if clauses else ''
        values.append(int(limit))
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f'''SELECT * FROM option_execution_telemetry
                    {where}
                    ORDER BY observed_timestamp DESC LIMIT ?''',
                tuple(values),
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_signal_pipeline_status(
        self,
        row: dict[str, object],
    ) -> None:
        self.initialize()
        now = datetime.now().astimezone().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO signal_pipeline_status(
                    signal_id,instrument_key,trading_date,
                    market_context_ready,volume_structure_ready,
                    options_context_ready,core_eligible,hybrid_eligible,
                    last_error,updated_at
                )
                VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(signal_id) DO UPDATE SET
                    market_context_ready=excluded.market_context_ready,
                    volume_structure_ready=excluded.volume_structure_ready,
                    options_context_ready=excluded.options_context_ready,
                    core_eligible=excluded.core_eligible,
                    hybrid_eligible=excluded.hybrid_eligible,
                    last_error=excluded.last_error,
                    updated_at=excluded.updated_at
                """,
                (
                    row.get("signal_id"),
                    row.get("instrument_key"),
                    row.get("trading_date"),
                    int(bool(row.get("market_context_ready"))),
                    int(bool(row.get("volume_structure_ready"))),
                    int(bool(row.get("options_context_ready"))),
                    int(bool(row.get("core_eligible"))),
                    int(bool(row.get("hybrid_eligible"))),
                    row.get("last_error"),
                    now,
                ),
            )
            conn.commit()

    def read_signal_pipeline_status_range(
        self,
        instrument_key: str,
        date_from: str,
        date_to: str,
    ) -> list[dict[str, object]]:
        self.initialize()
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM signal_pipeline_status
                WHERE instrument_key=?
                  AND trading_date>=?
                  AND trading_date<=?
                ORDER BY trading_date, signal_id
                """,
                (instrument_key, date_from, date_to),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_pipeline_run_status(
        self,
        *,
        instrument_key: str,
        trading_date: str,
        status: str,
        message: str | None,
        confirmed_count: int | None = None,
        core_eligible_count: int | None = None,
        hybrid_eligible_count: int | None = None,
        run_duration_ms: float | None = None,
        started_at: str | None = None,
    ) -> None:
        self.initialize()
        now = datetime.now().astimezone().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO intelligence_pipeline_run_status(
                    instrument_key,trading_date,status,message,
                    confirmed_count,core_eligible_count,hybrid_eligible_count,
                    run_duration_ms,started_at,updated_at
                )
                VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(instrument_key,trading_date) DO UPDATE SET
                    status=excluded.status,
                    message=excluded.message,
                    confirmed_count=excluded.confirmed_count,
                    core_eligible_count=excluded.core_eligible_count,
                    hybrid_eligible_count=excluded.hybrid_eligible_count,
                    run_duration_ms=excluded.run_duration_ms,
                    started_at=excluded.started_at,
                    updated_at=excluded.updated_at
                """,
                (
                    instrument_key,
                    trading_date,
                    status,
                    message,
                    int(confirmed_count) if confirmed_count is not None else None,
                    int(core_eligible_count) if core_eligible_count is not None else None,
                    int(hybrid_eligible_count) if hybrid_eligible_count is not None else None,
                    float(run_duration_ms) if run_duration_ms is not None else None,
                    started_at,
                    now,
                ),
            )
            conn.commit()

    def read_pipeline_run_status(
        self,
        instrument_key: str,
        trading_date: str,
    ) -> dict[str, object] | None:
        self.initialize()
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT *
                FROM intelligence_pipeline_run_status
                WHERE instrument_key=? AND trading_date=?
                """,
                (instrument_key,trading_date),
            ).fetchone()
        return dict(row) if row else None

    def read_latest_pipeline_run_status(
        self,
        instrument_key: str,
    ) -> dict[str, object] | None:
        """Return the most recent pipeline run row for an instrument, any date.

        Used by the live cadence UI to show the last successful run even
        when today's row hasn't been written yet (the orchestrator runs
        after market close).
        """
        self.initialize()
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT *
                FROM intelligence_pipeline_run_status
                WHERE instrument_key=?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (instrument_key,),
            ).fetchone()
        return dict(row) if row else None

    def upsert_eod_pipeline_validation(
        self,
        row: dict[str, object],
    ) -> None:
        self.initialize()
        now = datetime.now().astimezone().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO eod_pipeline_validation(
                    instrument_key,trading_date,confirmed_signals,
                    core_eligible,hybrid_eligible,
                    core_completeness_pct,hybrid_completeness_pct,
                    status,updated_at
                )
                VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(instrument_key,trading_date) DO UPDATE SET
                    confirmed_signals=excluded.confirmed_signals,
                    core_eligible=excluded.core_eligible,
                    hybrid_eligible=excluded.hybrid_eligible,
                    core_completeness_pct=excluded.core_completeness_pct,
                    hybrid_completeness_pct=excluded.hybrid_completeness_pct,
                    status=excluded.status,
                    updated_at=excluded.updated_at
                """,
                (
                    row.get("instrument_key"),
                    row.get("trading_date"),
                    int(row.get("confirmed_signals") or 0),
                    int(row.get("core_eligible") or 0),
                    int(row.get("hybrid_eligible") or 0),
                    float(row.get("core_completeness_pct") or 0.0),
                    float(row.get("hybrid_completeness_pct") or 0.0),
                    row.get("status"),
                    now,
                ),
            )
            conn.commit()

    def read_eod_pipeline_validation(
        self,
        instrument_key: str,
        trading_date: str,
    ) -> dict[str, object] | None:
        self.initialize()
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT *
                FROM eod_pipeline_validation
                WHERE instrument_key=? AND trading_date=?
                """,
                (instrument_key,trading_date),
            ).fetchone()
        return dict(row) if row else None



    def upsert_historical_option_backfill(
        self,
        row: dict[str, object],
    ) -> None:
        self.initialize()
        now = datetime.now().astimezone().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO historical_option_backfill(
                    instrument_key,trading_date,option_expiry,
                    spot_closing_price,total_call_oi,total_put_oi,pcr_oi,
                    total_call_oi_change,total_put_oi_change,pcr_oi_change,
                    call_wall_strike,put_wall_strike,max_pain_strike,
                    strike_count,source_type,entry_aligned,
                    oi_artifact_path,change_artifact_path,
                    created_at,updated_at
                )
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(instrument_key,trading_date) DO UPDATE SET
                    option_expiry=excluded.option_expiry,
                    spot_closing_price=excluded.spot_closing_price,
                    total_call_oi=excluded.total_call_oi,
                    total_put_oi=excluded.total_put_oi,
                    pcr_oi=excluded.pcr_oi,
                    total_call_oi_change=excluded.total_call_oi_change,
                    total_put_oi_change=excluded.total_put_oi_change,
                    pcr_oi_change=excluded.pcr_oi_change,
                    call_wall_strike=excluded.call_wall_strike,
                    put_wall_strike=excluded.put_wall_strike,
                    max_pain_strike=excluded.max_pain_strike,
                    strike_count=excluded.strike_count,
                    source_type=excluded.source_type,
                    entry_aligned=excluded.entry_aligned,
                    oi_artifact_path=excluded.oi_artifact_path,
                    change_artifact_path=excluded.change_artifact_path,
                    updated_at=excluded.updated_at
                """,
                (
                    row.get("instrument_key"),
                    row.get("trading_date"),
                    row.get("option_expiry"),
                    row.get("spot_closing_price"),
                    row.get("total_call_oi"),
                    row.get("total_put_oi"),
                    row.get("pcr_oi"),
                    row.get("total_call_oi_change"),
                    row.get("total_put_oi_change"),
                    row.get("pcr_oi_change"),
                    row.get("call_wall_strike"),
                    row.get("put_wall_strike"),
                    row.get("max_pain_strike"),
                    row.get("strike_count"),
                    row.get("source_type"),
                    int(bool(row.get("entry_aligned"))),
                    row.get("oi_artifact_path"),
                    row.get("change_artifact_path"),
                    now,
                    now,
                ),
            )
            conn.commit()

    def read_historical_option_backfill_day(
        self,
        instrument_key: str,
        trading_date: str,
    ) -> dict[str, object] | None:
        self.initialize()
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT *
                FROM historical_option_backfill
                WHERE instrument_key=? AND trading_date=?
                """,
                (instrument_key, trading_date),
            ).fetchone()
        return dict(row) if row else None

    def read_historical_option_backfill_range(
        self,
        instrument_key: str,
        date_from: str,
        date_to: str,
    ) -> list[dict[str, object]]:
        self.initialize()
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM historical_option_backfill
                WHERE instrument_key=?
                  AND trading_date>=?
                  AND trading_date<=?
                ORDER BY trading_date
                """,
                (instrument_key, date_from, date_to),
            ).fetchall()
        return [dict(row) for row in rows]



    def ensure_paper_execution_account(
        self,
        *,
        account_id: str,
        account_name: str,
        initial_capital: float,
    ) -> None:
        self.initialize()
        now = datetime.now().astimezone().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO paper_execution_accounts(
                    account_id,account_name,initial_capital,
                    created_at,updated_at
                )
                VALUES(?,?,?,?,?)
                ON CONFLICT(account_id) DO UPDATE SET
                    account_name=excluded.account_name,
                    updated_at=excluded.updated_at
                """,
                (
                    account_id,
                    account_name,
                    float(initial_capital),
                    now,
                    now,
                ),
            )
            conn.commit()

    def insert_paper_execution_order(
        self,
        row: dict[str, object],
    ) -> None:
        self.initialize()
        now = datetime.now().astimezone().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO paper_execution_orders(
                    order_id,account_id,signal_id,
                    market_data_provider,execution_provider,execution_mode,
                    underlying_name,underlying_price_entry,
                    instrument_token,exchange,tradingsymbol,
                    option_type,strike,expiry,lot_size,side,quantity,
                    entry_timestamp,entry_price,current_price,
                    stop_price,target1_price,target2_price,status,
                    entry_reason,exit_timestamp,exit_price,exit_reason,
                    unrealized_pnl,realized_pnl,mfe_points,mae_points,
                    execution_strategy_source,strategy_stop_loss_pct,
                    strategy_target_pct,exit_mode,evaluation_horizon_minutes,
                    signal_sources_json,merge_status,rsi_signal_id,
                    rsi_confirmation_timestamp,updated_at
                )
                VALUES(
                    ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
                )
                """,
                (
                    row.get("order_id"),
                    row.get("account_id"),
                    row.get("signal_id"),
                    row.get("market_data_provider"),
                    row.get("execution_provider"),
                    row.get("execution_mode"),
                    row.get("underlying_name"),
                    row.get("underlying_price_entry"),
                    row.get("instrument_token"),
                    row.get("exchange"),
                    row.get("tradingsymbol"),
                    row.get("option_type"),
                    row.get("strike"),
                    row.get("expiry"),
                    row.get("lot_size"),
                    row.get("side"),
                    row.get("quantity"),
                    row.get("entry_timestamp"),
                    row.get("entry_price"),
                    row.get("current_price"),
                    row.get("stop_price"),
                    row.get("target1_price"),
                    row.get("target2_price"),
                    row.get("status"),
                    row.get("entry_reason"),
                    row.get("exit_timestamp"),
                    row.get("exit_price"),
                    row.get("exit_reason"),
                    row.get("unrealized_pnl"),
                    row.get("realized_pnl"),
                    row.get("mfe_points"),
                    row.get("mae_points"),
                    row.get("execution_strategy_source"),
                    row.get("strategy_stop_loss_pct"),
                    row.get("strategy_target_pct"),
                    row.get("exit_mode"),
                    row.get("evaluation_horizon_minutes"),
                    json.dumps(row.get("signal_sources") or [], sort_keys=True, default=str),
                    row.get("merge_status"),
                    row.get("rsi_signal_id"),
                    row.get("rsi_confirmation_timestamp"),
                    now,
                ),
            )
            conn.commit()

    def read_paper_execution_order(
        self,
        order_id: str,
    ) -> dict[str, object] | None:
        self.initialize()
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT *
                FROM paper_execution_orders
                WHERE order_id=?
                """,
                (order_id,),
            ).fetchone()
        return dict(row) if row else None

    def read_paper_execution_orders(
        self,
        account_id: str,
    ) -> list[dict[str, object]]:
        self.initialize()
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM paper_execution_orders
                WHERE account_id=?
                ORDER BY entry_timestamp DESC
                """,
                (account_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def read_open_paper_execution_orders(
        self,
        account_id: str,
    ) -> list[dict[str, object]]:
        self.initialize()
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM paper_execution_orders
                WHERE account_id=? AND status='OPEN'
                ORDER BY entry_timestamp
                """,
                (account_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_paper_execution_mark_to_order(
        self,
        *,
        order_id: str,
        current_price: float,
        unrealized_pnl: float,
        mfe_points: float,
        mae_points: float,
        updated_at: str,
    ) -> None:
        self.initialize()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE paper_execution_orders
                SET current_price=?,
                    unrealized_pnl=?,
                    mfe_points=?,
                    mae_points=?,
                    updated_at=?
                WHERE order_id=? AND status='OPEN'
                """,
                (
                    float(current_price),
                    float(unrealized_pnl),
                    float(mfe_points),
                    float(mae_points),
                    updated_at,
                    order_id,
                ),
            )
            conn.commit()

    def update_paper_exit_protection(
        self,
        *,
        order_id: str,
        effective_stop: float | None,
        breakeven_armed: bool,
        trailing_active: bool,
        trailing_stop_price: float | None,
        exit_health_score: float | None,
        exit_action: str | None,
        exit_detail: str | None,
    ) -> None:
        self.initialize()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE paper_execution_orders
                SET stop_price=COALESCE(?, stop_price),
                    breakeven_armed=?,
                    trailing_active=?,
                    trailing_stop_price=?,
                    exit_health_score=?,
                    exit_action=?,
                    exit_detail=?,
                    updated_at=?
                WHERE order_id=? AND status='OPEN'
                """,
                (
                    effective_stop,
                    int(bool(breakeven_armed)),
                    int(bool(trailing_active)),
                    trailing_stop_price,
                    exit_health_score,
                    exit_action,
                    exit_detail,
                    datetime.now().astimezone().isoformat(),
                    order_id,
                ),
            )
            conn.commit()

    def close_paper_execution_order(
        self,
        *,
        order_id: str,
        exit_timestamp: str,
        exit_price: float,
        exit_reason: str,
        realized_pnl: float,
        mfe_points: float,
        mae_points: float,
    ) -> None:
        self.initialize()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE paper_execution_orders
                SET current_price=?,
                    exit_timestamp=?,
                    exit_price=?,
                    exit_reason=?,
                    unrealized_pnl=0,
                    realized_pnl=?,
                    mfe_points=?,
                    mae_points=?,
                    status='CLOSED',
                    updated_at=?
                WHERE order_id=? AND status='OPEN'
                """,
                (
                    float(exit_price),
                    exit_timestamp,
                    float(exit_price),
                    exit_reason,
                    float(realized_pnl),
                    float(mfe_points),
                    float(mae_points),
                    datetime.now().astimezone().isoformat(),
                    order_id,
                ),
            )
            conn.commit()

    def insert_paper_execution_mark(
        self,
        row: dict[str, object],
    ) -> None:
        self.initialize()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO paper_execution_marks(
                    order_id,timestamp,price,underlying_price,
                    unrealized_pnl,mfe_points,mae_points,event_type
                )
                VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    row.get("order_id"),
                    row.get("timestamp"),
                    row.get("price"),
                    row.get("underlying_price"),
                    row.get("unrealized_pnl"),
                    row.get("mfe_points"),
                    row.get("mae_points"),
                    row.get("event_type"),
                ),
            )
            conn.commit()

    def paper_execution_exists_for_signal(
        self,
        *,
        signal_id: str,
        account_id: str,
    ) -> bool:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM paper_execution_orders
                WHERE signal_id=? AND account_id=?
                LIMIT 1
                """,
                (signal_id, account_id),
            ).fetchone()
        return row is not None

    def paper_execution_exists_for_candidate(
        self,
        *,
        signal_id: str,
        account_id: str,
        instrument_token: int,
    ) -> bool:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM paper_execution_orders
                WHERE signal_id=? AND account_id=? AND instrument_token=?
                LIMIT 1
                """,
                (signal_id, account_id, int(instrument_token)),
            ).fetchone()
        return row is not None

    def insert_trade_selection_evaluation(self, row: dict[str, object]) -> None:
        self.evaluation.insert_trade_selection_evaluation(row)

    def read_trade_selection_evaluations(
        self, *, signal_id: str | None = None, trading_date: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, object]]:
        return self.evaluation.read_trade_selection_evaluations(
            signal_id=signal_id, trading_date=trading_date, limit=limit
        )

    def insert_institutional_execution_evaluation(
        self, row: dict[str, object]
    ) -> None:
        self.evaluation.insert_institutional_execution_evaluation(row)

    def read_institutional_execution_evaluations(
        self, *, signal_id: str | None = None, trading_date: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, object]]:
        return self.evaluation.read_institutional_execution_evaluations(
            signal_id=signal_id, trading_date=trading_date, limit=limit
        )

    def insert_execution_state_event(
        self,
        row: dict[str, object],
    ) -> None:
        self.evaluation.insert_execution_state_event(row)

    def read_execution_state_events(
        self,
        *,
        signal_id: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, object]]:
        return self.evaluation.read_execution_state_events(
            signal_id=signal_id, limit=limit
        )

    def read_execution_state_events_for_signals(
        self,
        signal_ids: Iterable[str],
        *,
        per_signal_limit: int = 50,
    ) -> dict[str, list[dict[str, object]]]:
        """Batch-load newest lifecycle events for multiple signals."""
        return self.evaluation.read_execution_state_events_for_signals(
            signal_ids, per_signal_limit=per_signal_limit
        )

    def upsert_execution_queue_item(self, row: dict[str, object]) -> None:
        self.evaluation.upsert_execution_queue_item(row)

    def read_execution_queue(
        self, *, status: str | None = None, signal_id: str | None = None,
        trading_date: str | None = None, limit: int = 200,
    ) -> list[dict[str, object]]:
        return self.evaluation.read_execution_queue(
            status=status, signal_id=signal_id, trading_date=trading_date, limit=limit
        )

    def update_execution_queue_status(
        self, *, queue_id: str, status: str, reason: str | None = None,
        order_id: str | None = None, executed_at: str | None = None,
    ) -> None:
        self.evaluation.update_execution_queue_status(
            queue_id=queue_id, status=status, reason=reason,
            order_id=order_id, executed_at=executed_at,
        )

    def update_execution_queue_for_order(
        self, *, order_id: str, status: str, reason: str | None = None,
    ) -> None:
        self.evaluation.update_execution_queue_for_order(
            order_id=order_id, status=status, reason=reason,
        )

    def upsert_paper_candidate_decision(
        self,
        row: dict[str, object],
    ) -> None:
        self.evaluation.upsert_paper_candidate_decision(row)

    def read_paper_candidate_decision(
        self,
        signal_id: str,
    ) -> dict[str, object] | None:
        return self.evaluation.read_paper_candidate_decision(signal_id)

    def read_paper_candidate_decisions(
        self,
        trading_date: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, object]]:
        return self.evaluation.read_paper_candidate_decisions(
            trading_date=trading_date, limit=limit
        )




    def insert_shadow_intelligence_evaluation(
        self,
        row: dict[str, object],
    ) -> None:
        self.evaluation.insert_shadow_intelligence_evaluation(row)

    def read_shadow_intelligence_evaluations(
        self,
        *,
        signal_id: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, object]]:
        return self.evaluation.read_shadow_intelligence_evaluations(
            signal_id=signal_id, limit=limit
        )

    def upsert_paper_monitor_status(
        self,
        row: dict[str, object],
    ) -> None:
        self.evaluation.upsert_paper_monitor_status(row)

    def read_paper_monitor_status(
        self,
        monitor_id: str = "PAPER-MONITOR",
    ) -> dict[str, object] | None:
        return self.evaluation.read_paper_monitor_status(monitor_id)

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
        return self.evaluation.write_step_evidence(
            process_name=process_name,
            run_id=run_id,
            step_name=step_name,
            parent_step=parent_step,
            started_at=started_at,
            status=status,
            artifacts=artifacts,
        )

    def update_step_evidence(
        self,
        *,
        step_id: int,
        completed_at: str,
        status: str,
        duration_ms: float,
        error_message: str | None = None,
    ) -> None:
        self.evaluation.update_step_evidence(
            step_id=step_id,
            completed_at=completed_at,
            status=status,
            duration_ms=duration_ms,
            error_message=error_message,
        )

    def read_step_timelines(
        self,
        *,
        process_name: str | None = None,
        limit_per_step: int = 5,
    ) -> dict[str, list[dict[str, object]]]:
        return self.evaluation.read_step_timelines(
            process_name=process_name,
            limit_per_step=limit_per_step,
        )

    def read_latest_step_evidence(
        self,
        *,
        process_name: str,
        step_name: str,
    ) -> dict[str, object] | None:
        return self.evaluation.read_latest_step_evidence(
            process_name=process_name,
            step_name=step_name,
        )

    def read_running_steps(
        self,
        *,
        older_than_seconds: float = 60.0,
    ) -> list[dict[str, object]]:
        return self.evaluation.read_running_steps(
            older_than_seconds=older_than_seconds,
        )

    def write_process_run_correlation(
        self,
        *,
        process_name: str,
        run_id: str,
        started_at: str,
        artifacts: dict[str, object] | None = None,
    ) -> None:
        return self.evaluation.write_process_run_correlation(
            process_name=process_name,
            run_id=run_id,
            started_at=started_at,
            artifacts=artifacts,
        )

    def read_process_run_correlation(
        self, *, process_name: str
    ) -> dict[str, object] | None:
        return self.evaluation.read_process_run_correlation(
            process_name=process_name,
        )

    def read_all_process_run_correlations(self) -> list[dict[str, object]]:
        return self.evaluation.read_all_process_run_correlations()

    def read_run_evidence(self, *, run_id: str) -> list[dict[str, object]]:
        return self.evaluation.read_run_evidence(run_id=run_id)

    def read_latest_error_per_process(self) -> list[dict[str, object]]:
        return self.evaluation.read_latest_error_per_process()

    def cleanup_process_evidence(
        self, *, retention_days: int = 7
    ) -> int:
        return self.evaluation.cleanup_process_evidence(
            retention_days=retention_days,
        )

    def read_last_cleanup_at(self) -> str | None:
        return self.evaluation.read_last_cleanup_at()

    def write_last_cleanup_at(self, started_at: str) -> None:
        return self.evaluation.write_last_cleanup_at(started_at=started_at)

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
        self.evaluation.record_paper_monitor_success(
            monitor_id,
            success_at=success_at,
            decision=decision,
            signal_id=signal_id,
            total_ms=total_ms,
            stages=stages,
            underlying_status=underlying_status,
            readiness_ms=readiness_ms,
            futures_status=futures_status,
            candle_timestamp=candle_timestamp,
            candle_age_seconds=candle_age_seconds,
            bridge_alignment=bridge_alignment,
            readiness_reason=readiness_reason,
        )


    def upsert_candidate_lifecycle(self, row: dict[str, object]) -> None:
        self.evaluation.upsert_candidate_lifecycle(row)

    def read_candidate_lifecycle(
        self, *, signal_id: str | None = None, state: str | None = None, limit: int = 100
    ) -> list[dict[str, object]]:
        return self.evaluation.read_candidate_lifecycle(
            signal_id=signal_id, state=state, limit=limit
        )

    def expire_execution_queue_for_signal(self, *, signal_id: str, reason: str) -> None:
        self.evaluation.expire_execution_queue_for_signal(
            signal_id=signal_id, reason=reason
        )

    def insert_opportunity_evaluation(
        self,
        row: dict[str, object],
    ) -> None:
        self.evaluation.insert_opportunity_evaluation(row)

    def read_opportunity_evaluations(
        self,
        *,
        limit: int = 100,
        signal_id: str | None = None,
        entry_mode: str | None = None,
    ) -> list[dict[str, object]]:
        return self.evaluation.read_opportunity_evaluations(
            limit=limit, signal_id=signal_id, entry_mode=entry_mode
        )

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
        self.evaluation.update_paper_entry_intelligence(
            order_id=order_id, entry_mode=entry_mode,
            signal_age_at_entry=signal_age_at_entry,
            opportunity_score=opportunity_score,
            reward_remaining_pct=reward_remaining_pct,
            candidate_rank=candidate_rank, candidate_score=candidate_score,
            selection_score=selection_score,
            historical_win_rate_pct=historical_win_rate_pct,
            historical_profit_factor=historical_profit_factor,
            historical_expectancy_pct=historical_expectancy_pct,
            historical_sample_size=historical_sample_size,
            execution_probability_pct=execution_probability_pct,
            expected_value_pct=expected_value_pct,
            intelligence_score=intelligence_score,
        )

    def insert_paper_signal_diagnostic(
        self,
        row: dict[str, object],
    ) -> None:
        self.evaluation.insert_paper_signal_diagnostic(row)

    def read_paper_signal_diagnostics(
        self,
        *,
        limit: int = 100,
        signal_id: str | None = None,
    ) -> list[dict[str, object]]:
        return self.evaluation.read_paper_signal_diagnostics(
            limit=limit, signal_id=signal_id
        )

    def read_latest_signal_for_trading(
        self, *, instrument_key: str, trading_date: str
    ) -> dict[str, object] | None:
        return self.evaluation.read_latest_signal_for_trading(
            instrument_key=instrument_key, trading_date=trading_date
        )

    def read_today_paper_activity(
        self, *, account_id: str, trading_date: str
    ) -> dict[str, object]:
        return self.evaluation.read_today_paper_activity(
            account_id=account_id, trading_date=trading_date
        )

    def read_today_signal_counts(
        self, *, instrument_key: str, trading_date: str
    ) -> dict[str, int]:
        return self.evaluation.read_today_signal_counts(
            instrument_key=instrument_key, trading_date=trading_date
        )

    def read_latest_option_chain_snapshot(
        self,
        instrument_key: str,
        trading_date: str,
    ) -> dict[str, object] | None:
        return self.evaluation.read_latest_option_chain_snapshot(
            instrument_key, trading_date
        )


    def update_signal_state(
        self,
        signal_id: str,
        state: str,
    ) -> None:
        """Persist a lifecycle state change for one signal."""
        self.signal.update_signal_state(signal_id, state)

    def prune_old_data(self, keep_days: int = 7) -> dict[str, int]:
        """Delete rows older than keep_days from high-volume tables.

        Returns a dict of table_name -> rows_deleted for observability.
        """
        self.initialize()
        cutoff_expr = "datetime('now', ?)"
        cutoff_param = f"-{keep_days} days"
        tables = [
            ("execution_state_events", "timestamp"),
            ("paper_signal_diagnostics", "timestamp"),
            ("institutional_execution_evaluations", "evaluated_at"),
            ("trade_selection_evaluations", "evaluated_at"),
            ("opportunity_evaluations", "evaluated_at"),
            ("option_execution_telemetry", "captured_at"),
        ]
        result: dict[str, int] = {}
        with self._connect() as conn:
            for table, ts_col in tables:
                try:
                    cursor = conn.execute(
                        f"DELETE FROM {table} WHERE {ts_col} < {cutoff_expr}",
                        (cutoff_param,),
                    )
                    result[table] = cursor.rowcount
                except Exception:
                    result[table] = -1
            conn.commit()
        return result

    def count_signal_entries(self, account_id: str, signal_id: str) -> int:
        """Count paper orders for a signal using SQL instead of loading all orders."""
        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM paper_execution_orders "
                "WHERE account_id=? AND signal_id=?",
                (account_id, signal_id),
            ).fetchone()
            return int(row[0]) if row else 0

