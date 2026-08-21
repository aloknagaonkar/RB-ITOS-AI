from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from red_bar_lab.config import UNDERLYINGS
from red_bar_lab.services.intraday_acceptance_engine import (
    build_futures_vwap_acceptance,
    read_intraday_acceptance,
)
from red_bar_lab.services.market_evidence_bundle_store import persist_market_evidence_bundle
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
_OPTION_WARNING_SECONDS = 120.0
_OPTION_MAX_AGE_SECONDS = 180.0
_FUTURES_COLLECTION_WARNING_SECONDS = 120.0
_FUTURES_COLLECTION_MAX_AGE_SECONDS = 180.0
_COMPLETED_5M_MAX_AGE_SECONDS = 420.0
_MAX_COMPLETED_5M_ALIGNMENT_GAP_SECONDS = 420.0
_OPTION_SLOPE_SUPPORT_PER_MINUTE = 1.0
_OPTION_TREND_EPSILON = 0.25

_REASON_PRIORITY = {
    "OPTION_TIMESTAMP_MISSING": 10,
    "FUTURES_COLLECTION_TIMESTAMP_MISSING": 11,
    "FUTURES_MARKET_CANDLE_MISSING": 12,
    "UNDERLYING_CANDLE_MISSING": 13,
    "OPTION_SNAPSHOT_STALE": 20,
    "FUTURES_COLLECTOR_STALE": 21,
    "FUTURES_MARKET_CANDLE_STALE": 22,
    "UNDERLYING_CANDLE_STALE": 23,
    "MARKET_TIMESTAMPS_MISALIGNED": 30,
    "OPTION_SCORES_UNAVAILABLE": 40,
    "NO_ELIGIBLE_CE_CONTRACT": 41,
    "NO_ELIGIBLE_PE_CONTRACT": 42,
}

_OPERATOR_ACTIONS = {
    "OPTION_TIMESTAMP_MISSING": "Inspect option participation persistence and collector output.",
    "OPTION_SNAPSHOT_STALE": "Check the option collector heartbeat and wait for the next option snapshot.",
    "FUTURES_COLLECTION_TIMESTAMP_MISSING": "Inspect futures diagnostic persistence.",
    "FUTURES_COLLECTOR_STALE": "Check or restart the futures diagnostic collector.",
    "FUTURES_MARKET_CANDLE_MISSING": "Verify the futures completed-candle calculation.",
    "FUTURES_MARKET_CANDLE_STALE": "Verify the futures candle feed and completed-candle generation.",
    "UNDERLYING_CANDLE_MISSING": "Check the integrated live-reference refresh output.",
    "UNDERLYING_CANDLE_STALE": "Check the integrated live-reference refresh and Upstox candle feed.",
    "MARKET_TIMESTAMPS_MISALIGNED": "Wait for the next synchronized collection cycle.",
    "OPTION_SCORES_UNAVAILABLE": "Inspect ATM ±4 option capture completeness.",
    "NO_ELIGIBLE_CE_CONTRACT": "Wait for valid CE liquidity and two-sided quotes.",
    "NO_ELIGIBLE_PE_CONTRACT": "Wait for valid PE liquidity and two-sided quotes.",
}


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


def _freshness_result(source: str, timestamp: datetime | None, *, now: datetime, warning_seconds: float | None, stale_seconds: float, missing_code: str, stale_code: str) -> dict[str, Any]:
    age = _age(timestamp, now)
    if timestamp is None:
        status, reason = "MISSING", missing_code
    elif age is not None and age > stale_seconds:
        status, reason = "STALE", stale_code
    elif warning_seconds is not None and age is not None and age > warning_seconds:
        status, reason = "WARNING", None
    else:
        status, reason = "PASS", None
    return {"source": source, "timestamp": timestamp.isoformat() if timestamp else None, "age_seconds": age, "warning_seconds": warning_seconds, "limit_seconds": stale_seconds, "status": status, "reason_code": reason}


def _alignment_result(option_time: datetime | None, futures_market_time: datetime | None, underlying_time: datetime | None) -> dict[str, Any]:
    times = [option_time, futures_market_time, underlying_time]
    if any(value is None for value in times):
        return {"source": "Cross-source alignment", "timestamp": None, "age_seconds": None, "warning_seconds": None, "limit_seconds": _MAX_COMPLETED_5M_ALIGNMENT_GAP_SECONDS, "status": "MISSING", "reason_code": None}
    utc_values = [value.astimezone(timezone.utc) for value in times if value is not None]
    gap = (max(utc_values) - min(utc_values)).total_seconds()
    failed = gap > _MAX_COMPLETED_5M_ALIGNMENT_GAP_SECONDS
    return {"source": "Cross-source alignment", "timestamp": None, "age_seconds": gap, "warning_seconds": None, "limit_seconds": _MAX_COMPLETED_5M_ALIGNMENT_GAP_SECONDS, "status": "MISALIGNED" if failed else "PASS", "reason_code": "MARKET_TIMESTAMPS_MISALIGNED" if failed else None}


def _evidence_readiness(diagnostics: list[Mapping[str, Any]]) -> str:
    statuses = {str(item.get("status") or "") for item in diagnostics}
    if "MISSING" in statuses:
        return "MISSING"
    if "STALE" in statuses:
        return "STALE"
    if "MISALIGNED" in statuses:
        return "MISALIGNED"
    return "READY"


def _primary_reason(reasons: list[str]) -> str | None:
    return min(reasons, key=lambda value: _REASON_PRIORITY.get(value, 999)) if reasons else None


def _option_interpretation(bullish: float | None, bearish: float | None, gap: float | None, ce_slope: float | None, pe_slope: float | None) -> tuple[str, str, str, str]:
    if bullish is None or bearish is None:
        return "UNAVAILABLE", "UNAVAILABLE", "UNAVAILABLE", "UNAVAILABLE"
    if bullish > bearish:
        side, score, slope = "CE", bullish, ce_slope
        hard_direction, lean_direction = "BULLISH", "BULLISH"
    elif bearish > bullish:
        side, score, slope = "PE", bearish, pe_slope
        hard_direction, lean_direction = "BEARISH", "BEARISH"
    else:
        return "WAIT", "BALANCED", "FLAT", "NEUTRAL"
    hard = score >= 50.0 and gap is not None and gap >= 8.0
    direction = hard_direction if hard else "WAIT"
    label = f"STRONG {lean_direction}" if hard else f"WEAK {lean_direction} LEAN" if gap is not None and gap >= 8.0 else "NO CLEAR LEAN"
    if slope is None:
        trend = "UNAVAILABLE"
    elif slope > _OPTION_TREND_EPSILON:
        trend = "STRENGTHENING"
    elif slope < -_OPTION_TREND_EPSILON:
        trend = "FADING"
    else:
        trend = "FLAT"
    return direction, label, trend, side


def build_market_at_a_glance(summary: Mapping[str, Any], futures: Mapping[str, Any], underlying: Mapping[str, Any] | None = None, *, now: datetime | None = None, early_1m: Mapping[str, Any] | None = None, spot_vwap: Mapping[str, Any] | None = None, futures_vwap: Mapping[str, Any] | None = None) -> dict[str, Any]:
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
    ce_slope = _number(summary.get("ce_score_slope"))
    pe_slope = _number(summary.get("pe_score_slope"))
    option_direction, option_pressure_label, option_pressure_trend, option_winning_side = _option_interpretation(bullish, bearish, gap, ce_slope, pe_slope)
    option_momentum = "BULLISH" if ce_slope is not None and pe_slope is not None and ce_slope >= _OPTION_SLOPE_SUPPORT_PER_MINUTE and ce_slope > pe_slope else "BEARISH" if ce_slope is not None and pe_slope is not None and pe_slope >= _OPTION_SLOPE_SUPPORT_PER_MINUTE and pe_slope > ce_slope else "FLAT"

    futures_state = str(futures.get("positioning_state") or "UNAVAILABLE").upper()
    futures_strength = str(futures.get("strength") or "UNAVAILABLE").upper()
    futures_direction = "BULLISH" if futures_state in _BULLISH_FUTURES else "BEARISH" if futures_state in _BEARISH_FUTURES else "NEUTRAL"
    underlying_state = str(underlying.get("state") or "UNAVAILABLE").upper()
    observed_direction = str(underlying.get("direction") or "UNAVAILABLE").upper()
    structural_state = str(underlying.get("acceptance_state") or underlying_state or "UNAVAILABLE").upper()
    rsi_view = str(underlying.get("rsi_view") or "UNAVAILABLE").upper()
    early_state = str(early_1m.get("state") or "UNAVAILABLE").upper()
    early_direction = str(early_1m.get("direction") or "UNAVAILABLE").upper()
    spot_vwap_state = str(spot_vwap.get("state") or "UNAVAILABLE").upper()
    spot_vwap_direction = str(spot_vwap.get("direction") or "UNAVAILABLE").upper()
    futures_vwap_state = str(futures_vwap.get("state") or futures.get("futures_vwap_acceptance") or "UNAVAILABLE").upper()
    futures_vwap_direction = str(futures_vwap.get("direction") or "UNAVAILABLE").upper()

    early_alert = "NONE"
    if early_direction in {"BULLISH", "BEARISH"}:
        early_alert = f"{early_direction} 1M BREAK"
    elif rsi_view == "BULLISH_RECOVERY":
        early_alert = "BULLISH RSI RECOVERY"
    elif rsi_view == "BEARISH_FADE":
        early_alert = "BEARISH RSI FADE"

    option_time = _timestamp(summary.get("observed_at"))
    futures_collection_time = _timestamp(futures.get("observed_at"))
    futures_market_time = _timestamp(futures.get("latest_timestamp") or futures.get("observed_at"))
    underlying_time = _timestamp(underlying.get("observed_at"))
    freshness_diagnostics = [
        _freshness_result("Option snapshot", option_time, now=current_time, warning_seconds=_OPTION_WARNING_SECONDS, stale_seconds=_OPTION_MAX_AGE_SECONDS, missing_code="OPTION_TIMESTAMP_MISSING", stale_code="OPTION_SNAPSHOT_STALE"),
        _freshness_result("Futures collection", futures_collection_time, now=current_time, warning_seconds=_FUTURES_COLLECTION_WARNING_SECONDS, stale_seconds=_FUTURES_COLLECTION_MAX_AGE_SECONDS, missing_code="FUTURES_COLLECTION_TIMESTAMP_MISSING", stale_code="FUTURES_COLLECTOR_STALE"),
        _freshness_result("Futures candle", futures_market_time, now=current_time, warning_seconds=None, stale_seconds=_COMPLETED_5M_MAX_AGE_SECONDS, missing_code="FUTURES_MARKET_CANDLE_MISSING", stale_code="FUTURES_MARKET_CANDLE_STALE"),
        _freshness_result("Underlying candle", underlying_time, now=current_time, warning_seconds=None, stale_seconds=_COMPLETED_5M_MAX_AGE_SECONDS, missing_code="UNDERLYING_CANDLE_MISSING", stale_code="UNDERLYING_CANDLE_STALE"),
        _alignment_result(option_time, futures_market_time, underlying_time),
    ]
    evidence_readiness = _evidence_readiness(freshness_diagnostics)
    blocking_reasons = [str(item["reason_code"]) for item in freshness_diagnostics if item.get("reason_code")]
    if bullish is None or bearish is None:
        blocking_reasons.append("OPTION_SCORES_UNAVAILABLE")
    eligible_ce = int(summary.get("eligible_ce") or 0)
    eligible_pe = int(summary.get("eligible_pe") or 0)
    if eligible_ce <= 0:
        blocking_reasons.append("NO_ELIGIBLE_CE_CONTRACT")
    if eligible_pe <= 0:
        blocking_reasons.append("NO_ELIGIBLE_PE_CONTRACT")
    contract_quality = "PASS" if eligible_ce > 0 and eligible_pe > 0 else "FAIL"

    structure_confirmed = structural_state == "HOLD_CONFIRMED"
    spot_vwap_conflict = spot_vwap_direction in {"BULLISH", "BEARISH"} and observed_direction in {"BULLISH", "BEARISH"} and spot_vwap_direction != observed_direction
    futures_vwap_conflict = futures_vwap_direction in {"BULLISH", "BEARISH"} and observed_direction in {"BULLISH", "BEARISH"} and futures_vwap_direction != observed_direction
    strong_futures_conflict = futures_direction in {"BULLISH", "BEARISH"} and observed_direction in {"BULLISH", "BEARISH"} and futures_direction != observed_direction and futures_strength in _CONFIRMING_STRENGTH
    weak_futures_opposition = futures_direction in {"BULLISH", "BEARISH"} and observed_direction in {"BULLISH", "BEARISH"} and futures_direction != observed_direction and futures_strength not in _CONFIRMING_STRENGTH
    option_conflict = option_direction in {"BULLISH", "BEARISH"} and observed_direction in {"BULLISH", "BEARISH"} and option_direction != observed_direction
    rsi_conflict = rsi_view in {"BULLISH", "BEARISH"} and observed_direction in {"BULLISH", "BEARISH"} and rsi_view != observed_direction

    caution_reasons: list[str] = []
    if weak_futures_opposition:
        caution_reasons.append("WEAK_FUTURES_OPPOSITION")
    if any(item.get("status") == "WARNING" for item in freshness_diagnostics):
        caution_reasons.append("SOURCE_APPROACHING_STALE_LIMIT")

    if observed_direction == "UNAVAILABLE":
        direction_state = "UNAVAILABLE"
    elif observed_direction == "NEUTRAL":
        direction_state = "EARLY" if early_direction in {"BULLISH", "BEARISH"} else "NEUTRAL"
        if direction_state == "EARLY":
            observed_direction = early_direction
    elif not structure_confirmed:
        direction_state = "EARLY"
    elif spot_vwap_conflict or futures_vwap_conflict or strong_futures_conflict or option_conflict or rsi_conflict:
        direction_state = "CONFLICTED"
    elif weak_futures_opposition:
        direction_state = "CONFIRMED_WITH_CAUTION"
    else:
        direction_state = "CONFIRMED"

    primary_blocker = _primary_reason(blocking_reasons)
    next_action = _OPERATOR_ACTIONS.get(primary_blocker) if primary_blocker else None
    trade_eligibility = "ELIGIBLE" if evidence_readiness == "READY" and contract_quality == "PASS" and direction_state == "CONFIRMED" and observed_direction in {"BULLISH", "BEARISH"} else "BLOCKED"
    trade_bias = "BUY CE" if trade_eligibility == "ELIGIBLE" and observed_direction == "BULLISH" else "BUY PE" if trade_eligibility == "ELIGIBLE" and observed_direction == "BEARISH" else "WAIT"
    market_state = f"CONFIRMED {observed_direction}" if direction_state == "CONFIRMED" else f"CONFIRMED {observed_direction} WITH CAUTION" if direction_state == "CONFIRMED_WITH_CAUTION" else f"EARLY {observed_direction} TRANSITION" if direction_state == "EARLY" else "CONFLICTED" if direction_state == "CONFLICTED" else underlying_state if direction_state == "NEUTRAL" and underlying_state.startswith("SIDEWAYS") else "SIDEWAYS" if direction_state == "NEUTRAL" else "UNAVAILABLE"
    confirmation = f"Blocked by {primary_blocker}." if primary_blocker else "Direction is conflicted." if direction_state == "CONFLICTED" else "Direction is confirmed with caution." if direction_state == "CONFIRMED_WITH_CAUTION" else "Direction is structurally confirmed and evidence is ready." if trade_eligibility == "ELIGIBLE" else "Direction is visible but not trade-eligible."

    freshness_rows = [{"Source": item["source"], "Timestamp": item["timestamp"] or "—", "Age": "—" if item["age_seconds"] is None else f"{item['age_seconds']:.0f}s", "Warning": "—" if item["warning_seconds"] is None else f"{item['warning_seconds']:.0f}s", "Limit": f"{item['limit_seconds']:.0f}s", "Result": item["status"]} for item in freshness_diagnostics]
    checklist = [
        {"Check": "Completed 1m early state", "Live value": early_state, "Rule": "Early observation only", "Status": early_direction},
        {"Check": "Underlying 5m structure", "Live value": underlying_state, "Rule": "Completed breakout plus hold", "Status": f"{observed_direction} / {structural_state}"},
        {"Check": "Early alert", "Live value": early_alert, "Rule": "Alert only; cannot own direction", "Status": "OBSERVATIONAL"},
        {"Check": "Spot VWAP acceptance", "Live value": spot_vwap_state, "Rule": "No synthetic index VWAP", "Status": spot_vwap.get("reason") or "—"},
        {"Check": "RSI slope", "Live value": f"{_score(underlying.get('rsi'))} / {_score(underlying.get('rsi_slope'))}", "Rule": "Confirmation, recovery or fade", "Status": rsi_view},
        {"Check": "Option pressure", "Live value": f"CE {_score(bullish)} / PE {_score(bearish)} / gap {_score(gap)}", "Rule": "Hard confirmation requires winner >=50 and gap >=8", "Status": f"{option_pressure_label} / {option_pressure_trend}"},
        {"Check": "Option persistence", "Live value": f"CE {_score(ce_slope)} / PE {_score(pe_slope)} points/min", "Rule": "Same-session persistence", "Status": option_momentum},
        {"Check": "Contract quality", "Live value": f"CE {eligible_ce} / PE {eligible_pe}; {summary.get('rejected', 0)} rejected", "Rule": "Two-sided quotes and liquidity", "Status": contract_quality},
        {"Check": "Futures", "Live value": f"{futures_state} / {futures_strength}", "Rule": "Weak opposition is caution; moderate/strong opposition is conflict", "Status": "WEAK_OPPOSITION" if weak_futures_opposition else "CONFLICT" if strong_futures_conflict else "CONFIRMS" if futures_direction == observed_direction else "NEUTRAL"},
        {"Check": "Futures VWAP", "Live value": futures_vwap_state, "Rule": "Current-month futures traded-volume VWAP", "Status": futures_vwap.get("reason") or futures.get("futures_vwap_acceptance") or "—"},
    ]
    latest_complete = max([value for value in (futures_market_time, underlying_time) if value is not None], default=None)
    return {
        "as_of_timestamp": current_time.isoformat(), "observed_direction": observed_direction, "structural_state": structural_state,
        "direction_state": direction_state, "evidence_readiness": evidence_readiness, "contract_quality": contract_quality,
        "trade_eligibility": trade_eligibility, "trade_bias": trade_bias, "blocking_reasons": tuple(blocking_reasons),
        "caution_reasons": tuple(caution_reasons), "primary_blocker": primary_blocker, "next_action": next_action,
        "freshness_diagnostics": freshness_diagnostics, "freshness_rows": freshness_rows, "market_state": market_state,
        "confirmation": confirmation, "bullish_score": bullish, "bearish_score": bearish, "score_gap": gap,
        "underlying_state": underlying_state, "underlying_direction": observed_direction, "acceptance_state": structural_state,
        "early_1m_state": early_state, "early_1m_direction": early_direction, "early_alert": early_alert,
        "spot_vwap_state": spot_vwap_state, "futures_vwap_state": futures_vwap_state, "option_direction": option_direction,
        "option_momentum": option_momentum, "option_pressure_label": option_pressure_label,
        "option_pressure_trend": option_pressure_trend, "option_winning_side": option_winning_side,
        "futures_direction": futures_direction, "evidence_status": evidence_readiness,
        "alignment_gap_seconds": freshness_diagnostics[-1].get("age_seconds"),
        "option_timestamp": option_time.isoformat() if option_time else None,
        "futures_collection_timestamp": futures_collection_time.isoformat() if futures_collection_time else None,
        "futures_market_timestamp": futures_market_time.isoformat() if futures_market_time else None,
        "underlying_timestamp": underlying_time.isoformat() if underlying_time else None,
        "latest_complete_evidence_time": latest_complete.isoformat() if latest_complete else None,
        "checklist": checklist,
        "explanation": f"Structure {underlying_state}; early alert {early_alert}; options {option_pressure_label}/{option_pressure_trend}; futures {futures_state}/{futures_strength}; evidence {evidence_readiness}; trade {trade_eligibility}.",
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
    view = build_market_at_a_glance(normalized, futures, underlying, now=now, early_1m=intraday["early_1m"], spot_vwap=intraday["spot_vwap"], futures_vwap=futures_vwap)
    try:
        view["bundle_id"] = persist_market_evidence_bundle(settings.database_path, underlying_name=underlying_name, view=view)
    except Exception as exc:
        view["bundle_persistence_error"] = str(exc)

    st.caption("Observed structure, early alerts, confirmation readiness and trade eligibility are evaluated independently.")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Observed direction", view["observed_direction"])
    c2.metric("Direction state", view["direction_state"])
    c3.metric("Evidence readiness", view["evidence_readiness"])
    c4.metric("Trade eligibility", view["trade_eligibility"])
    c5.metric("Trade bias", view["trade_bias"])
    if view["trade_eligibility"] == "ELIGIBLE":
        st.success(f"{view['market_state']}: evidence is ready and contract quality passed.")
    else:
        st.warning(f"{view['market_state']}: trade eligibility is BLOCKED; bias remains WAIT.")
    if view["primary_blocker"]:
        st.error(f"Primary blocker: {view['primary_blocker']}")
    if view["caution_reasons"]:
        st.warning("Cautions: " + ", ".join(view["caution_reasons"]))
    if view["next_action"]:
        st.info(f"Next action: {view['next_action']}")

    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Market structure", view["underlying_state"])
    s2.metric("Early alert", view["early_alert"])
    s3.metric("Options", f"{view['option_pressure_label']} / {view['option_pressure_trend']}")
    s4.metric("Futures", f"{futures.get('positioning_state', 'UNAVAILABLE')} / {futures.get('strength', 'UNAVAILABLE')}")
    p1, p2, p3 = st.columns(3)
    p1.metric("CE pressure", _score(view["bullish_score"]))
    p2.metric("PE pressure", _score(view["bearish_score"]))
    p3.metric("Confirmation gap", _score(view["score_gap"]))

    st.markdown("### Freshness diagnostics")
    st.dataframe(_arrow_safe_rows(view["freshness_rows"]), width="stretch", hide_index=True)
    st.markdown("### Direction and confirmation diagnostics")
    st.dataframe(_arrow_safe_rows(view["checklist"]), width="stretch", hide_index=True)
    st.write(f"**What is happening:** {view['explanation']}")
    st.write(f"**Decision reason:** {view['confirmation']}")
    if view.get("latest_complete_evidence_time"):
        st.caption(f"Latest complete market evidence time: {view['latest_complete_evidence_time']}")
    if view.get("bundle_id"):
        st.caption(f"Evidence bundle: {view['bundle_id']}")
    st.caption("Observational only. Spot structure owns direction; futures VWAP and options only confirm or caution. No synthetic spot VWAP is used, and Red Bar execution is unchanged.")
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
