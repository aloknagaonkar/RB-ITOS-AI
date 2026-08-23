from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum

from red_bar_lab.domain.red_bar_v2 import Direction, EntryType, OptionSide


class PaperExecutionMode(str, Enum):
    OBSERVE_ONLY = "OBSERVE_ONLY"
    PAPER_CANARY = "PAPER_CANARY"


class PaperExecutionState(str, Enum):
    PREPARED = "PREPARED"
    SUBMISSION_STARTED = "SUBMISSION_STARTED"
    PAPER_ACCEPTED = "PAPER_ACCEPTED"
    PAPER_FILLED = "PAPER_FILLED"
    PAPER_REJECTED = "PAPER_REJECTED"
    SUBMISSION_UNCERTAIN = "SUBMISSION_UNCERTAIN"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


class PaperExecutionEventType(str, Enum):
    COMMAND_PREPARED = "COMMAND_PREPARED"
    SUBMISSION_STARTED = "SUBMISSION_STARTED"
    PAPER_ACCEPTED = "PAPER_ACCEPTED"
    PAPER_FILLED = "PAPER_FILLED"
    PAPER_REJECTED = "PAPER_REJECTED"
    SUBMISSION_UNCERTAIN = "SUBMISSION_UNCERTAIN"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


class PaperExecutionOutcome(str, Enum):
    FEATURE_DISABLED = "FEATURE_DISABLED"
    OBSERVE_ONLY = "OBSERVE_ONLY"
    BUNDLE_UNAVAILABLE = "BUNDLE_UNAVAILABLE"
    BUNDLE_CORRUPT = "BUNDLE_CORRUPT"
    BUNDLE_INELIGIBLE = "BUNDLE_INELIGIBLE"
    RESERVATION_UNAVAILABLE = "RESERVATION_UNAVAILABLE"
    RESERVATION_CORRUPT = "RESERVATION_CORRUPT"
    RESERVATION_EXPIRED = "RESERVATION_EXPIRED"
    RESERVATION_OWNER_MISMATCH = "RESERVATION_OWNER_MISMATCH"
    CONTRACT_UNAVAILABLE = "CONTRACT_UNAVAILABLE"
    COMMAND_PREPARED = "COMMAND_PREPARED"
    IDEMPOTENT_REPLAY = "IDEMPOTENT_REPLAY"
    SUBMISSION_ACCEPTED = "SUBMISSION_ACCEPTED"
    SUBMISSION_REJECTED = "SUBMISSION_REJECTED"
    SUBMISSION_UNCERTAIN = "SUBMISSION_UNCERTAIN"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    INVALID_REQUEST = "INVALID_REQUEST"


def _text(name: str, value: object) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _positive_int(name: str, value: object) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _aware(name: str, value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


@dataclass(frozen=True, slots=True)
class CanonicalPaperContract:
    instrument_token: int
    instrument_key: str
    tradingsymbol: str
    exchange: str
    option_side: OptionSide
    strike: float
    expiry: date
    lot_size: int
    selected_at: datetime
    quote_timestamp: datetime
    last_price: float
    best_bid: float | None
    best_ask: float | None

    def __post_init__(self) -> None:
        _positive_int("instrument_token", self.instrument_token)
        _text("instrument_key", self.instrument_key)
        _text("tradingsymbol", self.tradingsymbol)
        _text("exchange", self.exchange)
        if type(self.strike) not in (int, float) or float(self.strike) <= 0:
            raise ValueError("strike must be positive")
        _positive_int("lot_size", self.lot_size)
        _aware("selected_at", self.selected_at)
        _aware("quote_timestamp", self.quote_timestamp)
        if type(self.last_price) not in (int, float) or float(self.last_price) <= 0:
            raise ValueError("last_price must be positive")
        for name, value in (("best_bid", self.best_bid), ("best_ask", self.best_ask)):
            if value is not None and (type(value) not in (int, float) or float(value) <= 0):
                raise ValueError(f"{name} must be positive when supplied")


@dataclass(frozen=True, slots=True)
class CanonicalPaperExecutionCommand:
    command_id: str
    execution_id: str
    reservation_id: str
    bundle_id: str
    signal_id: str
    idempotency_key: str
    strategy_id: str
    strategy_version: str
    instrument_key: str
    trading_date: date
    direction: Direction
    option_side: OptionSide
    entry_type: EntryType
    signal_timestamp: datetime
    reservation_owner: str
    reservation_expiry: datetime
    contract: CanonicalPaperContract
    quantity: int
    order_side: str
    order_type: str
    limit_price: float | None
    created_at: datetime
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        for name in (
            "command_id", "execution_id", "reservation_id", "bundle_id", "signal_id",
            "idempotency_key", "strategy_id", "strategy_version", "instrument_key",
            "reservation_owner", "order_side", "order_type", "schema_version",
        ):
            _text(name, getattr(self, name))
        if self.strategy_id != "RED_BAR_V2":
            raise ValueError("strategy_id must be RED_BAR_V2")
        if self.schema_version != "1.0":
            raise ValueError("unsupported command schema")
        if self.contract.option_side is not self.option_side:
            raise ValueError("selected contract option side mismatch")
        _aware("signal_timestamp", self.signal_timestamp)
        _aware("reservation_expiry", self.reservation_expiry)
        _aware("created_at", self.created_at)
        _positive_int("quantity", self.quantity)
        if self.quantity % self.contract.lot_size != 0:
            raise ValueError("quantity must be a multiple of lot_size")
        if self.order_side != "BUY":
            raise ValueError("canonical paper entry order_side must be BUY")
        if self.order_type not in {"MARKET", "LIMIT"}:
            raise ValueError("unsupported paper order_type")
        if self.order_type == "LIMIT":
            if type(self.limit_price) not in (int, float) or float(self.limit_price) <= 0:
                raise ValueError("LIMIT order requires positive limit_price")
        elif self.limit_price is not None:
            raise ValueError("MARKET order cannot contain limit_price")
        from .paper_execution_identity import build_command_id, build_execution_id

        expected_execution = build_execution_id(
            bundle_id=self.bundle_id,
            reservation_id=self.reservation_id,
            contract_instrument_key=self.contract.instrument_key,
            quantity=self.quantity,
            order_side=self.order_side,
            order_type=self.order_type,
            limit_price=self.limit_price,
        )
        expected_command = build_command_id(execution_id=expected_execution, created_at=self.created_at)
        if self.execution_id != expected_execution:
            raise ValueError("execution_id does not match canonical intent identity")
        if self.command_id != expected_command:
            raise ValueError("command_id does not match canonical command identity")


@dataclass(frozen=True, slots=True)
class PaperExecutionResult:
    outcome: PaperExecutionOutcome
    reason_code: str
    command: CanonicalPaperExecutionCommand | None = None
    state: PaperExecutionState | None = None
    paper_order_id: str | None = None
