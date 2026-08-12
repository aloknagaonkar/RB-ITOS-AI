from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

class TradeStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"

class ExitReason(str, Enum):
    OPEN = "OPEN"
    TARGET = "TARGET"
    STOP = "STOP"
    EOD = "EOD"
    TRAILING_STOP = "TRAILING_STOP"
    BREAK_EVEN = "BREAK_EVEN"
    NOT_EVALUABLE = "NOT_EVALUABLE"

class ExitModel(str, Enum):
    FIXED_TARGET = "FIXED_TARGET"
    RISK_REWARD = "RISK_REWARD"
    TRAILING_STOP = "TRAILING_STOP"
    BREAK_EVEN_1R = "BREAK_EVEN_1R"
    EOD_HOLD = "EOD_HOLD"

@dataclass(frozen=True)
class PaperTradeOutcome:
    trade_id: str
    signal_id: str
    instrument_key: str
    trading_date: str
    level_type: str
    direction: str
    entry_timestamp: datetime
    entry_price: float
    stop_price: float
    risk_points: float
    exit_model: ExitModel
    model_parameter: str
    target_points: float | None
    target_price: float | None
    exit_timestamp: datetime | None
    exit_price: float | None
    exit_reason: ExitReason
    status: TradeStatus
    points: float | None
    r_multiple: float | None
    mfe: float | None
    mae: float | None
    holding_minutes: int | None
    session_mfe_points: float | None
    session_mae_points: float | None
    session_extreme_price: float | None
    session_extreme_timestamp: datetime | None
    move_after_target_points: float | None
    minutes_from_target_to_extreme: int | None
    giveback_from_extreme_points: float | None
