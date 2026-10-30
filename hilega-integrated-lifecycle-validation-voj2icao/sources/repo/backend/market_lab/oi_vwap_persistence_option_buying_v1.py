
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List


STRATEGY_NAME = "OI_VWAP_PERSISTENCE_OPTION_BUYING_V1"
MAX_OPEN_POSITIONS = 4
MAX_HOLDING_MINUTES = None
LIVE_TRADING_ENABLED = False


class Direction(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"


class OptionType(str, Enum):
    CE = "CE"
    PE = "PE"


class Decision(str, Enum):
    NO_TRADE = "NO_TRADE"
    P1_PENDING = "P1_PENDING"
    WAIT_P2 = "WAIT_P2"
    ENTER_CE_PAPER = "ENTER_CE_PAPER"
    ENTER_PE_PAPER = "ENTER_PE_PAPER"
    CAPACITY_REJECTED = "CAPACITY_REJECTED"
    DATA_REJECTED = "DATA_REJECTED"


@dataclass(frozen=True)
class OICheckpoint:
    timestamp: str
    previous_imbalance_5m: float
    current_imbalance_5m: float
    pcr_change_5m: float
    previous_session_imbalance: float
    current_session_imbalance: float
    ce_delta_5m: float
    pe_delta_5m: float


@dataclass(frozen=True)
class VWAPContext:
    candle_time: str
    available_at: str
    close: float
    vwap: float

    @property
    def side(self) -> str:
        if self.close > self.vwap:
            return "ABOVE"
        if self.close < self.vwap:
            return "BELOW"
        return "AT"


@dataclass(frozen=True)
class P1Setup:
    timestamp: str
    direction: Direction
    oi: OICheckpoint
    vwap: VWAPContext


@dataclass(frozen=True)
class PaperSignal:
    strategy: str
    decision: Decision
    timestamp: str
    direction: Optional[Direction] = None
    option_type: Optional[OptionType] = None
    reason: str = ""
    p1_timestamp: Optional[str] = None
    p2_timestamp: Optional[str] = None
    atm_strike: Optional[float] = None


@dataclass
class StrategyState:
    pending: Optional[P1Setup] = None
    open_position_count: int = 0
    audit: List[PaperSignal] = field(default_factory=list)


def detect_p1(oi: OICheckpoint) -> Optional[Direction]:
    """
    Fresh transition only.

    Bullish:
      previous imbalance <= 0
      current imbalance > 0
      PCR 5m change > 0
      session imbalance improves

    Bearish:
      previous imbalance >= 0
      current imbalance < 0
      PCR 5m change < 0
      session imbalance weakens
    """
    bullish = (
        oi.previous_imbalance_5m <= 0
        and oi.current_imbalance_5m > 0
        and oi.pcr_change_5m > 0
        and oi.current_session_imbalance > oi.previous_session_imbalance
    )
    if bullish:
        return Direction.BULLISH

    bearish = (
        oi.previous_imbalance_5m >= 0
        and oi.current_imbalance_5m < 0
        and oi.pcr_change_5m < 0
        and oi.current_session_imbalance < oi.previous_session_imbalance
    )
    if bearish:
        return Direction.BEARISH

    return None


def vwap_aligned(direction: Direction, vwap: VWAPContext) -> bool:
    if direction == Direction.BULLISH:
        return vwap.side == "ABOVE"
    return vwap.side == "BELOW"


def p2_persists(direction: Direction, next_oi: OICheckpoint) -> bool:
    """
    P2 is known only from the NEXT completed OI checkpoint.
    No future P3/P4 information is used here.
    """
    if direction == Direction.BULLISH:
        return next_oi.current_imbalance_5m > 0 and next_oi.pcr_change_5m > 0
    return next_oi.current_imbalance_5m < 0 and next_oi.pcr_change_5m < 0


class OIVWAPPersistenceStrategyV1:
    def __init__(self, max_open_positions: int = MAX_OPEN_POSITIONS):
        if max_open_positions != 4:
            raise ValueError("V1 is frozen for paper research with max_open_positions=4")
        self.state = StrategyState()

    def on_p1_checkpoint(self, oi: OICheckpoint, vwap: VWAPContext) -> PaperSignal:
        direction = detect_p1(oi)

        if direction is None:
            sig = PaperSignal(
                strategy=STRATEGY_NAME,
                decision=Decision.NO_TRADE,
                timestamp=oi.timestamp,
                reason="No fresh OI/PCR transition.",
            )
            self.state.audit.append(sig)
            return sig

        if not vwap_aligned(direction, vwap):
            self.state.pending = None
            sig = PaperSignal(
                strategy=STRATEGY_NAME,
                decision=Decision.NO_TRADE,
                timestamp=oi.timestamp,
                direction=direction,
                reason=f"P1 detected but causal VWAP side is {vwap.side}; alignment rejected.",
                p1_timestamp=oi.timestamp,
            )
            self.state.audit.append(sig)
            return sig

        setup = P1Setup(
            timestamp=oi.timestamp,
            direction=direction,
            oi=oi,
            vwap=vwap,
        )
        self.state.pending = setup
        sig = PaperSignal(
            strategy=STRATEGY_NAME,
            decision=Decision.WAIT_P2,
            timestamp=oi.timestamp,
            direction=direction,
            reason="Fresh P1 + causal VWAP alignment. Wait for next completed OI checkpoint (P2).",
            p1_timestamp=oi.timestamp,
        )
        self.state.audit.append(sig)
        return sig

    def on_p2_checkpoint(
        self,
        oi: OICheckpoint,
        *,
        exact_atm_strike: Optional[float],
        exact_atm_quote_available: bool,
        data_fresh: bool = True,
    ) -> PaperSignal:
        setup = self.state.pending
        if setup is None:
            sig = PaperSignal(
                strategy=STRATEGY_NAME,
                decision=Decision.NO_TRADE,
                timestamp=oi.timestamp,
                reason="No pending P1 setup.",
            )
            self.state.audit.append(sig)
            return sig

        if not data_fresh or not exact_atm_quote_available or exact_atm_strike is None:
            self.state.pending = None
            sig = PaperSignal(
                strategy=STRATEGY_NAME,
                decision=Decision.DATA_REJECTED,
                timestamp=oi.timestamp,
                direction=setup.direction,
                reason="P2 reached but required fresh data/exact ATM quote is unavailable.",
                p1_timestamp=setup.timestamp,
                p2_timestamp=oi.timestamp,
            )
            self.state.audit.append(sig)
            return sig

        if not p2_persists(setup.direction, oi):
            self.state.pending = None
            sig = PaperSignal(
                strategy=STRATEGY_NAME,
                decision=Decision.NO_TRADE,
                timestamp=oi.timestamp,
                direction=setup.direction,
                reason="P1 did not persist through P2.",
                p1_timestamp=setup.timestamp,
                p2_timestamp=oi.timestamp,
            )
            self.state.audit.append(sig)
            return sig

        if self.state.open_position_count >= MAX_OPEN_POSITIONS:
            self.state.pending = None
            sig = PaperSignal(
                strategy=STRATEGY_NAME,
                decision=Decision.CAPACITY_REJECTED,
                timestamp=oi.timestamp,
                direction=setup.direction,
                reason="Maximum 4 open paper positions already reached; do not evict an existing trade.",
                p1_timestamp=setup.timestamp,
                p2_timestamp=oi.timestamp,
                atm_strike=exact_atm_strike,
            )
            self.state.audit.append(sig)
            return sig

        decision = (
            Decision.ENTER_CE_PAPER
            if setup.direction == Direction.BULLISH
            else Decision.ENTER_PE_PAPER
        )
        option_type = OptionType.CE if setup.direction == Direction.BULLISH else OptionType.PE

        self.state.pending = None
        self.state.open_position_count += 1
        sig = PaperSignal(
            strategy=STRATEGY_NAME,
            decision=decision,
            timestamp=oi.timestamp,
            direction=setup.direction,
            option_type=option_type,
            reason="P1 + causal VWAP alignment + P2 persistence confirmed.",
            p1_timestamp=setup.timestamp,
            p2_timestamp=oi.timestamp,
            atm_strike=exact_atm_strike,
        )
        self.state.audit.append(sig)
        return sig

    def on_position_closed(self) -> None:
        if self.state.open_position_count <= 0:
            raise RuntimeError("No open position to close")
        self.state.open_position_count -= 1
