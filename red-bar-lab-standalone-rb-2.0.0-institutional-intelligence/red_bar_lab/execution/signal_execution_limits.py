from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo


IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class SignalExecutionLimitDecision:
    allowed: bool
    reason: str
    existing_entries: int
    existing_contracts: int
    signal_age_seconds: float | None
    seconds_since_last_entry: float | None


def _timestamp(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        stamp = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if stamp.tzinfo is None:
        return stamp.replace(tzinfo=IST)
    return stamp.astimezone(IST)


def evaluate_signal_execution_limits(
    database_path: str | Path,
    *,
    account_id: str,
    signal_id: str | None,
    instrument_token: int,
    now: datetime | None = None,
    max_contracts_per_signal: int = 2,
    max_entries_per_signal: int = 2,
    reentry_cooldown_seconds: int = 300,
    max_signal_age_seconds: int = 180,
    allow_stale_signal_override: bool = False,
    enforce_freshness: bool = True,
) -> SignalExecutionLimitDecision:
    """Evaluate durable per-signal limits and optional live freshness policy.

    Persisted orders provide restart-safe entry and contract counts. Duplicate
    protection applies only to an OPEN position; a closed contract may re-enter
    when the total-entry ceiling and cooldown permit it. Freshness is optional so
    historical evidence builders and low-level paper-engine tests are not made
    dependent on wall-clock time. Live automation owns the freshness decision.
    """

    canonical = str(signal_id or "").strip()
    if not canonical:
        return SignalExecutionLimitDecision(
            True, "MANUAL_ENTRY_WITHOUT_SIGNAL", 0, 0, None, None
        )

    current = now or datetime.now(IST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=IST)
    else:
        current = current.astimezone(IST)

    with sqlite3.connect(Path(database_path)) as connection:
        connection.row_factory = sqlite3.Row
        orders = connection.execute(
            """
            SELECT instrument_token, entry_timestamp, status
            FROM paper_execution_orders
            WHERE account_id=? AND signal_id=?
            ORDER BY entry_timestamp
            """,
            (str(account_id), canonical),
        ).fetchall()
        signal = connection.execute(
            """
            SELECT confirmation_timestamp
            FROM signal_attempts
            WHERE signal_id=?
            LIMIT 1
            """,
            (canonical,),
        ).fetchone()

    existing_entries = len(orders)
    existing_contracts = len({int(row["instrument_token"]) for row in orders})
    open_duplicate = any(
        int(row["instrument_token"]) == int(instrument_token)
        and str(row["status"] or "").upper() == "OPEN"
        for row in orders
    )
    if open_duplicate:
        return SignalExecutionLimitDecision(
            False,
            "DUPLICATE_OPEN_SIGNAL_CONTRACT",
            existing_entries,
            existing_contracts,
            None,
            None,
        )
    if existing_entries >= max(1, int(max_entries_per_signal)):
        return SignalExecutionLimitDecision(
            False,
            "MAX_ENTRIES_PER_SIGNAL_REACHED",
            existing_entries,
            existing_contracts,
            None,
            None,
        )
    new_contract = not any(
        int(row["instrument_token"]) == int(instrument_token) for row in orders
    )
    if new_contract and existing_contracts >= max(1, int(max_contracts_per_signal)):
        return SignalExecutionLimitDecision(
            False,
            "MAX_CONTRACTS_PER_SIGNAL_REACHED",
            existing_entries,
            existing_contracts,
            None,
            None,
        )

    seconds_since_last_entry = None
    if orders and int(reentry_cooldown_seconds) > 0:
        last_entry = _timestamp(orders[-1]["entry_timestamp"])
        if last_entry is not None:
            seconds_since_last_entry = (current - last_entry).total_seconds()
            if seconds_since_last_entry < int(reentry_cooldown_seconds):
                return SignalExecutionLimitDecision(
                    False,
                    "SIGNAL_REENTRY_COOLDOWN_ACTIVE",
                    existing_entries,
                    existing_contracts,
                    None,
                    seconds_since_last_entry,
                )

    if not enforce_freshness:
        return SignalExecutionLimitDecision(
            True,
            "DURABLE_SIGNAL_LIMITS_PASS",
            existing_entries,
            existing_contracts,
            None,
            seconds_since_last_entry,
        )

    confirmation = _timestamp(signal["confirmation_timestamp"] if signal else None)
    if confirmation is None:
        return SignalExecutionLimitDecision(
            False,
            "SIGNAL_CONFIRMATION_TIMESTAMP_MISSING",
            existing_entries,
            existing_contracts,
            None,
            seconds_since_last_entry,
        )
    signal_age_seconds = (current - confirmation).total_seconds()
    if signal_age_seconds < 0:
        return SignalExecutionLimitDecision(
            False,
            "SIGNAL_TIMESTAMP_IN_FUTURE",
            existing_entries,
            existing_contracts,
            signal_age_seconds,
            seconds_since_last_entry,
        )
    if (
        signal_age_seconds > max(0, int(max_signal_age_seconds))
        and not allow_stale_signal_override
    ):
        return SignalExecutionLimitDecision(
            False,
            "MAX_SIGNAL_AGE_EXCEEDED",
            existing_entries,
            existing_contracts,
            signal_age_seconds,
            seconds_since_last_entry,
        )

    return SignalExecutionLimitDecision(
        True,
        "SIGNAL_EXECUTION_LIMITS_PASS",
        existing_entries,
        existing_contracts,
        signal_age_seconds,
        seconds_since_last_entry,
    )


__all__ = ["SignalExecutionLimitDecision", "evaluate_signal_execution_limits"]
