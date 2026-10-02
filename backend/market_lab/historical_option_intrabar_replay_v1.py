from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .historical_option_ohlc_adapter_v1 import (
    OptionMinuteCandle,
    choose_option_ohlc_session,
    instrument_candles,
)
from .historical_option_paper_replay_v1 import (
    HARD_STOP_PCT,
    BREAKEVEN_ARM_PCT,
    TRAIL_ARM_PCT,
    TRAIL_DISTANCE_PCT,
    HistoricalPaperPosition,
    replay_historical_paper_date,
)


INTRABAR_MODEL = "OPTION_1M_OHLC_INTRABAR_NEXT_MINUTE_OPEN_V1"


@dataclass
class IntrabarTrade:
    position_id: str
    session_date: str
    direction: str
    option_type: str
    strike: float
    instrument_key: str
    signal_time: str
    entry_time: str | None = None
    entry_price: float | None = None
    exit_time: str | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    highest_price: float | None = None
    breakeven_armed: bool = False
    trailing_armed: bool = False
    active_stop_price: float | None = None
    pending_stop_price: float | None = None
    entry_status: str = "PENDING"

    @property
    def pnl_pct(self) -> float | None:
        if self.entry_price is None or self.exit_price is None:
            return None
        return ((self.exit_price / self.entry_price) - 1.0) * 100.0


@dataclass(frozen=True)
class IntrabarEvent:
    timestamp: str
    event_type: str
    position_id: str
    reason_code: str | None = None
    data: dict = field(default_factory=dict)


@dataclass
class IntrabarReplayResult:
    session_date: str
    model: str
    ohlc_source: str
    trades: list[IntrabarTrade] = field(default_factory=list)
    events: list[IntrabarEvent] = field(default_factory=list)

    def summary(self) -> dict:
        entered = [t for t in self.trades if t.entry_status == "FILLED"]
        rejected = [t for t in self.trades if t.entry_status == "REJECTED"]
        closed = [t for t in entered if t.exit_time is not None]
        winners = [t for t in closed if (t.pnl_pct or 0.0) > 0]
        losers = [t for t in closed if (t.pnl_pct or 0.0) < 0]
        breakeven = [t for t in closed if abs(t.pnl_pct or 0.0) < 1e-12]
        return {
            "session_date": self.session_date,
            "model": self.model,
            "signals": len(self.trades),
            "entries": len(entered),
            "entry_rejects": len(rejected),
            "closed": len(closed),
            "open_at_end": sum(1 for t in entered if t.exit_time is None),
            "winners": len(winners),
            "losers": len(losers),
            "breakeven": len(breakeven),
            "aggregate_pnl_pct": sum((t.pnl_pct or 0.0) for t in closed),
        }


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _new_trade(position: HistoricalPaperPosition) -> IntrabarTrade:
    return IntrabarTrade(
        position_id=position.position_id,
        session_date=position.session_date,
        direction=position.direction,
        option_type=position.option_type,
        strike=position.strike,
        instrument_key=position.instrument_key,
        signal_time=position.opened_at,
    )


def _fill_at_next_minute_open(
    trade: IntrabarTrade,
    candles: list[OptionMinuteCandle],
) -> tuple[OptionMinuteCandle | None, IntrabarEvent]:
    signal_time = _dt(trade.signal_time)
    candidates = [c for c in candles if c.timestamp > signal_time]

    if not candidates:
        trade.entry_status = "REJECTED"
        return None, IntrabarEvent(
            timestamp=trade.signal_time,
            event_type="PAPER_ENTRY_REJECTED",
            position_id=trade.position_id,
            reason_code="NEXT_MINUTE_OPTION_CANDLE_UNAVAILABLE",
        )

    entry_candle = candidates[0]
    if entry_candle.open <= 0:
        trade.entry_status = "REJECTED"
        return None, IntrabarEvent(
            timestamp=entry_candle.timestamp.isoformat(),
            event_type="PAPER_ENTRY_REJECTED",
            position_id=trade.position_id,
            reason_code="NEXT_MINUTE_OPEN_INVALID",
            data={"open": entry_candle.open},
        )

    trade.entry_status = "FILLED"
    trade.entry_time = entry_candle.timestamp.isoformat()
    trade.entry_price = entry_candle.open
    trade.highest_price = entry_candle.open
    trade.active_stop_price = entry_candle.open * (
        1.0 + HARD_STOP_PCT / 100.0
    )

    return entry_candle, IntrabarEvent(
        timestamp=entry_candle.timestamp.isoformat(),
        event_type="PAPER_POSITION_OPENED",
        position_id=trade.position_id,
        data={
            "signal_time": trade.signal_time,
            "entry_price": trade.entry_price,
            "entry_model": "NEXT_MINUTE_OPTION_OPEN",
            "initial_stop": trade.active_stop_price,
        },
    )


def _activate_pending_stop(
    trade: IntrabarTrade,
    candle: OptionMinuteCandle,
) -> IntrabarEvent | None:
    if trade.pending_stop_price is None:
        return None

    old = trade.active_stop_price
    trade.active_stop_price = max(
        old if old is not None else float("-inf"),
        trade.pending_stop_price,
    )
    trade.pending_stop_price = None

    return IntrabarEvent(
        timestamp=candle.timestamp.isoformat(),
        event_type="STOP_ACTIVATED",
        position_id=trade.position_id,
        data={
            "previous_stop": old,
            "active_stop_price": trade.active_stop_price,
        },
    )


def _exit_on_active_stop(
    trade: IntrabarTrade,
    candle: OptionMinuteCandle,
) -> IntrabarEvent | None:
    stop = trade.active_stop_price
    if stop is None:
        return None

    # An already-active stop:
    # 1) gap-through at OPEN -> exit at OPEN
    # 2) otherwise LOW touch -> exit at stop
    if candle.open <= stop:
        exit_price = candle.open
    elif candle.low <= stop:
        exit_price = stop
    else:
        return None

    trade.exit_time = candle.timestamp.isoformat()
    trade.exit_price = exit_price

    if trade.trailing_armed:
        reason = "TRAIL_STOP"
    elif trade.breakeven_armed:
        reason = "BREAKEVEN_STOP"
    else:
        reason = "HARD_STOP"

    trade.exit_reason = reason

    return IntrabarEvent(
        timestamp=candle.timestamp.isoformat(),
        event_type="POSITION_CLOSED",
        position_id=trade.position_id,
        reason_code=reason,
        data={
            "open": candle.open,
            "high": candle.high,
            "low": candle.low,
            "close": candle.close,
            "active_stop_price": stop,
            "exit_price": exit_price,
            "pnl_pct": trade.pnl_pct,
        },
    )


def _stage_next_bar_stop(
    trade: IntrabarTrade,
    candle: OptionMinuteCandle,
) -> IntrabarEvent | None:
    assert trade.entry_price is not None

    if candle.high > (trade.highest_price or trade.entry_price):
        trade.highest_price = candle.high

    gain_high_pct = (
        (candle.high / trade.entry_price) - 1.0
    ) * 100.0

    next_stop = (
        trade.active_stop_price
        if trade.active_stop_price is not None
        else trade.entry_price * (1.0 + HARD_STOP_PCT / 100.0)
    )
    changed = False

    if gain_high_pct >= BREAKEVEN_ARM_PCT:
        if not trade.breakeven_armed:
            trade.breakeven_armed = True
            changed = True
        if trade.entry_price > next_stop:
            next_stop = trade.entry_price
            changed = True

    if gain_high_pct >= TRAIL_ARM_PCT:
        if not trade.trailing_armed:
            trade.trailing_armed = True
            changed = True

    if trade.trailing_armed:
        trail = (trade.highest_price or candle.high) * (
            1.0 - TRAIL_DISTANCE_PCT / 100.0
        )
        if trail > next_stop:
            next_stop = trail
            changed = True

    if not changed:
        return None

    trade.pending_stop_price = next_stop
    return IntrabarEvent(
        timestamp=candle.timestamp.isoformat(),
        event_type="STOP_STAGED_FOR_NEXT_BAR",
        position_id=trade.position_id,
        data={
            "candle_high": candle.high,
            "highest_price": trade.highest_price,
            "breakeven_armed": trade.breakeven_armed,
            "trailing_armed": trade.trailing_armed,
            "current_active_stop": trade.active_stop_price,
            "pending_stop_price": trade.pending_stop_price,
        },
    )


def replay_intrabar_trade(
    position: HistoricalPaperPosition,
    candles: list[OptionMinuteCandle],
) -> tuple[IntrabarTrade, list[IntrabarEvent]]:
    trade = _new_trade(position)
    events: list[IntrabarEvent] = []

    entry_candle, entry_event = _fill_at_next_minute_open(trade, candles)
    events.append(entry_event)
    if entry_candle is None:
        return trade, events

    start_index = candles.index(entry_candle)

    # The hard stop is active immediately after entry, so it can trigger inside
    # the entry minute. Any newly raised BE/trailing stop remains next-bar only.
    for idx in range(start_index, len(candles)):
        candle = candles[idx]

        if idx > start_index:
            activated = _activate_pending_stop(trade, candle)
            if activated is not None:
                events.append(activated)

        closed = _exit_on_active_stop(trade, candle)
        if closed is not None:
            events.append(closed)
            break

        staged = _stage_next_bar_stop(trade, candle)
        if staged is not None:
            events.append(staged)

    return trade, events


def replay_intrabar_date(
    session_date: str,
    *,
    data_root: str | Path = "data",
    futures_csv: str | Path = "data/historical-evidence/midpoint-v2-nifty-futures-vwap-v1-development.csv",
) -> IntrabarReplayResult:
    # P3H.3 remains the signal/exact-ATM source. Its checkpoint close price is
    # intentionally ignored here; P3H.4.1 derives entry from next-minute OHLC.
    base = replay_historical_paper_date(
        session_date,
        data_root=data_root,
        futures_csv=futures_csv,
    )

    ohlc = choose_option_ohlc_session(
        session_date,
        data_root=data_root,
    )

    result = IntrabarReplayResult(
        session_date=session_date,
        model=INTRABAR_MODEL,
        ohlc_source=ohlc.source_path,
    )

    for position in base.positions:
        candles = instrument_candles(
            ohlc,
            instrument_key=position.instrument_key,
            side=position.option_type,
        )
        trade, events = replay_intrabar_trade(position, candles)
        result.trades.append(trade)
        result.events.extend(events)

    return result
