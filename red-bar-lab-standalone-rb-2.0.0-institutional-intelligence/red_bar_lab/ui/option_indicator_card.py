from __future__ import annotations

from typing import Any, Mapping


_NOT_AVAILABLE = "—"


def _number(value: object, digits: int = 2) -> str:
    if value in (None, ""):
        return _NOT_AVAILABLE
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return _NOT_AVAILABLE


def _change(current: object, entry: object) -> float | None:
    if current in (None, "") or entry in (None, ""):
        return None
    try:
        return float(current) - float(entry)
    except (TypeError, ValueError):
        return None


def classify_entry_vwap_distance(
    entry_price: object,
    entry_vwap: object,
) -> dict[str, object]:
    """Classify how far the option entry fill was from entry-time VWAP.

    Distance is absolute percentage deviation from VWAP. Direction is retained
    separately so the UI can distinguish entries above and below VWAP.
    """
    try:
        price = float(entry_price)
        vwap = float(entry_vwap)
    except (TypeError, ValueError):
        price = vwap = 0.0
    if price <= 0.0 or vwap <= 0.0:
        return {
            "classification": "UNAVAILABLE",
            "distance_points": None,
            "distance_pct": None,
            "relation": "UNKNOWN",
        }

    signed_points = price - vwap
    distance_points = abs(signed_points)
    distance_pct = distance_points / vwap * 100.0
    if distance_pct <= 0.25:
        classification = "VERY CLOSE"
    elif distance_pct <= 0.75:
        classification = "CLOSE"
    elif distance_pct <= 1.50:
        classification = "FAR"
    else:
        classification = "VERY FAR"

    relation = "AT VWAP"
    if signed_points > 0:
        relation = "ABOVE VWAP"
    elif signed_points < 0:
        relation = "BELOW VWAP"
    return {
        "classification": classification,
        "distance_points": distance_points,
        "distance_pct": distance_pct,
        "relation": relation,
    }


def install(full_trade_card_module: Any) -> None:
    """Add persisted option VWAP and RSI-14 lifecycle details to the Full Card."""
    if getattr(full_trade_card_module, "_option_indicator_card_installed", False):
        return

    original_build = full_trade_card_module.build_active_trade_card
    original_render = full_trade_card_module.render_active_trade_card

    def build_active_trade_card(order, telemetry, *, lifecycle=None, now=None):
        card = dict(original_build(order, telemetry, lifecycle=lifecycle, now=now))
        life = dict(lifecycle or {})
        entry = dict(life.get("entry") or {})
        status = str(card.get("status") or "OPEN").upper()
        current = dict(life.get("exit") or {}) if status == "CLOSED" else dict(life.get("latest") or {})
        entry_vwap = entry.get("option_vwap")
        current_vwap = current.get("option_vwap")
        entry_rsi = entry.get("option_rsi14")
        current_rsi = current.get("option_rsi14")
        entry_distance = classify_entry_vwap_distance(
            card.get("entry_price"),
            entry_vwap,
        )
        card.update(
            {
                "entry_option_vwap": entry_vwap,
                "current_option_vwap": current_vwap,
                "option_vwap_change": _change(current_vwap, entry_vwap),
                "entry_option_rsi14": entry_rsi,
                "current_option_rsi14": current_rsi,
                "option_rsi14_change": _change(current_rsi, entry_rsi),
                "entry_vwap_distance_class": entry_distance["classification"],
                "entry_vwap_distance_points": entry_distance["distance_points"],
                "entry_vwap_distance_pct": entry_distance["distance_pct"],
                "entry_vwap_relation": entry_distance["relation"],
                "indicator_source": current.get("indicator_source") or "NOT_AVAILABLE",
            }
        )
        return card

    def render_active_trade_card(st: Any, card: Mapping[str, object]) -> None:
        original_render(st, card)
        label = str(card.get("comparison_label") or "Current")
        st.markdown("#### Option VWAP & RSI")
        st.caption(
            "Derived from persisted option telemetry only. No provider call is made by this UI."
        )
        st.dataframe(
            [
                {
                    "Indicator": "Option VWAP",
                    "Entry": _number(card.get("entry_option_vwap"), 2),
                    label: _number(card.get("current_option_vwap"), 2),
                    "Change": _number(card.get("option_vwap_change"), 2),
                },
                {
                    "Indicator": "Option RSI-14",
                    "Entry": _number(card.get("entry_option_rsi14"), 2),
                    label: _number(card.get("current_option_rsi14"), 2),
                    "Change": _number(card.get("option_rsi14_change"), 2),
                },
            ],
            width="stretch",
            hide_index=True,
        )
        st.write(
            {
                "Entry distance from VWAP": card.get("entry_vwap_distance_class") or "UNAVAILABLE",
                "Entry relation": card.get("entry_vwap_relation") or "UNKNOWN",
                "Distance points": _number(card.get("entry_vwap_distance_points"), 2),
                "Distance %": _number(card.get("entry_vwap_distance_pct"), 2),
            }
        )
        st.caption(
            "Distance bands: VERY CLOSE ≤0.25%, CLOSE ≤0.75%, FAR ≤1.50%, VERY FAR >1.50%."
        )
        st.caption(f"Indicator source: {card.get('indicator_source') or 'NOT_AVAILABLE'}")

    full_trade_card_module.build_active_trade_card = build_active_trade_card
    full_trade_card_module.render_active_trade_card = render_active_trade_card
    full_trade_card_module._option_indicator_card_installed = True


__all__ = ["classify_entry_vwap_distance", "install"]
