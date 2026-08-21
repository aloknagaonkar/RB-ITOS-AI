from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from red_bar_lab.config import UNDERLYINGS
from red_bar_lab.services.intraday_acceptance_engine import (
    build_futures_vwap_acceptance,
    read_intraday_acceptance,
)
from red_bar_lab.services.market_evidence_engine import (
    corrected_option_summary,
    read_option_score_history,
    read_underlying_evidence,
    score_slope,
)
from red_bar_lab.services.nifty_futures_snapshot_store import read_nifty_futures_snapshots
from red_bar_lab.services.option_participation_store import read_latest_option_participation
from red_bar_lab.storage.artifacts import ArtifactLayout
from red_bar_lab.ui._shared import _arrow_safe_rows, st

_BULLISH_FUTURES = {"LONG_BUILDUP", "SHORT_COVERING"}
_BEARISH_FUTURES = {"SHORT_BUILDUP", "LONG_UNWINDING"}
_CONFIRMING_STRENGTH = {"STRONG", "MODERATE"}
_OPTION_MAX_AGE_SECONDS = 180.0
_FUTURES_COLLECTION_MAX_AGE_SECONDS = 180.0
_COMPLETED_5M_MAX_AGE_SECONDS = 420.0
_MAX_COMPLETED_5M_ALIGNMENT_GAP_SECONDS = 420.0
_OPTION_SLOPE_SUPPORT_PER_MINUTE = 1.0


def _number(value: object) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def _score(value: object) -> str:
    number = _number(value)
    return "—" if number is None else f"{number:.1f}"


def _timestamp(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _age(value: datetime | None, now: datetime) -> float | None:
    if value is None:
        return None
    return max(0.0, (now.astimezone(timezone.utc) - value.astimezone(timezone.utc)).total_seconds())


def build_market_at_a_glance(
    summary: Mapping[str, Any],
    futures: Mapping[str, Any],
    underlying: Mapping[str, Any] | None = None,
    *,
    now: datetime | None = None,
    early_1m: Mapping[str, Any] | None = None,
    spot_vwap: Mapping[str, Any] | None = None,
    futures_vwap: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    underlying = dict(underlying or {})
    early_1m = dict(early_1m or {})
    spot_vwap = dict(spot_vwap or {})
    futures_vwap = dict(futures_vwap or {})

    bullish = _number(summary.get("ce_score"))
    bearish = _number(summary.get("pe_score"))
    gap = abs(bullish - bearish) if bullish is not None and bearish is not None else None
    winning_side = (
        "CE" if bullish is not None and bearish is not None and bullish > bearish
        else "PE" if bullish is not None and bearish is not None and bearish > bullish
        else "TIE" if bullish is not None and bearish is not None
        else "UNAVAILABLE"
    )
    option_direction = (
        "BULLISH" if winning_side == "CE" and bullish >= 50.0 and gap is not None and gap >= 8.0
        else "BEARISH" if winning_side == "PE" and bearish >= 50.0 and gap is not None and gap >= 8.0
        else "WAIT" if winning_side != "UNAVAILABLE"
        else "UNAVAILABLE"
    )
    ce_slope = _number(summary.get("ce_score_slope"))
    pe_slope = _number(summary.get("pe_score_slope"))
    option_momentum = (
        "BULLISH" if ce_slope is not None and pe_slope is not None
        and ce_slope >= _OPTION_SLOPE_SUPPORT_PER_MINUTE and ce_slope > pe_slope
        else "BEARISH" if ce_slope is not None and pe_slope is not None
        and pe_slope >= _OPTION_SLOPE_SUPPORT_PER_MINUTE and pe_slope > ce_slope
        else "FLAT"
    )

    futures_state = str(futures.get("positioning_state") or "UNAVAILABLE").upper()
    futures_strength = str(futures.get("strength") or "UNAVAILABLE").upper()
    futures_direction = (
        "BULLISH" if futures_state in _BULLISH_FUTURES
        else "BEARISH" if futures_state in _BEARISH_FUTURES
        else "NEUTRAL"
    )
    futures_quality = "CONFIRMING" if futures_strength in _CONFIRMING_STRENGTH else "WEAK"

    underlying_state = str(underlying.get("state") or "UNAVAILABLE").upper()
    underlying_direction = str(underlying.get("direction") or "UNAVAILABLE").upper()
    underlying_momentum = str(underlying.get("momentum") or "UNAVAILABLE").upper()
    acceptance_state = str(underlying.get("acceptance_state") or "UNAVAILABLE").upper()
    rsi_view = str(underlying.get("rsi_view") or "UNAVAILABLE").upper()
    early_state = str(early_1m.get("state") or "UNAVAILABLE").upper()
    early_direction = str(early_1m.get("direction") or "UNAVAILABLE").upper()
    spot_vwap_state = str(spot_vwap.get("state") or "UNAVAILABLE").upper()
    spot_vwap_direction = str(spot_vwap.get("direction") or "UNAVAILABLE").upper()
    futures_vwap_state = str(futures_vwap.get("state") or "UNAVAILABLE").upper()
    futures_vwap_direction = str(futures_vwap.get("direction") or "UNAVAILABLE").upper()

    option_time = _timestamp(summary.get("observed_at"))
    futures_collection_time = _timestamp(futures.get("observed_at"))
    futures_market_time = _timestamp(futures.get("latest_timestamp"))
    underlying_time = _timestamp(underlying.get("observed_at"))
    option_age = _age(option_time, current_time)
    futures_collection_age = _age(futures_collection_time, current_time)
    futures_market_age = _age(futures_market_time, current_time)
    underlying_age = _age(underlying_time, current_time)
    alignment_gap = None
    if option_time and futures_market_time and underlying_time:
        values = [option_time.astimezone(timezone.utc), futures_market_time.astimezone(timezone.utc), underlying_time.astimezone(timezone.utc)]
        alignment_gap = (max(values) - min(values)).total_seconds()
    evidence_status = (
        "ALIGNED_TO_COMPLETED_5M"
        if option_age is not None and option_age <= _OPTION_MAX_AGE_SECONDS
        and futures_collection_age is not None and futures_collection_age <= _FUTURES_COLLECTION_MAX_AGE_SECONDS
        and futures_market_age is not None and futures_market_age <= _COMPLETED_5M_MAX_AGE_SECONDS
        and underlying_age is not None and underlying_age <= _COMPLETED_5M_MAX_AGE_SECONDS
        and alignment_gap is not None and alignment_gap <= _MAX_COMPLETED_5M_ALIGNMENT_GAP_SECONDS
        else "STALE"
        if all(value is not None for value in (option_time, futures_collection_time, futures_market_time, underlying_time))
        else "UNAVAILABLE"
    )

    mandatory_scores = bullish is not None and bearish is not None
    contracts_eligible = int(summary.get("eligible_ce") or 0) > 0 and int(summary.get("eligible_pe") or 0) > 0
    structure_confirmed = acceptance_state == "HOLD_CONFIRMED"
    option_level_supports = option_direction == underlying_direction
    option_slope_supports = option_momentum in {underlying_direction, "FLAT"}
    option_early_supports = option_direction == "WAIT" and option_momentum == underlying_direction
    spot_vwap_conflict = spot_vwap_direction in {"BULLISH", "BEARISH"} and spot_vwap_direction != underlying_direction
    futures_vwap_conflict = futures_vwap_direction in {"BULLISH", "BEARISH"} and futures_vwap_direction != underlying_direction
    early_supports = early_direction == underlying_direction

    if not mandatory_scores or not contracts_eligible or evidence_status != "ALIGNED_TO_COMPLETED_5M" or underlying_direction == "UNAVAILABLE":
        market_state, trade_bias = "UNAVAILABLE", "WAIT"
        confirmation = "MANDATORY EVIDENCE MISSING, STALE, MISALIGNED OR ILLIQUID"
    elif underlying_direction == "NEUTRAL":
        if early_direction in {"BULLISH", "BEARISH"} and not spot_vwap_conflict:
            market_state = f"EARLY {early_direction} TRANSITION"
            trade_bias = "WAIT"
            confirmation = "COMPLETED 1M BREAK DETECTED; 5M CONFIRMATION PENDING"
        else:
            market_state = underlying_state if underlying_state.startswith("SIDEWAYS") else "SIDEWAYS"
            trade_bias = "WAIT"
            confirmation = "UNDERLYING 5M STRUCTURE HAS NO ACCEPTED DIRECTIONAL BREAK"
    elif not structure_confirmed:
        market_state = f"EARLY {underlying_direction} TRANSITION"
        trade_bias = "WAIT"
        confirmation = f"{acceptance_state}: BREAK OR TRANSITION EXISTS BUT 5M HOLD IS NOT CONFIRMED"
    elif spot_vwap_conflict or futures_vwap_conflict:
        market_state, trade_bias = "CONFLICTED", "WAIT"
        confirmation = "PRICE STRUCTURE AND AVAILABLE VWAP ACCEPTANCE DISAGREE"
    elif futures_direction not in {underlying_direction, "NEUTRAL"}:
        market_state, trade_bias = "CONFLICTED", "WAIT"
        confirmation = "UNDERLYING AND FUTURES DISAGREE"
    elif option_direction not in {underlying_direction, "WAIT"}:
        market_state, trade_bias = "CONFLICTED", "WAIT"
        confirmation = "UNDERLYING AND OPTIONS DISAGREE"
    elif rsi_view in {"BULLISH", "BEARISH"} and rsi_view != underlying_direction:
        market_state, trade_bias = "CONFLICTED / TRANSITIONAL", "WAIT"
        confirmation = "PRICE STRUCTURE AND RSI SLOPE DISAGREE"
    elif futures_direction == underlying_direction and futures_quality == "CONFIRMING" and option_level_supports and option_slope_supports:
        market_state = f"CONFIRMED {underlying_direction}"
        trade_bias = "BUY CE" if underlying_direction == "BULLISH" else "BUY PE"
        confirmation = "5M HOLD, FUTURES AND OPTION LEVEL/PERSISTENCE AGREE; VWAP DOES NOT CONTRADICT"
    elif option_early_supports or early_supports:
        market_state = f"EARLY {underlying_direction} TRANSITION"
        trade_bias = "WAIT"
        confirmation = "UNDERLYING DIRECTION EXISTS; 1M OR OPTION PERSISTENCE SUPPORTS BUT FULL CONFIRMATION IS INCOMPLETE"
    else:
        market_state = f"EARLY {underlying_direction} TRANSITION"
        trade_bias = "WAIT"
        confirmation = "UNDERLYING LEADS; DERIVATIVE OR VWAP CONFIRMATION IS INCOMPLETE"

    checklist = [
        {"Check": "Completed 1m early state", "Live value": early_state, "Rule": "Completed 1m structure break; never full confirmation", "Status": early_direction},
        {"Check": "Underlying 5m structure", "Live value": underlying_state, "Rule": "Completed breakout plus subsequent completed hold", "Status": f"{underlying_direction} / {acceptance_state}"},
        {"Check": "Underlying momentum", "Live value": underlying_momentum, "Rule": "ATR-normalized expansion on completed candles", "Status": underlying.get("reason") or "—"},
        {"Check": "Spot VWAP acceptance", "Live value": spot_vwap_state, "Rule": "VWAP direction and ATR-normalized distance; unavailable when provider volume is zero", "Status": spot_vwap.get("reason") or "—"},
        {"Check": "RSI slope", "Live value": f"{_score(underlying.get('rsi'))} / slope {_score(underlying.get('rsi_slope'))}", "Rule": "Completed 5m RSI slope confirms or flags recovery/fade", "Status": rsi_view},
        {"Check": "Option pressure", "Live value": f"CE {_score(bullish)} / PE {_score(bearish)} / gap {_score(gap)}", "Rule": "Normalized symmetric ATM-distance weights", "Status": option_direction},
        {"Check": "Option persistence", "Live value": f"CE {_score(ce_slope)} / PE {_score(pe_slope)} points/min", "Rule": "Same-session, same-expiry slope", "Status": option_momentum},
        {"Check": "Contract quality", "Live value": f"CE {summary.get('eligible_ce', 0)} / PE {summary.get('eligible_pe', 0)} eligible; {summary.get('rejected', 0)} rejected", "Rule": "Two-sided quote, midpoint spread, volume, OI and IV", "Status": "PASS" if contracts_eligible else "FAIL"},
        {"Check": "Futures", "Live value": f"{futures_state} / {futures_strength}", "Rule": "Latest completed futures candle plus fresh collector", "Status": futures_quality},
        {"Check": "Futures VWAP acceptance", "Live value": futures_vwap_state, "Rule": "Used when futures snapshot exposes VWAP", "Status": futures_vwap.get("reason") or "—"},
        {"Check": "Evidence alignment", "Live value": "—" if alignment_gap is None else f"{alignment_gap:.0f}s market-time gap", "Rule": "Option snapshot + futures candle + underlying completed candle", "Status": evidence_status},
    ]
    return {
        "market_state": market_state,
        "trade_bias": trade_bias,
        "confirmation": confirmation,
        "bullish_score": bullish,
        "bearish_score": bearish,
        "score_gap": gap,
        "underlying_state": underlying_state,
        "underlying_direction": underlying_direction,
        "acceptance_state": acceptance_state,
        "early_1m_state": early_state,
        "early_1m_direction": early_direction,
        "spot_vwap_state": spot_vwap_state,
        "futures_vwap_state": futures_vwap_state,
        "option_direction": option_direction,
        "option_momentum": option_momentum,
        "futures_direction": futures_direction,
        "evidence_status": evidence_status,
        "alignment_gap_seconds": alignment_gap,
        "checklist": checklist,
        "explanation": (
            f"1m {early_state}; 5m {underlying_state}/{acceptance_state}; spot VWAP {spot_vwap_state}; "
            f"options CE {_score(bullish)} vs PE {_score(bearish)} with persistence {option_momentum}; "
            f"futures {futures_state}/{futures_strength}, VWAP {futures_vwap_state}; RSI {rsi_view}; evidence {evidence_status}."
        ),
    }


def render_market_at_a_glance(settings, underlying_name: str) -> None:
    st.markdown("## Market at a Glance")
    rows = list(read_latest_option_participation(settings.database_path, underlying_name=underlying_name) or [])
    if not rows:
        st.warning("No current ATM ±4 option evidence is available.")
        return
    normalized = corrected_option_summary(rows)
    normalized["observed_at"] = rows[0].get("observed_at")
    history = read_option_score_history(settings.database_path, underlying_name=underlying_name, limit=5)
    normalized["ce_score_slope"] = score_slope(history, "CE")
    normalized["pe_score_slope"] = score_slope(history, "PE")

    futures_rows = read_nifty_futures_snapshots(settings.database_path, underlying_name=underlying_name, limit=1)
    futures = futures_rows[0] if futures_rows else {}
    futures_vwap = build_futures_vwap_acceptance(futures)
    layout = ArtifactLayout(settings)
    underlying_key = UNDERLYINGS.get(underlying_name, "NSE_INDEX|Nifty 50")
    live_path = layout.live_session_path("upstox", underlying_key, 1)
    now = datetime.now(timezone.utc)
    underlying = read_underlying_evidence(live_path, as_of_timestamp=now)
    intraday = read_intraday_acceptance(live_path, as_of_timestamp=now)
    view = build_market_at_a_glance(
        normalized,
        futures,
        underlying,
        now=now,
        early_1m=intraday["early_1m"],
        spot_vwap=intraday["spot_vwap"],
        futures_vwap=futures_vwap,
    )

    st.caption(
        "EMA-free observational model: completed 1m detects early breaks; completed 5m breakout/hold owns confirmation; VWAP, RSI, futures and ATM ±4 options confirm or contradict."
    )
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Current market", view["market_state"])
    c2.metric("Trade bias", view["trade_bias"])
    c3.metric("Bullish score", _score(view["bullish_score"]))
    c4.metric("Bearish score", _score(view["bearish_score"]))
    c5.metric("Score gap", _score(view["score_gap"]))
    state = view["market_state"]
    if state == "CONFIRMED BULLISH":
        st.success("CONFIRMED BULLISH: 5m hold, futures and CE level/persistence agree without VWAP contradiction.")
    elif state == "CONFIRMED BEARISH":
        st.error("CONFIRMED BEARISH: 5m hold, futures and PE level/persistence agree without VWAP contradiction.")
    elif state == "UNAVAILABLE":
        st.warning("UNAVAILABLE: mandatory evidence is missing, stale, misaligned or contract quality failed.")
    elif "CONFLICTED" in state:
        st.warning(f"{state}: independent evidence groups disagree. Trade bias remains WAIT.")
    else:
        st.info(f"{state}: direction is not fully confirmed. Trade bias remains WAIT.")
    st.write(f"**What is happening:** {view['explanation']}")
    st.write(f"**Decision reason:** {view['confirmation']}")
    st.dataframe(_arrow_safe_rows(view["checklist"]), width="stretch", hide_index=True)
    st.caption("Observational only. Scores and thresholds are normalized heuristics pending historical outcome calibration. This panel does not modify Red Bar execution.")
    st.markdown("---")


def install(page_module: Any) -> None:
    if getattr(page_module, "_market_at_a_glance_installed", False):
        return
    if not str(getattr(page_module, "__name__", "")).endswith("market_readiness"):
        return
    original_render = getattr(page_module, "render_page", None)
    if not callable(original_render):
        return

    def wrapped_render(settings, layout, database, token, underlying_name, instrument_key, interval):
        render_market_at_a_glance(settings, underlying_name)
        return original_render(settings, layout, database, token, underlying_name, instrument_key, interval)

    page_module.render_page = wrapped_render
    page_module._market_at_a_glance_installed = True


__all__ = ["build_market_at_a_glance", "install", "render_market_at_a_glance"]
