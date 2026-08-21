from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from red_bar_lab.config import UNDERLYINGS
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
_COMPLETED_5M_MAX_AGE_SECONDS = 420.0
_MAX_COMPLETED_5M_ALIGNMENT_GAP_SECONDS = 420.0


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
) -> dict[str, Any]:
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    underlying = dict(underlying or {})

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
        "BULLISH" if ce_slope is not None and pe_slope is not None and ce_slope >= 2.0 and ce_slope > pe_slope
        else "BEARISH" if ce_slope is not None and pe_slope is not None and pe_slope >= 2.0 and pe_slope > ce_slope
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
    rsi_view = str(underlying.get("rsi_view") or "UNAVAILABLE").upper()

    option_time = _timestamp(summary.get("observed_at"))
    futures_time = _timestamp(futures.get("observed_at"))
    underlying_time = _timestamp(underlying.get("observed_at"))
    option_age = _age(option_time, current_time)
    futures_age = _age(futures_time, current_time)
    underlying_age = _age(underlying_time, current_time)
    alignment_gap = None
    if option_time and futures_time and underlying_time:
        utc_values = [value.astimezone(timezone.utc) for value in (option_time, futures_time, underlying_time)]
        alignment_gap = (max(utc_values) - min(utc_values)).total_seconds()

    option_fresh = option_age is not None and option_age <= _OPTION_MAX_AGE_SECONDS
    futures_fresh = futures_age is not None and futures_age <= _COMPLETED_5M_MAX_AGE_SECONDS
    underlying_fresh = underlying_age is not None and underlying_age <= _COMPLETED_5M_MAX_AGE_SECONDS
    evidence_aligned = (
        alignment_gap is not None
        and alignment_gap <= _MAX_COMPLETED_5M_ALIGNMENT_GAP_SECONDS
    )
    evidence_status = (
        "ALIGNED_TO_COMPLETED_5M"
        if option_fresh and futures_fresh and underlying_fresh and evidence_aligned
        else "STALE"
        if all(value is not None for value in (option_time, futures_time, underlying_time))
        else "UNAVAILABLE"
    )

    mandatory_scores = bullish is not None and bearish is not None
    contracts_eligible = int(summary.get("eligible_ce") or 0) > 0 and int(summary.get("eligible_pe") or 0) > 0
    evidence_ready = evidence_status == "ALIGNED_TO_COMPLETED_5M"
    if not mandatory_scores or not contracts_eligible or not evidence_ready or underlying_direction == "UNAVAILABLE":
        market_state, trade_bias = "UNAVAILABLE", "WAIT"
        confirmation = "MANDATORY EVIDENCE MISSING, STALE, MISALIGNED OR ILLIQUID"
    elif underlying_direction == "NEUTRAL":
        market_state, trade_bias = "SIDEWAYS_COMPRESSION", "WAIT"
        confirmation = "UNDERLYING STRUCTURE HAS NO DIRECTIONAL BREAK"
    elif underlying_state.startswith("TRANSITION") or underlying_momentum in {"EARLY", "DEVELOPING"}:
        market_state = f"EARLY {underlying_direction} TRANSITION"
        trade_bias = "WAIT"
        confirmation = "UNDERLYING TRANSITION EXISTS BUT BREAK/HOLD QUALITY IS INCOMPLETE"
    elif futures_direction not in {underlying_direction, "NEUTRAL"}:
        market_state, trade_bias = "CONFLICTED", "WAIT"
        confirmation = "UNDERLYING AND FUTURES DISAGREE"
    elif option_direction not in {underlying_direction, "WAIT"}:
        market_state, trade_bias = "CONFLICTED", "WAIT"
        confirmation = "UNDERLYING AND OPTIONS DISAGREE"
    elif rsi_view in {"BULLISH", "BEARISH"} and rsi_view != underlying_direction:
        market_state, trade_bias = "CONFLICTED / TRANSITIONAL", "WAIT"
        confirmation = "PRICE STRUCTURE AND RSI SLOPE DISAGREE"
    elif futures_direction == underlying_direction and futures_quality == "CONFIRMING" and option_direction == underlying_direction:
        market_state = f"CONFIRMED {underlying_direction}"
        trade_bias = "BUY CE" if underlying_direction == "BULLISH" else "BUY PE"
        confirmation = "UNDERLYING STRUCTURE, FUTURES AND OPTIONS CONFIRM"
    else:
        market_state = f"EARLY {underlying_direction} TRANSITION"
        trade_bias = "WAIT"
        confirmation = "UNDERLYING LEADS; DERIVATIVE CONFIRMATION IS WEAK OR INCOMPLETE"

    checklist = [
        {"Check": "Underlying structure", "Live value": underlying_state, "Rule": "Break/hold plus ATR-normalized expansion owns direction", "Status": underlying_direction},
        {"Check": "Underlying momentum", "Live value": underlying_momentum, "Rule": "Expansion or developing transition", "Status": underlying.get("reason") or "—"},
        {"Check": "RSI slope", "Live value": f"{_score(underlying.get('rsi'))} / slope {_score(underlying.get('rsi_slope'))}", "Rule": "Slope confirms or flags recovery/fade", "Status": rsi_view},
        {"Check": "Option pressure", "Live value": f"CE {_score(bullish)} / PE {_score(bearish)} / gap {_score(gap)}", "Rule": "Calibrated distance-weighted scores; no volume double count", "Status": option_direction},
        {"Check": "Option persistence", "Live value": f"CE {_score(ce_slope)} / PE {_score(pe_slope)} per snapshot", "Rule": "3–5 snapshot score slope", "Status": option_momentum},
        {"Check": "Contract quality", "Live value": f"CE {summary.get('eligible_ce', 0)} / PE {summary.get('eligible_pe', 0)} eligible; {summary.get('rejected', 0)} rejected", "Rule": "Price, volume, OI, spread and IV eligibility", "Status": "PASS" if contracts_eligible else "FAIL"},
        {"Check": "Futures", "Live value": f"{futures_state} / {futures_strength}", "Rule": "Supportive state plus STRONG or MODERATE", "Status": futures_quality},
        {
            "Check": "Evidence alignment",
            "Live value": "—" if alignment_gap is None else f"{alignment_gap:.0f}s max gap",
            "Rule": "Options <=180s; completed 5m futures/underlying <=420s; max gap <=420s",
            "Status": evidence_status,
        },
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
        "option_direction": option_direction,
        "futures_direction": futures_direction,
        "evidence_status": evidence_status,
        "option_age_seconds": option_age,
        "futures_age_seconds": futures_age,
        "underlying_age_seconds": underlying_age,
        "alignment_gap_seconds": alignment_gap,
        "checklist": checklist,
        "explanation": (
            f"Underlying {underlying_state}; options CE {_score(bullish)} vs PE {_score(bearish)}; "
            f"futures {futures_state}/{futures_strength}; RSI {rsi_view}; evidence {evidence_status}."
        ),
    }


def render_market_at_a_glance(settings, underlying_name: str) -> None:
    st.markdown("## Market at a Glance")
    rows = list(read_latest_option_participation(settings.database_path, underlying_name=underlying_name) or [])
    if not rows:
        st.warning("No current ATM ±4 option evidence is available.")
        return
    calibrated = corrected_option_summary(rows)
    calibrated["observed_at"] = rows[0].get("observed_at")
    history = read_option_score_history(settings.database_path, underlying_name=underlying_name, limit=5)
    calibrated["ce_score_slope"] = score_slope(history, "CE")
    calibrated["pe_score_slope"] = score_slope(history, "PE")

    futures_rows = read_nifty_futures_snapshots(settings.database_path, underlying_name=underlying_name, limit=1)
    futures = futures_rows[0] if futures_rows else {}
    layout = ArtifactLayout(settings)
    underlying_key = UNDERLYINGS.get(underlying_name, "NSE_INDEX|Nifty 50")
    underlying = read_underlying_evidence(layout.live_session_path("upstox", underlying_key, 1))
    view = build_market_at_a_glance(calibrated, futures, underlying)

    st.caption(
        "EMA-free observational model: completed NIFTY price structure owns direction; ATR momentum, RSI slope, futures and ATM ±4 options confirm or contradict it."
    )
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Current market", view["market_state"])
    c2.metric("Trade bias", view["trade_bias"])
    c3.metric("Bullish score", _score(view["bullish_score"]))
    c4.metric("Bearish score", _score(view["bearish_score"]))
    c5.metric("Score gap", _score(view["score_gap"]))

    state = view["market_state"]
    if state == "CONFIRMED BULLISH":
        st.success("CONFIRMED BULLISH: price structure, futures and CE participation agree.")
    elif state == "CONFIRMED BEARISH":
        st.error("CONFIRMED BEARISH: price structure, futures and PE participation agree.")
    elif state == "UNAVAILABLE":
        st.warning("UNAVAILABLE: mandatory evidence is missing, stale, misaligned or contract quality failed.")
    elif "CONFLICTED" in state:
        st.warning(f"{state}: independent evidence groups disagree. Trade bias remains WAIT.")
    else:
        st.info(f"{state}: direction is not fully confirmed. Trade bias remains WAIT.")

    st.write(f"**What is happening:** {view['explanation']}")
    st.write(f"**Decision reason:** {view['confirmation']}")
    st.dataframe(_arrow_safe_rows(view["checklist"]), width="stretch", hide_index=True)
    st.caption("Observational only. This panel does not approve execution or modify Red Bar entry/exit behavior.")
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