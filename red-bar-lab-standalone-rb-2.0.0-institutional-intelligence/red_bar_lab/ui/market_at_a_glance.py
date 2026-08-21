from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from red_bar_lab.services.nifty_futures_snapshot_store import (
    read_nifty_futures_snapshots,
)
from red_bar_lab.services.option_participation_store import (
    read_latest_option_participation,
    summarize_option_participation,
)
from red_bar_lab.ui._shared import _arrow_safe_rows, st

_BULLISH_FUTURES = {"LONG_BUILDUP", "SHORT_COVERING"}
_BEARISH_FUTURES = {"SHORT_BUILDUP", "LONG_UNWINDING"}
_CONFIRMING_STRENGTH = {"STRONG", "MODERATE"}
_MAX_SOURCE_AGE_SECONDS = 180.0
_MAX_ALIGNMENT_GAP_SECONDS = 120.0


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
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _age_seconds(value: datetime | None, now: datetime) -> float | None:
    if value is None:
        return None
    return max(0.0, (now.astimezone(timezone.utc) - value.astimezone(timezone.utc)).total_seconds())


def build_market_at_a_glance(
    summary: Mapping[str, Any],
    futures: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)

    bullish = _number(summary.get("ce_score"))
    bearish = _number(summary.get("pe_score"))
    scores_available = bullish is not None and bearish is not None
    gap = abs(bullish - bearish) if scores_available else None
    winning_score = max(bullish, bearish) if scores_available else None
    winning_side = (
        "CE" if scores_available and bullish > bearish
        else "PE" if scores_available and bearish > bullish
        else "TIE" if scores_available
        else "UNAVAILABLE"
    )

    option_direction = (
        "BULLISH"
        if winning_side == "CE" and winning_score is not None and winning_score >= 50.0 and gap is not None and gap >= 8.0
        else "BEARISH"
        if winning_side == "PE" and winning_score is not None and winning_score >= 50.0 and gap is not None and gap >= 8.0
        else "WAIT"
        if scores_available
        else "UNAVAILABLE"
    )

    futures_state = str(futures.get("positioning_state") or "UNAVAILABLE").upper()
    futures_strength = str(futures.get("strength") or "UNAVAILABLE").upper()
    futures_direction = (
        "BULLISH" if futures_state in _BULLISH_FUTURES
        else "BEARISH" if futures_state in _BEARISH_FUTURES
        else "NEUTRAL"
    )
    futures_quality = (
        "CONFIRMING" if futures_strength in _CONFIRMING_STRENGTH
        else "WEAK" if futures_direction in {"BULLISH", "BEARISH"}
        else "UNAVAILABLE"
    )

    rsi = _number(summary.get("underlying_rsi"))
    if rsi is None:
        rsi_view = "UNAVAILABLE"
    elif rsi > 55.0:
        rsi_view = "BULLISH"
    elif rsi < 45.0:
        rsi_view = "BEARISH"
    else:
        rsi_view = "NEUTRAL"

    option_time = _timestamp(summary.get("observed_at"))
    futures_time = _timestamp(futures.get("observed_at"))
    underlying_time = _timestamp(futures.get("latest_timestamp"))
    option_age = _age_seconds(option_time, current_time)
    futures_age = _age_seconds(futures_time, current_time)
    underlying_age = _age_seconds(underlying_time, current_time)
    alignment_gap = (
        abs((option_time.astimezone(timezone.utc) - futures_time.astimezone(timezone.utc)).total_seconds())
        if option_time is not None and futures_time is not None
        else None
    )
    evidence_fresh = all(
        age is not None and age <= _MAX_SOURCE_AGE_SECONDS
        for age in (option_age, futures_age, underlying_age)
    )
    evidence_aligned = alignment_gap is not None and alignment_gap <= _MAX_ALIGNMENT_GAP_SECONDS
    evidence_status = (
        "ALIGNED"
        if evidence_fresh and evidence_aligned
        else "STALE"
        if all(value is not None for value in (option_time, futures_time, underlying_time))
        else "UNAVAILABLE"
    )

    if not scores_available or evidence_status != "ALIGNED":
        market_state = "UNAVAILABLE"
        trade_bias = "WAIT"
        confirmation = "MANDATORY EVIDENCE MISSING, STALE OR MISALIGNED"
    elif option_direction == "WAIT":
        if futures_direction in {"BULLISH", "BEARISH"} and rsi_view in {"BULLISH", "BEARISH"} and futures_direction != rsi_view:
            market_state = "CONFLICTED / TRANSITIONAL"
            confirmation = "OPTIONS WEAK; FUTURES AND RSI DISAGREE"
        else:
            market_state = "WAIT / NO CLEAR EDGE"
            confirmation = "OPTION SCORE THRESHOLD OR SEPARATION NOT MET"
        trade_bias = "WAIT"
    elif futures_direction not in {"BULLISH", "BEARISH"}:
        market_state = f"EARLY {option_direction} TRANSITION"
        trade_bias = "WAIT"
        confirmation = "OPTIONS LEAD; FUTURES UNAVAILABLE OR NEUTRAL"
    elif futures_direction != option_direction:
        market_state = "CONFLICTED"
        trade_bias = "WAIT"
        confirmation = "OPTIONS AND FUTURES DISAGREE"
    elif rsi_view in {"BULLISH", "BEARISH"} and rsi_view != option_direction:
        market_state = "CONFLICTED / TRANSITIONAL"
        trade_bias = "WAIT"
        confirmation = "DERIVATIVES AGREE; UNDERLYING RSI CONTRADICTS"
    elif futures_quality != "CONFIRMING":
        market_state = f"EARLY {option_direction} TRANSITION"
        trade_bias = "WAIT"
        confirmation = "FUTURES DIRECTION SUPPORTS BUT STRENGTH IS WEAK"
    else:
        market_state = f"CONFIRMED {option_direction}"
        trade_bias = "BUY CE" if option_direction == "BULLISH" else "BUY PE"
        confirmation = "OPTIONS, FUTURES QUALITY AND RSI CONFIRM"

    reason_parts = [
        f"Bullish CE score {_score(bullish)}",
        f"Bearish PE score {_score(bearish)}",
        f"gap {_score(gap)}",
        f"futures {futures_state}/{futures_strength}",
        f"RSI {rsi_view}",
        f"evidence {evidence_status}",
    ]
    explanation = "; ".join(reason_parts) + "."

    checklist = [
        {"Check": "Bullish score (CE)", "Live value": _score(bullish), "Rule": "Higher than PE, at least 50, gap at least 8", "Status": "UNAVAILABLE" if bullish is None else "LEADING" if winning_side == "CE" else "TRAILING"},
        {"Check": "Bearish score (PE)", "Live value": _score(bearish), "Rule": "Higher than CE, at least 50, gap at least 8", "Status": "UNAVAILABLE" if bearish is None else "LEADING" if winning_side == "PE" else "TRAILING"},
        {"Check": "Score gap", "Live value": _score(gap), "Rule": "At least 8 points", "Status": "UNAVAILABLE" if gap is None else "PASS" if gap >= 8.0 else "WAIT"},
        {"Check": "Futures confirmation", "Live value": f"{futures_state} / {futures_strength}", "Rule": "Supportive state plus STRONG or MODERATE strength", "Status": futures_quality},
        {"Check": "Underlying RSI", "Live value": "—" if rsi is None else f"{rsi:.1f}", "Rule": "Above 55 bullish; below 45 bearish; contradiction forces WAIT", "Status": rsi_view},
        {"Check": "Evidence alignment", "Live value": "—" if alignment_gap is None else f"{alignment_gap:.0f}s gap", "Rule": "All sources <=180s old and option/futures gap <=120s", "Status": evidence_status},
    ]

    return {
        "market_state": market_state,
        "trade_bias": trade_bias,
        "bullish_score": bullish,
        "bearish_score": bearish,
        "score_gap": gap,
        "winning_side": winning_side,
        "option_direction": option_direction,
        "futures_state": futures_state,
        "futures_strength": futures_strength,
        "futures_direction": futures_direction,
        "futures_quality": futures_quality,
        "confirmation": confirmation,
        "rsi_view": rsi_view,
        "evidence_status": evidence_status,
        "option_observed_at": summary.get("observed_at"),
        "futures_observed_at": futures.get("observed_at"),
        "underlying_timestamp": futures.get("latest_timestamp"),
        "option_age_seconds": option_age,
        "futures_age_seconds": futures_age,
        "underlying_age_seconds": underlying_age,
        "alignment_gap_seconds": alignment_gap,
        "explanation": explanation,
        "checklist": checklist,
    }


def render_market_at_a_glance(settings, underlying_name: str) -> None:
    rows = list(read_latest_option_participation(settings.database_path, underlying_name=underlying_name) or [])
    st.markdown("## Market at a Glance")
    if not rows:
        st.warning("No current ATM ±4 option evidence is available. Run the paper monitor during market hours.")
        return

    summary = summarize_option_participation(rows)
    futures_rows = read_nifty_futures_snapshots(settings.database_path, underlying_name=underlying_name, limit=1)
    futures = futures_rows[0] if futures_rows else {}
    view = build_market_at_a_glance(summary, futures)

    st.caption(
        "Underlying momentum, futures quality and ATM ±4 option participation are evaluated separately. "
        "Options confirm pressure; they do not independently own the NIFTY trend."
    )
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Current market", view["market_state"])
    c2.metric("Trade bias", view["trade_bias"])
    c3.metric("Bullish score", _score(view["bullish_score"]))
    c4.metric("Bearish score", _score(view["bearish_score"]))
    c5.metric("Score gap", _score(view["score_gap"]))

    state = view["market_state"]
    if state == "CONFIRMED BULLISH":
        st.success("CONFIRMED BULLISH: CE pressure, futures quality and underlying RSI agree.")
    elif state == "CONFIRMED BEARISH":
        st.error("CONFIRMED BEARISH: PE pressure, futures quality and underlying RSI agree.")
    elif state == "UNAVAILABLE":
        st.warning("UNAVAILABLE: mandatory evidence is missing, stale or timestamp-misaligned. No direction is inferred from missing values.")
    elif "CONFLICTED" in state:
        st.warning(f"{state}: evidence groups disagree. Keep the trade bias at WAIT.")
    elif state.startswith("EARLY"):
        st.info(f"{state}: a directional lean exists, but confirmation quality is incomplete. Keep the trade bias at WAIT.")
    else:
        st.info("WAIT: option pressure has not reached the minimum score and separation requirements.")

    st.write(f"**What is happening:** {view['explanation']}")
    st.dataframe(_arrow_safe_rows(view["checklist"]), width="stretch", hide_index=True)
    st.caption(
        f"Option observed: {view['option_observed_at'] or '—'} · Futures observed: {view['futures_observed_at'] or '—'} · "
        f"Underlying candle: {view['underlying_timestamp'] or '—'}. This panel remains observational only."
    )
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
