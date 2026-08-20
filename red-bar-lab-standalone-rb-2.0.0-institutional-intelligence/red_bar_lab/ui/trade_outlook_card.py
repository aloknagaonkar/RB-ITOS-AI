from __future__ import annotations

from typing import Any, Mapping

from red_bar_lab.ui.trade_outlook import build_trade_outlook


def _evidence_text(values: object) -> str:
    items = tuple(str(item) for item in (values or ()))
    return "\n".join(f"• {item}" for item in items) if items else "—"


def install(full_trade_card_module: Any) -> None:
    """Add a read-only outlook panel to the selected Full Card.

    The panel consumes only the card's persisted order/telemetry view model. It
    never calls a provider and never changes paper entry, exit, or protection.
    """
    if getattr(full_trade_card_module, "_trade_outlook_installed", False):
        return

    original_build = full_trade_card_module.build_active_trade_card
    original_render = full_trade_card_module.render_active_trade_card

    def build_active_trade_card(
        order: Mapping[str, object],
        telemetry: Mapping[str, object] | None,
        **kwargs,
    ) -> dict[str, object]:
        card = dict(original_build(order, telemetry, **kwargs))
        card["trade_outlook"] = build_trade_outlook(order, card)
        return card

    def render_active_trade_card(st, card: Mapping[str, object]) -> None:
        original_render(st, card)
        outlook = dict(card.get("trade_outlook") or {})
        if not outlook:
            return

        st.markdown("### Current Trade Outlook")
        st.caption(
            f"{outlook.get('model_version', 'RBV2-OUTLOOK-V1')} · "
            f"{outlook.get('authority', 'OBSERVATIONAL ONLY')} · "
            "existing paper exit rules remain authoritative"
        )
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Recommendation", outlook.get("recommendation") or "MONITOR")
        c2.metric("Outlook", outlook.get("outlook") or "UNKNOWN")
        c3.metric("Trade Health", outlook.get("trade_health") or "UNKNOWN")
        c4.metric("Confidence", f"{int(outlook.get('confidence_pct') or 0)}%")

        st.write({
            "Underlying bias": outlook.get("underlying_bias") or "UNKNOWN",
            "Data quality": outlook.get("data_quality") or "UNAVAILABLE",
            "Evidence score": outlook.get("score"),
            "Authority": outlook.get("authority") or "OBSERVATIONAL ONLY",
        })
        st.markdown("**Supporting evidence**")
        st.text(_evidence_text(outlook.get("supportive_evidence")))
        st.markdown("**Conflicting evidence**")
        st.text(_evidence_text(outlook.get("conflicting_evidence")))
        st.markdown("**Observations**")
        st.text(_evidence_text(outlook.get("observations")))

    full_trade_card_module.build_active_trade_card = build_active_trade_card
    full_trade_card_module.render_active_trade_card = render_active_trade_card
    full_trade_card_module._trade_outlook_installed = True


__all__ = ["install"]
