from __future__ import annotations

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


def _number(value: object) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def _score(value: object) -> str:
    number = _number(value)
    return "—" if number is None else f"{number:.1f}"


def build_market_at_a_glance(
    summary: Mapping[str, Any],
    futures: Mapping[str, Any],
) -> dict[str, Any]:
    bullish = _number(summary.get("ce_score")) or 0.0
    bearish = _number(summary.get("pe_score")) or 0.0
    gap = abs(bullish - bearish)
    winning_score = max(bullish, bearish)
    winning_side = "CE" if bullish > bearish else "PE" if bearish > bullish else "TIE"

    option_direction = (
        "BULLISH"
        if winning_side == "CE" and winning_score >= 50.0 and gap >= 8.0
        else "BEARISH"
        if winning_side == "PE" and winning_score >= 50.0 and gap >= 8.0
        else "WAIT"
    )

    futures_state = str(futures.get("positioning_state") or "UNAVAILABLE").upper()
    futures_strength = str(futures.get("strength") or "UNAVAILABLE").upper()
    futures_direction = (
        "BULLISH"
        if futures_state in _BULLISH_FUTURES
        else "BEARISH"
        if futures_state in _BEARISH_FUTURES
        else "NEUTRAL"
    )

    if option_direction == "WAIT":
        market_state = "WAIT / NO CLEAR EDGE"
        trade_bias = "WAIT"
        confirmation = "SCORE THRESHOLD OR SEPARATION NOT MET"
    elif futures_direction == "NEUTRAL":
        market_state = option_direction
        trade_bias = "BUY CE" if option_direction == "BULLISH" else "BUY PE"
        confirmation = "OPTIONS LEAD; FUTURES NEUTRAL OR UNAVAILABLE"
    elif futures_direction == option_direction:
        market_state = option_direction
        trade_bias = "BUY CE" if option_direction == "BULLISH" else "BUY PE"
        confirmation = "OPTIONS AND FUTURES CONFIRM"
    else:
        market_state = "CONFLICTED"
        trade_bias = "WAIT"
        confirmation = "OPTIONS AND FUTURES DISAGREE"

    rsi = _number(summary.get("underlying_rsi"))
    if rsi is None:
        rsi_view = "UNAVAILABLE"
    elif rsi > 55.0:
        rsi_view = "BULLISH"
    elif rsi < 45.0:
        rsi_view = "BEARISH"
    else:
        rsi_view = "NEUTRAL"

    reason_parts = [
        f"Bullish CE score {bullish:.1f}",
        f"Bearish PE score {bearish:.1f}",
        f"gap {gap:.1f}",
        f"futures {futures_state}",
        f"RSI {rsi_view}",
    ]
    explanation = "; ".join(reason_parts) + "."

    checklist = [
        {
            "Check": "Bullish score (CE)",
            "Live value": f"{bullish:.1f}",
            "Bullish rule": "Higher than PE, at least 50, gap at least 8",
            "Bearish rule": "Not used",
            "Status": "LEADING" if winning_side == "CE" else "TRAILING",
        },
        {
            "Check": "Bearish score (PE)",
            "Live value": f"{bearish:.1f}",
            "Bullish rule": "Not used",
            "Bearish rule": "Higher than CE, at least 50, gap at least 8",
            "Status": "LEADING" if winning_side == "PE" else "TRAILING",
        },
        {
            "Check": "Score gap",
            "Live value": f"{gap:.1f}",
            "Bullish rule": "At least 8 points",
            "Bearish rule": "At least 8 points",
            "Status": "PASS" if gap >= 8.0 else "WAIT",
        },
        {
            "Check": "Futures confirmation",
            "Live value": futures_state,
            "Bullish rule": "LONG_BUILDUP or SHORT_COVERING",
            "Bearish rule": "SHORT_BUILDUP or LONG_UNWINDING",
            "Status": confirmation,
        },
        {
            "Check": "Underlying RSI",
            "Live value": "—" if rsi is None else f"{rsi:.1f}",
            "Bullish rule": "Above 55 supports bullishness",
            "Bearish rule": "Below 45 supports bearishness",
            "Status": rsi_view,
        },
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
        "confirmation": confirmation,
        "rsi_view": rsi_view,
        "explanation": explanation,
        "checklist": checklist,
    }


def render_market_at_a_glance(settings, underlying_name: str) -> None:
    rows = list(
        read_latest_option_participation(
            settings.database_path,
            underlying_name=underlying_name,
        )
        or []
    )
    if not rows:
        st.markdown("## Market at a Glance")
        st.warning("No current ATM ±4 option evidence is available. Run the paper monitor during market hours.")
        return

    summary = summarize_option_participation(rows)
    futures_rows = read_nifty_futures_snapshots(
        settings.database_path,
        underlying_name=underlying_name,
        limit=1,
    )
    futures = futures_rows[0] if futures_rows else {}
    view = build_market_at_a_glance(summary, futures)

    st.markdown("## Market at a Glance")
    st.caption(
        "Quick interpretation of the independent option and futures evidence. "
        "Bullish score = CE pressure. Bearish score = PE pressure."
    )

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Current market", view["market_state"])
    c2.metric("Trade bias", view["trade_bias"])
    c3.metric("Bullish score", _score(view["bullish_score"]))
    c4.metric("Bearish score", _score(view["bearish_score"]))
    c5.metric("Score gap", _score(view["score_gap"]))

    if view["market_state"] == "BULLISH":
        st.success(
            f"BULLISH: CE evidence leads and {view['confirmation'].lower()}. "
            "The independent observation favours CE."
        )
    elif view["market_state"] == "BEARISH":
        st.error(
            f"BEARISH: PE evidence leads and {view['confirmation'].lower()}. "
            "The independent observation favours PE."
        )
    elif view["market_state"] == "CONFLICTED":
        st.warning(
            "CONFLICTED: options and futures point in opposite directions. "
            "Do not treat either CE or PE as confirmed."
        )
    else:
        st.info(
            "WAIT: the winning score is below 50, the CE/PE gap is below 8, "
            "or the evidence has no clear directional edge."
        )

    st.write(f"**What is happening:** {view['explanation']}")
    st.dataframe(
        _arrow_safe_rows(view["checklist"]),
        width="stretch",
        hide_index=True,
    )
    st.caption(
        "This panel is observational only. A bullish or bearish label is not execution approval; "
        "conflicting, stale or incomplete evidence should remain WAIT."
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

    def wrapped_render(
        settings,
        layout,
        database,
        token,
        underlying_name,
        instrument_key,
        interval,
    ):
        render_market_at_a_glance(settings, underlying_name)
        return original_render(
            settings,
            layout,
            database,
            token,
            underlying_name,
            instrument_key,
            interval,
        )

    page_module.render_page = wrapped_render
    page_module._market_at_a_glance_installed = True


__all__ = ["build_market_at_a_glance", "install", "render_market_at_a_glance"]
