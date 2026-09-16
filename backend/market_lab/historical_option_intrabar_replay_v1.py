from __future__ import annotations

from dataclasses import dataclass, field, asdict
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
    MAX_OPEN_POSITIONS,
    HistoricalPaperPosition,
    replay_historical_paper_date,
)


INTRABAR_MODEL = "OPTION_1M_OHLC_INTRABAR_V1"


@dataclass
class IntrabarTrade:
    position_id: str
    session_date: str
    direction: str
    option_type: str
    strike: float
    instrument_key: str
    entry_time: str
    entry_price: float
    exit_time: str | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    highest_price: float | None = None
    breakeven_armed: bool = False
    trailing_armed: bool = False
    active_stop_price: float | None = None
    pending_stop_price: float | None = None

    @property
    def pnl_pct(self) -> float | None:
        if self.exit_price is None:
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
        closed = [t for t in self.trades if t.exit_time is not None]
        return {
            "session_date": self.session_date,
            "model": self.model,
            "trades": len(self.trades),
            "closed": len(closed),
            "open_at_end": sum(1 for t in self.trades if t.exit_time is None),
            "winners": sum(1 for t in closed if (t.pnl_pct or 0) > 0),
            "losers": sum(1 for t in closed if (t.pnl_pct or 0) < 0),
            "aggregate_pnl_pct": sum((t.pnl_pct or 0.0) for t in closed),
        }


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _initial_trade(position: HistoricalPaperPosition) -> IntrabarTrade:
    hard_stop = position.entry_price * (1.0 + HARD_STOP_PCT / 100.0)
    return IntrabarTrade(
        position_id=position.position_id,
        session_date=position.session_date,
        direction=position.direction,
        option_type=position.option_type,
        strike=position.strike,
        instrument_key=position.instrument_key,
        entry_time=position.opened_at,
        entry_price=position.entry_price,
        highest_price=position.entry_price,
        active_stop_price=hard_stop,
    )


def _exit_on_active_stop(
    trade: IntrabarTrade,
    candle: OptionMinuteCandle,
) -> IntrabarEvent | None:
    stop = trade.active_stop_price
    if stop is None:
        return None

    # Frozen semantics:
    # - gap through an already-active stop => fill at bar OPEN
    # - otherwise intrabar LOW touch => fill at stop price
    if candle.open <= stop:
        trade.exit_time = candle.timestamp.isoformat()
        trade.exit_price = candle.open
    elif candle.low <= stop:
        trade.exit_time = candle.timestamp.isoformat()
        trade.exit_price = stop
    else:
        return None

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
            "exit_price": trade.exit_price,
            "pnl_pct": trade.pnl_pct,
        },
    )


def _stage_next_bar_stop(
    trade: IntrabarTrade,
    candle: OptionMinuteCandle,
) -> IntrabarEvent | None:
    if candle.high > (trade.highest_price or trade.entry_price):
        trade.highest_price = candle.high

    gain_high_pct = (
        ((candle.high / trade.entry_price) - 1.0) * 100.0
    )

    next_stop = trade.active_stop_price or (
        trade.entry_price * (1.0 + HARD_STOP_PCT / 100.0)
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

    # Activation is on the NEXT minute bar. Do not let a high and low inside
    # this same candle both activate and trigger the newly raised stop.
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


def _activate_pending_stop(
    trade: IntrabarTrade,
    candle: OptionMinuteCandle,
) -> IntrabarEvent | None:
    if trade.pending_stop_price is None:
        return None

    old = trade.active_stop_price
    trade.active_stop_price = max(
        old or float("-inf"),
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


def replay_intrabar_trade(
    position: HistoricalPaperPosition,
    candles: list[OptionMinuteCandle],
) -> tuple[IntrabarTrade, list[IntrabarEvent]]:
    trade = _initial_trade(position)
    events: list[IntrabarEvent] = []
    entry_time = _dt(position.opened_at)

    # Entry price remains the historical checkpoint-close proxy because the
    # source does not provide historical bid/ask. Risk evaluation begins only
    # with the first 1-minute candle AFTER the entry timestamp.
    future = [c for c in candles if c.timestamp > entry_time]

    for candle in future:
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
    base = replay_historical_paper_date(
        session_date,
        data_root=data_root,
        futures_csv=futures_csv,
    )

    if not base.positions:
        return IntrabarReplayResult(
            session_date=session_date,
            model=INTRABAR_MODEL,
            ohlc_source="",
        )

    expected_expiry = None
    for position in base.positions:
        parts = position.instrument_key.split("|")
        if len(parts) >= 3:
            # The adapter selects by cache expiry through the session file; the
            # exact expected expiry is obtained from the chosen positioning
            # session in the base phase, so no parsing dependency is required.
            break

    # Base P3H.3 exact-ATM positions are generated from the same historical
    # option expiry as the positioning cache. Choose the exact one-session OHLC
    # cache where available.
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
