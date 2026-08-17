from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def _number(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _timestamp(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=IST)
    return parsed.astimezone(IST)


@dataclass(frozen=True)
class CheckpointCaptureResult:
    captured: int
    skipped: int
    errors: tuple[str, ...]


class TradeCheckpointService:
    """Capture observational T+N option-premium outcomes.

    This service never closes a position, updates a stop, or changes queue state.
    The unique order_id+horizon key makes repeated and restarted cycles idempotent.
    """

    def __init__(self, database, *, account_id: str):
        self.database = database
        self.account_id = str(account_id)

    def capture_due(self, *, now: datetime | None = None) -> CheckpointCaptureResult:
        current = (now or datetime.now(IST)).astimezone(IST)
        captured = 0
        skipped = 0
        errors: list[str] = []

        orders = self.database.read_paper_execution_orders(self.account_id)
        for order in orders:
            try:
                horizon = int(order.get("evaluation_horizon_minutes") or 0)
                if horizon <= 0:
                    skipped += 1
                    continue

                order_id = str(order.get("order_id") or "")
                if not order_id:
                    skipped += 1
                    continue

                if self.database.read_paper_trade_checkpoint(
                    order_id=order_id,
                    horizon_minutes=horizon,
                ):
                    skipped += 1
                    continue

                entry_at = _timestamp(order.get("entry_timestamp"))
                due_at = entry_at + timedelta(minutes=horizon)
                if current < due_at:
                    skipped += 1
                    continue

                marks = self.database.read_paper_execution_marks(order_id)
                eligible_marks = []
                for mark in marks:
                    mark_at = _timestamp(mark.get("timestamp"))
                    if mark_at <= current:
                        eligible_marks.append((mark_at, mark))

                exit_timestamp = order.get("exit_timestamp")
                exited_at = (
                    _timestamp(exit_timestamp)
                    if exit_timestamp else None
                )

                after_due = [
                    item for item in eligible_marks
                    if item[0] >= due_at
                ]
                if after_due:
                    observed_at, observed_mark = after_due[0]
                    lag_seconds = max(
                        0.0,
                        (observed_at - due_at).total_seconds(),
                    )
                    observation_quality = (
                        "EXACT"
                        if lag_seconds <= 5.0
                        else "FIRST_MARK_AFTER_DUE"
                    )
                    observation_note = (
                        "Market mark captured at due time."
                        if observation_quality == "EXACT"
                        else (
                            "First available market mark after due time; "
                            f"lag={lag_seconds:.1f}s."
                        )
                    )
                elif exited_at is not None and exited_at < due_at:
                    observed_at = exited_at
                    observed_mark = {"price": order.get("exit_price")}
                    lag_seconds = (
                        observed_at - due_at
                    ).total_seconds()
                    observation_quality = "EXIT_BEFORE_HORIZON"
                    observation_note = (
                        "Position closed before checkpoint horizon; exit "
                        "premium is recorded and is not a T+N market mark."
                    )
                else:
                    observed_at = current
                    observed_mark = {
                        "price": (
                            order.get("current_price")
                            or order.get("exit_price")
                        )
                    }
                    lag_seconds = max(
                        0.0,
                        (observed_at - due_at).total_seconds(),
                    )
                    observation_quality = "LATE_FALLBACK"
                    observation_note = (
                        "No stored market mark existed at or after due time; "
                        "latest available position premium used as fallback."
                    )

                entry_price = _number(order.get("entry_price"))
                checkpoint_price = _number(observed_mark.get("price"), entry_price)
                if entry_price <= 0 or checkpoint_price <= 0:
                    raise ValueError(
                        "PRICE_UNAVAILABLE:"
                        f"quality={observation_quality}"
                    )

                marks_to_checkpoint = [
                    mark for mark_at, mark in eligible_marks if mark_at <= observed_at
                ]
                prices = [
                    _number(mark.get("price"))
                    for mark in marks_to_checkpoint
                    if _number(mark.get("price")) > 0
                ]
                if not prices:
                    prices = [entry_price, checkpoint_price]

                peak_price = max([entry_price] + prices)
                trough_price = min([entry_price] + prices)
                mfe_points = max(0.0, peak_price - entry_price)
                mae_points = min(0.0, trough_price - entry_price)
                return_pct = (checkpoint_price - entry_price) / entry_price * 100.0

                status_at_checkpoint = "OPEN"
                if exited_at is not None and exited_at <= due_at:
                    status_at_checkpoint = "CLOSED"

                checkpoint_id = f"{order_id}:{horizon}"
                self.database.upsert_paper_trade_checkpoint({
                    "checkpoint_id": checkpoint_id,
                    "order_id": order_id,
                    "signal_id": order.get("signal_id"),
                    "execution_strategy_source": order.get("execution_strategy_source"),
                    "horizon_minutes": horizon,
                    "due_timestamp": due_at.isoformat(),
                    "observed_timestamp": observed_at.isoformat(),
                    "entry_price": round(entry_price, 4),
                    "checkpoint_price": round(checkpoint_price, 4),
                    "return_pct": round(return_pct, 4),
                    "mfe_points": round(mfe_points, 4),
                    "mae_points": round(mae_points, 4),
                    "peak_price": round(peak_price, 4),
                    "protected_stop_price": (
                        round(_number(order.get("stop_price")), 4)
                        if _number(order.get("stop_price")) > 0
                        else None
                    ),
                    "position_status_at_checkpoint": status_at_checkpoint,
                    "captured_order_status": str(order.get("status") or "UNKNOWN"),
                    "observation_quality": observation_quality,
                    "observation_lag_seconds": round(
                        float(lag_seconds),
                        3,
                    ),
                    "observation_note": observation_note,
                    "created_at": current.isoformat(),
                })
                captured += 1
            except Exception as exc:
                errors.append(f"{order.get('order_id')}:{type(exc).__name__}:{exc}")

        return CheckpointCaptureResult(captured, skipped, tuple(errors))
