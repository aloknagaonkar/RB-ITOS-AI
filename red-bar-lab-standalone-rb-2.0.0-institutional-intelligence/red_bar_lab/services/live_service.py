from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from red_bar_lab.services.historical_service import (
    RedBarHistoricalService,
    india_today,
    normalize_candles,
)
from red_bar_lab.storage.artifacts import ArtifactLayout
from red_bar_lab.storage.database import RedBarDatabase
from red_bar_lab.strategy.level_engine import aggregate_candles, build_daily_levels
from red_bar_lab.strategy.trade_engine import evaluate_active_signals
from red_bar_lab.strategy.trade_outcome import (
    summarize_actionable_models,
    benchmark_summary,
)
from red_bar_lab.strategy.signal_view import (
    trader_status,
    current_result,
    priority_label,
    quality_explanation,
    actionable_score,
    quality_band,
    quality_symbol,
    sequence_signal_attempts,
    summarize_completed_signals,
)
from red_bar_lab.strategy.signal_engine import scan_reference_levels


INDIA_TZ = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class LiveSnapshot:
    connected: bool
    last_update: datetime | None
    rows: int
    message: str
    candles: pd.DataFrame


@dataclass(frozen=True)
class LiveMonitorResult:
    connected: bool
    trading_date: date
    last_refresh: datetime
    source_rows: int
    completed_five_minute_rows: int
    levels_stored: int
    attempts: int
    active: int
    failed: int
    awaiting: int
    latest_completed_candle: dict[str, object] | None
    active_attempts: tuple[dict[str, object], ...]
    completed_attempts: tuple[dict[str, object], ...]
    failed_attempts: tuple[dict[str, object], ...]
    awaiting_attempts: tuple[dict[str, object], ...]
    event_timeline: tuple[dict[str, object], ...]
    current_price: float | None
    level_diagnostics: tuple[dict[str, object], ...] = ()
    message: str = ""


def _build_level_diagnostics(
    *,
    levels: list[object],
    current_price: float | None,
    attempts: tuple[object, ...] | list[object],
) -> tuple[dict[str, object], ...]:
    """Return a per-level diagnostic record for the live monitor log/UI.

    Each entry explains whether ``current_price`` is currently inside the
    level's source candle range (already consumed), above it (would need a
    bearish break to re-trigger), or below it (would need a bullish break).
    The output is also annotated with the latest attempt state for the level
    so an operator can immediately see why no signal was generated.
    """
    if current_price is None or not levels:
        return ()

    latest_attempt_by_level: dict[str, object] = {}
    for attempt in attempts:
        level_type = getattr(attempt, "level_type", None)
        if not level_type:
            continue
        existing = latest_attempt_by_level.get(level_type)
        if existing is None:
            latest_attempt_by_level[level_type] = attempt
            continue
        existing_ts = getattr(existing, "cross_timestamp", None)
        new_ts = getattr(attempt, "cross_timestamp", None)
        if new_ts is not None and (
            existing_ts is None or new_ts > existing_ts
        ):
            latest_attempt_by_level[level_type] = attempt

    diagnostics: list[dict[str, object]] = []
    for level in levels:
        level_type = getattr(level, "level_type", None)
        source_high = getattr(level, "source_high", None)
        source_low = getattr(level, "source_low", None)
        source_timestamp = getattr(level, "source_timestamp", None)
        interval_minutes = getattr(level, "interval_minutes", None)
        if level_type is None or source_high is None or source_low is None:
            continue
        midpoint = (float(source_high) + float(source_low)) / 2.0
        price = float(current_price)
        if source_low <= price <= source_high:
            status = "PRICE_INSIDE_RANGE"
        elif price > source_high:
            status = "PRICE_ABOVE_LEVEL"
        elif price < source_low:
            status = "PRICE_BELOW_LEVEL"

        last_attempt = latest_attempt_by_level.get(level_type)
        last_attempt_state = getattr(last_attempt, "state", None)
        last_attempt_state_value = (
            last_attempt_state.value
            if last_attempt_state is not None and hasattr(last_attempt_state, "value")
            else last_attempt_state
        )
        entry: dict[str, object] = {
            "level_type": str(level_type),
            "source_timestamp": (
                source_timestamp.isoformat()
                if source_timestamp is not None
                else None
            ),
            "source_high": float(source_high),
            "source_low": float(source_low),
            "midpoint": midpoint,
            "interval_minutes": int(interval_minutes) if interval_minutes is not None else None,
            "current_price": price,
            "status": status,
            "distance_to_high": float(source_high) - price,
            "distance_to_low": price - float(source_low),
        }
        if status == "PRICE_INSIDE_RANGE":
            entry["explanation"] = (
                "Current price is inside the level's source candle range; "
                "no cross can fire until price leaves the range."
            )
        elif status == "PRICE_ABOVE_LEVEL":
            entry["explanation"] = (
                f"Need a bearish break (close below {float(source_low):.2f}) "
                "to trigger a new attempt."
            )
        elif status == "PRICE_BELOW_LEVEL":
            entry["explanation"] = (
                f"Need a bullish break (close above {float(source_high):.2f}) "
                "to trigger a new attempt."
            )
        entry["last_attempt_state"] = last_attempt_state_value
        entry["has_active_attempt"] = last_attempt_state_value in {
            "ACTIVE",
            "AWAITING_CONFIRMATION",
        }
        diagnostics.append(entry)
    return tuple(diagnostics)


def completed_signal_source(
    frame: pd.DataFrame,
    *,
    now: datetime | None = None,
    interval_minutes: int = 1,
) -> pd.DataFrame:
    """Return completed 1-minute candles available at the refresh instant.

    RB-0.5 needs the completed 1-minute candles inside the current 5-minute
    bucket because they are the confirmation candles. The signal engine itself
    ensures that Candle A is always a fully completed 5-minute setup candle.
    """
    normalized = normalize_candles(frame)
    if normalized.empty:
        return normalized

    current = now or datetime.now(INDIA_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=INDIA_TZ)
    else:
        current = current.astimezone(INDIA_TZ)

    local = normalized["timestamp"].dt.tz_convert(INDIA_TZ)
    if current.time() >= time(15, 30):
        cutoff = pd.Timestamp(
            datetime.combine(current.date(), time(15, 30), tzinfo=INDIA_TZ)
        )
    else:
        cutoff = pd.Timestamp(
            current.replace(second=0, microsecond=0)
        )

    return normalized.loc[local < cutoff].reset_index(drop=True)


def _confirmation_requirement(direction: str | None, cross_high, cross_low):
    if direction == "BULLISH":
        return (
            "1m close > setup high",
            float(cross_high) if cross_high is not None else None,
        )
    if direction == "BEARISH":
        return (
            "1m close < setup low",
            float(cross_low) if cross_low is not None else None,
        )
    return ("Unknown", None)


def _attempt_visibility(
    one_minute: pd.DataFrame,
    attempt: dict[str, object],
) -> dict[str, object]:
    """Build a human-readable explanation of one live signal attempt."""
    direction = attempt.get("direction")
    state = attempt.get("state")
    requirement, required_price = _confirmation_requirement(
        direction,
        attempt.get("cross_high"),
        attempt.get("cross_low"),
    )

    cross_raw = attempt.get("cross_timestamp")
    confirmation_rows: list[dict[str, object]] = []
    if cross_raw:
        cross_ts = pd.Timestamp(cross_raw)
        if cross_ts.tzinfo is None:
            cross_ts = cross_ts.tz_localize(INDIA_TZ)
        else:
            cross_ts = cross_ts.tz_convert(INDIA_TZ)

        start = cross_ts + pd.Timedelta(minutes=5)
        end = start + pd.Timedelta(minutes=5)
        local = normalize_candles(one_minute)
        local_ts = local["timestamp"].dt.tz_convert(INDIA_TZ)
        window = local.loc[
            (local_ts >= start) & (local_ts < end)
        ].copy()

        for _, row in window.iterrows():
            close_value = float(row["close"])
            confirmed = (
                close_value > required_price
                if direction == "BULLISH" and required_price is not None
                else close_value < required_price
                if direction == "BEARISH" and required_price is not None
                else False
            )
            confirmation_rows.append(
                {
                    "timestamp": row["timestamp"].tz_convert(INDIA_TZ),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": close_value,
                    "confirmed": confirmed,
                }
            )

    checked = len(confirmation_rows)

    if state == "ACTIVE":
        reason = (
            "CONFIRMED_1M_CLOSE_ABOVE_SETUP_HIGH"
            if direction == "BULLISH"
            else "CONFIRMED_1M_CLOSE_BELOW_SETUP_LOW"
        )
    elif state in {"TIMEOUT", "CONFIRMATION_FAILED"}:
        reason = (
            "TIMEOUT_NO_1M_CLOSE_ABOVE_SETUP_HIGH"
            if direction == "BULLISH"
            else "TIMEOUT_NO_1M_CLOSE_BELOW_SETUP_LOW"
        )
    elif state == "AWAITING_CONFIRMATION":
        reason = (
            "WAITING_FOR_1M_CLOSE_ABOVE_SETUP_HIGH"
            if direction == "BULLISH"
            else "WAITING_FOR_1M_CLOSE_BELOW_SETUP_LOW"
        )
    else:
        reason = state or "UNKNOWN"

    return {
        **attempt,
        "required_condition": requirement,
        "required_price": required_price,
        "confirmation_candles_checked": checked,
        "confirmation_candles_remaining": max(0, 5 - checked),
        "reason": reason,
        "confirmation_window": confirmation_rows,
    }


def _event_timeline(
    details: list[dict[str, object]],
) -> tuple[dict[str, object], ...]:
    events: list[dict[str, object]] = []
    for item in details:
        events.append(
            {
                "timestamp": item.get("cross_timestamp"),
                "level_type": item.get("level_type"),
                "direction": item.get("direction"),
                "event": "5M_SETUP",
                "detail": (
                    f"5m setup crossed level {item.get('level_value')} and "
                    f"closed beyond midpoint."
                ),
            }
        )

        for candle in item.get("confirmation_window", []):
            events.append(
                {
                    "timestamp": candle["timestamp"],
                    "level_type": item.get("level_type"),
                    "direction": item.get("direction"),
                    "event": (
                        "1M_CONFIRMED"
                        if candle["confirmed"]
                        else "1M_CHECK"
                    ),
                    "detail": (
                        f"1m close={candle['close']} | "
                        f"required: {item.get('required_condition')} "
                        f"{item.get('required_price')}"
                    ),
                }
            )

        terminal_time = (
            item.get("confirmation_timestamp")
            or (
                item.get("confirmation_window", [])[-1]["timestamp"]
                if item.get("confirmation_window")
                else item.get("cross_timestamp")
            )
        )
        events.append(
            {
                "timestamp": terminal_time,
                "level_type": item.get("level_type"),
                "direction": item.get("direction"),
                "event": item.get("state"),
                "detail": item.get("reason"),
            }
        )

    def sort_key(event):
        value = event.get("timestamp")
        try:
            return pd.Timestamp(value)
        except Exception:
            return pd.Timestamp.min.tz_localize("UTC")

    events.sort(key=sort_key)
    return tuple(events)


def _live_points(direction: str | None, entry, current_price):
    if entry is None or current_price is None:
        return None
    entry = float(entry)
    current_price = float(current_price)
    if direction == "BULLISH":
        return current_price - entry
    if direction == "BEARISH":
        return entry - current_price
    return None



def _trade_model_counts(
    database,
    instrument_key: str,
    trading_date: str,
    signal_id: str,
    current_price=None,
    direction=None,
    entry_price=None,
):
    rows = database.read_paper_trade_outcomes(
        instrument_key, trading_date
    )
    matching = [
        row for row in rows
        if row.get("signal_id") == signal_id
    ]
    actionable = summarize_actionable_models(matching)
    benchmark = benchmark_summary(
        matching,
        current_price=current_price,
        direction=direction,
        entry_price=entry_price,
    )
    return actionable, benchmark


FIXED_TARGET_MILESTONES = (20.0, 30.0, 40.0, 50.0)


def _session_complete_for_live(refresh_time: datetime) -> bool:
    return refresh_time.timetz().replace(tzinfo=None) >= time(15, 30)


def _live_excursions(
    one_minute: pd.DataFrame,
    attempt: dict[str, object],
):
    entry = attempt.get("underlying_entry")
    confirmation = attempt.get("confirmation_timestamp")
    direction = attempt.get("direction")
    if entry is None or confirmation is None or one_minute.empty:
        return None, None

    source = normalize_candles(one_minute)
    confirm_ts = pd.Timestamp(confirmation)
    if confirm_ts.tzinfo is None:
        confirm_ts = confirm_ts.tz_localize(INDIA_TZ)
    else:
        confirm_ts = confirm_ts.tz_convert(INDIA_TZ)

    local_ts = source["timestamp"].dt.tz_convert(INDIA_TZ)
    future = source.loc[local_ts > confirm_ts]
    if future.empty:
        return 0.0, 0.0

    entry = float(entry)
    if direction == "BULLISH":
        mfe = float(future["high"].max()) - entry
        mae = entry - float(future["low"].min())
    elif direction == "BEARISH":
        mfe = entry - float(future["low"].min())
        mae = float(future["high"].max()) - entry
    else:
        return None, None
    return max(0.0, mfe), max(0.0, mae)


def _target_progress(
    live_points,
    live_mfe,
):
    favorable_now = max(0.0, float(live_points or 0.0))
    favorable_best = max(0.0, float(live_mfe or 0.0))

    hit = [
        int(target)
        for target in FIXED_TARGET_MILESTONES
        if favorable_best >= target
    ]
    next_target = next(
        (
            int(target)
            for target in FIXED_TARGET_MILESTONES
            if favorable_best < target
        ),
        None,
    )
    points_to_next = (
        max(0.0, float(next_target) - favorable_now)
        if next_target is not None
        else 0.0
    )

    return {
        "targets_hit": ",".join(str(x) for x in hit) if hit else "NONE",
        "highest_target_hit": max(hit) if hit else None,
        "next_target": next_target,
        "points_to_next_target": round(points_to_next, 2),
        "target_progress": (
            "ALL_20_30_40_50_HIT"
            if next_target is None
            else f"{favorable_now:.2f}/{next_target}"
        ),
    }


@dataclass
class RedBarLiveService:
    historical: RedBarHistoricalService
    layout: ArtifactLayout
    database: RedBarDatabase
    provider_name: str = "upstox"

    def snapshot(self, instrument_key: str, interval_minutes: int = 1) -> LiveSnapshot:
        try:
            candles = self.historical.provider.intraday_candles(
                instrument_key, interval_minutes=interval_minutes
            )
            candles = normalize_candles(candles)
            return LiveSnapshot(
                connected=True,
                last_update=datetime.now(timezone.utc),
                rows=len(candles),
                message="Upstox intraday polling connected",
                candles=candles,
            )
        except Exception as exc:
            return LiveSnapshot(
                connected=False,
                last_update=None,
                rows=0,
                message=str(exc),
                candles=pd.DataFrame(),
            )

    def refresh(
        self,
        instrument_key: str,
        *,
        now: datetime | None = None,
    ) -> LiveMonitorResult:
        refresh_time = now or datetime.now(INDIA_TZ)
        if refresh_time.tzinfo is None:
            refresh_time = refresh_time.replace(tzinfo=INDIA_TZ)
        else:
            refresh_time = refresh_time.astimezone(INDIA_TZ)
        trading_date = refresh_time.date()

        download = self.historical.load_or_download(
            instrument_key,
            trading_date,
            trading_date,
            interval_minutes=1,
            force=True,
        )
        current = self.historical.read_day(
            instrument_key, trading_date, interval_minutes=1
        )
        if current.empty:
            return LiveMonitorResult(
                connected=False,
                trading_date=trading_date,
                last_refresh=refresh_time,
                source_rows=0,
                completed_five_minute_rows=0,
                levels_stored=0,
                attempts=0,
                active=0,
                failed=0,
                awaiting=0,
                latest_completed_candle=None,
                active_attempts=(),
                completed_attempts=(),
                failed_attempts=(),
                awaiting_attempts=(),
                event_timeline=(),
                current_price=None,
                message="No current-session candles returned.",
            )

        live_path = self.layout.live_session_path(
            self.provider_name, instrument_key, 1
        )
        live_path.parent.mkdir(parents=True, exist_ok=True)
        current.to_csv(live_path, index=False)

        dates = self.historical.available_dates(instrument_key, interval_minutes=1)
        previous_dates = [day for day in dates if day < trading_date][-10:]
        previous = [
            (
                day,
                self.historical.read_day(
                    instrument_key, day, interval_minutes=1
                ),
            )
            for day in previous_dates
        ]

        daily = build_daily_levels(
            trading_date, current, previous, previous_days=10
        )
        levels = list(daily.previous_day_levels)
        levels.extend(
            level
            for level in (
                daily.first_candle,
                daily.next_red_candle,
                daily.mid_session_candle,
            )
            if level is not None
        )
        levels_stored = self.database.replace_reference_levels(
            instrument_key, trading_date.isoformat(), levels
        )

        completed_source = completed_signal_source(
            current, now=refresh_time, interval_minutes=1
        )
        completed_five = aggregate_candles(completed_source, 5)
        if not completed_five.empty:
            counts = (
                completed_source.set_index(
                    completed_source["timestamp"].dt.tz_convert(INDIA_TZ)
                )
                .resample(
                    "5min",
                    origin="start_day",
                    offset="15min",
                    label="left",
                    closed="left",
                )["close"]
                .count()
            )
            complete_starts = set(counts[counts >= 5].index)
            completed_five = completed_five[
                completed_five["timestamp"].isin(complete_starts)
            ].reset_index(drop=True)
        scan = scan_reference_levels(completed_source, levels)
        self.database.replace_signal_attempts(
            "LIVE_MONITOR",
            instrument_key,
            trading_date.isoformat(),
            scan.attempts,
        )

        # RB-0.6.8: live paper trades are refreshed automatically from the
        # same ACTIVE signals. Unresolved models remain OPEN before 15:30.
        live_outcomes = evaluate_active_signals(
            completed_source,
            scan.active,
            instrument_key=instrument_key,
            trading_date=trading_date.isoformat(),
            session_complete=_session_complete_for_live(refresh_time),
        )
        self.database.replace_paper_trade_outcomes(
            instrument_key,
            trading_date.isoformat(),
            live_outcomes,
        )

        stored_attempts = self.database.read_signal_attempts(
            instrument_key,
            trading_date.isoformat(),
        )
        sequenced_attempts = sequence_signal_attempts(stored_attempts)
        details = [
            _attempt_visibility(completed_source, attempt)
            for attempt in sequenced_attempts
        ]
        current_price = (
            float(current.iloc[-1]["close"])
            if not current.empty
            else None
        )

        enriched_active = []
        for item in details:
            if item.get("state") != "ACTIVE":
                continue
            signal_id = item.get("signal_id")
            actionable = {
                "actionable_total": 0,
                "actionable_open": 0,
                "actionable_closed": 0,
                "actionable_success": 0,
                "actionable_failed": 0,
                "actionable_breakeven": 0,
                "actionable_success_rate_pct": 0.0,
                "signal_lifecycle": "ACTIVE",
                "signal_quality": "IN_PROGRESS",
            }
            benchmark = {
                "benchmark_status": "NOT_AVAILABLE",
                "benchmark_current_points": None,
                "benchmark_final_points": None,
                "benchmark_mfe": None,
                "benchmark_mae": None,
            }
            if signal_id:
                actionable, benchmark = _trade_model_counts(
                    self.database,
                    instrument_key,
                    trading_date.isoformat(),
                    str(signal_id),
                    current_price=current_price,
                    direction=item.get("direction"),
                    entry_price=item.get("underlying_entry"),
                )
            enriched = dict(item)
            enriched["current_price"] = current_price
            enriched["live_points"] = _live_points(
                enriched.get("direction"),
                enriched.get("underlying_entry"),
                current_price,
            )
            live_mfe, live_mae = _live_excursions(
                completed_source,
                enriched,
            )
            enriched["live_mfe_points"] = live_mfe
            enriched["live_mae_points"] = live_mae
            enriched.update(
                _target_progress(
                    enriched.get("live_points"),
                    live_mfe,
                )
            )
            enriched.update(actionable)
            enriched["quality_explanation"] = quality_explanation(
                actionable["actionable_success"],
                actionable["actionable_failed"],
                actionable["actionable_breakeven"],
            )
            enriched["actionable_score"] = actionable_score(
                actionable["actionable_success"],
                10,
            )
            enriched["quality_band"] = quality_band(
                actionable["actionable_success"]
            )
            enriched["quality_symbol"] = quality_symbol(
                actionable["actionable_success"]
            )
            enriched["priority"] = priority_label(
                actionable["actionable_success"]
            )
            enriched.update(benchmark)
            enriched["trade_status"] = trader_status(
                actionable["signal_lifecycle"],
                benchmark.get("benchmark_status"),
            )
            enriched["current_result"] = current_result(
                enriched.get("live_points")
            )

            if (
                actionable["signal_lifecycle"] == "COMPLETED"
                and signal_id
            ):
                self.database.update_signal_state(
                    str(signal_id),
                    "CLOSED",
                )

            enriched_active.append(enriched)

        active_details = tuple(enriched_active)

        all_trade_rows = self.database.read_paper_trade_outcomes(
            instrument_key,
            trading_date.isoformat(),
        )
        completed_details = tuple(
            summarize_completed_signals(
                sequenced_attempts,
                all_trade_rows,
                current_price=current_price,
            )
        )

        failed_details = tuple(
            item
            for item in details
            if item.get("state") in {"TIMEOUT", "CONFIRMATION_FAILED"}
        )
        awaiting_details = tuple(
            item
            for item in details
            if item.get("state") == "AWAITING_CONFIRMATION"
        )
        timeline = _event_timeline(details)

        latest = None
        if not completed_five.empty:
            row = completed_five.iloc[-1]
            latest = {
                "timestamp": row["timestamp"],
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            }

        level_diagnostics = _build_level_diagnostics(
            levels=levels,
            current_price=current_price,
            attempts=scan.attempts,
        )

        return LiveMonitorResult(
            connected=True,
            trading_date=trading_date,
            last_refresh=refresh_time,
            source_rows=len(current),
            completed_five_minute_rows=len(completed_five),
            levels_stored=levels_stored,
            attempts=len(scan.attempts),
            active=len(active_details),
            failed=len(failed_details),
            awaiting=len(awaiting_details),
            latest_completed_candle=latest,
            active_attempts=active_details,
            completed_attempts=completed_details,
            failed_attempts=failed_details,
            awaiting_attempts=awaiting_details,
            event_timeline=timeline,
            current_price=current_price,
            level_diagnostics=level_diagnostics,
            message=(
                f"Current session refreshed; {len(completed_five)} completed "
                "five-minute setup candles evaluated with one-minute confirmation."
            ),
        )
