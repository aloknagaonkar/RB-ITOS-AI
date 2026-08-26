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


def _points(value: float, maximum: float) -> str:
    return f"{value:.1f} / {maximum:.0f}"


def _component_scores(
    row: Mapping[str, Any],
    *,
    max_side_volume: float,
) -> dict[str, float]:
    state = str(row.get("participation_state") or "INSUFFICIENT").upper()
    directional = {
        "FRESH_BUYING": 30.0,
        "SHORT_COVERING": 22.0,
        "NEUTRAL": 10.0,
        "INSUFFICIENT": 5.0,
        "WRITING_PRESSURE": 0.0,
        "LONG_UNWINDING": 0.0,
    }.get(state, 0.0)

    current = _number(row.get("current_price"))
    vwap = _number(row.get("vwap"))
    vwap_score = (
        20.0
        if current is not None and vwap not in (None, 0.0) and current >= vwap
        else 0.0
    )

    volume = _number(row.get("volume"))
    volume_score = 0.0
    if volume is not None and max_side_volume > 0:
        volume_score = min(15.0, max(0.0, volume / max_side_volume * 15.0))

    oi_change = _number(row.get("oi_change"))
    oi_score = 0.0
    if oi_change is not None:
        if state == "FRESH_BUYING":
            oi_score = 15.0
        elif state == "SHORT_COVERING":
            oi_score = 10.0
        elif oi_change == 0:
            oi_score = 5.0

    option_rsi = _number(row.get("option_rsi"))
    rsi_score = 0.0
    if option_rsi is not None:
        if 55.0 <= option_rsi <= 70.0:
            rsi_score = 10.0
        elif 50.0 <= option_rsi < 55.0:
            rsi_score = 7.0
        elif 70.0 < option_rsi <= 75.0:
            rsi_score = 6.0
        elif 45.0 <= option_rsi < 50.0:
            rsi_score = 4.0
        elif option_rsi > 75.0:
            rsi_score = 2.0

    delta = _number(row.get("delta"))
    delta_score = 0.0
    if delta is not None:
        absolute = abs(delta)
        if 0.40 <= absolute <= 0.65:
            delta_score = 10.0
        elif 0.30 <= absolute < 0.40 or 0.65 < absolute <= 0.75:
            delta_score = 7.0
        elif 0.20 <= absolute < 0.30:
            delta_score = 4.0

    total = directional + vwap_score + volume_score + oi_score + rsi_score + delta_score
    return {
        "directional": directional,
        "vwap": vwap_score,
        "volume": volume_score,
        "oi": oi_score,
        "rsi": rsi_score,
        "delta": delta_score,
        "total": round(total, 2),
    }


def _breakdown_rows(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    side_max_volume: dict[str, float] = {}
    for side in ("CE", "PE"):
        side_max_volume[side] = max(
            (
                _number(row.get("volume")) or 0.0
                for row in rows
                if str(row.get("option_type") or "").upper() == side
            ),
            default=0.0,
        )

    result: list[dict[str, Any]] = []
    for row in rows:
        side = str(row.get("option_type") or "").upper()
        components = _component_scores(
            row,
            max_side_volume=side_max_volume.get(side, 0.0),
        )
        persisted_total = _number(row.get("strike_score"))
        result.append(
            {
                "Side": side or "—",
                "Strike": row.get("strike") or "—",
                "Offset": row.get("strike_offset_steps") if row.get("strike_offset_steps") is not None else "—",
                "Moneyness": row.get("moneyness") or "—",
                "State": row.get("participation_state") or "INSUFFICIENT",
                "Direction / state": _points(components["directional"], 30.0),
                "Above VWAP": _points(components["vwap"], 20.0),
                "Relative volume": _points(components["volume"], 15.0),
                "OI behaviour": _points(components["oi"], 15.0),
                "Option RSI": _points(components["rsi"], 10.0),
                "Delta": _points(components["delta"], 10.0),
                "Calculated total": _score(components["total"]),
                "Persisted score": _score(persisted_total),
            }
        )
    return result


def _decision_rows(
    summary: Mapping[str, Any],
    futures: Mapping[str, Any],
) -> list[dict[str, str]]:
    bullish = _number(summary.get("ce_score")) or 0.0
    bearish = _number(summary.get("pe_score")) or 0.0
    best = max(bullish, bearish)
    gap = abs(bullish - bearish)
    winning_side = "CE" if bullish > bearish else "PE" if bearish > bullish else "TIE"
    futures_state = str(futures.get("positioning_state") or "NEUTRAL").upper()
    futures_side = (
        "CE"
        if futures_state in _BULLISH_FUTURES
        else "PE"
        if futures_state in _BEARISH_FUTURES
        else "NEUTRAL"
    )
    futures_result = (
        "CONFIRMS"
        if winning_side in {"CE", "PE"} and futures_side == winning_side
        else "CONTRADICTS"
        if winning_side in {"CE", "PE"} and futures_side in {"CE", "PE"}
        else "NEUTRAL / UNAVAILABLE"
    )
    return [
        {
            "Decision check": "Bullish score",
            "Live value": f"{bullish:.1f}",
            "Rule": "CE ATM ±4 weighted pressure score",
            "Result": "BULLISH EVIDENCE",
        },
        {
            "Decision check": "Bearish score",
            "Live value": f"{bearish:.1f}",
            "Rule": "PE ATM ±4 weighted pressure score",
            "Result": "BEARISH EVIDENCE",
        },
        {
            "Decision check": "Winning score",
            "Live value": f"{best:.1f}",
            "Rule": "Must be at least 50.0",
            "Result": "PASS" if best >= 50.0 else "FAIL",
        },
        {
            "Decision check": "Score separation",
            "Live value": f"{gap:.1f}",
            "Rule": "Must be at least 8.0 points",
            "Result": "PASS" if gap >= 8.0 else "FAIL",
        },
        {
            "Decision check": "Higher side",
            "Live value": winning_side,
            "Rule": "CE higher = bullish; PE higher = bearish",
            "Result": summary.get("recommended_direction") or "NEUTRAL",
        },
        {
            "Decision check": "Futures confirmation",
            "Live value": futures_state,
            "Rule": "Confirms or contradicts the winning option side",
            "Result": futures_result,
        },
        {
            "Decision check": "Final independent view",
            "Live value": str(summary.get("recommended_side") or "WAIT"),
            "Rule": "Score threshold + separation; futures used as confirmation",
            "Result": str(summary.get("grade") or "UNAVAILABLE"),
        },
    ]


def render_score_explanation(settings, underlying_name: str) -> None:
    del settings, underlying_name


def install(page_module: Any) -> None:
    if getattr(page_module, "_market_score_explanation_installed", False):
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
        result = original_render(
            settings,
            layout,
            database,
            token,
            underlying_name,
            instrument_key,
            interval,
        )
        render_score_explanation(settings, underlying_name)
        return result

    page_module.render_page = wrapped_render
    page_module._market_score_explanation_installed = True


__all__ = ["install", "render_score_explanation"]
