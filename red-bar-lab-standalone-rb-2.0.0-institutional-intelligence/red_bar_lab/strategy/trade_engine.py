from __future__ import annotations

from datetime import time
import hashlib

import pandas as pd

from red_bar_lab.strategy.identity import canonical_signal_id
from red_bar_lab.strategy.models import (
    Direction,
    SignalAttempt,
    SignalState,
)
from red_bar_lab.strategy.trade_models import (
    ExitModel,
    ExitReason,
    PaperTradeOutcome,
    TradeStatus,
)


IST = "Asia/Kolkata"
DEFAULT_FIXED_TARGETS = (20.0, 30.0, 40.0, 50.0)
DEFAULT_R_MULTIPLES = (1.0, 2.0, 3.0)
DEFAULT_TRAIL_POINTS = (10.0, 20.0)


def deterministic_signal_id(
    instrument_key: str,
    trading_date: str,
    attempt: SignalAttempt,
) -> str:
    return canonical_signal_id(
        instrument_key,
        trading_date,
        attempt.level_type,
        attempt.direction.value if attempt.direction else None,
        attempt.cross_timestamp.isoformat()
        if attempt.cross_timestamp else None,
        attempt.confirmation_timestamp.isoformat()
        if attempt.confirmation_timestamp else None,
    )


def deterministic_trade_id(
    signal_id: str,
    exit_model: ExitModel,
    model_parameter: str,
) -> str:
    raw = f"{signal_id}|{exit_model.value}|{model_parameter}"
    return (
        f"TRD-"
        f"{hashlib.sha1(raw.encode()).hexdigest()[:16].upper()}"
    )


def _to_ist(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(
            columns=(
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
            )
        )
    result = frame.copy()
    ts = pd.to_datetime(
        result["timestamp"],
        errors="coerce",
        utc=True,
    )
    result = result.loc[ts.notna()].copy()
    result["timestamp"] = ts.loc[ts.notna()].dt.tz_convert(IST)
    return (
        result.sort_values("timestamp")
        .drop_duplicates("timestamp", keep="last")
        .reset_index(drop=True)
    )


def _stop_price(attempt: SignalAttempt) -> float:
    if attempt.direction is Direction.BULLISH:
        if attempt.cross_low is None:
            raise ValueError(
                "Bullish ACTIVE signal requires setup candle low."
            )
        return float(attempt.cross_low)
    if attempt.direction is Direction.BEARISH:
        if attempt.cross_high is None:
            raise ValueError(
                "Bearish ACTIVE signal requires setup candle high."
            )
        return float(attempt.cross_high)
    raise ValueError("Trade requires BULLISH or BEARISH direction.")


def _points(
    direction: Direction,
    entry: float,
    exit_price: float,
) -> float:
    return (
        exit_price - entry
        if direction is Direction.BULLISH
        else entry - exit_price
    )


def _target_price(
    direction: Direction,
    entry: float,
    target_points: float,
) -> float:
    return (
        entry + target_points
        if direction is Direction.BULLISH
        else entry - target_points
    )


def _excursions(
    direction: Direction,
    entry: float,
    rows: pd.DataFrame,
):
    if rows.empty:
        return None, None
    if direction is Direction.BULLISH:
        mfe = float(rows["high"].max()) - entry
        mae = entry - float(rows["low"].min())
    else:
        mfe = entry - float(rows["low"].min())
        mae = float(rows["high"].max()) - entry
    return max(0.0, mfe), max(0.0, mae)


def _session_analytics(
    direction,
    entry,
    session_rows,
    target_hit_timestamp=None,
    target_points=None,
):
    if session_rows.empty:
        return (None, None, None, None, None, None, None)

    session_mfe, session_mae = _excursions(
        direction, entry, session_rows
    )
    if direction is Direction.BULLISH:
        idx = session_rows["high"].idxmax()
        extreme_price = float(session_rows.loc[idx, "high"])
    else:
        idx = session_rows["low"].idxmin()
        extreme_price = float(session_rows.loc[idx, "low"])
    extreme_ts = pd.Timestamp(
        session_rows.loc[idx, "timestamp"]
    )

    move_after_target = None
    minutes_to_extreme = None
    giveback = None

    if target_hit_timestamp is not None and target_points is not None:
        post = session_rows[
            session_rows["timestamp"] >= target_hit_timestamp
        ].reset_index(drop=True)
        if not post.empty:
            if direction is Direction.BULLISH:
                pidx = post["high"].idxmax()
                post_extreme = float(post.loc[pidx, "high"])
                post_extreme_ts = pd.Timestamp(
                    post.loc[pidx, "timestamp"]
                )
                move_after_target = max(
                    0.0,
                    post_extreme - (entry + target_points),
                )
                giveback = max(
                    0.0,
                    post_extreme
                    - float(session_rows.iloc[-1]["close"]),
                )
            else:
                pidx = post["low"].idxmin()
                post_extreme = float(post.loc[pidx, "low"])
                post_extreme_ts = pd.Timestamp(
                    post.loc[pidx, "timestamp"]
                )
                move_after_target = max(
                    0.0,
                    (entry - target_points) - post_extreme,
                )
                giveback = max(
                    0.0,
                    float(session_rows.iloc[-1]["close"])
                    - post_extreme,
                )
            minutes_to_extreme = int(
                (
                    post_extreme_ts - target_hit_timestamp
                ).total_seconds()
                // 60
            )

    return (
        session_mfe,
        session_mae,
        extreme_price,
        extreme_ts.to_pydatetime(),
        move_after_target,
        minutes_to_extreme,
        giveback,
    )


def _base_context(
    frame,
    attempt,
    instrument_key,
    trading_date,
    session_end,
):
    if attempt.state is not SignalState.ACTIVE:
        raise ValueError(
            "Only ACTIVE signal attempts can become paper trades."
        )
    if attempt.direction is None:
        raise ValueError("ACTIVE signal direction is required.")
    if (
        attempt.confirmation_timestamp is None
        or attempt.underlying_entry is None
    ):
        raise ValueError(
            "ACTIVE signal requires confirmation time and entry."
        )

    source = _to_ist(frame)
    entry_ts = pd.Timestamp(attempt.confirmation_timestamp)
    if entry_ts.tzinfo is None:
        entry_ts = entry_ts.tz_localize(IST)
    else:
        entry_ts = entry_ts.tz_convert(IST)

    entry = float(attempt.underlying_entry)
    stop = _stop_price(attempt)
    risk = abs(entry - stop)
    if risk <= 0:
        raise ValueError("Trade risk must be greater than zero.")

    future = source[
        (source["timestamp"] > entry_ts)
        & (source["timestamp"].dt.time < session_end)
    ].reset_index(drop=True)

    signal_id = deterministic_signal_id(
        instrument_key,
        trading_date,
        attempt,
    )
    return entry_ts, entry, stop, risk, future, signal_id


def _make_outcome(
    *,
    attempt,
    instrument_key,
    trading_date,
    signal_id,
    exit_model,
    model_parameter,
    entry_ts,
    entry,
    stop,
    risk,
    target_points,
    target_price,
    exit_timestamp,
    exit_price,
    exit_reason,
    tracked,
    session_rows,
    target_hit_timestamp=None,
    status=TradeStatus.CLOSED,
):
    points = (
        None
        if exit_price is None
        else _points(
            attempt.direction,
            entry,
            float(exit_price),
        )
    )
    mfe, mae = _excursions(
        attempt.direction,
        entry,
        tracked,
    )
    holding = (
        None
        if exit_timestamp is None
        else int(
            (
                pd.Timestamp(exit_timestamp) - entry_ts
            ).total_seconds()
            // 60
        )
    )
    (
        session_mfe,
        session_mae,
        session_extreme_price,
        session_extreme_timestamp,
        move_after_target,
        minutes_to_extreme,
        giveback,
    ) = _session_analytics(
        attempt.direction,
        entry,
        session_rows,
        target_hit_timestamp,
        target_points,
    )

    return PaperTradeOutcome(
        trade_id=deterministic_trade_id(
            signal_id,
            exit_model,
            model_parameter,
        ),
        signal_id=signal_id,
        instrument_key=instrument_key,
        trading_date=trading_date,
        level_type=attempt.level_type,
        direction=attempt.direction.value,
        entry_timestamp=entry_ts.to_pydatetime(),
        entry_price=entry,
        stop_price=stop,
        risk_points=risk,
        exit_model=exit_model,
        model_parameter=model_parameter,
        target_points=target_points,
        target_price=target_price,
        exit_timestamp=(
            pd.Timestamp(exit_timestamp).to_pydatetime()
            if exit_timestamp is not None
            else None
        ),
        exit_price=(
            float(exit_price)
            if exit_price is not None
            else None
        ),
        exit_reason=exit_reason,
        status=status,
        points=points,
        r_multiple=(
            points / risk
            if points is not None
            else None
        ),
        mfe=mfe,
        mae=mae,
        holding_minutes=holding,
        session_mfe_points=session_mfe,
        session_mae_points=session_mae,
        session_extreme_price=session_extreme_price,
        session_extreme_timestamp=session_extreme_timestamp,
        move_after_target_points=move_after_target,
        minutes_from_target_to_extreme=minutes_to_extreme,
        giveback_from_extreme_points=giveback,
    )


def _open_outcome(
    *,
    attempt,
    instrument_key,
    trading_date,
    signal_id,
    exit_model,
    model_parameter,
    entry_ts,
    entry,
    stop,
    risk,
    target_points,
    target_price,
    future,
):
    return _make_outcome(
        attempt=attempt,
        instrument_key=instrument_key,
        trading_date=trading_date,
        signal_id=signal_id,
        exit_model=exit_model,
        model_parameter=model_parameter,
        entry_ts=entry_ts,
        entry=entry,
        stop=stop,
        risk=risk,
        target_points=target_points,
        target_price=target_price,
        exit_timestamp=None,
        exit_price=None,
        exit_reason=ExitReason.OPEN,
        tracked=future,
        session_rows=future,
        status=TradeStatus.OPEN,
    )


def evaluate_fixed_target(
    frame,
    attempt,
    *,
    instrument_key,
    trading_date,
    target_points,
    session_end=time(15, 30),
    exit_model=ExitModel.FIXED_TARGET,
    model_parameter=None,
    session_complete=True,
):
    (
        entry_ts,
        entry,
        stop,
        risk,
        future,
        signal_id,
    ) = _base_context(
        frame,
        attempt,
        instrument_key,
        trading_date,
        session_end,
    )

    target = _target_price(
        attempt.direction,
        entry,
        target_points,
    )
    parameter = model_parameter or f"{target_points:g}pt"

    if future.empty:
        if not session_complete:
            return _open_outcome(
                attempt=attempt,
                instrument_key=instrument_key,
                trading_date=trading_date,
                signal_id=signal_id,
                exit_model=exit_model,
                model_parameter=parameter,
                entry_ts=entry_ts,
                entry=entry,
                stop=stop,
                risk=risk,
                target_points=target_points,
                target_price=target,
                future=future,
            )
        return _make_outcome(
            attempt=attempt,
            instrument_key=instrument_key,
            trading_date=trading_date,
            signal_id=signal_id,
            exit_model=exit_model,
            model_parameter=parameter,
            entry_ts=entry_ts,
            entry=entry,
            stop=stop,
            risk=risk,
            target_points=target_points,
            target_price=target,
            exit_timestamp=None,
            exit_price=None,
            exit_reason=ExitReason.NOT_EVALUABLE,
            tracked=pd.DataFrame(),
            session_rows=pd.DataFrame(),
        )

    tracked = []
    exit_row = None
    exit_price = None
    exit_reason = None
    target_hit_ts = None

    for _, row in future.iterrows():
        tracked.append(row)
        high = float(row["high"])
        low = float(row["low"])

        if attempt.direction is Direction.BULLISH:
            stop_hit = low <= stop
            target_hit = high >= target
        else:
            stop_hit = high >= stop
            target_hit = low <= target

        # Conservative same-candle ambiguity rule.
        if stop_hit:
            exit_row = row
            exit_price = stop
            exit_reason = ExitReason.STOP
            break

        if target_hit:
            exit_row = row
            exit_price = target
            exit_reason = ExitReason.TARGET
            target_hit_ts = pd.Timestamp(row["timestamp"])
            break

    tracked_df = pd.DataFrame(tracked)

    if exit_row is None:
        if not session_complete:
            return _open_outcome(
                attempt=attempt,
                instrument_key=instrument_key,
                trading_date=trading_date,
                signal_id=signal_id,
                exit_model=exit_model,
                model_parameter=parameter,
                entry_ts=entry_ts,
                entry=entry,
                stop=stop,
                risk=risk,
                target_points=target_points,
                target_price=target,
                future=future,
            )

        exit_row = future.iloc[-1]
        exit_price = float(exit_row["close"])
        exit_reason = ExitReason.EOD
        tracked_df = future

    return _make_outcome(
        attempt=attempt,
        instrument_key=instrument_key,
        trading_date=trading_date,
        signal_id=signal_id,
        exit_model=exit_model,
        model_parameter=parameter,
        entry_ts=entry_ts,
        entry=entry,
        stop=stop,
        risk=risk,
        target_points=target_points,
        target_price=target,
        exit_timestamp=exit_row["timestamp"],
        exit_price=exit_price,
        exit_reason=exit_reason,
        tracked=tracked_df,
        session_rows=future,
        target_hit_timestamp=target_hit_ts,
    )


def evaluate_risk_reward(
    frame,
    attempt,
    *,
    instrument_key,
    trading_date,
    r_multiple,
    session_complete=True,
):
    entry = float(attempt.underlying_entry)
    stop = _stop_price(attempt)
    risk = abs(entry - stop)
    return evaluate_fixed_target(
        frame,
        attempt,
        instrument_key=instrument_key,
        trading_date=trading_date,
        target_points=risk * r_multiple,
        exit_model=ExitModel.RISK_REWARD,
        model_parameter=f"{r_multiple:g}R",
        session_complete=session_complete,
    )


def evaluate_eod_hold(
    frame,
    attempt,
    *,
    instrument_key,
    trading_date,
    session_end=time(15, 30),
    session_complete=True,
):
    (
        entry_ts,
        entry,
        stop,
        risk,
        future,
        signal_id,
    ) = _base_context(
        frame,
        attempt,
        instrument_key,
        trading_date,
        session_end,
    )

    if not session_complete:
        return _open_outcome(
            attempt=attempt,
            instrument_key=instrument_key,
            trading_date=trading_date,
            signal_id=signal_id,
            exit_model=ExitModel.EOD_HOLD,
            model_parameter="EOD",
            entry_ts=entry_ts,
            entry=entry,
            stop=stop,
            risk=risk,
            target_points=None,
            target_price=None,
            future=future,
        )

    if future.empty:
        return _make_outcome(
            attempt=attempt,
            instrument_key=instrument_key,
            trading_date=trading_date,
            signal_id=signal_id,
            exit_model=ExitModel.EOD_HOLD,
            model_parameter="EOD",
            entry_ts=entry_ts,
            entry=entry,
            stop=stop,
            risk=risk,
            target_points=None,
            target_price=None,
            exit_timestamp=None,
            exit_price=None,
            exit_reason=ExitReason.NOT_EVALUABLE,
            tracked=pd.DataFrame(),
            session_rows=pd.DataFrame(),
        )

    final = future.iloc[-1]
    return _make_outcome(
        attempt=attempt,
        instrument_key=instrument_key,
        trading_date=trading_date,
        signal_id=signal_id,
        exit_model=ExitModel.EOD_HOLD,
        model_parameter="EOD",
        entry_ts=entry_ts,
        entry=entry,
        stop=stop,
        risk=risk,
        target_points=None,
        target_price=None,
        exit_timestamp=final["timestamp"],
        exit_price=float(final["close"]),
        exit_reason=ExitReason.EOD,
        tracked=future,
        session_rows=future,
    )


def evaluate_trailing_stop(
    frame,
    attempt,
    *,
    instrument_key,
    trading_date,
    trail_points,
    session_end=time(15, 30),
    session_complete=True,
):
    (
        entry_ts,
        entry,
        stop,
        risk,
        future,
        signal_id,
    ) = _base_context(
        frame,
        attempt,
        instrument_key,
        trading_date,
        session_end,
    )

    if future.empty:
        if not session_complete:
            return _open_outcome(
                attempt=attempt,
                instrument_key=instrument_key,
                trading_date=trading_date,
                signal_id=signal_id,
                exit_model=ExitModel.TRAILING_STOP,
                model_parameter=f"{trail_points:g}pt",
                entry_ts=entry_ts,
                entry=entry,
                stop=stop,
                risk=risk,
                target_points=None,
                target_price=None,
                future=future,
            )
        return _make_outcome(
            attempt=attempt,
            instrument_key=instrument_key,
            trading_date=trading_date,
            signal_id=signal_id,
            exit_model=ExitModel.TRAILING_STOP,
            model_parameter=f"{trail_points:g}pt",
            entry_ts=entry_ts,
            entry=entry,
            stop=stop,
            risk=risk,
            target_points=None,
            target_price=None,
            exit_timestamp=None,
            exit_price=None,
            exit_reason=ExitReason.NOT_EVALUABLE,
            tracked=pd.DataFrame(),
            session_rows=pd.DataFrame(),
        )

    tracked = []
    trail = stop
    best = entry
    exit_row = None
    exit_price = None

    for _, row in future.iterrows():
        tracked.append(row)
        high = float(row["high"])
        low = float(row["low"])

        if attempt.direction is Direction.BULLISH:
            best = max(best, high)
            trail = max(stop, best - trail_points)
            if low <= trail:
                exit_row = row
                exit_price = trail
                break
        else:
            best = min(best, low)
            trail = min(stop, best + trail_points)
            if high >= trail:
                exit_row = row
                exit_price = trail
                break

    tracked_df = pd.DataFrame(tracked)

    if exit_row is None:
        if not session_complete:
            return _open_outcome(
                attempt=attempt,
                instrument_key=instrument_key,
                trading_date=trading_date,
                signal_id=signal_id,
                exit_model=ExitModel.TRAILING_STOP,
                model_parameter=f"{trail_points:g}pt",
                entry_ts=entry_ts,
                entry=entry,
                stop=stop,
                risk=risk,
                target_points=None,
                target_price=None,
                future=future,
            )

        exit_row = future.iloc[-1]
        exit_price = float(exit_row["close"])
        reason = ExitReason.EOD
        tracked_df = future
    else:
        reason = ExitReason.TRAILING_STOP

    return _make_outcome(
        attempt=attempt,
        instrument_key=instrument_key,
        trading_date=trading_date,
        signal_id=signal_id,
        exit_model=ExitModel.TRAILING_STOP,
        model_parameter=f"{trail_points:g}pt",
        entry_ts=entry_ts,
        entry=entry,
        stop=stop,
        risk=risk,
        target_points=None,
        target_price=None,
        exit_timestamp=exit_row["timestamp"],
        exit_price=exit_price,
        exit_reason=reason,
        tracked=tracked_df,
        session_rows=future,
    )


def evaluate_break_even_1r(
    frame,
    attempt,
    *,
    instrument_key,
    trading_date,
    session_end=time(15, 30),
    session_complete=True,
):
    (
        entry_ts,
        entry,
        stop,
        risk,
        future,
        signal_id,
    ) = _base_context(
        frame,
        attempt,
        instrument_key,
        trading_date,
        session_end,
    )

    if future.empty:
        if not session_complete:
            return _open_outcome(
                attempt=attempt,
                instrument_key=instrument_key,
                trading_date=trading_date,
                signal_id=signal_id,
                exit_model=ExitModel.BREAK_EVEN_1R,
                model_parameter="BE@1R",
                entry_ts=entry_ts,
                entry=entry,
                stop=stop,
                risk=risk,
                target_points=None,
                target_price=None,
                future=future,
            )
        return _make_outcome(
            attempt=attempt,
            instrument_key=instrument_key,
            trading_date=trading_date,
            signal_id=signal_id,
            exit_model=ExitModel.BREAK_EVEN_1R,
            model_parameter="BE@1R",
            entry_ts=entry_ts,
            entry=entry,
            stop=stop,
            risk=risk,
            target_points=None,
            target_price=None,
            exit_timestamp=None,
            exit_price=None,
            exit_reason=ExitReason.NOT_EVALUABLE,
            tracked=pd.DataFrame(),
            session_rows=pd.DataFrame(),
        )

    armed = False
    tracked = []
    exit_row = None
    exit_price = None
    reason = None

    for _, row in future.iterrows():
        tracked.append(row)
        high = float(row["high"])
        low = float(row["low"])

        if attempt.direction is Direction.BULLISH:
            if not armed and high >= entry + risk:
                armed = True
            active_stop = entry if armed else stop
            if low <= active_stop:
                exit_row = row
                exit_price = active_stop
                reason = (
                    ExitReason.BREAK_EVEN
                    if armed
                    else ExitReason.STOP
                )
                break
        else:
            if not armed and low <= entry - risk:
                armed = True
            active_stop = entry if armed else stop
            if high >= active_stop:
                exit_row = row
                exit_price = active_stop
                reason = (
                    ExitReason.BREAK_EVEN
                    if armed
                    else ExitReason.STOP
                )
                break

    tracked_df = pd.DataFrame(tracked)

    if exit_row is None:
        if not session_complete:
            return _open_outcome(
                attempt=attempt,
                instrument_key=instrument_key,
                trading_date=trading_date,
                signal_id=signal_id,
                exit_model=ExitModel.BREAK_EVEN_1R,
                model_parameter="BE@1R",
                entry_ts=entry_ts,
                entry=entry,
                stop=stop,
                risk=risk,
                target_points=None,
                target_price=None,
                future=future,
            )

        exit_row = future.iloc[-1]
        exit_price = float(exit_row["close"])
        reason = ExitReason.EOD
        tracked_df = future

    return _make_outcome(
        attempt=attempt,
        instrument_key=instrument_key,
        trading_date=trading_date,
        signal_id=signal_id,
        exit_model=ExitModel.BREAK_EVEN_1R,
        model_parameter="BE@1R",
        entry_ts=entry_ts,
        entry=entry,
        stop=stop,
        risk=risk,
        target_points=None,
        target_price=None,
        exit_timestamp=exit_row["timestamp"],
        exit_price=exit_price,
        exit_reason=reason,
        tracked=tracked_df,
        session_rows=future,
    )


def evaluate_active_signals(
    frame,
    attempts,
    *,
    instrument_key,
    trading_date,
    fixed_targets=DEFAULT_FIXED_TARGETS,
    risk_reward_multiples=DEFAULT_R_MULTIPLES,
    trail_points=DEFAULT_TRAIL_POINTS,
    session_complete=True,
):
    outcomes = []

    for attempt in attempts:
        if attempt.state is not SignalState.ACTIVE:
            continue

        for target in fixed_targets:
            outcomes.append(
                evaluate_fixed_target(
                    frame,
                    attempt,
                    instrument_key=instrument_key,
                    trading_date=trading_date,
                    target_points=float(target),
                    session_complete=session_complete,
                )
            )

        for multiple in risk_reward_multiples:
            outcomes.append(
                evaluate_risk_reward(
                    frame,
                    attempt,
                    instrument_key=instrument_key,
                    trading_date=trading_date,
                    r_multiple=float(multiple),
                    session_complete=session_complete,
                )
            )

        for trail in trail_points:
            outcomes.append(
                evaluate_trailing_stop(
                    frame,
                    attempt,
                    instrument_key=instrument_key,
                    trading_date=trading_date,
                    trail_points=float(trail),
                    session_complete=session_complete,
                )
            )

        outcomes.append(
            evaluate_break_even_1r(
                frame,
                attempt,
                instrument_key=instrument_key,
                trading_date=trading_date,
                session_complete=session_complete,
            )
        )
        outcomes.append(
            evaluate_eod_hold(
                frame,
                attempt,
                instrument_key=instrument_key,
                trading_date=trading_date,
                session_complete=session_complete,
            )
        )

    outcomes.sort(
        key=lambda item: (
            item.entry_timestamp,
            item.level_type,
            item.exit_model.value,
            item.model_parameter,
        )
    )
    return tuple(outcomes)
