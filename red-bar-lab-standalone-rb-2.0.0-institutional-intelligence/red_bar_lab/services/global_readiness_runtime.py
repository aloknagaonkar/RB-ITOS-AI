from __future__ import annotations

from datetime import datetime
from typing import Mapping

from red_bar_lab.services.authoritative_market_evidence import (
    build_and_persist_authoritative_market_evidence,
)
from red_bar_lab.services.global_readiness import assess_global_readiness
from red_bar_lab.services.global_readiness_store import persist_global_readiness_snapshot


def _diagnostic_status(latest: Mapping[str, object], *keys: str, default: str = "UNAVAILABLE") -> str:
    for key in keys:
        value = latest.get(key)
        if value not in (None, ""):
            return str(value).upper()
    return default


def _outside_entry_hours(latest: Mapping[str, object], candle_status: str) -> bool:
    explicit = _diagnostic_status(latest, "market_hours_status", default="")
    if explicit:
        return explicit in {"CLOSED", "MARKET_CLOSED", "OUTSIDE_ENTRY_HOURS"}
    if candle_status == "MARKET_CLOSED":
        return True
    return latest.get("market_hours_ok") is False


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
):
    """Build one best-effort global observation from already calculated values.

    The monitor runtime owns persistence. UI pages only read these observations.
    This adapter performs no market-data calls and no execution action.
    """

    latest = dict(latest_signal_diagnostic or {})
    candle_status = str(
        getattr(getattr(candle_diagnostic, "readiness", None), "status", "UNAVAILABLE")
    ).upper()
    outside_hours = _outside_entry_hours(latest, candle_status)
    market_hours_status = _diagnostic_status(
        latest,
        "market_hours_status",
        default=(
            "OUTSIDE_ENTRY_HOURS"
            if outside_hours
            else "OPEN" if bool(latest.get("market_hours_ok")) else "UNAVAILABLE"
        ),
    )
    option_chain_status = _diagnostic_status(
        latest,
        "option_chain_status",
        "chain_status",
        "option_data_status",
        default="READY" if int(getattr(report, "signals_seen", 0) or 0) > 0 else "UNAVAILABLE",
    )
    option_quote_status = _diagnostic_status(
        latest,
        "option_quote_status",
        "quote_status",
        "quotes_status",
        default=(
            "MARKET_CLOSED"
            if outside_hours
            else "READY" if int(getattr(report, "candidates_scored", 0) or 0) > 0 else "UNAVAILABLE"
        ),
    )
    pcr_status = _diagnostic_status(
        latest,
        "pcr_status",
        "pcr_readiness",
        default=(
            "MARKET_CLOSED"
            if outside_hours
            else "READY" if latest.get("pcr") is not None else "UNAVAILABLE"
        ),
    )
    bridge_status = str(getattr(bridge, "status", "UNAVAILABLE") or "UNAVAILABLE").upper()
    bridge_reason = str(getattr(bridge, "reason", "") or "").upper()
    if bridge_status in {"PUBLISHED", "READY", "NO_SIGNAL"}:
        alignment_status = "ALIGNED"
    elif outside_hours and bridge_reason == "V2_SNAPSHOT_STALE":
        alignment_status = "AFTER_HOURS_EXPECTED"
    else:
        alignment_status = bridge_status
    source_status = "ENABLED" if bool(getattr(authority, "source_enabled", False)) else "DISABLED"
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
            signals_scored=int(getattr(report, "candidates_scored", 0) or 0),
            orders_opened=int(getattr(report, "paper_orders_opened", 0) or 0),
            orders_skipped=int(getattr(report, "skipped", 0) or 0),
        )
    except Exception:
        pass

    # Additive observational persistence. A failure must not affect the stable
    # paper cycle or global readiness result.
    try:
        build_and_persist_authoritative_market_evidence(
            database_path=database_path,
            underlying_name=underlying_name,
            observed_at=observed_at,
        )
    except Exception:
        pass
    return result
