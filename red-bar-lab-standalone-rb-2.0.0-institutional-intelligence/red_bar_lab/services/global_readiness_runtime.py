from __future__ import annotations

from datetime import datetime
from typing import Mapping

from red_bar_lab.services.global_readiness import assess_global_readiness
from red_bar_lab.services.global_readiness_store import persist_global_readiness_snapshot


def _diagnostic_status(latest: Mapping[str, object], *keys: str, default: str = "UNAVAILABLE") -> str:
    for key in keys:
        value = latest.get(key)
        if value not in (None, ""):
            return str(value).upper()
    return default


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

    This function performs no market-data calls and has no execution authority.
    It is intended to be invoked after the stable paper cycle has completed.
    """

    latest = dict(latest_signal_diagnostic or {})
    candle_status = str(getattr(getattr(candle_diagnostic, "readiness", None), "status", "UNAVAILABLE"))
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
        default="READY" if int(getattr(report, "candidates_scored", 0) or 0) > 0 else "UNAVAILABLE",
    )
    pcr_status = _diagnostic_status(
        latest,
        "pcr_status",
        "pcr_readiness",
        default="READY" if latest.get("pcr") is not None else "UNAVAILABLE",
    )
    alignment_status = "ALIGNED" if str(getattr(bridge, "status", "")) in {"PUBLISHED", "READY", "NO_SIGNAL"} else str(getattr(bridge, "status", "UNAVAILABLE"))
    source_status = "ENABLED" if bool(getattr(authority, "source_enabled", False)) else "DISABLED"
    market_hours_status = _diagnostic_status(
        latest,
        "market_hours_status",
        default="OPEN" if bool(latest.get("market_hours_ok")) else "OUTSIDE_ENTRY_HOURS",
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
            signals_scored=int(getattr(report, "candidates_scored", 0) or 0),
            orders_opened=int(getattr(report, "paper_orders_opened", 0) or 0),
            orders_skipped=int(getattr(report, "skipped", 0) or 0),
        )
    except Exception:
        pass
    return result
