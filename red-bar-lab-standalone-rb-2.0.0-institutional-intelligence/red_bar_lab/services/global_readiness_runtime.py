from __future__ import annotations

from datetime import datetime, time
import logging
import sqlite3
from typing import Mapping
from zoneinfo import ZoneInfo

from red_bar_lab.services.authoritative_market_evidence import (
    build_and_persist_authoritative_market_evidence,
)
from red_bar_lab.services.global_readiness import assess_global_readiness
from red_bar_lab.services.global_readiness_store import persist_global_readiness_snapshot

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")

AUTOMATIC_ENTRY_OPEN = time(9, 15)
AUTOMATIC_ENTRY_CLOSE = time(15, 25)

DEFAULT_OPTION_QUOTE_MAX_AGE_SECONDS = 600.0
DEFAULT_PCR_MAX_AGE_SECONDS = 900.0


def _diagnostic_status(
    latest: Mapping[str, object],
    *keys: str,
    default: str = "UNAVAILABLE",
) -> str:
    for key in keys:
        value = latest.get(key)
        if value not in (None, ""):
            return str(value).upper()
    return default


def _within_automatic_entry_hours(moment: datetime) -> bool:
    if moment.tzinfo is None:
        ist_moment = moment.replace(tzinfo=IST)
    else:
        ist_moment = moment.astimezone(IST)
    return (
        ist_moment.weekday() < 5
        and AUTOMATIC_ENTRY_OPEN <= ist_moment.time() <= AUTOMATIC_ENTRY_CLOSE
    )


def _age_seconds(value: object, *, now: datetime) -> float | None:
    """Age of an ISO timestamp (or datetime) relative to ``now``.

    Returns None when the value is missing or unparseable. Naive
    timestamps are interpreted as IST.
    """
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        stamp = value
    else:
        try:
            stamp = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=IST)
    reference = now if now.tzinfo is not None else now.replace(tzinfo=IST)
    return (reference - stamp).total_seconds()


def _option_quote_fresh(
    option_chain_snapshot: Mapping[str, object] | None,
    *,
    now: datetime,
    max_age_seconds: float,
) -> bool:
    """Option quotes are considered available when a recent option chain
    snapshot exists for the current trading date. The chain snapshot is the
    platform's live source of ATM strike quotes; a fresh snapshot implies
    quote data is flowing."""
    if not option_chain_snapshot:
        return False
    age = _age_seconds(option_chain_snapshot.get("snapshot_timestamp"), now=now)
    return age is not None and age <= max_age_seconds


def _latest_pcr_age_seconds(
    database_path,
    underlying_name: str,
    trading_date: str,
    *,
    now: datetime,
) -> float | None:
    """Age of the newest 5-minute PCR projection row for today, or None when
    the table is missing or has no row for this underlying/date."""
    try:
        with sqlite3.connect(str(database_path)) as conn:
            row = conn.execute(
                "SELECT candle_close_timestamp "
                "FROM market_trend_research_pcr_5m_history "
                "WHERE underlying=? AND trading_date=? "
                "ORDER BY candle_close_timestamp DESC LIMIT 1",
                (underlying_name, trading_date),
            ).fetchone()
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        return None
    if row is None:
        return None
    return _age_seconds(row[0], now=now)


def build_and_persist_global_readiness(
    *,
    database_path,
    observed_at: datetime,
    underlying_name: str,
    instrument_key: str,
    candle_diagnostic,
    futures_readiness,
    futures_strength,
    bridge,
    authority,
    latest_signal_diagnostic: Mapping[str, object] | None,
    report,
    option_chain_snapshot: Mapping[str, object] | None = None,
    option_quote_max_age_seconds: float = DEFAULT_OPTION_QUOTE_MAX_AGE_SECONDS,
    pcr_max_age_seconds: float = DEFAULT_PCR_MAX_AGE_SECONDS,
):
    """Build one best-effort global observation from calculated values.

    This adapter performs no market-data calls and no execution action.
    Persistence failures are non-fatal to the paper cycle, but are logged with
    stable reason codes so a stale UI bundle is distinguishable from success.

    Market hours, option-quote availability, and PCR availability are derived
    from the clock and the platform's own persisted collections (option chain
    snapshots, PCR 5-minute history) rather than from the newest signal
    diagnostic row, which may be days old when no signals have been seen.
    Explicit status fields on the diagnostic row still take precedence when a
    writer supplies them.
    """
    if isinstance(observed_at, str):
        observed_at = datetime.fromisoformat(observed_at)
    latest = dict(latest_signal_diagnostic or {})
    candle_status = str(
        getattr(
            getattr(candle_diagnostic, "readiness", None),
            "status",
            "UNAVAILABLE",
        )
    ).upper()

    outside_hours = not _within_automatic_entry_hours(observed_at)
    market_hours_status = "OUTSIDE_ENTRY_HOURS" if outside_hours else "OPEN"

    option_chain_status = _diagnostic_status(
        latest,
        "option_chain_status",
        "chain_status",
        "option_data_status",
        default=(
            "MARKET_CLOSED"
            if outside_hours
            else "READY"
            if option_chain_snapshot
            else "UNAVAILABLE"
        ),
    )
    option_quote_status = _diagnostic_status(
        latest,
        "option_quote_status",
        "quote_status",
        "quotes_status",
        default=(
            "MARKET_CLOSED"
            if outside_hours
            else "READY"
            if _option_quote_fresh(
                option_chain_snapshot,
                now=observed_at,
                max_age_seconds=option_quote_max_age_seconds,
            )
            else "UNAVAILABLE"
        ),
    )
    reference = observed_at if observed_at.tzinfo is not None else observed_at.replace(tzinfo=IST)
    trading_date = reference.astimezone(IST).date().isoformat()
    pcr_age = _latest_pcr_age_seconds(
        database_path,
        underlying_name,
        trading_date,
        now=observed_at,
    )
    pcr_status = _diagnostic_status(
        latest,
        "pcr_status",
        "pcr_readiness",
        default=(
            "MARKET_CLOSED"
            if outside_hours
            else "READY"
            if pcr_age is not None and pcr_age <= pcr_max_age_seconds
            else "UNAVAILABLE"
        ),
    )

    bridge_status = str(
        getattr(bridge, "status", "UNAVAILABLE") or "UNAVAILABLE"
    ).upper()
    bridge_reason = str(getattr(bridge, "reason", "") or "").upper()
    if bridge_status in {"PUBLISHED", "READY", "NO_SIGNAL"}:
        alignment_status = "ALIGNED"
    elif outside_hours and bridge_reason == "V2_SNAPSHOT_STALE":
        alignment_status = "AFTER_HOURS_EXPECTED"
    else:
        alignment_status = bridge_status
    source_status = (
        "ENABLED"
        if bool(getattr(authority, "source_enabled", False))
        else "DISABLED"
    )
    result = assess_global_readiness(
        underlying_candle=candle_status,
        option_chain=option_chain_status,
        option_quotes=option_quote_status,
        pcr=pcr_status,
        futures=futures_readiness,
        futures_strength=futures_strength,
        v2_alignment=alignment_status,
        execution_source=source_status,
        market_hours=market_hours_status,
    )
    try:
        persist_global_readiness_snapshot(
            database_path,
            observed_at=observed_at,
            underlying_name=underlying_name,
            instrument_key=instrument_key,
            readiness=result,
            signals_seen=int(getattr(report, "signals_seen", 0) or 0),
            signals_scored=int(
                getattr(report, "candidates_scored", 0) or 0
            ),
            orders_opened=int(
                getattr(report, "paper_orders_opened", 0) or 0
            ),
            orders_skipped=int(getattr(report, "skipped", 0) or 0),
        )
    except Exception:
        logger.exception(
            "GLOBAL_READINESS_PERSIST_FAILED underlying=%s observed_at=%s",
            underlying_name,
            observed_at.isoformat(),
        )

    try:
        build_and_persist_authoritative_market_evidence(
            database_path=database_path,
            underlying_name=underlying_name,
            observed_at=observed_at,
        )
    except Exception:
        logger.exception(
            "MARKET_EVIDENCE_BUNDLE_PERSIST_FAILED underlying=%s observed_at=%s",
            underlying_name,
            observed_at.isoformat(),
        )
    return result
