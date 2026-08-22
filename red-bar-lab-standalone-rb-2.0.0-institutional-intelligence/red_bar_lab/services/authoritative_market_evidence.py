from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from red_bar_lab.config import RedBarSettings, UNDERLYINGS
from red_bar_lab.services.intraday_acceptance_engine import (
    build_futures_vwap_acceptance,
    read_intraday_acceptance,
)
from red_bar_lab.services.market_evidence_bundle_store import (
    persist_market_evidence_bundle,
)
from red_bar_lab.services.market_evidence_engine import (
    corrected_option_summary,
    read_option_score_history,
    read_underlying_evidence,
    score_slope,
)
from red_bar_lab.services.nifty_futures_snapshot_store import (
    read_nifty_futures_snapshots,
)
from red_bar_lab.services.option_participation_store import (
    read_latest_option_participation,
)
from red_bar_lab.storage.artifacts import ArtifactLayout

_CONFIRMING_STRENGTH = {"STRONG", "MODERATE"}
_BULLISH_FUTURES = {"LONG_BUILDUP", "SHORT_COVERING"}
_BEARISH_FUTURES = {"SHORT_BUILDUP", "LONG_UNWINDING"}


def _timestamp(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def completed_bar_timestamps(
    evidence: Mapping[str, Any] | None,
    *,
    interval_minutes: int = 5,
) -> dict[str, Any]:
    """Normalize a completed bar to explicit open and close timestamps.

    Existing close timestamps are authoritative and are never shifted again.
    Otherwise the persisted candle timestamp is treated as the bar-open label,
    matching the resampled candle convention used by the evidence engines.
    """
    result = dict(evidence or {})
    explicit_close = _timestamp(result.get("bar_close_timestamp"))
    if explicit_close is not None:
        result["bar_close_timestamp"] = explicit_close.isoformat()
        result["observed_at"] = explicit_close.isoformat()
        opened = _timestamp(result.get("bar_open_timestamp"))
        if opened is not None:
            result["bar_open_timestamp"] = opened.isoformat()
        else:
            result.setdefault("bar_open_timestamp", None)
        return result

    raw_open = result.get("bar_open_timestamp") or result.get("observed_at")
    opened = _timestamp(raw_open)
    if opened is None:
        result.setdefault("bar_open_timestamp", raw_open if raw_open not in (None, "") else None)
        result.setdefault("bar_close_timestamp", None)
        return result

    closed = opened + timedelta(minutes=max(1, int(interval_minutes)))
    result["bar_open_timestamp"] = opened.isoformat()
    result["bar_close_timestamp"] = closed.isoformat()
    result["observed_at"] = closed.isoformat()
    return result


def _direction_from_futures(futures: Mapping[str, Any]) -> str:
    state = str(futures.get("positioning_state") or "").upper()
    if state in _BULLISH_FUTURES:
        return "BULLISH"
    if state in _BEARISH_FUTURES:
        return "BEARISH"
    return "NEUTRAL"


def apply_affirmative_derivatives_gate(
    view: Mapping[str, Any],
    *,
    futures: Mapping[str, Any],
    futures_vwap: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Require positive derivatives confirmation for trade eligibility."""
    result = dict(view)
    direction = str(result.get("observed_direction") or "").upper()
    option_direction = str(result.get("option_direction") or "").upper()
    futures_direction = _direction_from_futures(futures)
    futures_strength = str(futures.get("strength") or "").upper()
    vwap_direction = str((futures_vwap or {}).get("direction") or "").upper()
    vwap_state = str((futures_vwap or {}).get("state") or "").upper()

    option_confirms = direction in {"BULLISH", "BEARISH"} and option_direction == direction
    futures_confirms = (
        direction in {"BULLISH", "BEARISH"}
        and futures_direction == direction
        and futures_strength in _CONFIRMING_STRENGTH
    )
    futures_vwap_confirms = (
        direction in {"BULLISH", "BEARISH"}
        and vwap_direction == direction
        and vwap_state not in {"UNAVAILABLE", "NEUTRAL", "CONFLICTED", ""}
    )
    passed = option_confirms or futures_confirms or futures_vwap_confirms
    confirmations = tuple(
        label
        for label, value in (
            ("OPTIONS", option_confirms),
            ("FUTURES", futures_confirms),
            ("FUTURES_VWAP", futures_vwap_confirms),
        )
        if value
    )
    result["derivatives_confirmation_passed"] = passed
    result["derivatives_confirmations"] = confirmations

    blockers = list(result.get("blocking_reasons") or ())
    if (
        result.get("direction_state") == "CONFIRMED"
        and direction in {"BULLISH", "BEARISH"}
        and not passed
    ):
        if "DERIVATIVES_CONFIRMATION_MISSING" not in blockers:
            blockers.append("DERIVATIVES_CONFIRMATION_MISSING")
        result["trade_eligibility"] = "BLOCKED"
        result["trade_bias"] = "WAIT"
        result["primary_blocker"] = (
            result.get("primary_blocker") or "DERIVATIVES_CONFIRMATION_MISSING"
        )
        result["confirmation"] = (
            "Structure is confirmed, but no positive derivatives confirmation is present."
        )
    result["blocking_reasons"] = tuple(blockers)
    return result


def _safe_evidence_time(view: Mapping[str, Any]) -> str | None:
    values = []
    for key in (
        "option_timestamp",
        "futures_bar_close_timestamp",
        "futures_market_timestamp",
        "underlying_bar_close_timestamp",
        "underlying_timestamp",
    ):
        parsed = _timestamp(view.get(key))
        if parsed is not None:
            values.append(parsed.astimezone(timezone.utc))
    return min(values).isoformat() if values else None


def build_and_persist_authoritative_market_evidence(
    *,
    database_path,
    underlying_name: str,
    observed_at: datetime,
) -> dict[str, Any] | None:
    """Collector/monitor-side authoritative bundle creation.

    This function reads already persisted market inputs and the shared live
    candle artifact. It performs no execution action.
    """
    from red_bar_lab.ui.market_at_a_glance import build_market_at_a_glance

    rows = list(
        read_latest_option_participation(
            database_path,
            underlying_name=underlying_name,
        )
        or []
    )
    if not rows:
        return None
    summary = corrected_option_summary(rows)
    summary["observed_at"] = rows[0].get("observed_at")
    history = read_option_score_history(
        database_path,
        underlying_name=underlying_name,
        limit=5,
    )
    summary["ce_score_slope"] = score_slope(history, "CE")
    summary["pe_score_slope"] = score_slope(history, "PE")

    futures_rows = read_nifty_futures_snapshots(
        database_path,
        underlying_name=underlying_name,
        limit=1,
    )
    futures = dict(futures_rows[0]) if futures_rows else {}
    if futures:
        futures.setdefault("bar_open_timestamp", futures.get("latest_timestamp"))
        futures = completed_bar_timestamps(futures)
    futures_vwap = build_futures_vwap_acceptance(futures)

    settings = RedBarSettings.from_env()
    layout = ArtifactLayout(settings)
    instrument_key = UNDERLYINGS.get(underlying_name, "NSE_INDEX|Nifty 50")
    live_path = layout.live_session_path("upstox", instrument_key, 1)
    underlying = completed_bar_timestamps(
        read_underlying_evidence(live_path, as_of_timestamp=observed_at)
    )
    intraday = read_intraday_acceptance(live_path, as_of_timestamp=observed_at)

    view = build_market_at_a_glance(
        summary,
        futures,
        underlying,
        now=observed_at,
        early_1m=intraday["early_1m"],
        spot_vwap=intraday["spot_vwap"],
        futures_vwap=futures_vwap,
    )
    view = apply_affirmative_derivatives_gate(
        view,
        futures=futures,
        futures_vwap=futures_vwap,
    )
    view["underlying_bar_open_timestamp"] = underlying.get("bar_open_timestamp")
    view["underlying_bar_close_timestamp"] = underlying.get("bar_close_timestamp")
    view["futures_bar_open_timestamp"] = futures.get("bar_open_timestamp")
    view["futures_bar_close_timestamp"] = futures.get("bar_close_timestamp")
    view["safe_evidence_time"] = _safe_evidence_time(view)
    view["latest_complete_evidence_time"] = view["safe_evidence_time"]
    view["authority"] = "OBSERVATIONAL_ONLY"
    view["bundle_id"] = persist_market_evidence_bundle(
        database_path,
        underlying_name=underlying_name,
        view=view,
    )
    return view


__all__ = [
    "apply_affirmative_derivatives_gate",
    "build_and_persist_authoritative_market_evidence",
    "completed_bar_timestamps",
]
